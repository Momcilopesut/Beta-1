"""Tests for scraper.py - pure parsing logic, network calls mocked."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper import ScraperError, fetch_news, fetch_price


def _mock_response(json_payload=None, text: str | None = None) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    if json_payload is not None:
        response.json.return_value = json_payload
    if text is not None:
        response.text = text
    return response


def _chart_payload(timestamps: list[int], closes: list[float | None]) -> dict:
    return {"chart": {"result": [{"timestamp": timestamps, "indicators": {"quote": [{"close": closes}]}}]}}


def test_fetch_price_parses_latest_close_and_change_pct():
    # 2026-01-01 and 2026-01-02 at midnight UTC.
    payload = _chart_payload([1767225600, 1767312000], [100.0, 105.0])
    with patch("scraper._session.get", return_value=_mock_response(json_payload=payload)):
        result = fetch_price("AAPL")

    assert result["close"] == 105.0
    assert result["as_of"] == "2026-01-02"
    assert result["change_pct"] == pytest.approx(5.0)


def test_fetch_price_skips_null_closes_from_a_still_trading_session():
    """Yahoo's chart API pads today's close with null until the market
    actually closes - these must be filtered out, not treated as a real
    (zero) price or as the latest value."""
    payload = _chart_payload([1767225600, 1767312000, 1767398400], [100.0, 105.0, None])
    with patch("scraper._session.get", return_value=_mock_response(json_payload=payload)):
        result = fetch_price("AAPL")

    assert result["close"] == 105.0
    assert result["as_of"] == "2026-01-02"


def test_fetch_price_single_close_has_no_change_pct():
    payload = _chart_payload([1767312000], [105.0])
    with patch("scraper._session.get", return_value=_mock_response(json_payload=payload)):
        result = fetch_price("AAPL")

    assert result["close"] == 105.0
    assert result["change_pct"] is None


def test_fetch_price_handles_ticker_with_no_data():
    empty_payload = {"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{"close": []}]}}]}}
    with patch("scraper._session.get", return_value=_mock_response(json_payload=empty_payload)):
        result = fetch_price("NOSUCHTICKER")

    assert result == {"close": None, "as_of": None, "change_pct": None}


def test_fetch_price_handles_unexpected_response_shape():
    with patch("scraper._session.get", return_value=_mock_response(json_payload={"chart": {"result": None}})):
        result = fetch_price("AAPL")

    assert result == {"close": None, "as_of": None, "change_pct": None}


def test_fetch_price_wraps_network_errors():
    with patch("scraper._session.get", side_effect=requests.ConnectionError("no route")):
        with pytest.raises(ScraperError):
            fetch_price("AAPL")


def test_fetch_price_wraps_non_json_responses():
    bad_response = MagicMock()
    bad_response.raise_for_status.return_value = None
    bad_response.json.side_effect = ValueError("not JSON")
    with patch("scraper._session.get", return_value=bad_response):
        with pytest.raises(ScraperError):
            fetch_price("AAPL")


# --- News (RSS) ---


def _fake_feed(entries: list[dict]) -> dict:
    return {"entries": entries}


def test_fetch_news_uses_yahoo_feed_when_it_has_entries():
    yahoo_entries = [{"title": "Yahoo headline", "link": "https://example.com/1", "published": "today"}]
    with patch("scraper.feedparser.parse", return_value=_fake_feed(yahoo_entries)) as mock_parse:
        result = fetch_news("AAPL")

    assert result == [{"title": "Yahoo headline", "link": "https://example.com/1", "published": "today", "source": None}]
    mock_parse.assert_called_once()
    assert "feeds.finance.yahoo.com" in mock_parse.call_args[0][0]


def test_fetch_news_falls_back_to_google_when_yahoo_is_empty():
    google_entries = [{"title": "Google headline", "link": "https://example.com/2", "published": "today"}]

    def fake_parse(url, agent=None):
        if "feeds.finance.yahoo.com" in url:
            return _fake_feed([])
        return _fake_feed(google_entries)

    with patch("scraper.feedparser.parse", side_effect=fake_parse):
        result = fetch_news("AAPL")

    assert result[0]["title"] == "Google headline"


def test_fetch_news_returns_empty_list_when_every_source_fails():
    with patch("scraper.feedparser.parse", side_effect=RuntimeError("feed server down")):
        result = fetch_news("AAPL")

    assert result == []


def test_fetch_news_respects_limit():
    many_entries = [{"title": f"Headline {i}", "link": "https://example.com", "published": None} for i in range(20)]
    with patch("scraper.feedparser.parse", return_value=_fake_feed(many_entries)):
        result = fetch_news("AAPL", limit=3)

    assert len(result) == 3
