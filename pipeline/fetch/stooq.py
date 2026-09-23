"""Stooq daily price/volume history. Free, no API key, no documented rate
limit - used as a fallback price source when FMP's historical-price or
quote endpoints are unavailable (e.g. plan-gated, see pipeline/fetch/fmp.py).

Stooq's CSV endpoint returns less than FMP would (no bid/ask, no live
intraday quote) but covers exactly what the scoring engine actually needs:
daily close and volume, which is enough to derive returns, moving averages,
RSI, and a volume-vs-own-average ratio.

A real weekly-screen.yml run (Stage 2 of the watchlist expansion, 906
companies) hit every single request failing - starting as HTTP 404 on the
very first ticker and escalating to TCP connect timeouts within two
minutes, while SEC EDGAR's requests (which send a required custom
User-Agent) succeeded throughout. requests' default User-Agent
("python-requests/x.y.z") is a well-known bot signature many sites,
Stooq apparently included, block outright - so a browser-like UA is sent
below. Timeout/retries are also kept short: at the default 15s timeout x
3 retries, a wholesale block burns ~45s+ per company for nothing: with
hundreds of companies relying on this as their only phase-1 price source,
that alone can exhaust a GitHub Actions run's time budget before it
finishes the universe, regardless of company count.
"""

import csv
import io

from pipeline.utils.http import HttpError, get_text

BASE_URL = "https://stooq.com/q/d/l/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


class StooqError(Exception):
    pass


def fetch_daily_prices(ticker: str) -> list[dict]:
    """Returns [{"date": "YYYY-MM-DD", "close": float, "volume": float}, ...]
    ascending by date - the same shape pipeline.scoring.fundamentals expects
    from FMP's historical-price endpoint, so it's a drop-in substitute.

    A ticker with a dot (e.g. "BRK.B") is retried with a hyphen ("BRK-B")
    if the dot form comes back empty or 404s - Stooq spells share classes
    with a hyphen, not the dot notation this pipeline's watchlist uses."""
    candidates = [ticker]
    if "." in ticker:
        candidates.append(ticker.replace(".", "-"))

    last_exc: StooqError | None = None
    for candidate in candidates:
        try:
            rows = _fetch_daily_prices(candidate)
        except StooqError as exc:
            last_exc = exc
            continue
        if rows:
            return rows
    if last_exc is not None:
        raise last_exc
    return []


def _fetch_daily_prices(ticker: str) -> list[dict]:
    params = {"s": f"{ticker.lower()}.us", "i": "d"}
    try:
        text = get_text(
            BASE_URL,
            params=params,
            headers=_HEADERS,
            host_key="stooq",
            min_interval_seconds=0.2,
            timeout=5.0,
            max_retries=2,
        )
    except HttpError as exc:
        raise StooqError(f"Failed to fetch Stooq prices for {ticker}: {exc}") from exc

    if not text or text.strip().lower().startswith("no data"):
        return []

    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            close = float(row["Close"])
            volume = float(row["Volume"])
        except (KeyError, ValueError, TypeError):
            continue
        rows.append({"date": row.get("Date"), "close": close, "volume": volume})
    return rows
