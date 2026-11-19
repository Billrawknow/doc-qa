"""
Document Q&A: ask questions about a PDF (or Word / text file) and get answers
that quote the document and cite the page they came from.

    python doc_qa.py contract.pdf                          # interactive: ask as many questions as you like
    python doc_qa.py contract.pdf -q "What are the penalties for late delivery?"
    python doc_qa.py contract.pdf --search "late delivery" # no AI, no cost: show matching passages
    python doc_qa.py contract.pdf --report answers.docx    # also save the Q&A session as a Word report

How it works:
  1. Extract  - pull the text out of every page (pypdf / python-docx), remembering page numbers.
  2. Chunk    - split the text into ~1,200-character pieces that overlap, each tagged with its page.
  3. Retrieve - score every chunk against the question (BM25 keyword ranking) and keep the best few.
                Short documents skip this step and are sent whole.
  4. Answer   - Claude answers ONLY from those passages, cites pages like [p. 3], and says so
                when the document doesn't contain the answer.
"""

import argparse
import logging
import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

logging.getLogger("pypdf").setLevel(logging.ERROR)   # we report broken PDFs ourselves, in plain English

MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5").strip()
# Haiku 5.5 thinks by default; for short factual answers that only costs tokens.
EXTRA_ARGS = {"thinking": {"type": "disabled"}} if "haiku" in MODEL else {}
PRICE_PER_MTOK = {"input": 0.10, "output": 0.50}   # Haiku 5.5, prompts up to 100K tokens

CHUNK_CHARS = 1200       # about 300-400 tokens per chunk
CHUNK_OVERLAP = 200      # so a sentence cut at a boundary still appears whole in one chunk
TOP_K = 6                # chunks sent with each question
WHOLE_DOC_CHARS = int(os.getenv("WHOLE_DOC_CHARS", "15000"))  # shorter docs (~4-5 pages) are sent whole
MAX_ANSWER_TOKENS = 800
FOLLOW_UP_EXTRA = 3      # passages carried over from the previous question for follow-ups
HISTORY_TURNS = 3        # earlier Q&A kept so follow-ups like "and the deposit?" make sense


class DocError(Exception):
    """A problem the user can fix: missing file, scanned PDF, missing API key..."""


@dataclass
class Chunk:
    id: int
    page: int
    text: str

    @property
    def label(self):
        return f"p. {self.page}"


# ------------------------------------------------------------------ 1. extract

def load_pages(path):
    """Return [(page_number, text), ...]. Word and text files are split into ~page-sized blocks."""
    path = Path(path)
    if not path.exists():
        raise DocError(f"Can't find '{path}'. Check the file name and folder.")
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(path)
            if reader.is_encrypted and not reader.decrypt(""):
                raise DocError(f"{path.name} is password-protected. Save an unlocked copy and try again.")
            pages = [(n, clean(extract_page(page))) for n, page in enumerate(reader.pages, start=1)]
        except PdfReadError as err:
            raise DocError(f"{path.name} isn't a readable PDF ({err}).")
        if not any(text for _, text in pages):
            raise DocError(f"{path.name} has {len(pages)} page(s) but no text. It is probably a scanned "
                           f"image; run it through OCR first (e.g. 'ocrmypdf in.pdf out.pdf').")
        return strip_headers_footers(pages)

    if suffix == ".docx":
        import docx
        document = docx.Document(path)
        paragraphs = [p.text for p in document.paragraphs]
        for table in document.tables:                       # tables hold prices and dates in contracts
            for row in table.rows:
                paragraphs.append(" | ".join(cell.text.strip() for cell in row.cells))
        text = "\n".join(paragraphs)
    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        raise DocError(f"'{suffix}' files aren't supported. Use a .pdf, .docx or .txt file.")

    text = clean(text)
    if not text:
        raise DocError(f"{path.name} is empty.")
    # Word files have no fixed pages, so call every ~3,000 characters a "page".
    return [(n, text[i:i + 3000]) for n, i in enumerate(range(0, len(text), 3000), start=1)]


def extract_page(page):
    """Layout mode keeps table rows on one line ("Y12 bar ... 1,130 ... In stock"); plain mode is the fallback."""
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except Exception:
        return page.extract_text() or ""


