"""Free-source scraping for a single ticker - no API key required.

Price: Yahoo Finance's free chart JSON endpoint
(query1.finance.yahoo.com/v8/finance/chart) - the same unofficial
endpoint most free stock-data tools use. Stooq's CSV endpoint was tried
first; it's documented (and abandoned) as its own incident in CLAUDE.md -
short version: it added a client-side proof-of-work challenge, which
this code learned to solve, and THEN started returning a flat "Access
denied" on the actual data request regardless, confirmed from a real
browser on the same connection, not just this app's own requests. That
last part matters: once a real browser gets denied too, there's no
scripted workaround left to find - it's not a "look more like a
browser" problem the way SEC EDGAR's was.

News: Yahoo Finance's per-ticker RSS feed, falling back to a Google News
RSS search if that's empty or unavailable. RSS is explicitly built for
automated readers, so it hasn't shown either of the above problems.
Neither feed is guaranteed to stay at this exact URL forever; if both
come back empty, that's surfaced as a plain empty list, not a crash.
"""

from datetime import datetime, timezone

import feedparser
import requests

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_session = requests.Session()
_session.headers.update(_BROWSER_HEADERS)


class ScraperError(Exception):
    pass


def fetch_price(ticker: str) -> dict:
    """Returns {"close": float|None, "as_of": str|None, "change_pct":
    float|None} from Yahoo Finance's free chart endpoint. change_pct
    compares the two most recent closes; None (never a guess) if there's
    no second close to compare against, or Yahoo has no data for this
    ticker at all."""
    try:
        resp = _session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"interval": "1d", "range": "5d"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise ScraperError(f"Price fetch failed for {ticker}: {exc}") from exc

    empty = {"close": None, "as_of": None, "change_pct": None}
    try:
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return empty

    dated_closes = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
    if not dated_closes:
        return empty

    as_of_ts, close = dated_closes[-1]
    as_of = datetime.fromtimestamp(as_of_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    change_pct = None
    if len(dated_closes) >= 2 and dated_closes[-2][1]:
        change_pct = (close - dated_closes[-2][1]) / dated_closes[-2][1] * 100
    return {"close": close, "as_of": as_of, "change_pct": change_pct}


def _parse_feed(url: str, limit: int) -> list[dict]:
    try:
        parsed = feedparser.parse(url, agent=_BROWSER_HEADERS["User-Agent"])
    except Exception:  # noqa: BLE001 - a feed fetch/parse failure just means "try the next source"
        return []
    entries = parsed.get("entries") or []
    out = []
    for entry in entries[:limit]:
        source = entry.get("source")
        out.append(
            {
                "title": entry.get("title"),
                "link": entry.get("link"),
                "published": entry.get("published"),
                "source": source.get("title") if isinstance(source, dict) else None,
            }
        )
    return out


def fetch_news(ticker: str, limit: int = 8) -> list[dict]:
    """Returns [{"title", "link", "published", "source"}, ...], most
    recent first, up to `limit` items - never raises just because one
    feed came up empty, only degrades to an empty list if every source
    does."""
    items = _parse_feed(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US", limit)
    if items:
        return items
    return _parse_feed(f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en", limit)
