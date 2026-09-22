"""Normalizes raw FMP + SEC EDGAR payloads into the flat metric dict the
scoring engine consumes, plus a grouped `display` dict for the output JSON.

FMP field names are matched defensively (a short list of candidate keys per
metric) since the exact free-tier response shape should be confirmed against
a live account before relying on this in production. Any metric that can't
be resolved from any candidate key, or whose source call failed upstream, is
left as None here - every checklist that consumes these metrics
(pipeline.scoring.value_investing) treats a missing metric as excluded (not
failed) rather than crashing.

Deliberately centered on the balance sheet: "does the company own more than
it owes, and is the price fair for what's actually owned" (assets vs
liabilities), plus the smallest set of earnings-based checks needed to round
that out (P/E, EPS growth, cash generation). See README's "Assets vs
Liabilities" section for the reasoning behind what's kept vs. cut.
"""

import math
from typing import Any

_MARGIN_TREND_SCORE = {"improving": 100, "stable": 60, "declining": 20}


def _first_of(row: dict, *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _first_row(payload: Any) -> dict:
    if isinstance(payload, list) and payload:
        return payload[0]
    if isinstance(payload, dict):
        return payload
    return {}


def normalize_price_rows(historical_prices: Any) -> list[dict]:
    """FMP's /stable/historical-price-eod/full has returned a bare list of
    {date, close, ...} rows directly in practice, not the older
    {"symbol":..., "historical": [...]} wrapper this originally assumed.
    Accept either shape (or a missing/failed fetch) instead of crashing.
    Public since pipeline.main also uses this to normalize the benchmark
    (SPY) price payload for pipeline.scoring.history."""
    if isinstance(historical_prices, list):
        return historical_prices
    if isinstance(historical_prices, dict):
        return historical_prices.get("historical") or []
    return []


def _latest_close(historical: list[dict]) -> dict:
    """Just the latest close price + its date - no moving averages, RSI, or
    volume analysis. Those are price-momentum/technical-trading signals,
    not "does this company own more than it owes" value investing, and
    this pipeline no longer scores on them (see README)."""
    rows = sorted((h for h in historical if h.get("close") is not None), key=lambda h: h["date"])
    if not rows:
        return {}
    return {"close": rows[-1]["close"], "as_of": rows[-1]["date"]}


def _cagr(latest: float, base: float, periods: int) -> float | None:
    if not base or (latest / base) <= 0:
        return None
    return ((latest / base) ** (1 / periods) - 1) * 100


def _eps_growth_cagr_3yr(statements: list[dict]) -> float | None:
    """statements: annual statements, most-recent-first (FMP convention).
    Needs 4 annual statements (this year + 3 years back)."""
    values = [v for row in statements if (v := _first_of(row, "epsdiluted", "eps")) is not None]
    if len(values) < 4:
        return None
    return _cagr(values[0], values[3], 3)


def _margin_trend(statements: list[dict]) -> str:
    margins = []
    for row in statements[:3]:
        revenue = _first_of(row, "revenue")
        gross_profit = _first_of(row, "grossProfit")
        if revenue:
            margins.append(gross_profit / revenue * 100 if gross_profit is not None else None)
    margins = [m for m in margins if m is not None]
    if len(margins) < 2:
        return "stable"
    delta = margins[0] - margins[-1]
    if delta > 1.5:
        return "improving"
    if delta < -1.5:
        return "declining"
    return "stable"


def _graham_number(eps: float | None, book_value_per_share: float | None) -> float | None:
    """sqrt(22.5 x EPS x BVPS) - Graham's quick fair-value estimate, combining
    earnings and book value (assets vs liabilities, per share) in one closed-
    form formula - no growth projections or discount-rate assumptions. 22.5
    is Graham's own combined ceiling (P/E <= 15 x P/B <= 1.5). Undefined
    (None) if either input is missing or non-positive."""
    if eps is None or book_value_per_share is None or eps <= 0 or book_value_per_share <= 0:
        return None
    return math.sqrt(22.5 * eps * book_value_per_share)


def build_metrics(
    ticker: str, fmp_data: dict, sec_data: dict, stooq_prices: list[dict] | None = None
) -> dict:
    """Returns {"metrics": {...flat, scoring-ready...}, "display": {...grouped
    for output JSON...}, "profile": {name, sector, industry, cik}}.

    Falls back to free sources when FMP's own endpoint failed outright
    (empty/None) rather than just being missing one field: SEC XBRL company
    facts (already fetched for filing links, see pipeline/fetch/sec_edgar.py)
    for statements, and Stooq (pipeline/fetch/stooq.py, called by the
    pipeline only when FMP's price data is missing) for the latest price.
    Every downstream calculation below is source-agnostic - it just reads
    whichever statement/price rows ended up populated.
    """
    profile = _first_row(fmp_data.get("profile"))
    quote = _first_row(fmp_data.get("quote"))
    ratios = _first_row(fmp_data.get("ratios_ttm"))
    key_metrics = _first_row(fmp_data.get("key_metrics_ttm"))

    xbrl = sec_data.get("xbrl_fundamentals") or {}
    income_stmts = fmp_data.get("income_statement") or xbrl.get("income_stmts") or []
    balance_stmts = fmp_data.get("balance_sheet") or xbrl.get("balance_stmts") or []
    cashflow_stmts = fmp_data.get("cash_flow") or xbrl.get("cashflow_stmts") or []
    historical = normalize_price_rows(fmp_data.get("historical_prices")) or (stooq_prices or [])

    price_data = _latest_close(historical)
    if not price_data:
        price_data = {"close": _first_of(quote, "price"), "as_of": None}

    price = price_data.get("close")
    balance0 = balance_stmts[0] if balance_stmts else {}
    income0 = income_stmts[0] if income_stmts else {}

    pe_ttm = _first_of(ratios, "priceToEarningsRatioTTM", "peRatioTTM")

    eps_growth_cagr_3yr_pct = _eps_growth_cagr_3yr(income_stmts)

    revenue = _first_of(income0, "revenue") if income_stmts else None
    net_income = _first_of(income0, "netIncome") if income_stmts else None
    margin_trend = _margin_trend(income_stmts)

    # --- The core "assets vs liabilities" numbers ---
    total_assets = _first_of(balance0, "totalAssets")
    total_liabilities = _first_of(balance0, "totalLiabilities")
    total_equity = _first_of(balance0, "totalStockholdersEquity")
    total_debt = _first_of(balance0, "totalDebt")
    current_assets = _first_of(balance0, "totalCurrentAssets")
    current_liabilities = _first_of(balance0, "totalCurrentLiabilities")

    debt_to_equity = _first_of(ratios, "debtToEquityRatioTTM", "debtEquityRatioTTM")
    if debt_to_equity is None and total_debt is not None and total_equity:
        debt_to_equity = total_debt / total_equity

    # Munger/Buffett's own quality bar: return on the equity shareholders
    # have put in. Simple two-input math (net income / equity), not the
    # multi-input ROIC formula this pipeline cut earlier for being too
    # complex to verify by hand.
    roe_pct = _first_of(key_metrics, "roeTTM", "returnOnEquityTTM")
    if roe_pct is not None:
        roe_pct = roe_pct * 100
    if roe_pct is None and net_income is not None and total_equity:
        roe_pct = net_income / total_equity * 100

    current_ratio = _first_of(ratios, "currentRatioTTM")
    if current_ratio is None and current_assets is not None and current_liabilities:
        current_ratio = current_assets / current_liabilities

    fcf_ttm = None
    fcf_margin_pct = None
    if cashflow_stmts:
        fcf_ttm = _first_of(cashflow_stmts[0], "freeCashFlow")
        if fcf_ttm is None:
            ocf = _first_of(cashflow_stmts[0], "operatingCashFlow")
            capex0 = _first_of(cashflow_stmts[0], "capitalExpenditure")
            if ocf is not None and capex0 is not None:
                fcf_ttm = ocf - abs(capex0)
        if fcf_ttm is not None and revenue:
            fcf_margin_pct = fcf_ttm / revenue * 100

    ebitda_0 = None
    if income_stmts:
        operating_income_0 = _first_of(income0, "operatingIncome")
        d_and_a_0 = _first_of(cashflow_stmts[0], "depreciationAndAmortization") if cashflow_stmts else None
        if operating_income_0 is not None and d_and_a_0 is not None:
            ebitda_0 = operating_income_0 + d_and_a_0
    debt_to_ebitda = total_debt / ebitda_0 if total_debt is not None and ebitda_0 and ebitda_0 > 0 else None

    shares_outstanding = (
        _first_of(quote, "sharesOutstanding")
        or _first_of(key_metrics, "sharesOutstandingTTM")
        or sec_data.get("shares_outstanding")
    )
    market_cap = _first_of(quote, "marketCap") or _first_of(profile, "mktCap")
    if market_cap is None and price and shares_outstanding:
        market_cap = price * shares_outstanding
    if shares_outstanding is None and market_cap and price:
        shares_outstanding = market_cap / price

    book_value_per_share = _first_of(ratios, "bookValuePerShareTTM") or _first_of(
        key_metrics, "bookValuePerShareTTM"
    )
    if book_value_per_share is None and shares_outstanding and total_equity is not None:
        book_value_per_share = total_equity / shares_outstanding

    pb_ratio = _first_of(ratios, "priceToBookRatioTTM")
    if pb_ratio is None and price and book_value_per_share:
        pb_ratio = price / book_value_per_share

    eps_ttm = _first_of(quote, "eps") or _first_of(income0, "epsdiluted", "eps")
    if pe_ttm is None and price and eps_ttm and eps_ttm > 0:
        pe_ttm = price / eps_ttm

    graham_number = _graham_number(eps_ttm, book_value_per_share)
    graham_upside_pct = (graham_number - price) / price * 100 if graham_number and price else None
    graham_multiple = pe_ttm * pb_ratio if pe_ttm is not None and pb_ratio is not None else None

    # NCAV - Graham's strictest "assets vs liabilities" test: even ignoring
    # everything but current assets, does that alone (after paying off ALL
    # liabilities) exceed what the market is charging for the whole company?
    ncav_margin_pct = None
    if shares_outstanding and price and current_assets is not None and total_liabilities is not None:
        ncav_per_share = (current_assets - total_liabilities) / shares_outstanding
        ncav_margin_pct = (ncav_per_share - price) / price * 100

    metrics = {
        "pe_ttm": pe_ttm,
        "pb_ratio": pb_ratio,
        "graham_upside_pct": graham_upside_pct,
        "graham_multiple": graham_multiple,
        "ncav_margin_pct": ncav_margin_pct,
        "debt_to_equity": debt_to_equity,
        "debt_to_ebitda": debt_to_ebitda,
        "current_ratio": current_ratio,
        "fcf_margin_pct": fcf_margin_pct,
        "eps_growth_cagr_3yr_pct": eps_growth_cagr_3yr_pct,
        "margin_trend_score": _MARGIN_TREND_SCORE[margin_trend],
        "roe_pct": roe_pct,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "shareholders_equity": total_equity,
        "book_value_per_share": book_value_per_share,
    }

    display = {
        "price": {
            "close": price_data.get("close"),
            "as_of": price_data.get("as_of"),
        },
        "fundamentals": {
            "balance_sheet_basics": {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "shareholders_equity": total_equity,
                "book_value_per_share": book_value_per_share,
            },
            "valuation": {
                "pe_ttm": pe_ttm,
                "pb_ratio": pb_ratio,
                "graham_number": graham_number,
                "graham_upside_pct": graham_upside_pct,
                "graham_multiple": graham_multiple,
                "ncav_margin_pct": ncav_margin_pct,
            },
            "balance_sheet": {
                "debt_to_equity": debt_to_equity,
                "debt_to_ebitda": debt_to_ebitda,
                "current_ratio": current_ratio,
            },
            "cash_flow": {
                "fcf_margin_pct": fcf_margin_pct,
            },
            "growth": {
                "eps_growth_cagr_3yr_pct": eps_growth_cagr_3yr_pct,
            },
            "profitability": {
                "trend": margin_trend,
                "roe_pct": roe_pct,
            },
        },
    }

    # SEC's SIC description (e.g. "Motor Vehicles & Passenger Car Bodies")
    # is not the same taxonomy as FMP's GICS-style sector, so it's only used
    # as an "industry" fallback, purely for display. "sector" is left None
    # here when FMP's profile call fails - pipeline/main.py then falls back
    # to the watchlist's own hand-set sector.
    profile_out = {
        "name": _first_of(profile, "companyName") or ticker,
        "sector": _first_of(profile, "sector"),
        "industry": _first_of(profile, "industry") or sec_data.get("sic_description"),
        "cik": sec_data.get("cik"),
        "market_cap": market_cap,
        "shares_outstanding": shares_outstanding,
    }

    return {
        "metrics": metrics,
        "display": display,
        "profile": profile_out,
        "raw": {
            "income_stmts": income_stmts,
            "balance_stmts": balance_stmts,
            "cashflow_stmts": cashflow_stmts,
            "price_history": historical,
        },
    }