def strip_headers_footers(pages):
    """Drop lines that repeat on most pages (letterheads, 'Page 3 of 12', confidentiality footers)."""
    if len(pages) < 3:
        return pages
    shape = lambda line: re.sub(r"\d+", "#", line.strip().lower())
    counts = Counter(s for _, text in pages for s in {shape(l) for l in text.splitlines() if l.strip()})
    repeated = {s for s, n in counts.items() if n >= max(3, 0.6 * len(pages)) and len(s) < 120}
    return [(n, clean("\n".join(l for l in text.splitlines() if shape(l) not in repeated)))
            for n, text in pages]


def clean(text):
    text = text.replace("­", "")                      # soft hyphens from PDFs
    text = re.sub(r"-\n(?=[a-z])", "", text)                # re-join words hyphenated across lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ------------------------------------------------------------------ 2. chunk

def chunk_pages(pages, size=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """Split each page into overlapping chunks, breaking at paragraph or sentence ends when possible."""
    chunks = []
    for page, text in pages:
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                window = text[start:end]
                cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
                if cut > size // 2:
                    end = start + cut + 1
            piece = re.sub(r"\n\s*\n(?=[A-Z]{2,4}-\d)", "\n", text[start:end]).strip()   # tight table rows
            if piece:
                chunks.append(Chunk(len(chunks), page, piece))
            if end >= len(text):
                break
            nxt = max(end - overlap, start + 1)
            boundary = max(text.find("\n", nxt, end), -1)     # begin the next chunk on a fresh line
            if boundary == -1:
                boundary = text.find(". ", nxt, end) + 1 or -1
            start = boundary + 1 if 0 < boundary < end - 1 else nxt
    return chunks


# ------------------------------------------------------------------ 3. retrieve

STOPWORDS = set("""a an and are as at be by can do does for from has have how i if in is it its of on or
that the their there this to was what when where which who will with would should shall any all
about tell me please document contract say says much many we our us get got there""".split())


# Business documents rarely use the words people ask with ("penalty" vs "1% per day of delay").
SYNONYMS = {
    "penalty": "late interest fee charge discount breach", "penalties": "late interest fee charge discount",
    "fine": "interest fee charge", "cost": "price fee charge", "price": "cost kes",
    "pay": "payment invoice", "paid": "payment invoice", "deadline": "within days date",
    "cancel": "termination terminate notice", "end": "termination terminate notice",
    "quit": "termination notice", "refund": "return credit", "guarantee": "warranty",
    "who": "parties represented", "parties": "between represented", "start": "term commence",
    "late": "delay overdue", "deliver": "delivery", "transport": "delivery kilometre",
    "early": "prompt within", "paying": "payment paid", "discount": "prompt rebate",
    "bulk": "volume", "cheaper": "discount bulk", "deposit": "advance", "return": "refund credit",
}


def tokens(text):
    words = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", text.lower())
    return [stem(w) for w in words if w not in STOPWORDS]


def query_tokens(question):
    words = re.findall(r"[a-z0-9]+", question.lower())
    expanded = question + " " + " ".join(SYNONYMS.get(w, "") for w in words)
    return set(tokens(expanded))


def stem(word):
    """Very light stemming so 'deliveries', 'delivered' and 'delivery' match."""
    for suffix in ("ies", "ied", "ing", "ed", "es", "s", "y"):
        if word.endswith(suffix) and len(word) - len(suffix) >= (3 if suffix == "ing" else 4):
            return word[: -len(suffix)]
    return word


FOLLOW_UP_WORDS = ("and ", "what about", "how about", "also", "it ", "it?", "that", "those", "this ",
                   "they", "them", "same", "instead", "then", "else", "more")


def is_follow_up(question, hit_count):
    """Short questions or ones leaning on pronouns ('and if we pay early?') continue the last topic."""
    q = question.lower().strip()
    return hit_count < 2 or len(q.split()) <= 4 or q.startswith(FOLLOW_UP_WORDS) or \
        any(f" {w}" in f" {q}" for w in ("it", "that", "those", "they", "them", "this one"))


class Retriever:
    """BM25: the ranking formula search engines used for decades. Pure Python, no API cost."""

    def __init__(self, chunks, k1=1.5, b=0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(c.text)) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if chunks else 0
        df = Counter(term for d in self.docs for term in d)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query, k=TOP_K):
        terms = query_tokens(query)
        scored = []
        for chunk, doc, length in zip(self.chunks, self.docs, self.lengths):
            score = 0.0
            for t in terms:
                if t in doc:
                    tf = doc[t]
                    score += self.idf[t] * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda s: -s[0])
        return [chunk for _, chunk in scored[:k]]


