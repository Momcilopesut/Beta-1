"""Tests for filings.py - network calls mocked via a fake session."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from filings import FilingsFetchError, fetch_filings


@pytest.fixture(autouse=True)
def sec_contact(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "Test User test@example.com")


def _recent_block(forms, accession_numbers, filing_dates, report_dates, primary_docs):
    return {
        "form": forms,
        "accessionNumber": accession_numbers,
        "filingDate": filing_dates,
        "reportDate": report_dates,
        "primaryDocument": primary_docs,
    }


def _mock_response(json_payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = json_payload
    return response


def _recent_date(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_fetch_filings_keeps_only_10k_and_10q_within_5_years():
    recent = _recent_block(
        forms=["10-K", "10-Q", "8-K", "10-Q"],
        accession_numbers=["A1", "A2", "A3", "A4"],
        filing_dates=[_recent_date(10), _recent_date(20), _recent_date(15), _recent_date(365 * 7)],
        report_dates=["2026-01-01", "2026-02-01", "2026-02-15", "2019-01-01"],
        primary_docs=["a1.htm", "a2.htm", "a3.htm", "a4.htm"],
    )
    payload = {"filings": {"recent": recent, "files": []}}
    with patch("filings.sec_client.get_session") as mock_get_session:
        mock_get_session.return_value.get.return_value = _mock_response(payload)
        result = fetch_filings(320193)

    accession_numbers = {f["accession_number"] for f in result}
    assert accession_numbers == {"A1", "A2"}


def test_fetch_filings_follows_paginated_older_files():
    recent = _recent_block(
        forms=["10-Q"],
        accession_numbers=["RECENT"],
        filing_dates=[_recent_date(5)],
        report_dates=["2026-02-01"],
        primary_docs=["recent.htm"],
    )
    older = _recent_block(
        forms=["10-K"],
        accession_numbers=["OLDER"],
        filing_dates=[_recent_date(400)],
        report_dates=["2025-01-01"],
        primary_docs=["older.htm"],
    )
    payload = {"filings": {"recent": recent, "files": [{"name": "CIK0000320193-submissions-001.json"}]}}

    def fake_get(url, timeout=None):
        if "submissions-001" in url:
            return _mock_response(older)
        return _mock_response(payload)

    with patch("filings.sec_client.get_session") as mock_get_session:
        mock_get_session.return_value.get.side_effect = fake_get
        result = fetch_filings(320193)

    accession_numbers = {f["accession_number"] for f in result}
    assert accession_numbers == {"RECENT", "OLDER"}


def test_fetch_filings_sorted_newest_first():
    recent = _recent_block(
        forms=["10-K", "10-Q"],
        accession_numbers=["OLD", "NEW"],
        filing_dates=[_recent_date(300), _recent_date(5)],
        report_dates=["2025-06-01", "2026-03-01"],
        primary_docs=["old.htm", "new.htm"],
    )
    payload = {"filings": {"recent": recent, "files": []}}
    with patch("filings.sec_client.get_session") as mock_get_session:
        mock_get_session.return_value.get.return_value = _mock_response(payload)
        result = fetch_filings(320193)

    assert [f["accession_number"] for f in result] == ["NEW", "OLD"]


def test_fetch_filings_wraps_network_errors():
    with patch("filings.sec_client.get_session") as mock_get_session:
        mock_get_session.return_value.get.side_effect = requests.ConnectionError("no route")
        with pytest.raises(FilingsFetchError):
            fetch_filings(320193)


def test_fetch_filings_wraps_unexpected_shape():
    with patch("filings.sec_client.get_session") as mock_get_session:
        mock_get_session.return_value.get.return_value = _mock_response({"unexpected": True})
        with pytest.raises(FilingsFetchError):
            fetch_filings(320193)
