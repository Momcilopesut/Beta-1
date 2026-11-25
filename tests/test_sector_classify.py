"""Tests for sector_classify.py - network calls mocked, database swapped
to a temp file, sleep patched out so the test suite doesn't actually wait."""

from unittest.mock import MagicMock, patch

import pytest
import requests

import db
import sector_classify
from sector_classify import SectorFetchError, classify_pending, fetch_sector


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.db")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("sector_classify.time.sleep", lambda _: None)


@pytest.fixture(autouse=True)
def reset_crumb(monkeypatch):
    # _crumb is cached at module scope across calls (intentionally, in
    # real use) - reset it per test so tests don't leak state into each other.
    monkeypatch.setattr(sector_classify, "_crumb", None)


def _crumb_aware_get(profile_response: MagicMock, crumb: str = "testcrumb"):
    """A fake for _session.get that handles the cookie-seed + getcrumb
    handshake fetch_sector does before its real quoteSummary request."""

    def fake_get(url, timeout=None, **kwargs):
        response = MagicMock()
        response.raise_for_status.return_value = None
        if "fc.yahoo.com" in url:
            return response
        if "getcrumb" in url:
            response.text = crumb
            return response
        return profile_response

    return fake_get


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
    profile_response = _mock_response(_profile_payload("Technology", "Software"))
    with patch("sector_classify._session.get", side_effect=_crumb_aware_get(profile_response)):
        result = fetch_sector("AAPL")

    assert result == {"sector": "Technology", "industry": "Software"}


def test_fetch_sector_handles_missing_profile():
    profile_response = _mock_response({"quoteSummary": {"result": []}})
    with patch("sector_classify._session.get", side_effect=_crumb_aware_get(profile_response)):
        result = fetch_sector("NOSUCH")

    assert result == {"sector": None, "industry": None}


def test_fetch_sector_wraps_network_errors():
    with patch("sector_classify._session.get", side_effect=requests.ConnectionError("no route")):
        with pytest.raises(SectorFetchError):
            fetch_sector("AAPL")


def test_fetch_sector_refreshes_crumb_once_on_401_then_succeeds():
    profile_response = _mock_response(_profile_payload("Technology", "Software"))
    unauthorized = MagicMock(status_code=401)
    calls = {"quote_summary": 0}

    def fake_get(url, timeout=None, **kwargs):
        if "fc.yahoo.com" in url:
            ok = MagicMock()
            ok.raise_for_status.return_value = None
            return ok
        if "getcrumb" in url:
            ok = MagicMock()
            ok.raise_for_status.return_value = None
            ok.text = "testcrumb"
            return ok
        calls["quote_summary"] += 1
        return unauthorized if calls["quote_summary"] == 1 else profile_response

    with patch("sector_classify._session.get", side_effect=fake_get):
        result = fetch_sector("AAPL")

    assert result == {"sector": "Technology", "industry": "Software"}
    assert calls["quote_summary"] == 2


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