# ------------------------------------------------------------------ 4. answer

SYSTEM_PROMPT = """You answer questions about one document for a busy business owner.

Rules:
- Use ONLY the document excerpts provided. Do not use outside knowledge about laws, prices or companies.
- After every fact, cite where it came from like [p. 3]. Use the page labels given in the excerpts.
- Quote figures, dates, percentages and names exactly as written.
- If the excerpts don't contain the answer, say: "The document doesn't say." and, if useful, what
  related information it does contain. Never guess.
- Keep it short: a direct answer first, then supporting points. Plain language, no legal jargon."""


class DocumentQA:
    def __init__(self, path, client=None):
        self.path = Path(path)
        self.pages = load_pages(self.path)
        self.chunks = chunk_pages(self.pages)
        self.retriever = Retriever(self.chunks)
        self.total_chars = sum(len(t) for _, t in self.pages)
        self.whole = self.total_chars <= WHOLE_DOC_CHARS
        self.client = client
        self.history = []        # [(question, answer)]
        self.log = []            # [(question, answer, pages_used, tokens_in, tokens_out)]
        self.cost = 0.0

    def describe(self):
        mode = ("short enough to send whole" if self.whole
                else f"sending the best {TOP_K} chunks per question")
        return (f"{self.path.name}: {len(self.pages)} page(s), {self.total_chars:,} characters, "
                f"{len(self.chunks)} chunks ({mode})")

    def context_for(self, question):
        if self.whole:
            return self.chunks_to_text(None), sorted({p for p, t in self.pages if t})
        # Search with THIS question only, so a new topic isn't drowned by the last one.
        hits = self.retriever.search(question)
        if self.history and is_follow_up(question, len(hits)):
            # "And in bulk?" / "What about the deposit?": add the passages the previous question used.
            for chunk in self.retriever.search(self.history[-1][0], k=FOLLOW_UP_EXTRA):
                if chunk not in hits:
                    hits.append(chunk)
        if not hits:   # no keyword overlap at all: fall back to the opening chunks
            hits = self.chunks[:TOP_K]
        hits.sort(key=lambda c: c.id)   # keep document order so clauses read naturally
        return self.chunks_to_text(hits), sorted({c.page for c in hits})

    def chunks_to_text(self, hits):
        if hits is None:
            return "\n\n".join(f"[p. {page}]\n{text}" for page, text in self.pages if text)
        return "\n\n".join(f"[{c.label}]\n{c.text}" for c in hits)

    def ask(self, question):
        question = question.strip()
        if not question:
            raise DocError("Type a question.")
        excerpts, pages_used = self.context_for(question)

        messages = []
        for q, a in self.history[-HISTORY_TURNS:]:
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        messages.append({"role": "user", "content":
                         f"Document: {self.path.name}\n\n<excerpts>\n{excerpts}\n</excerpts>\n\n"
                         f"Question: {question}"})

        response = self.call_claude(messages)
        answer = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        if not answer:
            answer = "(No answer came back. Try asking again.)"
        usage = response.usage
        self.cost += (usage.input_tokens * PRICE_PER_MTOK["input"]
                      + usage.output_tokens * PRICE_PER_MTOK["output"]) / 1_000_000
        self.history.append((question, answer))
        self.log.append((question, answer, pages_used, usage.input_tokens, usage.output_tokens))
        return answer, pages_used, usage

    def call_claude(self, messages):
        import anthropic
        if self.client is None:
            key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            if not key:
                raise DocError("ANTHROPIC_API_KEY is missing. Copy .env.example to .env and paste your key "
                               "(or use --search, which needs no key).")
            self.client = anthropic.Anthropic(api_key=key)
        try:
            return self.client.messages.create(model=MODEL, max_tokens=MAX_ANSWER_TOKENS,
                                               system=SYSTEM_PROMPT, messages=messages, **EXTRA_ARGS)
        except anthropic.AuthenticationError:
            raise DocError("The API key was rejected. Check ANTHROPIC_API_KEY in .env.")
        except anthropic.RateLimitError:
            raise DocError("Too many requests just now. Wait a minute and ask again.")
        except anthropic.APIConnectionError:
            raise DocError("Couldn't reach the Claude API. Check your internet connection.")
        except anthropic.APIStatusError as err:
            raise DocError(f"The Claude API returned an error ({err.status_code}). Try again shortly.")

    def save_report(self, out_path):
        """Save the Q&A session as a Word document (python-docx)."""
        import docx
        from docx.shared import Pt, RGBColor
        report = docx.Document()
        report.add_heading(f"Questions on {self.path.name}", 0)
        meta = report.add_paragraph()
        meta.add_run(f"{datetime.now():%d %B %Y, %H:%M}  |  {len(self.pages)} pages  |  "
                     f"{len(self.log)} question(s)").italic = True
        for n, (question, answer, pages, _, _) in enumerate(self.log, start=1):
            report.add_heading(f"{n}. {question}", level=1)
            for para in answer.split("\n"):
                if para.strip():
                    report.add_paragraph(para.strip().lstrip("-* ").strip(),
                                         style="List Bullet" if para.strip()[:1] in "-*" else None)
            src = report.add_paragraph()
            run = src.add_run(f"Pages searched: {', '.join(map(str, pages))}")
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
        note = report.add_paragraph()
        note.add_run("Answers were generated by AI from the document text. Check the cited pages "
                     "before relying on them.").font.size = Pt(9)
        report.save(out_path)
        return out_path


