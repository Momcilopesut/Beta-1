"""Tests for app.py's HTTP-level behavior: the local on-demand /api/lookup
(what used to be api/lookup.py's Vercel function) and the background
/api/refresh + /api/refresh/status (what used to be the scheduled
weekly-screen.yml GitHub Action). The actual fetch/score/qualitative and
run_full() calls are mocked - that logic is already covered by
pipeline/main.py's own tests; this file only verifies the request-handling
and background-thread wrapper around it."""

import threading
import time

from unittest.mock import patch

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    app_module._refresh_state.update(status="idle", started_at=None, finished_at=None, message=None)
    if app_module._refresh_lock.locked():
        app_module._refresh_lock.release()
    return app_module.app.test_client()


def _mock_lookup_pipeline():
    return (
        patch(
            "app.fetch_and_score_company",
            return_value={
                "metrics": {},
                "display": {"price": {}},
                "raw": {"income_stmts": [], "balance_stmts": [], "cashflow_stmts": []},
                "profile": {},
            },
        ),
        patch("app.finalize_company", return_value=({"ticker": "MSFT"}, {}, False)),
        patch("app._macro_context", return_value=({}, {"regime": "Neutral/Expansion", "signals": {}}, [])),
    )


def _wait_until_idle_or_done(client, max_wait_seconds: float = 2.0) -> dict:
    deadline = time.time() + max_wait_seconds
    status = {}
    while time.time() < deadline:
        status = client.get("/api/refresh/status").get_json()
        if status["status"] != "running":
            return status
        time.sleep(0.01)
    return status


# --- Static serving ---


def test_index_serves_site_index_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Top Performers" in resp.data


def test_static_serves_repo_files(client):
    resp = client.get("/site/css/styles.css")
    assert resp.status_code == 200


# --- /api/lookup ---


def test_missing_ticker_returns_400(client):
    resp = client.get("/api/lookup")
    assert resp.status_code == 400


def test_invalid_ticker_characters_rejected(client):
    resp = client.get("/api/lookup?ticker=%3Cscript%3E")
    assert resp.status_code == 400


def test_ticker_too_long_rejected(client):
    resp = client.get("/api/lookup?ticker=" + "A" * 20)
    assert resp.status_code == 400


def test_valid_lookup_returns_on_demand_doc(client):
    m1, m2, m3 = _mock_lookup_pipeline()
    with m1, m2, m3:
        resp = client.get("/api/lookup?ticker=MSFT")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ticker"] == "MSFT"
    assert body["on_demand"] is True


def test_lookup_never_uses_fmp(client):
    m1, m2, m3 = _mock_lookup_pipeline()
    with m1 as mock_fetch, m2, m3:
        client.get("/api/lookup?ticker=MSFT")
    assert mock_fetch.call_args.kwargs["use_fmp"] is False


def test_skip_ai_flag_passed_through_to_finalize_company(client):
    m1, m2, m3 = _mock_lookup_pipeline()
    with m1, m2 as mock_finalize, m3:
        client.get("/api/lookup?ticker=MSFT&ai=0")
    assert mock_finalize.call_args[0][2] is True  # (state, regime_info, skip_ai)


def test_ai_defaults_to_enabled(client):
    m1, m2, m3 = _mock_lookup_pipeline()
    with m1, m2 as mock_finalize, m3:
        client.get("/api/lookup?ticker=MSFT")
    assert mock_finalize.call_args[0][2] is False


def test_upstream_failure_returns_502_with_ticker_in_message(client):
    with (
        patch("app.fetch_and_score_company", side_effect=RuntimeError("boom")),
        patch("app._macro_context", return_value=({}, {"regime": "Neutral/Expansion", "signals": {}}, [])),
    ):
        resp = client.get("/api/lookup?ticker=ZZZZ")
    assert resp.status_code == 502
    assert "ZZZZ" in resp.get_json()["error"]


# --- /api/refresh + /api/refresh/status ---


def test_refresh_starts_and_reaches_done(client):
    with patch("app.run_full", return_value=0):
        resp = client.post("/api/refresh")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "started"
        status = _wait_until_idle_or_done(client)
    assert status["status"] == "done"


def test_refresh_reports_error_when_run_full_fails_outright(client):
    with patch("app.run_full", side_effect=RuntimeError("boom")):
        client.post("/api/refresh")
        status = _wait_until_idle_or_done(client)
    assert status["status"] == "error"
    assert "boom" in status["message"]


def test_refresh_reports_error_when_run_full_returns_nonzero(client):
    with patch("app.run_full", return_value=1):
        client.post("/api/refresh")
        status = _wait_until_idle_or_done(client)
    assert status["status"] == "error"


def test_concurrent_refresh_rejected_with_409(client):
    release = threading.Event()

    def blocking_run_full(_args):
        release.wait(timeout=2)
        return 0

    with patch("app.run_full", side_effect=blocking_run_full):
        resp1 = client.post("/api/refresh")
        assert resp1.get_json()["status"] == "started"

        resp2 = client.post("/api/refresh")
        assert resp2.status_code == 409
        assert resp2.get_json()["status"] == "already_running"

        release.set()
        _wait_until_idle_or_done(client)


def test_refresh_passes_tickers_and_skip_ai_through_to_run_full(client):
    with patch("app.run_full", return_value=0) as mock_run_full:
        client.post("/api/refresh", json={"tickers": "AAPL,MSFT", "skip_ai": True})
        _wait_until_idle_or_done(client)

    sent_args = mock_run_full.call_args[0][0]
    assert sent_args.tickers == "AAPL,MSFT"
    assert sent_args.skip_ai is True
    assert sent_args.use_fmp is False
    assert sent_args.dry_run is False
