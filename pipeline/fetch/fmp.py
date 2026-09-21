"""Financial Modeling Prep client (free tier, API key required).

Each endpoint is fetched independently and failures are captured per-call
rather than aborting the whole ticker — a single gated/renamed endpoint on
the account's free tier shouldn't take down every other metric.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pipeline.fetch import cache
from pipeline.utils.http import get_json

BASE_URL = "https://financialmodelingprep.com/stable"


class FmpError(Exception):
    pass


def _get(endpoint: str, ticker: str, **params: Any) -> Any:
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise FmpError("FMP_API_KEY is not set")

    cache_key = f"fmp/{endpoint}/{ticker}"
    if cache.enabled():
        cached = cache.read(cache_key)
        if cached is not None:
            return cached

    query = {"symbol": ticker, "apikey": api_key, **params}
    result = get_json(
        f"{BASE_URL}/{endpoint}",
        params=query,
        host_key="fmp",
        min_interval_seconds=0.2,
    )

    if cache.enabled():
        cache.write(cache_key, result)
    return result


def fetch_company(ticker: str) -> dict:
    """Fetch all FMP data needed for one ticker.

    The 9 endpoint calls are independent, so they run concurrently rather
    than one-at-a-time - on a degraded account (see module docstring; each
    failing call retries 3x with backoff before giving up) that's the
    difference between ~30-80s and ~single-call-latency per ticker, which
    matters for the on-demand lookup endpoint (api/lookup.py) far more than
    for the batch pipeline, though both benefit. pipeline.utils.http's
    per-host rate limiting is lock-protected so this stays polite to FMP.

    Returns {<call_name>: <payload or None>, "_errors": {<call_name>: str}}.
    """
    calls = {
        "profile": lambda: _get("profile", ticker),
        "quote": lambda: _get("quote", ticker),
        "historical_prices": lambda: _get("historical-price-eod/full", ticker),
        "ratios_ttm": lambda: _get("ratios-ttm", ticker),
        "key_metrics_ttm": lambda: _get("key-metrics-ttm", ticker),
        "income_statement": lambda: _get("income-statement", ticker, limit=6),
        "balance_sheet": lambda: _get("balance-sheet-statement", ticker, limit=6),
        "cash_flow": lambda: _get("cash-flow-statement", ticker, limit=6),
        "dcf": lambda: _get("discounted-cash-flow", ticker),
    }

    result: dict[str, Any] = {}
    errors: dict[str, str] = {}

    def run(name: str, call) -> None:
        try:
            result[name] = call()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see module docstring
            errors[name] = str(exc)
            result[name] = None

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, name, call) for name, call in calls.items()]
        for future in futures:
            future.result()

    result["_errors"] = errors
    return result


def fetch_benchmark_prices(symbol: str = "SPY") -> Any:
    """Historical daily prices for a single benchmark ticker - the plain
    stand-in for "the stock market average" used by the 5-year history charts
    (pipeline/scoring/history.py). Fetched once per pipeline run, not once
    per company, since every company is compared against the same market.
    SPY (an S&P 500 ETF) trades like any other US equity FMP already serves
    on the free tier, unlike a raw index symbol (e.g. ^GSPC), which is often
    plan-gated."""
    return _get("historical-price-eod/full", symbol)
