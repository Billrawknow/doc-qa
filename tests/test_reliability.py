"""
Reliability tests (Day 29): normal / empty / invalid input, unusual inputs, retries with
backoff, timeouts, error logging with the input, and the bugs found by probing.

    pytest -v                       # runs these and the original unittest tests
"""

import logging
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import anthropic
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import doc_qa  # noqa: E402

SAMPLE = ROOT / "samples" / "supply_agreement.pdf"


# ------------------------------------------------------------------ helpers

def reply(text="The Buyer gets 1% per day, up to 10% [p. 2].", stop="end_turn"):
    return NS(content=[NS(type="text", text=text)], stop_reason=stop,
              usage=NS(input_tokens=2000, output_tokens=100))


class FakeClient:
    """Replays scripted replies or errors, and records every request."""

    def __init__(self, *replies):
        self.replies = list(replies) or [reply()]
        self.requests = []
        self.messages = NS(create=self.create)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(item, Exception):
            raise item
        return item


def api_error(cls, status=0, retry_after=None):
    """An SDK error without a real HTTP response (works across anthropic SDK versions)."""
    err = cls.__new__(cls)
    Exception.__init__(err, f"error {status}")
    err.message, err.status_code, err.body = f"error {status}", status, None
    err.response = NS(headers={"retry-after": str(retry_after)} if retry_after else {})
    return err


@pytest.fixture
def qa():
    return doc_qa.DocumentQA(SAMPLE, client=FakeClient())


@pytest.fixture
def no_sleep():
    with mock.patch("time.sleep") as sleep, mock.patch("builtins.print"):
        yield sleep


@pytest.fixture
def error_log(tmp_path):
    """Send the doc_qa logger to a temp errors.log; return a function that reads it."""
    path = tmp_path / "errors.log"
    logger = logging.getLogger("doc_qa")
    old = logger.handlers[:]
    logger.handlers = []
    doc_qa.setup_error_log(path)
    yield lambda: path.read_text(encoding="utf-8") if path.exists() else ""
    for h in logger.handlers:
        h.close()
    logger.handlers = old


# ------------------------------------------------------------------ Step 1: normal, empty, invalid

def test_normal_input(qa):
    answer, pages, _ = qa.ask("What are the penalties if the supplier delivers late?")
    assert answer is not None and len(answer) > 10
    assert 2 in pages


@pytest.mark.parametrize("empty", ["", "   ", "\n\t ", None])
def test_empty_input(qa, empty):
    with pytest.raises(doc_qa.DocError, match="No question provided"):
        qa.ask(empty)
    assert qa.client.requests == []                         # no API call, no cost


def test_invalid_input_very_long(qa):
    with pytest.raises(doc_qa.DocError, match="5,000 characters long. Please keep it under 2,000"):
        qa.ask("x" * 5000)
    assert qa.client.requests == []                         # rejected before paying for 11,000 chars


# ------------------------------------------------------------------ Step 4: unusual inputs

def test_special_characters_reach_the_api_intact(qa):
    qa.ask("Does clause 8 mention <b>, & or {curly} [brackets]?")
    sent = qa.client.requests[-1]["messages"][-1]["content"]
    assert "<b>, & or {curly} [brackets]" in sent              # not escaped, mangled or dropped


def test_control_characters_do_not_crash_the_word_report(tmp_path):
    # BUG 1 found by probing: text pasted from a PDF carries \x0b/\x0c/\x00, and python-docx
    # raised "All strings must be XML compatible", losing the whole session's report.
    qa = doc_qa.DocumentQA(SAMPLE, client=FakeClient(reply("Limit is KES 800,000\x0b\x00 [p. 2]")))
    qa.ask("What is\x0c the credit limit?")
    out = qa.save_report(tmp_path / "report.docx")
    import docx
    text = "\n".join(p.text for p in docx.Document(out).paragraphs)
    assert "What is the credit limit?" in text
    assert "KES 800,000" in text


