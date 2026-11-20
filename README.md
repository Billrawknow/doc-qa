# Document Q&A

Ask questions about a PDF (or a Word or text file) and get short answers that **quote the document and cite the page**. If the document doesn't contain the answer, the tool says so instead of guessing.

Built for AI Masterclass 2, Week 6: Working with Documents.

```
$ python doc_qa.py samples/supply_agreement.pdf -q "What are the penalties if the supplier delivers late?"
supply_agreement.pdf: 11 page(s), 21,724 characters, 24 chunks (sending the best 6 chunks per question)

Q: What are the penalties if the supplier delivers late?

If the supplier delivers late, the buyer gets a discount, and can cancel in severe cases:

- **Discount:** 1% of the value of the late goods for each working day of delay, up to a maximum of 10%. [p. 2]
- **Cancellation:** If delivery is more than ten (10) working days late, the buyer may cancel that order without penalty and buy the goods elsewhere. [p. 2]
- **Deposit refund:** On cancellation, the supplier will refund any deposit paid for that order within seven (7) days. [p. 2]
- **Exception:** The supplier is not liable for delays caused by events outside its reasonable control, such as road closures, strikes, floods or factory shutdowns ("Force Majeure"), provided it notifies the buyer within 48 hours of becoming aware of the event. [p. 2]

The document does not state any other penalty, such as a fixed fee, for late delivery.

  (pages searched: 1, 2, 3 | 2,424 in / 303 out tokens | session cost $0.0004)
```

And when the answer isn't in the document, it says so instead of guessing:

```
Question> What does the contract say about fuel price increases?

The document doesn't say.

The excerpts contain nothing about fuel prices or fuel surcharges. The closest related content is clause 3, which allows the Supplier to change prices after the first three months with at least fourteen (14) days' written notice [p. 1], and a cap on cement increases of eight percent (8%) in any single quarter, unless the manufacturer's ex-factory price rises by more than that [p. 1]. Those rules apply to prices generally, not to fuel specifically.
```

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
               The last 3 questions are kept. A short follow-up ("And the pallet price?")
               also gets the passages from the previous question. A new topic is searched on its own.
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
pip install pytest
pytest -v                                # 50 tests, no API key or internet needed (Claude is mocked)
```

The tests cover:
- **Extraction:** pages, table rows on one line, footer removal, Word tables, and plain-English errors for a missing file, a scanned PDF ("run it through OCR"), a fake PDF and an unsupported type.
- **Chunking:** size, overlap, clean starts.
- **Retrieval:** the right clause for penalties, prices, interest, termination and warranty, and nothing for nonsense.
- **Answering:** only the chunks are sent for long documents, short ones are sent whole, history is kept for follow-ups, cost is tracked, there's a clear message for a missing key, and the Word report is created.
- **Reliability (`tests/test_reliability.py`, Day 29):** normal, empty and invalid input; special characters; Swahili; 10 repeated calls; retries and backoff; timeout; `errors.log`; and each bug below.

## Reliability (Day 29: Testing and Reliability)

Before changing anything, I probed the tool with the lesson's unusual inputs and failure cases to find what actually breaks.

### Bugs found and fixed

| # | Input or situation | Before | After |
|---|---|---|---|
| 1 | Question or answer containing control characters (`\x0b`, `\x0c`, `\x00`, common when pasting from PDFs) | **Crash** when saving the Word report: `ValueError: All strings must be XML compatible`. The whole session's answers were lost | Control characters are stripped from questions and from everything written to Word |
| 2 | Question in Swahili: *"Dhamana ya mabati ni miaka mingapi?"* (warranty on roofing sheets) | 0 keyword matches, so it silently sent pages 1-2. The warranty (page 3) was never seen, giving a wrong "The document doesn't say" | When nothing matches, a cheap Claude call (60 tokens max) turns the question into English keywords, then it searches again. Answers come back **in the question's language** |
| 3 | Answer longer than the token limit | Returned cut off mid-sentence ("The supplier must deliver within") as if complete | Flagged: *"This answer was cut short. Ask a narrower question to get the rest."* and logged |
| 4 | Any unexpected error, or Ctrl+C, during one question | Ended the interactive session, and the `--report` file was never written | That question fails with a plain message. The session continues and the report is still saved |
| 5 | Rate limit (429), server error (500), overload (529), dropped connection | One failure meant no answer. **No timeout at all**, so a hung request could wait forever | 30-second timeout, plus 3 attempts with exponential backoff (2s, 4s, with jitter). The API's `Retry-After` is honoured. A bad API key is **not** retried |
| 6 | 5,000-character "question" (usually a paste by mistake) | Sent in full: 11,000 characters billed | Rejected before any API call: *"That question is 5,000 characters long. Please keep it under 2,000"* |
| 7 | `-q "bad" -q "good"` where the first fails | Program exited, so the second question and the report were lost, with exit code 0 | Every question is tried, the report is saved, and the exit code is 1 so scripts can tell something failed |
| 8 | Used as a library (imported, no log configured) | Python's fallback logger printed warnings and tracebacks on the user's screen | Errors go only to `errors.log` |
| 9 | Empty or 5,000-character question *(found in the first real run)* | Rejected correctly, but nothing reached `errors.log` | Logged as `WARNING ... rejected input`, with a 200-character preview and the full length |
| 10 | 5,000-character question with `-q` *(real run)* | All 5,000 characters echoed back on the `Q:` line | Shows the first 200 characters plus `... (5,000 characters)` |
| 11 | Keyword rewrite for Swahili *(real run)* | Keyword line cut mid-word: `...corrugated iron s` | Claude is asked for at most 12 keywords, capped at 200 characters on a whole word |

### Real run: a Swahili question (20 Nov 2026)

```
$ python doc_qa.py samples/supply_agreement.pdf -q "Dhamana ya mabati ni miaka mingapi?"

  (no exact match; searched for: warranty period, guarantee period, warranty term, years, duration,
   galvanized iron sheets warranty, roofing sheets warranty, GI sheets warranty, ...)

