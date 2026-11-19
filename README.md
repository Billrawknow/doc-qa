# Document Q&A

Ask questions about a PDF (or a Word or text file) and get short answers that **quote the document and cite the page**. If the document doesn't contain the answer, the tool says so instead of guessing.

Built for AI Masterclass 2, Week 6: Working with Documents.

```
$ python doc_qa.py samples/supply_agreement.pdf -q "What are the penalties if the supplier delivers late?"
supply_agreement.pdf: 11 page(s), 21,724 characters, 24 chunks (sending the best 6 chunks per question)

Q: What are the penalties if the supplier delivers late?
```
*(Paste your real answer here after the first run.)*

**Who it's for:** procurement officers checking supplier contracts, accountants reading statements, lawyers, and shop owners with a 40-page agreement they never had time to read.

## How it works

```
PDF / DOCX / TXT
  1. Extract   pypdf (layout mode keeps table rows on one line), python-docx including tables.
               Headers and footers repeated on most pages are removed. Page numbers are kept.
  2. Chunk     ~1,200-character pieces with 200 characters of overlap, cut at line or sentence ends.
               Each chunk remembers its page.
  3. Retrieve  BM25 keyword ranking, plus contract synonyms ("penalty" also searches "late",
               "interest", "fee", "charge"). It picks the 6 best chunks.
               Documents under 15,000 characters skip this and are sent whole.
  4. Answer    Claude Haiku 5.5 answers ONLY from those passages and cites [p. N].
               The last 3 questions are kept, so follow-ups like "and if we pay early?" work.
```

**Why chunk instead of sending the whole PDF?**
- **Cost.** Haiku 5.5 charges 5 times more per token once a prompt goes over 100K tokens. A typical question here sends about 2,500 tokens and costs about **$0.0003**.
- **Accuracy.** The model reads the 6 passages that matter, not 300 rows of a price list.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env        # then paste your ANTHROPIC_API_KEY into .env
```

```bash
python doc_qa.py samples/supply_agreement.pdf                       # interactive: ask as many as you like
python doc_qa.py samples/supply_agreement.pdf -q "What is the credit limit?" -q "And the interest on late payment?"
python doc_qa.py samples/supply_agreement.pdf --search "credit limit"   # no AI, no cost: matching passages only
python doc_qa.py contract.pdf --report answers.docx                  # also save the session as a Word report
python doc_qa.py lease.docx                                          # Word files work too
```

Inside interactive mode:
- `/search <words>` shows the matching passages.
- `/pages` previews each page.
- `/quit` exits.

The tool prints the token count and the running cost after every answer.

## Sample document

`samples/supply_agreement.pdf` is an 11-page fictional supply agreement between a Nakuru building-materials distributor and a Kericho hardware shop. It has 16 clauses (delivery, late-delivery discounts, payment terms, interest, returns, warranty, termination, arbitration) and a 276-row price schedule. Rebuild it with `python make_sample_pdf.py`.

Good questions to try:
- What are the penalties if the supplier delivers late?
- What is the price of a Y12 bar, and is it cheaper in bulk?
- How much discount do we get for paying early?
- How do we end this contract?
- Can we return roofing sheets that were cut to length?
- What does the contract say about fuel price increases? *(It doesn't say, and the tool should tell you so.)*

## Tests

```bash
python -m unittest discover tests -v     # 24 tests, no API key needed (Claude is mocked)
```

The tests cover:
- **Extraction:** pages, table rows on one line, footer removal, Word tables, and plain-English errors for a missing file, a scanned PDF ("run it through OCR"), a fake PDF and an unsupported type.
- **Chunking:** size, overlap, clean starts.
- **Retrieval:** the right clause for penalties, prices, interest, termination and warranty, and nothing for nonsense.
- **Answering:** only the chunks are sent for long documents, short ones are sent whole, history is kept for follow-ups, cost is tracked, there's a clear message for a missing key, and the Word report is created.

## Limits

- **Scanned PDFs** (photos of paper) have no text layer. Run them through OCR first, e.g. `ocrmypdf scan.pdf out.pdf`.
- **Keyword retrieval** can miss a passage that uses completely different words. The synonym list covers the usual contract cases. Embeddings would be the next step.
- **Answers are AI-generated.** The page citations are there so a person can check before relying on them.

## Files

| File | Purpose |
|---|---|
| `doc_qa.py` | The tool: extract, chunk, retrieve, answer, and the Word report |
| `make_sample_pdf.py` | Builds the sample supply agreement (reportlab) |
| `samples/supply_agreement.pdf` | Sample document (all names and numbers are made up) |
| `tests/test_doc_qa.py` | 24 tests |
| `.env.example` | Where your API key goes (`.env` is git-ignored) |

## Stack

Python, pypdf, python-docx, the Anthropic SDK (Claude Haiku 5.5), python-dotenv and unittest.