def test_swahili_question_finds_the_right_clause():
    # BUG 2: keyword search matched nothing in Swahili, so it silently sent pages 1-2 and the
    # answer (warranty, page 3) was never seen. Now Claude turns the question into English keywords.
    client = FakeClient(reply("roofing sheets warranty years galvanised rust"),
                        reply("Mabati yana dhamana ya miaka kumi (10) [p. 3]."))
    qa = doc_qa.DocumentQA(SAMPLE, client=client)
    answer, pages, _ = qa.ask("Dhamana ya mabati ni miaka mingapi?")
    assert qa.retriever.search("Dhamana ya mabati ni miaka mingapi?") == []     # still no direct match
    assert "Translate if it isn't English" in client.requests[0]["messages"][0]["content"]
    assert client.requests[0]["max_tokens"] == 60                                 # a cheap call
    assert "ten (10) years" in client.requests[1]["messages"][-1]["content"]      # warranty clause sent
    assert "same language as the question" in client.requests[1]["system"]
    assert qa.last_keywords.startswith("roofing sheets warranty")


def test_english_question_does_not_pay_for_keyword_rewrite(qa):
    qa.ask("What is the warranty on roofing sheets?")
    assert len(qa.client.requests) == 1


def test_repeated_calls_same_quality_no_log_noise(qa, error_log):
    for _ in range(10):
        answer, pages, _ = qa.ask("What is the credit limit?")
        assert "[p." in answer
    assert len(qa.client.requests) == 10
    assert error_log() == ""                                    # successes don't fill errors.log


# ------------------------------------------------------------------ Step 2: retries with backoff

def test_rate_limit_is_retried_with_exponential_backoff(no_sleep):
    client = FakeClient(api_error(anthropic.RateLimitError, 429), api_error(anthropic.RateLimitError, 429), reply())
    qa = doc_qa.DocumentQA(SAMPLE, client=client)
    answer, _, _ = qa.ask("What is the credit limit?")
    assert "[p. 2]" in answer
    assert len(client.requests) == 3
    waits = [c.args[0] for c in no_sleep.call_args_list]
    assert 2 <= waits[0] < 3 and 4 <= waits[1] < 5              # 2s, 4s (+ up to 1s jitter)


def test_retry_after_header_is_respected(no_sleep):
    client = FakeClient(api_error(anthropic.RateLimitError, 429, retry_after=7), reply())
    doc_qa.DocumentQA(SAMPLE, client=client).ask("What is the credit limit?")
    assert no_sleep.call_args_list[0].args[0] == 7


def test_server_errors_and_overload_are_retried(no_sleep):
    overloaded = getattr(anthropic, "OverloadedError", anthropic.InternalServerError)
    client = FakeClient(api_error(anthropic.InternalServerError, 500), api_error(overloaded, 529), reply())
    answer, _, _ = doc_qa.DocumentQA(SAMPLE, client=client).ask("What is the credit limit?")
    assert "[p. 2]" in answer


def test_gives_up_after_three_tries_and_logs_the_input(no_sleep, error_log):
    timeout = getattr(anthropic, "APITimeoutError", anthropic.APIConnectionError)
    client = FakeClient(api_error(timeout))
    qa = doc_qa.DocumentQA(SAMPLE, client=client)
    with pytest.raises(doc_qa.DocError, match="didn't answer after 3 tries"):
        qa.ask("What is the credit limit?")
    assert len(client.requests) == 3
    log = error_log()
    assert "| ERROR | supply_agreement.pdf |" in log
    assert "input: 'What is the credit limit?'" in log          # Step 3: the input that caused it
    assert log.count("| WARNING | attempt") == 2                # each retry recorded


def test_bad_api_key_is_not_retried(no_sleep):
    client = FakeClient(api_error(anthropic.AuthenticationError, 401))
    with pytest.raises(doc_qa.DocError, match="API key was rejected"):
        doc_qa.DocumentQA(SAMPLE, client=client).ask("What is the credit limit?")
    assert len(client.requests) == 1
    no_sleep.assert_not_called()


# ------------------------------------------------------------------ Step 5: timeout

def test_client_is_created_with_a_timeout_and_our_own_retries():
    with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}), \
            mock.patch.object(anthropic, "Anthropic") as make_client:
        make_client.return_value = FakeClient()
        doc_qa.DocumentQA(SAMPLE).ask("What is the credit limit?")
    kwargs = make_client.call_args.kwargs
    assert kwargs["timeout"] == 30
    assert kwargs["max_retries"] == 0                           # SDK retries off: ours are logged and visible