Dhamana ya mabati (galvanised roofing sheets) ni miaka kumi (10) dhidi ya kutu kuharibu sheet
(rust-through) chini ya hali za kawaida. [p. 3]

Maelezo mengine yanayohusiana:
- Vifaa vya plumbing (plumbing fittings) vina dhamana ya miezi kumi na miwili (12) dhidi ya kasoro
  za utengenezaji. [p. 3]
- Mtoa huduma pia anahakikisha kwamba bidhaa zote zinakidhi viwango vya Kenya Bureau of Standards (KEBS). [p. 3]

  (pages searched: 1, 2, 3, 5, 6 | 3,488 in / 224 out tokens | session cost $0.0005)
```

Before the fix, this question searched pages 1-2 only and could not see the warranty clause on page 3. It now finds it, answers in Swahili, and cites the page. It costs $0.0005, including the keyword call.

### errors.log

Every failure is logged with a timestamp, the document, the reason, and **the input that caused it**, so it can be reproduced. Retries are logged as warnings. Successes are not logged, so 10 good calls in a row leave the log empty.

The first three lines below are from real runs. The last two show the format of a retry and a cut-off answer, taken from the tests:

```
2026-11-20 09:44:57,783 | ERROR | supply_agreement.pdf | The API key was rejected. Check ANTHROPIC_API_KEY in .env. | input: 'What is the credit limit?'
2026-11-20 09:54:36,836 | WARNING | supply_agreement.pdf | rejected input: No question provided. Please type a question first. | input: ''
2026-11-20 09:54:36,837 | WARNING | supply_agreement.pdf | rejected input: That question is 5,000 characters long. ... | input: 'xxxxxxxx...'... (5,000 chars)
2026-11-20 09:51:12,402 | WARNING | attempt 1/3 failed (RateLimitError), retrying in 2.4s
2026-11-20 09:51:20,118 | WARNING | supply_agreement.pdf | answer hit max_tokens | input: 'Summarise every clause in detail'
```

### Unusual-input checklist (lesson Step 4)

| Input | Result |
|---|---|
| Very long text (5,000+ chars) | Clean message, no API call |
| Empty string or whitespace | *"No question provided. Please type a question first."*, no API call |
| Special characters `<>&{}[]` | Sent to Claude exactly as typed. The Word report handles them |
| Non-English (Swahili) | Finds the right clause through the keyword rewrite and answers in Swahili |
| Same question 10 times | 10 consistent answers, nothing in `errors.log` |

The tests were checked by breaking the Swahili and Word-report fixes on purpose: the matching tests failed, then passed again once the fixes were restored.

### A bug found by real use

In the first live session, *"How much discount do we get for paying early?"* got "The document doesn't say", even though clause 8 gives 2% for paying within 7 days. The answer was honest but wrong.

The cause was retrieval, not the model. Each search included the previous question's words to help follow-ups, so the earlier "price of a Y12 bar... in bulk" filled all 6 slots with price-list chunks, and clause 8 was never sent.

The fix:
- Search with the current question first.
- Carry over passages from the previous question only for real follow-ups.
- Add "early" → "prompt/within" to the synonyms.

That session is now a regression test (`test_new_topic_is_not_drowned_by_the_previous_question`).

**The lesson:** when a RAG answer says "not in the document", check what was retrieved (`/search`) before blaming the model.

## Limits

- **Scanned PDFs** (photos of paper) have no text layer. Run them through OCR first, e.g. `ocrmypdf scan.pdf out.pdf`.
- **Keyword retrieval** can miss a passage that uses completely different words. The synonym list covers the usual contract cases, and questions with no matching words fall back to Claude-generated keywords. Embeddings would be the next step.
- **Answers are AI-generated.** The page citations are there so a person can check before relying on them.

## Files

| File | Purpose |
|---|---|
| `doc_qa.py` | The tool: extract, chunk, retrieve, answer (with retries and timeout), the Word report, and `errors.log` |
| `make_sample_pdf.py` | Builds the sample supply agreement (reportlab) |
| `samples/supply_agreement.pdf` | Sample document (all names and numbers are made up) |
| `tests/test_doc_qa.py` | 26 tests: extraction, chunking, retrieval, answering |
| `tests/test_reliability.py` | 24 tests: edge cases, retries, timeout, error log, regression tests for bugs 1-11 |
| `.env.example` | Where your API key goes (`.env` is git-ignored) |

## Stack

Python, pypdf, python-docx, the Anthropic SDK (Claude Haiku 5.5), python-dotenv, pytest and unittest.
