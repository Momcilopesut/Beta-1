"""Free-source scraping for a single ticker - no API key required.

Price: Stooq's daily CSV endpoint (no API key). It was only ever blocked
from GitHub Actions' shared runner IPs in this project's earlier history,
not from an ordinary residential one - but it was observed, on a real
user's machine, gating that same endpoint behind a client-side
proof-of-work challenge instead of a real CSV response (a page with a
<script> that finds n such that sha256(challenge+n) has a given number
of leading hex zeros, then POSTs it to /__verify before the real content
is served). That's fully solvable in plain Python - the algorithm is
right there in the page - so _solve_stooq_challenge() just replicates
exactly what that script does, no browser/JS engine needed. Unlike SEC
EDGAR's TLS-fingerprinting wall (see CLAUDE.md), this is a real puzzle
with a real answer, not something that requires looking like a browser.

News: Yahoo Finance's per-ticker RSS feed, falling back to a Google News
RSS search if that's empty or unavailable. RSS is explicitly built for
automated readers, so it hasn't shown either of the above problems.
Neither feed is guaranteed to stay at this exact URL forever; if both
come back empty, that's surfaced as a plain empty list, not a crash.
"""

import csv
import hashlib
import io
import logging
import re
import time

import feedparser
import requests

logger = logging.getLogger(__name__)

# A hard wall-clock cap on the proof-of-work loop below - without this,
# an unexpectedly high difficulty (Stooq could raise it at any time,
# e.g. in response to a client it's seen hit this endpoint a lot) would
# hang this call, and the single-threaded Flask dev server behind it,
# indefinitely instead of failing with a clear error.
_MAX_CHALLENGE_SECONDS = 20.0

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# A session (not bare requests.get/post) so a solved Stooq challenge's
# verification cookie is kept and reused by every later lookup in this
# running app, rather than re-solving the puzzle from scratch every time.
_session = requests.Session()
_session.headers.update(_BROWSER_HEADERS)

_STOOQ_URL = "https://stooq.com/q/d/l/"
_CHALLENGE_PATTERN = re.compile(r'c="([^"]+)"')
_DIFFICULTY_PATTERN = re.compile(r"\bd=(\d+)")


class ScraperError(Exception):
    pass


def _looks_like_challenge_page(text: str) -> bool:
    return "/__verify" in text and "crypto.subtle.digest" in text


def _solve_stooq_challenge(challenge_html: str) -> bool:
    """Finds n such that sha256(challenge + n) has `difficulty` leading
    hex-zero characters, then POSTs {c: challenge, n: n} to /__verify -
    exactly what the challenge page's own inline <script> does, computed
    here instead. Returns True if a challenge was found, solved within
    _MAX_CHALLENGE_SECONDS, and accepted; False otherwise (including a
    difficulty too high to solve in time) - never hangs indefinitely."""
    challenge_match = _CHALLENGE_PATTERN.search(challenge_html)
    difficulty_match = _DIFFICULTY_PATTERN.search(challenge_html)
    if not challenge_match or not difficulty_match:
        return False

    challenge = challenge_match.group(1)
    difficulty = int(difficulty_match.group(1))
    target_prefix = "0" * difficulty
    logger.info("Solving Stooq's proof-of-work challenge (difficulty=%d)…", difficulty)

    started = time.monotonic()
    n = 0
    while not hashlib.sha256(f"{challenge}{n}".encode()).hexdigest().startswith(target_prefix):
        if time.monotonic() - started > _MAX_CHALLENGE_SECONDS:
            logger.warning(
                "Gave up solving Stooq's challenge after %.1fs (%d attempts, difficulty=%d)",
                _MAX_CHALLENGE_SECONDS,
                n,
                difficulty,
            )
            return False
        n += 1
    logger.info("Solved Stooq's challenge in %.1fs (%d attempts)", time.monotonic() - started, n)

    try:
        resp = _session.post("https://stooq.com/__verify", data={"c": challenge, "n": str(n)}, timeout=10)
    except requests.RequestException:
        return False
    return resp.ok


def _fetch_stooq_csv(ticker: str) -> str:
    params = {"s": f"{ticker.lower()}.us", "i": "d"}
    resp = _session.get(_STOOQ_URL, params=params, timeout=10)
    resp.raise_for_status()

    if _looks_like_challenge_page(resp.text):
        if not _solve_stooq_challenge(resp.text):
            raise ScraperError("Stooq's anti-bot challenge could not be solved")
        resp = _session.get(_STOOQ_URL, params=params, timeout=10)
        resp.raise_for_status()
        if _looks_like_challenge_page(resp.text):
            raise ScraperError("Stooq kept returning its anti-bot challenge after solving it")

    return resp.text


def fetch_price(ticker: str) -> dict:
    """Returns {"close": float|None, "as_of": str|None, "change_pct":
    float|None} from Stooq's free daily CSV. change_pct compares the two
    most recent closes; None (never a guess) if there's no second close
    to compare against, or Stooq has no data for this ticker at all."""
    try:
        text = _fetch_stooq_csv(ticker)
    except requests.RequestException as exc:
        raise ScraperError(f"Price fetch failed for {ticker}: {exc}") from exc

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
