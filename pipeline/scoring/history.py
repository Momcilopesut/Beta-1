"""5-year history: earnings, spending, cash, and debt per fiscal year, plus
how the stock did that year compared to the broad market (SPY) - a plain,
unscored time series (no gates, no scoring) that sits beside the Investment
Meter's single-snapshot numbers so a reader can see the trend behind them.

Every value here comes from statements/prices already fetched elsewhere in
the pipeline (pipeline.fetch.fmp) - no new API calls per company. Any value
that can't be resolved is left as None, never a guessed or interpolated
number - the same "null not zero" rule the rest of this pipeline follows.
"""

from datetime import date
from typing import Any

_DATE_TOLERANCE_DAYS = 7
_MAX_YEARS = 5


def _get(row: dict, *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _spending(row: dict) -> float | None:
    """Total costs and expenses for the year - FMP's own combined field when
    present, else cost of revenue + operating expenses."""
    total = _get(row, "costAndExpenses")
    if total is not None:
        return total
    cost_of_revenue = _get(row, "costOfRevenue")
    operating_expenses = _get(row, "operatingExpenses")
    if cost_of_revenue is not None and operating_expenses is not None:
        return cost_of_revenue + operating_expenses
    return None


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except ValueError:
        return None


def _closest_close(price_rows: list[dict], target: date, tolerance_days: int = _DATE_TOLERANCE_DAYS) -> float | None:
    """Nearest trading-day close within `tolerance_days` of `target` - fiscal
    year ends often land on a weekend/holiday, so an exact-date match would
    miss most companies. Returns None (not a guess) when nothing is close
    enough."""
    best_close = None
    best_gap = None
    for row in price_rows:
        row_date = _parse_date(row.get("date"))
        close = row.get("close")
        if row_date is None or close is None:
            continue
        gap = abs((row_date - target).days)
        if gap > tolerance_days:
            continue
        if best_gap is None or gap < best_gap:
            best_gap, best_close = gap, close
    return best_close


def _year_return_pct(price_rows: list[dict], this_year: date, prior_year: date) -> float | None:
    this_close = _closest_close(price_rows, this_year)
    prior_close = _closest_close(price_rows, prior_year)
    if this_close is None or not prior_close:
        return None
    return (this_close - prior_close) / prior_close * 100


def build_five_year_history(
    income_stmts: list[dict], balance_stmts: list[dict], price_rows: list[dict], benchmark_rows: list[dict]
) -> dict | None:
    """income_stmts/balance_stmts: annual statements, most-recent-first (FMP
    convention), paired by index like the rest of this pipeline already
    assumes (see fundamentals.py). price_rows/benchmark_rows: normalized
    [{"date", "close"}, ...] lists (pipeline.scoring.fundamentals.normalize_price_rows).

    Returns None when there isn't enough statement history to show anything
    (fewer than 2 annual statements on either side) - otherwise {"years":
    [...]}, oldest-first, capped at the latest 5 fiscal years. Each year's
    stock_return_pct/market_return_pct is None for the oldest year shown
    whenever there's no earlier statement to anchor a year-over-year return.
    """
    if len(income_stmts) < 2 or len(balance_stmts) < 2:
        return None

    price_rows = price_rows or []
    benchmark_rows = benchmark_rows or []

    num_years = min(_MAX_YEARS, len(income_stmts), len(balance_stmts))
    years = []
    for i in range(num_years):
        income_row = income_stmts[i]
        balance_row = balance_stmts[i]
        fiscal_year = _get(income_row, "date")

        stock_return_pct = None
        market_return_pct = None
        this_date = _parse_date(fiscal_year)
        if this_date and i + 1 < len(income_stmts):
            prior_date = _parse_date(_get(income_stmts[i + 1], "date"))
            if prior_date:
                stock_return_pct = _year_return_pct(price_rows, this_date, prior_date)
                market_return_pct = _year_return_pct(benchmark_rows, this_date, prior_date)

        years.append(
            {
                "fiscal_year": fiscal_year,
                "earnings": _get(income_row, "netIncome"),
                "spending": _spending(income_row),
                "cash": _get(balance_row, "cashAndCashEquivalents", "cashAndShortTermInvestments"),
                "debt": _get(balance_row, "totalDebt"),
                "stock_return_pct": stock_return_pct,
                "market_return_pct": market_return_pct,
            }
        )

    years.reverse()  # oldest-first, for natural left-to-right chart order
    return {"years": years}
