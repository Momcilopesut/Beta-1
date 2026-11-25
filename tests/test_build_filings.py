"""Tests for build_filings.py - filings.fetch_filings mocked, database
swapped to a temp file, sleep patched out."""

from unittest.mock import patch

import pytest

import db
from build_filings import build_for_sector
from filings import FilingsFetchError


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.db")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("build_filings.time.sleep", lambda _: None)


def _seed_company(cik: int, ticker: str, sector: str = "Technology") -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO companies (cik, ticker, name, exchange, sector, sector_status) VALUES (?, ?, ?, 'NASDAQ', ?, 'done')",
            (cik, ticker, f"{ticker} Inc.", sector),
        )
        conn.commit()
    finally:
        conn.close()


def _filing(accession_number: str) -> dict:
    return {
        "accession_number": accession_number,
        "form": "10-K",
        "filing_date": "2026-01-01",
        "report_date": "2025-12-31",
        "primary_document": "doc.htm",
    }


def test_build_for_sector_stores_filings_and_marks_done():
    _seed_company(1, "AAPL")
    with patch("build_filings.filings.fetch_filings", return_value=[_filing("A1"), _filing("A2")]):
        counts = build_for_sector("Technology")

    assert counts == {"done": 1, "errored": 0}
    conn = db.get_connection()
    try:
        company = conn.execute("SELECT filings_status FROM companies WHERE cik = 1").fetchone()
        stored = conn.execute("SELECT accession_number FROM filings WHERE cik = 1").fetchall()
    finally:
        conn.close()
    assert company["filings_status"] == "done"
    assert {row["accession_number"] for row in stored} == {"A1", "A2"}


def test_build_for_sector_only_processes_matching_sector():
    _seed_company(1, "AAPL", sector="Technology")
    _seed_company(2, "JPM", sector="Financial Services")
    with patch("build_filings.filings.fetch_filings", return_value=[_filing("A1")]) as mock_fetch:
        build_for_sector("Technology")

    mock_fetch.assert_called_once_with(1)


def test_build_for_sector_marks_errors_without_crashing_the_batch():
    _seed_company(1, "BAD")
    _seed_company(2, "AAPL")

    def fake_fetch(cik):
        if cik == 1:
            raise FilingsFetchError("boom")
        return [_filing("A1")]

    with patch("build_filings.filings.fetch_filings", side_effect=fake_fetch):
        counts = build_for_sector("Technology")

    assert counts == {"done": 1, "errored": 1}
    conn = db.get_connection()
    try:
        bad = conn.execute("SELECT filings_status FROM companies WHERE cik = 1").fetchone()
        good = conn.execute("SELECT filings_status FROM companies WHERE cik = 2").fetchone()
    finally:
        conn.close()
    assert bad["filings_status"] == "error"
    assert good["filings_status"] == "done"


def test_build_for_sector_retries_errored_rows():
    _seed_company(1, "AAPL")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE companies SET filings_status = 'error' WHERE cik = 1")
        conn.commit()
    finally:
        conn.close()

    with patch("build_filings.filings.fetch_filings", return_value=[_filing("A1")]):
        counts = build_for_sector("Technology")

    assert counts == {"done": 1, "errored": 0}


def test_build_for_sector_skips_already_done_rows():
    _seed_company(1, "AAPL")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE companies SET filings_status = 'done' WHERE cik = 1")
        conn.commit()
    finally:
        conn.close()

    with patch("build_filings.filings.fetch_filings") as mock_fetch:
        counts = build_for_sector("Technology")

    mock_fetch.assert_not_called()
    assert counts == {"done": 0, "errored": 0}


def test_build_for_sector_respects_limit():
    _seed_company(1, "AAPL")
    _seed_company(2, "MSFT")
    with patch("build_filings.filings.fetch_filings", return_value=[_filing("A1")]) as mock_fetch:
        build_for_sector("Technology", limit=1)

    mock_fetch.assert_called_once()


def test_build_for_sector_upsert_is_idempotent():
    _seed_company(1, "AAPL")
    with patch("build_filings.filings.fetch_filings", return_value=[_filing("A1")]):
        build_for_sector("Technology")

    conn = db.get_connection()
    try:
        conn.execute("UPDATE companies SET filings_status = 'pending' WHERE cik = 1")
        conn.commit()
    finally:
        conn.close()

    with patch("build_filings.filings.fetch_filings", return_value=[_filing("A1")]):
        build_for_sector("Technology")

    conn = db.get_connection()
    try:
        stored = conn.execute("SELECT * FROM filings WHERE cik = 1").fetchall()
    finally:
        conn.close()
    assert len(stored) == 1
