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
automated readers, so it hasn't shown either of the above anti-bot
problems - the one real issue hit here was a local one: feedparser
fetching a feed URL itself goes through Python's stdlib urllib, which
on a real machine failed SSL certificate verification even though
`requests` (used for price/LLM calls) worked fine - see _parse_feed()
for why. Neither feed is guaranteed to stay at this exact URL forever;
if both come back empty, that's surfaced as a plain empty list, not a
crash.
"""

import logging
from datetime import datetime, timezone

import feedparser
import requests

logger = logging.getLogger(__name__)

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
    # feedparser can fetch a URL itself, but that path goes through
    # Python's stdlib urllib, with its own (separately configured) SSL
    # context - on a real machine that came back SSL_CERTIFICATE_VERIFY_
    # FAILED ("unable to get local issuer certificate") even though
    # `requests` (used for price/LLM calls) worked fine, since `requests`
    # bundles its own CA bundle via certifi and doesn't depend on the
    # system/Python install having one configured. Fetching with
    # `requests` first and handing feedparser the raw bytes to parse only
    # - never a URL - sidesteps that split entirely.
    try:
        resp = _session.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Feed fetch failed for %s: %s", url, exc)
        return []

    parsed = feedparser.parse(resp.content)
    entries = parsed.get("entries") or []
    if not entries:
        # feedparser rarely raises even on a real parse failure (a
        # malformed or unexpected response body) - it just comes back
        # with no entries and, usually, a non-exception explanation in
        # bozo_exception. Logging that here is the only way to tell
        # "genuinely no news right now" apart from "this response wasn't
        # a usable feed" after the fact - fetch_price's own empty-result
        # logging had the same gap until a real lookup showed why it
        # mattered.
        logger.warning("Feed parsed to no entries for %s (bozo_exception=%s)", url, parsed.get("bozo_exception"))

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
