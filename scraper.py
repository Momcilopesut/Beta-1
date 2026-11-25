"""Free-source scraping for a single ticker - no API key required.

Price: Stooq's daily CSV endpoint (no API key, works fine from a normal
home connection - it was only ever blocked from GitHub Actions' shared
runner IPs in this project's history, not from an ordinary residential
one).

News: Yahoo Finance's per-ticker RSS feed, falling back to a Google News
RSS search if that's empty or unavailable. RSS is explicitly built for
automated readers, so - unlike scraping a news site's HTML pages directly
- it doesn't run into the TLS-fingerprint/anti-bot wall this project hit
scraping SEC EDGAR (see CLAUDE.md for that whole story). Neither feed is
guaranteed to stay at this exact URL forever; if both come back empty,
that's surfaced as a plain empty list, not a crash.
"""

import csv
import io

import feedparser
import requests

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


class ScraperError(Exception):
    pass


def fetch_price(ticker: str) -> dict:
    """Returns {"close": float|None, "as_of": str|None, "change_pct":
    float|None} from Stooq's free daily CSV. change_pct compares the two
    most recent closes; None (never a guess) if there's no second close
    to compare against, or Stooq has no data for this ticker at all."""
    try:
        resp = requests.get(
            "https://stooq.com/q/d/l/",
            params={"s": f"{ticker.lower()}.us", "i": "d"},
            headers=_BROWSER_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Price fetch failed for {ticker}: {exc}") from exc

    text = resp.text
    empty = {"close": None, "as_of": None, "change_pct": None}
    if not text or text.strip().lower().startswith("no data"):
        return empty

    closes = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            closes.append((row["Date"], float(row["Close"])))
        except (KeyError, ValueError, TypeError):
            continue
    if not closes:
        return empty

    as_of, close = closes[-1]
    change_pct = None
    if len(closes) >= 2 and closes[-2][1]:
        change_pct = (close - closes[-2][1]) / closes[-2][1] * 100
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
