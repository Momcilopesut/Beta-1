"""Tests for build_summaries.py - filing_text/llm_client calls mocked,
database swapped to a temp file, sleep patched out."""

from unittest.mock import patch

import pytest

import db
from build_summaries import build_for_sector, summarize_one
from filing_text import FilingTextError
from llm_client import LlmError, ModelCrashedError


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.db")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("build_summaries.time.sleep", lambda _: None)


def _seed_company_with_filing(cik: int, ticker: str, accession_number: str, sector: str = "Technology") -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO companies (cik, ticker, name, exchange, sector, sector_status) VALUES (?, ?, ?, 'NASDAQ', ?, 'done')",
            (cik, ticker, f"{ticker} Inc.", sector),
        )
        conn.execute(
            "INSERT INTO filings (cik, accession_number, form, filing_date, report_date, primary_document) "
            "VALUES (?, ?, '10-K', '2026-01-01', '2025-12-31', 'doc.htm')",
            (cik, accession_number),
        )
        conn.commit()
    finally:
        conn.close()


def test_build_for_sector_stores_summary_and_marks_done():
    _seed_company_with_filing(1, "AMD", "A1")
    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"Management's Discussion and Analysis": "..."}),
        patch("build_summaries.llm_client.summarize_filing", return_value="Revenue grew."),
    ):
        counts = build_for_sector("Technology")

    assert counts == {"done": 1, "errored": 0}
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM filing_summaries WHERE cik = 1 AND accession_number = 'A1'").fetchone()
    finally:
        conn.close()
    assert row["status"] == "done"
    assert row["summary"] == "Revenue grew."


def test_build_for_sector_only_processes_matching_sector():
    _seed_company_with_filing(1, "AMD", "A1", sector="Technology")
    _seed_company_with_filing(2, "JPM", "A2", sector="Financial Services")
    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", return_value="x") as mock_summarize,
    ):
        build_for_sector("Technology")

    mock_summarize.assert_called_once()
    assert mock_summarize.call_args[0][0] == "AMD"


def test_build_for_sector_marks_fetch_failure_as_error_without_crashing():
    _seed_company_with_filing(1, "BAD", "A1")
    _seed_company_with_filing(2, "AMD", "A2")

    def fake_fetch(cik, accession_number, primary_document):
        if accession_number == "A1":
            raise FilingTextError("boom")
        return "raw text"

    with (
        patch("build_summaries.filing_text.fetch_filing_text", side_effect=fake_fetch),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", return_value="Revenue grew."),
    ):
        counts = build_for_sector("Technology")

    assert counts == {"done": 1, "errored": 1}
    conn = db.get_connection()
    try:
        bad = conn.execute("SELECT status FROM filing_summaries WHERE cik = 1 AND accession_number = 'A1'").fetchone()
        good = conn.execute("SELECT status FROM filing_summaries WHERE cik = 2 AND accession_number = 'A2'").fetchone()
    finally:
        conn.close()
    assert bad["status"] == "error"
    assert good["status"] == "done"


def test_build_for_sector_marks_llm_failure_as_error():
    _seed_company_with_filing(1, "AMD", "A1")
    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", side_effect=LlmError("local model unreachable")),
    ):
        counts = build_for_sector("Technology")

    assert counts == {"done": 0, "errored": 1}


def test_build_for_sector_retries_errored_rows():
    _seed_company_with_filing(1, "AMD", "A1")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO filing_summaries (cik, accession_number, status) VALUES (1, 'A1', 'error')")
        conn.commit()
    finally:
        conn.close()

    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", return_value="Revenue grew."),
    ):
        counts = build_for_sector("Technology")

    assert counts == {"done": 1, "errored": 0}


def test_build_for_sector_skips_already_done_rows():
    _seed_company_with_filing(1, "AMD", "A1")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO filing_summaries (cik, accession_number, summary, status) VALUES (1, 'A1', 'x', 'done')")
        conn.commit()
    finally:
        conn.close()

    with patch("build_summaries.filing_text.fetch_filing_text") as mock_fetch:
        counts = build_for_sector("Technology")

    mock_fetch.assert_not_called()
    assert counts == {"done": 0, "errored": 0}


def test_summarize_one_recovers_from_a_transient_model_crash(monkeypatch):
    monkeypatch.setattr("build_summaries._CRASH_RETRY_ATTEMPTS", 3)
    row = {"cik": 1, "accession_number": "A1", "form": "10-K", "primary_document": "doc.htm", "ticker": "AMD"}
    calls = []

    def fake_summarize_filing(ticker, form, sections):
        calls.append(1)
        if len(calls) < 2:
            raise ModelCrashedError("backend crashed")
        return "Revenue grew."

    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", side_effect=fake_summarize_filing),
    ):
        result = summarize_one(row)

    assert result == "Revenue grew."
    assert len(calls) == 2


def test_summarize_one_gives_up_after_exhausting_crash_retries(monkeypatch):
    monkeypatch.setattr("build_summaries._CRASH_RETRY_ATTEMPTS", 2)
    row = {"cik": 1, "accession_number": "A1", "form": "10-K", "primary_document": "doc.htm", "ticker": "AMD"}

    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", side_effect=ModelCrashedError("backend crashed")) as mock_summarize,
    ):
        with pytest.raises(ModelCrashedError):
            summarize_one(row)

    assert mock_summarize.call_count == 2


def test_build_for_sector_stops_the_whole_batch_on_model_crash():
    _seed_company_with_filing(1, "AMD", "A1")
    _seed_company_with_filing(2, "MSFT", "A2")

    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", side_effect=ModelCrashedError("model has crashed")),
    ):
        counts = build_for_sector("Technology")

    # Neither row should be marked "error" - the model being down isn't a
    # per-filing failure, so both should stay untouched (pending) for the
    # next run to pick up once the model is reloaded.
    assert counts == {"done": 0, "errored": 0}
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT * FROM filing_summaries").fetchall()
    finally:
        conn.close()
    assert rows == []


def test_build_for_sector_respects_limit():
    _seed_company_with_filing(1, "AMD", "A1")
    _seed_company_with_filing(2, "MSFT", "A2")
    with (
        patch("build_summaries.filing_text.fetch_filing_text", return_value="raw text"),
        patch("build_summaries.filing_text.extract_sections_for_form", return_value={"x": "y"}),
        patch("build_summaries.llm_client.summarize_filing", return_value="x") as mock_summarize,
    ):
        build_for_sector("Technology", limit=1)

    mock_summarize.assert_called_once()