# ------------------------------------------------------------------ other bugs found

def test_cut_off_answer_is_flagged(error_log):
    # BUG 3: an answer stopped by max_tokens looked complete ("must deliver within").
    qa = doc_qa.DocumentQA(SAMPLE, client=FakeClient(reply("The supplier must deliver within", stop="max_tokens")))
    answer, _, _ = qa.ask("Summarise every clause in detail")
    assert answer.endswith("(This answer was cut short. Ask a narrower question to get the rest.)")
    assert "answer hit max_tokens" in error_log()


def test_one_bad_question_does_not_end_the_session(qa, error_log, capsys):
    # BUG 4: any unexpected error inside a question killed the interactive session (and the report).
    original = qa.ask
    calls = iter([ValueError("weird"), KeyboardInterrupt(), None])

    def flaky(question):
        problem = next(calls)
        if problem:
            raise problem
        return original(question)

    qa.ask = flaky
    questions = iter(["first", "second", "What is the credit limit?", "/quit"])
    with mock.patch("builtins.input", lambda *_: next(questions)):
        doc_qa.interactive(qa)
    out = capsys.readouterr().out
    assert "Something went wrong with that question" in out
    assert "Cancelled." in out
    assert "[p. 2]" in out                                     # the third question still got answered
    assert "unexpected ValueError: weird | input: 'first'" in error_log()


def test_question_flag_mode_keeps_going_after_a_failed_question(tmp_path, monkeypatch, capsys):
    client = FakeClient(api_error(anthropic.BadRequestError, 400), reply())
    monkeypatch.setattr(doc_qa, "setup_error_log", lambda: None)
    real = doc_qa.DocumentQA
    monkeypatch.setattr(doc_qa, "DocumentQA", lambda path: real(path, client=client))
    out_file = tmp_path / "answers.docx"
    monkeypatch.setattr(sys, "argv", ["doc_qa.py", str(SAMPLE), "-q", "bad one", "-q", "good one",
                                      "--report", str(out_file)])
    with pytest.raises(SystemExit) as exit_:
        doc_qa.main()
    assert exit_.value.code == 1                                # a script can tell one question failed
    assert "Problem:" in capsys.readouterr().out
    assert out_file.exists()                                    # report still saved with the good answer


def test_library_use_never_prints_tracebacks(capsys):
    logging.getLogger("doc_qa").error("something failed")       # no errors.log configured
    assert capsys.readouterr().err == ""


# ------------------------------------------------------------------ found in the first real run (20 Nov)

def test_rejected_input_is_logged_with_a_short_preview(qa, error_log):
    # BUG 9: empty and over-long questions were rejected but never reached errors.log.
    for bad in ("", "x" * 5000):
        with pytest.raises(doc_qa.DocError):
            qa.ask(bad)
    log = error_log()
    assert log.count("| WARNING | supply_agreement.pdf | rejected input:") == 2
    assert "input: ''" in log
    assert "... (5,000 chars)" in log and "x" * 201 not in log       # preview, not the whole paste


def test_long_question_is_not_echoed_in_full(monkeypatch, capsys):
    # BUG 10: -q echoed all 5,000 characters back on the "Q:" line.
    monkeypatch.setattr(doc_qa, "setup_error_log", lambda: None)
    monkeypatch.setattr(sys, "argv", ["doc_qa.py", str(SAMPLE), "-q", "x" * 5000])
    with pytest.raises(SystemExit):
        doc_qa.main()
    out = capsys.readouterr().out
    assert "... (5,000 characters)" in out and "x" * 201 not in out


def test_keywords_are_capped_on_a_word_boundary():
    # BUG 11: the keyword line was cut mid-word ("corrugated iron s").
    many = " ".join(["warranty", "guarantee", "roofing sheets", "galvanized iron", "corrugated iron"] * 10)
    qa = doc_qa.DocumentQA(SAMPLE, client=FakeClient(reply(many)))
    keywords = qa.english_keywords("Dhamana ya mabati?")
    assert len(keywords) <= 200
    assert many.startswith(keywords) and many[len(keywords)] == " "  # ends on a whole word

