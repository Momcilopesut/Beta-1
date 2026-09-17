"""Stooq daily price/volume history. Free, no API key, no documented rate
limit - used as a fallback price source when FMP's historical-price or
quote endpoints are unavailable (e.g. plan-gated, see pipeline/fetch/fmp.py).

Stooq's CSV endpoint returns less than FMP would (no bid/ask, no live
intraday quote) but covers exactly what the scoring engine actually needs:
daily close and volume, which is enough to derive returns, moving averages,
RSI, and a volume-vs-own-average ratio.
"""

import csv
import io

from pipeline.utils.http import HttpError, get_text

BASE_URL = "https://stooq.com/q/d/l/"


class StooqError(Exception):
    pass


def fetch_daily_prices(ticker: str) -> list[dict]:
    """Returns [{"date": "YYYY-MM-DD", "close": float, "volume": float}, ...]
    ascending by date - the same shape pipeline.scoring.fundamentals expects
    from FMP's historical-price endpoint, so it's a drop-in substitute."""
    params = {"s": f"{ticker.lower()}.us", "i": "d"}
    try:
        text = get_text(BASE_URL, params=params, host_key="stooq", min_interval_seconds=0.2)
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
