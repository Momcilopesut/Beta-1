"""Financial Modeling Prep client (API key required).

Deliberately lean: FMP's free tier caps out around 250 requests/day, which
can't sustain a large tracked universe if every company pulls FMP's full
statement set every run. pipeline.scoring.fundamentals already has a
complete fallback chain to free sources (SEC EDGAR XBRL for statements,
Stooq for price history, the watchlist's own configured sector) for
everything FMP would otherwise supply, so FMP here is reserved for what
only it provides: live price/quote and profile (company name/sector/
website precision, when available).

pipeline.main was originally designed to call this only during phase 2's
finalist enrichment, leaving Stooq to cover price for the whole screening
universe for free - see run_full's module docstring. In practice Stooq
turned out to be blocked from GitHub Actions runners (see
pipeline.fetch.stooq's module docstring: every request failed on a real
run, 404s escalating to connection timeouts, regardless of a browser
User-Agent), so FMP is back to being called for every company, not just
finalists, until a working free price source is found. That means this
pipeline currently depends on an active paid/free-trial FMP plan to cover
its whole tracked universe - the ~250/day free-tier budget this module's
lean endpoint set was designed for does NOT currently hold at the scale
this pipeline runs at (500+ companies/week). Tracked as known follow-up
work, not solved.

Each endpoint is fetched independently and failures are captured per-call
rather than aborting the whole ticker.
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
    """A ticker with a dot (e.g. "BRK.B") is retried with a hyphen
    ("BRK-B") if the dot form fails - FMP spells share classes with a
    hyphen, not the dot notation this pipeline's watchlist uses. A real
    run confirmed this: FMP returned 402 Payment Required for BRK.B and
    MOG.A specifically, the same class of failure already seen (and
    fixed) for SEC EDGAR and Stooq on the same tickers."""
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise FmpError("FMP_API_KEY is not set")

    cache_key = f"fmp/{endpoint}/{ticker}"
    if cache.enabled():
        cached = cache.read(cache_key)
        if cached is not None:
            return cached

    candidates = [ticker]
    if "." in ticker:
        candidates.append(ticker.replace(".", "-"))

    last_exc: Exception | None = None
    result: Any = None
    for candidate in candidates:
        query = {"symbol": candidate, "apikey": api_key, **params}
        try:
            result = get_json(
                f"{BASE_URL}/{endpoint}", params=query, host_key="fmp", min_interval_seconds=0.2
            )
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001 - retry-with-alternate-ticker, see docstring
            last_exc = exc

    if last_exc is not None:
        raise last_exc

    if cache.enabled():
        cache.write(cache_key, result)
    return result


def fetch_company(ticker: str) -> dict:
    """Fetch the FMP data this pipeline actually can't get elsewhere for one
    ticker: profile (name/sector/website) and price (quote + history).
    Statements, ratios, and a discounted-cash-flow figure used to be fetched
    here too, but pipeline.scoring.fundamentals already derives every one of
    those from free sources (SEC EDGAR XBRL, computed ratios) with complete
    fallback formulas - see this module's docstring - so calling FMP for
    them was pure request-budget cost with no accuracy benefit at this
    pipeline's scale.

    The 3 endpoint calls are independent, so they run concurrently rather
    than one-at-a-time - on a degraded account (each failing call retries 3x
    with backoff before giving up) that's the difference between ~10-25s and
    ~single-call-latency per ticker, which matters for the on-demand lookup
    endpoint (api/lookup.py) far more than for the batch pipeline, though
    both benefit. pipeline.utils.http's per-host rate limiting is
    lock-protected so this stays polite to FMP.

    Returns {<call_name>: <payload or None>, "_errors": {<call_name>: str}}.
    """
    calls = {
        "profile": lambda: _get("profile", ticker),
        "quote": lambda: _get("quote", ticker),
        "historical_prices": lambda: _get("historical-price-eod/full", ticker),
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
