"""Tests for app.py's /api/lookup route - scraper/LLM calls mocked."""

from unittest.mock import patch

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_index_serves_the_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Stock Lookup" in resp.data


def test_missing_ticker_returns_400(client):
    resp = client.get("/api/lookup")
    assert resp.status_code == 400


def test_invalid_ticker_characters_rejected(client):
    resp = client.get("/api/lookup?ticker=%3Cscript%3E")
    assert resp.status_code == 400


def test_valid_lookup_returns_price_news_and_summary(client):
    price = {"close": 100.0, "as_of": "2026-01-02", "change_pct": 1.0}
    news = [{"title": "Headline", "link": "https://example.com", "published": "today", "source": None}]
    with (
        patch("app.scraper.fetch_price", return_value=price),
        patch("app.scraper.fetch_news", return_value=news),
        patch("app.summarize", return_value="A short summary."),
    ):
        resp = client.get("/api/lookup?ticker=AAPL")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ticker"] == "AAPL"
    assert body["price"] == price
    assert body["news"] == news
    assert body["summary"] == "A short summary."


def test_price_fetch_failure_degrades_to_null_price_not_a_crash(client):
    import scraper

    with (
        patch("app.scraper.fetch_price", side_effect=scraper.ScraperError("boom")),
        patch("app.scraper.fetch_news", return_value=[]),
        patch("app.summarize", return_value="x"),
    ):
        resp = client.get("/api/lookup?ticker=AAPL")

    assert resp.status_code == 200
    assert resp.get_json()["price"] == {"close": None, "as_of": None, "change_pct": None}


def test_llm_failure_degrades_to_null_summary_not_a_crash(client):
    import llm_client

    with (
        patch("app.scraper.fetch_price", return_value={"close": 1.0, "as_of": "x", "change_pct": None}),
        patch("app.scraper.fetch_news", return_value=[]),
        patch("app.summarize", side_effect=llm_client.LlmError("no server")),
    ):
        resp = client.get("/api/lookup?ticker=AAPL")

    assert resp.status_code == 200
    assert resp.get_json()["summary"] is None


def test_ticker_is_uppercased(client):
    with (
        patch("app.scraper.fetch_price", return_value={"close": None, "as_of": None, "change_pct": None}),
        patch("app.scraper.fetch_news", return_value=[]),
        patch("app.summarize", return_value="x"),
    ):
        resp = client.get("/api/lookup?ticker=aapl")

    assert resp.get_json()["ticker"] == "AAPL"
