"""Tests for directory.py - network calls mocked, database swapped to a
temp file per test so nothing touches the real ~/.stocklookup/market.db."""

from unittest.mock import MagicMock, patch

import pytest
import requests

import db
from directory import DirectoryError, build_directory, fetch_sec_companies
from sec_client import SecConfigError


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.db")


@pytest.fixture(autouse=True)
def sec_contact(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "Test User test@example.com")


def _mock_response(json_payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = json_payload
    return response


def _sec_payload(rows: list[list]) -> dict:
    return {"fields": ["cik", "name", "ticker", "exchange"], "data": rows}


def test_fetch_sec_companies_keeps_only_nyse_and_nasdaq():
    payload = _sec_payload(
        [
            [1, "Apple Inc.", "AAPL", "Nasdaq"],
            [2, "Example Corp", "EX", "NYSE"],
            [3, "Some OTC Co", "OTCX", "OTC Markets"],
            [4, "No Exchange Co", "NOEX", ""],
        ]
    )
    with patch("requests.Session.get", return_value=_mock_response(payload)):
        result = fetch_sec_companies()

    tickers = {row["ticker"] for row in result}
    assert tickers == {"AAPL", "EX"}


def test_fetch_sec_companies_requires_contact_email(monkeypatch):
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    with pytest.raises(SecConfigError):
        fetch_sec_companies()


def test_fetch_sec_companies_sends_contact_in_user_agent():
    payload = _sec_payload([[1, "Apple Inc.", "AAPL", "Nasdaq"]])
    captured_headers = {}

    def fake_get(self, *args, **kwargs):
        captured_headers.update(self.headers)
        return _mock_response(payload)

    with patch("requests.Session.get", fake_get):
        fetch_sec_companies()

    assert "test@example.com" in captured_headers.get("User-Agent", "")


def test_fetch_sec_companies_wraps_network_errors():
    with patch("requests.Session.get", side_effect=requests.ConnectionError("no route")):
        with pytest.raises(DirectoryError):
            fetch_sec_companies()


def test_fetch_sec_companies_wraps_unexpected_shape():
    with patch("requests.Session.get", return_value=_mock_response({"unexpected": True})):
        with pytest.raises(DirectoryError):
            fetch_sec_companies()


def test_build_directory_stores_rows_and_is_idempotent():
    payload = _sec_payload([[1, "Apple Inc.", "AAPL", "Nasdaq"]])
    with patch("requests.Session.get", return_value=_mock_response(payload)):
        count = build_directory()
        count_again = build_directory()

    assert count == 1
    assert count_again == 1
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM companies WHERE cik = 1").fetchone()
    finally:
        conn.close()
    assert row["ticker"] == "AAPL"
    assert row["sector_status"] == "pending"


def test_build_directory_does_not_reset_existing_sector_classification():
    payload = _sec_payload([[1, "Apple Inc.", "AAPL", "Nasdaq"]])
    with patch("requests.Session.get", return_value=_mock_response(payload)):
        build_directory()

    conn = db.get_connection()
    try:
        conn.execute("UPDATE companies SET sector = 'Technology', sector_status = 'done' WHERE cik = 1")
        conn.commit()
    finally:
        conn.close()

    with patch("requests.Session.get", return_value=_mock_response(payload)):
        build_directory()

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM companies WHERE cik = 1").fetchone()
    finally:
        conn.close()
    assert row["sector"] == "Technology"
    assert row["sector_status"] == "done"
