"""Financial Modeling Prep client (free tier, API key required).

Each endpoint is fetched independently and failures are captured per-call
rather than aborting the whole ticker — a single gated/renamed endpoint on
the account's free tier shouldn't take down every other metric.
"""

import os
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

    Returns {<call_name>: <payload or None>, "_errors": {<call_name>: str}}.
    """
    calls = {
        "profile": lambda: _get("profile", ticker),
        "quote": lambda: _get("quote", ticker),
        "historical_prices": lambda: _get("historical-price-eod/full", ticker),
        "ratios_ttm": lambda: _get("ratios-ttm", ticker),
        "key_metrics_ttm": lambda: _get("key-metrics-ttm", ticker),
        "income_statement": lambda: _get("income-statement", ticker, limit=5),
        "balance_sheet": lambda: _get("balance-sheet-statement", ticker, limit=5),
        "cash_flow": lambda: _get("cash-flow-statement", ticker, limit=5),
        "dcf": lambda: _get("discounted-cash-flow", ticker),
    }

    result: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name, call in calls.items():
        try:
            result[name] = call()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see module docstring
            errors[name] = str(exc)
            result[name] = None

    result["_errors"] = errors
    return result