# ------------------------------------------------------------------ command line

def print_search(qa, query):
    hits = qa.retriever.search(query, k=3)
    if not hits:
        print("  No passage matches those words.")
    for c in hits:
        snippet = c.text if len(c.text) <= 500 else c.text[:500] + "..."
        print(f"\n  [{c.label}]\n  " + snippet.replace("\n", "\n  "))


def answer_and_print(qa, question):
    answer, pages, usage = qa.ask(question)
    print(f"\n{answer}\n")
    print(f"  (pages searched: {', '.join(map(str, pages))} | "
          f"{usage.input_tokens:,} in / {usage.output_tokens:,} out tokens | "
          f"session cost ${qa.cost:.4f})")


def interactive(qa):
    print("\nAsk anything about the document. Commands: /search <words>, /pages, /quit\n")
    while True:
        try:
            question = input("Question> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in ("/quit", "/exit", "quit", "exit", "q"):
            break
        if question.lower() == "/pages":
            for page, text in qa.pages:
                print(f"  p. {page}: {text[:90].replace(chr(10), ' ')}...")
            continue
        if question.lower().startswith("/search "):
            print_search(qa, question[8:])
            print()
            continue
        try:
            answer_and_print(qa, question)
        except DocError as err:
            print(f"\n  Problem: {err}\n")
        print()


def main():
    p = argparse.ArgumentParser(description="Ask questions about a PDF, Word or text document.")
    p.add_argument("document", help="path to a .pdf, .docx or .txt file")
    p.add_argument("-q", "--question", action="append", help="ask this and exit (repeat for several)")
    p.add_argument("--search", metavar="WORDS", help="show matching passages only (no AI, no cost)")
    p.add_argument("--report", metavar="FILE.docx", help="save the questions and answers to Word")
    args = p.parse_args()

    try:
        qa = DocumentQA(args.document)
        print(qa.describe())
        if args.search:
            print_search(qa, args.search)
            return
        if args.question:
            for q in args.question:
                print(f"\nQ: {q}")
                answer_and_print(qa, q)
        else:
            interactive(qa)
        if args.report and qa.log:
            print(f"\nSaved {qa.save_report(args.report)}")
    except DocError as err:
        sys.exit(f"Problem: {err}")


if __name__ == "__main__":
    main()
