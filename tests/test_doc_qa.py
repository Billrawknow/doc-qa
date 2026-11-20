"""
Tests for doc_qa.py. They run without an API key: the Claude call is replaced
by a fake client that records what it was sent.

    python -m unittest discover tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import doc_qa  # noqa: E402

SAMPLE = ROOT / "samples" / "supply_agreement.pdf"


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns a canned answer, records the request."""

    def __init__(self, answer="The Buyer gets 1% off per working day of delay, up to 10% [p. 2]."):
        self.answer = answer
        self.requests = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.answer)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=2400, output_tokens=120))


def tmp_path(name):
    return Path(tempfile.mkdtemp()) / name


class TestExtract(unittest.TestCase):
    def test_reads_every_page_of_the_sample(self):
        pages = doc_qa.load_pages(SAMPLE)
        self.assertEqual(len(pages), 11)
        self.assertIn("Rift Valley Building Supplies Ltd", pages[0][1])

    def test_table_rows_stay_on_one_line(self):
        text = "\n".join(t for _, t in doc_qa.load_pages(SAMPLE))
        self.assertRegex(text, r"STL-0029 Y12 deformed bar 12m 1,130 ")

    def test_repeated_footer_is_removed(self):
        text = "\n".join(t for _, t in doc_qa.load_pages(SAMPLE))
        self.assertNotIn("Supply Agreement: Rift Valley Building Supplies / Mlimani Hardware", text)

    def test_missing_file(self):
        with self.assertRaisesRegex(doc_qa.DocError, "Can't find"):
            doc_qa.load_pages("nope.pdf")

    def test_scanned_pdf_without_text_explains_ocr(self):
        from pypdf import PdfWriter
        path = tmp_path("scan.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(path)
        with self.assertRaisesRegex(doc_qa.DocError, "scanned"):
            doc_qa.load_pages(path)

    def test_not_really_a_pdf(self):
        path = tmp_path("fake.pdf")
        path.write_text("hello, I am not a PDF")
        with self.assertRaises(doc_qa.DocError):
            doc_qa.load_pages(path)

    def test_unsupported_type(self):
        path = tmp_path("sheet.xlsx")
        path.write_bytes(b"x")
        with self.assertRaisesRegex(doc_qa.DocError, "aren't supported"):
            doc_qa.load_pages(path)

    def test_word_document_including_tables(self):
        import docx
        path = tmp_path("lease.docx")
        d = docx.Document()
        d.add_paragraph("Monthly rent is KES 45,000, payable by the 5th of each month.")
        t = d.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Deposit", "KES 90,000"
        d.save(path)
        text = doc_qa.load_pages(path)[0][1]
        self.assertIn("KES 45,000", text)
        self.assertIn("Deposit | KES 90,000", text)


class TestChunk(unittest.TestCase):
    def test_chunks_cover_the_text_and_keep_pages(self):
        pages = [(1, "Sentence one. " * 200), (2, "Clause two. " * 50)]
        chunks = doc_qa.chunk_pages(pages, size=500, overlap=100)
        self.assertTrue(all(len(c.text) <= 500 for c in chunks))
        self.assertEqual({c.page for c in chunks}, {1, 2})
        self.assertEqual([c.id for c in chunks], list(range(len(chunks))))

    def test_chunks_overlap_and_start_cleanly(self):
        text = "\n".join(f"Line {i} of the contract says something." for i in range(100))
        chunks = doc_qa.chunk_pages([(1, text)], size=400, overlap=120)
        for a, b in zip(chunks, chunks[1:]):
            self.assertTrue(b.text.startswith("Line "), b.text[:20])   # no chunk starts mid-word
            self.assertIn(b.text.splitlines()[0], a.text)              # overlap with the previous chunk

    def test_empty_page_gives_no_chunks(self):
        self.assertEqual(doc_qa.chunk_pages([(1, "")]), [])


class TestRetrieve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa = doc_qa.DocumentQA(SAMPLE, client=FakeClient())

    def top_text(self, question, k=doc_qa.TOP_K):
        return " ".join(c.text for c in self.qa.retriever.search(question, k))

    def test_finds_late_delivery_clause_when_asked_about_penalties(self):
        self.assertIn("percent (1%)", self.top_text("What are the penalties if delivery is late?"))

    def test_finds_a_price_in_the_schedule(self):
        self.assertIn("Y12 deformed bar 12m 1,130", self.top_text("What is the price of a Y12 bar?"))

    def test_finds_interest_on_late_payment(self):
        self.assertIn("1.5%", self.top_text("How much interest on overdue invoices?", k=3))

    def test_finds_termination_notice(self):
        self.assertIn("ninety (90) days", self.top_text("How do we end the contract?", k=3))

    def test_finds_roofing_warranty(self):
        self.assertIn("ten (10) years", self.top_text("warranty on roofing sheets", k=3))

    def test_nonsense_question_matches_nothing(self):
        self.assertEqual(self.qa.retriever.search("zebra xylophone quantum"), [])


class TestAnswer(unittest.TestCase):
    def test_long_document_sends_only_the_best_chunks(self):
        client = FakeClient()
        qa = doc_qa.DocumentQA(SAMPLE, client=client)
        self.assertFalse(qa.whole)
        answer, pages, usage = qa.ask("What are the penalties for late delivery?")
        self.assertIn("[p. 2]", answer)
        sent = client.requests[0]["messages"][-1]["content"]
        self.assertIn("percent (1%)", sent)
        self.assertLess(len(sent), 10000)           # a fraction of the 21,000-character document
        self.assertEqual(client.requests[0]["model"], doc_qa.MODEL)
        self.assertIn("ONLY the document excerpts", client.requests[0]["system"])

    def test_short_document_is_sent_whole(self):
        path = tmp_path("note.txt")
        path.write_text("Delivery address: Temple Road, Kericho.\nContact: Grace, 0712 000 000.")
        client = FakeClient("Temple Road, Kericho [p. 1].")
        qa = doc_qa.DocumentQA(path, client=client)
        self.assertTrue(qa.whole)
        qa.ask("Where do deliveries go?")
        self.assertIn("Temple Road", client.requests[0]["messages"][-1]["content"])

    def test_follow_up_questions_include_history(self):
        client = FakeClient()
        qa = doc_qa.DocumentQA(SAMPLE, client=client)
        qa.ask("What is the credit limit?")
        qa.ask("And what happens if we go above it?")
        msgs = client.requests[1]["messages"]
        self.assertEqual(msgs[0]["content"], "What is the credit limit?")
        self.assertEqual(len(msgs), 3)

    def test_new_topic_is_not_drowned_by_the_previous_question(self):
        # Real session, 19 Nov: after a Y12 price question, "paying early" missed clause 8
        # because the old question's words filled the search. The 2% clause must be sent now.
        client = FakeClient()
        qa = doc_qa.DocumentQA(SAMPLE, client=client)
        qa.ask("What are the penalties if the supplier delivers late?")
        qa.ask("What is the price of a Y12 bar, and is it cheaper in bulk?")
        qa.ask("How much discount do we get for paying early?")
        self.assertIn("prompt-payment discount of two percent", client.requests[-1]["messages"][-1]["content"])

    def test_short_follow_up_keeps_the_previous_topic(self):
        client = FakeClient()
        qa = doc_qa.DocumentQA(SAMPLE, client=client)
        qa.ask("What is the price of a Y12 bar?")
        qa.ask("And the pallet price?")
        self.assertIn("STL-0032 Y12 deformed bar 12m (pallet)", client.requests[-1]["messages"][-1]["content"])

    def test_cost_is_tracked(self):
        qa = doc_qa.DocumentQA(SAMPLE, client=FakeClient())
        qa.ask("Who are the parties?")
        self.assertAlmostEqual(qa.cost, (2400 * 0.10 + 120 * 0.50) / 1_000_000)

    def test_missing_api_key_is_a_clear_message(self):
        qa = doc_qa.DocumentQA(SAMPLE)
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaisesRegex(doc_qa.DocError, "ANTHROPIC_API_KEY is missing"):
                qa.ask("Who are the parties?")

    def test_empty_question(self):
        qa = doc_qa.DocumentQA(SAMPLE, client=FakeClient())
        with self.assertRaises(doc_qa.DocError):
            qa.ask("   ")

    def test_word_report(self):
        import docx
        qa = doc_qa.DocumentQA(SAMPLE, client=FakeClient())
        qa.ask("What are the penalties for late delivery?")
        out = qa.save_report(tmp_path("report.docx"))
        text = "\n".join(p.text for p in docx.Document(out).paragraphs)
        self.assertIn("1. What are the penalties for late delivery?", text)
        self.assertIn("up to 10% [p. 2]", text)


if __name__ == "__main__":
    unittest.main()
