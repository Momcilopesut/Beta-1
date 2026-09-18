"""Tests for the api/lookup.py Vercel function's HTTP-level behavior:
access control, ticker validation, CORS, and error handling. The actual
fetch/score/narrative calls are mocked - that logic is already covered by
pipeline/main.py's own code path and tests; this file only verifies the
request-handling wrapper around it."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import lookup  # noqa: E402


@pytest.fixture
def client():
    lookup.app.config["TESTING"] = True
    return lookup.app.test_client()


def _mock_pipeline():
    return (
        patch("lookup.fetch_and_score_company", return_value={"metrics": {}, "display": {"price": {}}}),
        patch("lookup.finalize_company", return_value=({"ticker": "MSFT"}, {}, 0, False)),
        patch("lookup._regime", return_value={"regime": "Neutral/Expansion", "signals": {}}),
    )


def test_missing_ticker_returns_400(client):
    resp = client.get("/api/lookup")
    assert resp.status_code == 400


def test_invalid_ticker_characters_rejected(client):
    resp = client.get("/api/lookup?ticker=%3Cscript%3E")
    assert resp.status_code == 400


def test_ticker_too_long_rejected(client):
    resp = client.get("/api/lookup?ticker=" + "A" * 20)
    assert resp.status_code == 400


def test_dotted_share_class_ticker_accepted(client, monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    m1, m2, m3 = _mock_pipeline()
    with m1, m2, m3:
        resp = client.get("/api/lookup?ticker=BRK.B")
    assert resp.status_code == 200


def test_search_key_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "secret123")
    resp = client.get("/api/lookup?ticker=AAPL")
    assert resp.status_code == 401


def test_search_key_accepted_via_header(client, monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "secret123")
    m1, m2, m3 = _mock_pipeline()
    with m1, m2, m3:
        resp = client.get("/api/lookup?ticker=AAPL", headers={"X-Search-Key": "secret123"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ticker"] == "MSFT"  # from the mocked finalize_company return
    assert body["on_demand"] is True


def test_search_key_accepted_via_query_param(client, monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "secret123")
    m1, m2, m3 = _mock_pipeline()
    with m1, m2, m3:
        resp = client.get("/api/lookup?ticker=AAPL&key=secret123")
    assert resp.status_code == 200


def test_wrong_search_key_rejected(client, monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "secret123")
    resp = client.get("/api/lookup?ticker=AAPL&key=wrong")
    assert resp.status_code == 401


def test_access_open_when_search_key_unset(client, monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    m1, m2, m3 = _mock_pipeline()
    with m1, m2, m3:
        resp = client.get("/api/lookup?ticker=MSFT")
    assert resp.status_code == 200


def test_cors_headers_present(client, monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    m1, m2, m3 = _mock_pipeline()
    with m1, m2, m3:
        resp = client.get("/api/lookup?ticker=MSFT")
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"


def test_options_preflight_handled(client):
    resp = client.options("/api/lookup")
    assert resp.status_code == 200
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"


def test_upstream_failure_returns_502_with_ticker_in_message(client, monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    with (
        patch("lookup.fetch_and_score_company", side_effect=RuntimeError("boom")),
        patch("lookup._regime", return_value={"regime": "Neutral/Expansion", "signals": {}}),
    ):
        resp = client.get("/api/lookup?ticker=ZZZZ")
    assert resp.status_code == 502
    assert "ZZZZ" in resp.get_json()["error"]


def test_skip_ai_flag_passed_through_to_finalize_company(client, monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    m1, m2, m3 = _mock_pipeline()
    with m1, m2 as mock_finalize, m3:
        client.get("/api/lookup?ticker=MSFT&ai=0")
    assert mock_finalize.call_args[0][2] is True  # (state, regime_info, skip_ai)


def test_ai_defaults_to_enabled(client, monkeypatch):
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    m1, m2, m3 = _mock_pipeline()
    with m1, m2 as mock_finalize, m3:
        client.get("/api/lookup?ticker=MSFT")
    assert mock_finalize.call_args[0][2] is False
