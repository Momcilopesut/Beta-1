"""Tests for sector_classify.py - network calls mocked, database swapped
to a temp file, sleep patched out so the test suite doesn't actually wait."""

from unittest.mock import MagicMock, patch

import pytest
import requests

import db
from sector_classify import SectorFetchError, classify_pending, fetch_sector


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.db")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("sector_classify.time.sleep", lambda _: None)


def _seed_company(cik: int, ticker: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO companies (cik, ticker, name, exchange) VALUES (?, ?, ?, 'NASDAQ')",
            (cik, ticker, f"{ticker} Inc."),
        )
        conn.commit()
    finally:
        conn.close()


def _mock_response(json_payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = json_payload
    return response


def _profile_payload(sector: str | None, industry: str | None) -> dict:
    return {"quoteSummary": {"result": [{"assetProfile": {"sector": sector, "industry": industry}}]}}


def test_fetch_sector_parses_profile():
    with patch("sector_classify._session.get", return_value=_mock_response(_profile_payload("Technology", "Software"))):
        result = fetch_sector("AAPL")

    assert result == {"sector": "Technology", "industry": "Software"}


def test_fetch_sector_handles_missing_profile():
    with patch("sector_classify._session.get", return_value=_mock_response({"quoteSummary": {"result": []}})):
        result = fetch_sector("NOSUCH")

    assert result == {"sector": None, "industry": None}


def test_fetch_sector_wraps_network_errors():
    with patch("sector_classify._session.get", side_effect=requests.ConnectionError("no route")):
        with pytest.raises(SectorFetchError):
            fetch_sector("AAPL")


def test_classify_pending_stores_results_and_marks_done():
    _seed_company(1, "AAPL")
    with patch("sector_classify.fetch_sector", return_value={"sector": "Technology", "industry": "Software"}):
        counts = classify_pending()

    assert counts == {"done": 1, "errored": 0}
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM companies WHERE cik = 1").fetchone()
    finally:
        conn.close()
    assert row["sector"] == "Technology"
    assert row["sector_status"] == "done"


def test_classify_pending_marks_errors_without_crashing_the_batch():
    _seed_company(1, "BAD")
    _seed_company(2, "AAPL")

    def fake_fetch(ticker):
        if ticker == "BAD":
            raise SectorFetchError("boom")
        return {"sector": "Technology", "industry": "Software"}

    with patch("sector_classify.fetch_sector", side_effect=fake_fetch):
        counts = classify_pending()

    assert counts == {"done": 1, "errored": 1}
    conn = db.get_connection()
    try:
        bad = conn.execute("SELECT sector_status FROM companies WHERE cik = 1").fetchone()
        good = conn.execute("SELECT sector_status FROM companies WHERE cik = 2").fetchone()
    finally:
        conn.close()
    assert bad["sector_status"] == "error"
    assert good["sector_status"] == "done"


def test_classify_pending_retries_errored_rows():
    _seed_company(1, "AAPL")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE companies SET sector_status = 'error' WHERE cik = 1")
        conn.commit()
    finally:
        conn.close()

    with patch("sector_classify.fetch_sector", return_value={"sector": "Technology", "industry": "Software"}):
        counts = classify_pending()

    assert counts == {"done": 1, "errored": 0}


def test_classify_pending_skips_already_done_rows():
    _seed_company(1, "AAPL")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE companies SET sector = 'Technology', sector_status = 'done' WHERE cik = 1")
        conn.commit()
    finally:
        conn.close()

    with patch("sector_classify.fetch_sector") as mock_fetch:
        counts = classify_pending()

    mock_fetch.assert_not_called()
    assert counts == {"done": 0, "errored": 0}


def test_classify_pending_respects_limit():
    _seed_company(1, "AAPL")
    _seed_company(2, "MSFT")
    with patch("sector_classify.fetch_sector", return_value={"sector": "Technology", "industry": "Software"}) as mock_fetch:
        classify_pending(limit=1)

    mock_fetch.assert_called_once()
