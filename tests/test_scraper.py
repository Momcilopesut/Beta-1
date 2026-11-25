"""Tests for scraper.py - pure parsing logic, network calls mocked."""

import hashlib
from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper import ScraperError, fetch_news, fetch_price

_SAMPLE_CSV = "Date,Open,High,Low,Close,Volume\n2026-01-01,100,101,99,100,1000\n2026-01-02,100,106,99,105,1200\n"

# A low difficulty (d=1) so the test's own proof-of-work loop finishes
# instantly - the real page uses a higher one, but the algorithm being
# verified is identical either way.
_CHALLENGE_HTML = (
    '<!DOCTYPE html><html><body><noscript>enable JS</noscript><script>'
    '(async()=>{const c="test-challenge-value",d=1,t="0".repeat(d),e=new TextEncoder;'
    "let n=0;while(1){const h=await crypto.subtle.digest(\"SHA-256\",e.encode(c+n))"
    ",x=Array.from(new Uint8Array(h)).map(b=>b.toString(16).padStart(2,\"0\")).join(\"\");"
    'if(x.startsWith(t))break;n++}const r=await fetch("/__verify",{method:"POST",'
    'headers:{"Content-Type":"application/x-www-form-urlencoded"},'
    'body:"c="+encodeURIComponent(c)+"&n="+n,credentials:"same-origin"});'
    "if(r.ok)location.reload()})();"
    "</script></body></html>"
)


def _mock_response(text: str, ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.ok = ok
    response.raise_for_status.return_value = None
    return response


def test_fetch_price_parses_latest_close_and_change_pct():
    with patch("scraper._session.get", return_value=_mock_response(_SAMPLE_CSV)):
        result = fetch_price("AAPL")

    assert result["close"] == 105.0
    assert result["as_of"] == "2026-01-02"
    assert result["change_pct"] == pytest.approx(5.0)


def test_fetch_price_handles_no_data_response():
    with patch("scraper._session.get", return_value=_mock_response("No data")):
        result = fetch_price("NOSUCHTICKER")

    assert result == {"close": None, "as_of": None, "change_pct": None}


def test_fetch_price_single_row_has_no_change_pct():
    single_row = "Date,Open,High,Low,Close,Volume\n2026-01-02,100,106,99,105,1200\n"
    with patch("scraper._session.get", return_value=_mock_response(single_row)):
        result = fetch_price("AAPL")

    assert result["close"] == 105.0
    assert result["change_pct"] is None


def test_fetch_price_wraps_network_errors():
    with patch("scraper._session.get", side_effect=requests.ConnectionError("no route")):
        with pytest.raises(ScraperError):
            fetch_price("AAPL")


# --- Stooq's client-side proof-of-work challenge (see scraper.py's module
# docstring) - a real anti-bot gate observed in practice, fully solvable
# without a browser since the algorithm is visible in the page itself. ---


def test_fetch_price_solves_challenge_then_retries_and_succeeds():
    responses = [_mock_response(_CHALLENGE_HTML), _mock_response(_SAMPLE_CSV)]

    def fake_get(url, params=None, timeout=None):
        return responses.pop(0)

    verify_calls = []

    def fake_post(url, data=None, timeout=None):
        verify_calls.append(data)
        return _mock_response("", ok=True)

    with patch("scraper._session.get", side_effect=fake_get), patch("scraper._session.post", side_effect=fake_post):
        result = fetch_price("AAPL")

    assert result["close"] == 105.0
    assert len(verify_calls) == 1
    assert verify_calls[0]["c"] == "test-challenge-value"
    # The posted answer must actually solve the puzzle, not just be any value.
    n = verify_calls[0]["n"]
    assert hashlib.sha256(f"test-challenge-value{n}".encode()).hexdigest().startswith("0")


def test_fetch_price_raises_if_challenge_persists_after_solving():
    with (
        patch("scraper._session.get", return_value=_mock_response(_CHALLENGE_HTML)),
        patch("scraper._session.post", return_value=_mock_response("", ok=True)),
    ):
        with pytest.raises(ScraperError):
            fetch_price("AAPL")


def test_fetch_price_raises_if_verify_post_fails():
    with (
        patch("scraper._session.get", return_value=_mock_response(_CHALLENGE_HTML)),
        patch("scraper._session.post", return_value=_mock_response("", ok=False)),
    ):
        with pytest.raises(ScraperError):
            fetch_price("AAPL")


def test_fetch_price_raises_if_challenge_page_has_no_extractable_puzzle():
    broken_challenge = '<html><script>crypto.subtle.digest fetch("/__verify")</script></html>'
    with patch("scraper._session.get", return_value=_mock_response(broken_challenge)):
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
