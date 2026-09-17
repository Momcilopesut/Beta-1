"""Normalizes raw FMP + SEC EDGAR payloads into the flat metric dict the
scoring engine consumes, plus a grouped `display` dict for the output JSON.

FMP field names are matched defensively (a short list of candidate keys per
metric) since the exact free-tier response shape should be confirmed against
a live account before relying on this in production. Any metric that can't
be resolved from any candidate key, or whose source call failed upstream, is
left as None here — pipeline.scoring.thresholds treats a missing metric as
neutral rather than failing the run.

Also computes the classic value-investing metrics associated with Benjamin
Graham and Warren Buffett (Graham Number, Graham multiple, net current asset
value, owner earnings, return on invested capital) - all derived from fields
already present in the existing FMP calls, deliberately adding no new
endpoints (this account is on a limited plan; see pipeline/fetch/fmp.py).
"""

import math
from typing import Any

from pipeline.fetch.sec_edgar import xbrl_concept

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


def _pct(fraction: float | None) -> float | None:
    """FMP *TTM ratio fields (e.g. roeTTM) are decimal fractions; convert to
    percentage points."""
    return None if fraction is None else fraction * 100


def _historical_rows(historical_prices: Any) -> list[dict]:
    """FMP's /stable/historical-price-eod/full has returned a bare list of
    {date, close, ...} rows directly in practice, not the older
    {"symbol":..., "historical": [...]} wrapper this originally assumed.
    Accept either shape (or a missing/failed fetch) instead of crashing."""
    if isinstance(historical_prices, list):
        return historical_prices
    if isinstance(historical_prices, dict):
        return historical_prices.get("historical") or []
    return []


def _returns_from_history(historical: list[dict]) -> dict:
    rows = sorted(
        (h for h in historical if h.get("close") is not None), key=lambda h: h["date"]
    )
    if not rows:
        return {}
    closes = [h["close"] for h in rows]
    latest, latest_date = closes[-1], rows[-1]["date"]

    def pct_change(n_back: int) -> float | None:
        if len(closes) <= n_back or not closes[-1 - n_back]:
            return None
        base = closes[-1 - n_back]
        return (latest - base) / base * 100

    def moving_avg(n: int) -> float | None:
        if len(closes) < n:
            return None
        return sum(closes[-n:]) / n

    def rsi_14() -> float | None:
        n = 14
        if len(closes) < n + 1:
            return None
        gains, losses = [], []
        for i in range(-n, 0):
            change = closes[i] - closes[i - 1]
            (gains if change > 0 else losses).append(abs(change))
        avg_gain, avg_loss = sum(gains) / n, sum(losses) / n
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    ma50, ma200, rsi = moving_avg(50), moving_avg(200), rsi_14()
    window = closes[-252:] if len(closes) >= 252 else closes

    return {
        "close": latest,
        "as_of": latest_date,
        "return_1m_pct": pct_change(21),
        "return_3m_pct": pct_change(63),
        "price_vs_ma50_pct": (latest - ma50) / ma50 * 100 if ma50 else None,
        "price_vs_ma200_pct": (latest - ma200) / ma200 * 100 if ma200 else None,
        "rsi_14": rsi,
        "rsi_distance_from_neutral": abs(rsi - 50) if rsi is not None else None,
        "high_52w": max(window),
        "low_52w": min(window),
    }


def _growth(statements: list[dict], *field_candidates: str) -> dict:
    """statements: annual statements, most-recent-first (FMP convention)."""
    values = [v for row in statements if (v := _first_of(row, *field_candidates)) is not None]
    if len(values) < 2:
        return {"yoy_pct": None, "cagr_3yr_pct": None}
    yoy = (values[0] - values[1]) / abs(values[1]) * 100 if values[1] else None
    cagr = None
    if len(values) >= 4 and values[3] and (values[0] / values[3]) > 0:
        cagr = ((values[0] / values[3]) ** (1 / 3) - 1) * 100
    return {"yoy_pct": yoy, "cagr_3yr_pct": cagr}


def _revenue_yoy_fallback(company_facts: dict | None) -> float | None:
    """SEC XBRL fallback for revenue YoY growth if FMP's income statement is
    unavailable."""
    if not company_facts:
        return None
    facts = sorted(
        (
            f
            for f in xbrl_concept(company_facts, "us-gaap", "Revenues")
            if f.get("form") == "10-K" and f.get("fp") == "FY"
        ),
        key=lambda f: f.get("end", ""),
    )
    if len(facts) < 2 or not facts[-2]["val"]:
        return None
    return (facts[-1]["val"] - facts[-2]["val"]) / abs(facts[-2]["val"]) * 100


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
    """sqrt(22.5 x EPS x BVPS) - Graham's quick fair-value estimate. 22.5 is
    Graham's own combined ceiling (P/E <= 15 x P/B <= 1.5). Undefined (None)
    if either input is missing or non-positive - a negative product has no
    real square root and isn't meaningful here anyway."""
    if eps is None or book_value_per_share is None or eps <= 0 or book_value_per_share <= 0:
        return None
    return math.sqrt(22.5 * eps * book_value_per_share)


def _owner_earnings(net_income: float | None, d_and_a: float | None, capex: float | None) -> float | None:
    """Buffett's simplified owner earnings: net income + depreciation &
    amortization - capital expenditures (working-capital changes omitted,
    as in the commonly-used simplified form). capex's sign varies by
    source, so its magnitude is always subtracted regardless of sign."""
    if net_income is None or d_and_a is None or capex is None:
        return None
    return net_income + d_and_a - abs(capex)


def _roic_pct(
    operating_income: float | None,
    income_tax_expense: float | None,
    income_before_tax: float | None,
    total_debt: float | None,
    total_equity: float | None,
    cash: float | None,
) -> float | None:
    """Return on invested capital: NOPAT / (debt + equity - cash), as a
    percentage. NOPAT = operating income x (1 - effective tax rate).
    None if pretax income isn't positive (effective tax rate is not
    meaningful for a loss-making period) or invested capital isn't
    positive."""
    if operating_income is None or income_before_tax is None or not income_before_tax > 0:
        return None
    if income_tax_expense is None:
        return None
    tax_rate = income_tax_expense / income_before_tax
    tax_rate = min(max(tax_rate, 0.0), 1.0)
    nopat = operating_income * (1 - tax_rate)
    if total_debt is None or total_equity is None or cash is None:
        return None
    invested_capital = total_debt + total_equity - cash
    if invested_capital <= 0:
        return None
    return nopat / invested_capital * 100


def build_metrics(ticker: str, fmp_data: dict, sec_data: dict) -> dict:
    """Returns {"metrics": {...flat, scoring-ready...}, "display": {...grouped
    for output JSON...}, "profile": {name, sector, industry, cik}}."""
    profile = _first_row(fmp_data.get("profile"))
    quote = _first_row(fmp_data.get("quote"))
    ratios = _first_row(fmp_data.get("ratios_ttm"))
    key_metrics = _first_row(fmp_data.get("key_metrics_ttm"))
    dcf = _first_row(fmp_data.get("dcf"))
    income_stmts = fmp_data.get("income_statement") or []
    balance_stmts = fmp_data.get("balance_sheet") or []
    cashflow_stmts = fmp_data.get("cash_flow") or []
    historical = _historical_rows(fmp_data.get("historical_prices"))
    company_facts = sec_data.get("company_facts")

    price_data = _returns_from_history(historical)
    if not price_data:
        price_data = {"close": _first_of(quote, "price"), "as_of": None}

    pe_ttm = _first_of(ratios, "priceToEarningsRatioTTM", "peRatioTTM")
    ev_ebitda = _first_of(key_metrics, "evToEBITDATTM", "enterpriseValueOverEBITDATTM")
    fair_value = _first_of(dcf, "dcf", "equityValuePerShare")
    price_for_dcf = _first_of(dcf, "Stock Price", "stockPrice") or price_data.get("close")
    dcf_upside_pct = (
        (fair_value - price_for_dcf) / price_for_dcf * 100 if fair_value and price_for_dcf else None
    )

    revenue_growth = _growth(income_stmts, "revenue")
    if revenue_growth["yoy_pct"] is None:
        revenue_growth["yoy_pct"] = _revenue_yoy_fallback(company_facts)
    eps_growth = _growth(income_stmts, "epsdiluted", "eps")

    gross_margin_pct = None
    net_income = None
    revenue = None
    if income_stmts:
        revenue = _first_of(income_stmts[0], "revenue")
        gross_profit = _first_of(income_stmts[0], "grossProfit")
        net_income = _first_of(income_stmts[0], "netIncome")
        if revenue and gross_profit is not None:
            gross_margin_pct = gross_profit / revenue * 100

    roe_pct = _pct(_first_of(key_metrics, "roeTTM", "returnOnEquityTTM"))
    margin_trend = _margin_trend(income_stmts)

    debt_to_equity = _first_of(ratios, "debtToEquityRatioTTM", "debtEquityRatioTTM")
    current_ratio = _first_of(ratios, "currentRatioTTM")
    interest_coverage = _first_of(ratios, "interestCoverageTTM", "interestCoverageRatioTTM")

    fcf_margin_pct = None
    fcf_to_net_income = None
    if cashflow_stmts:
        fcf = _first_of(cashflow_stmts[0], "freeCashFlow")
        if fcf is not None and revenue:
            fcf_margin_pct = fcf / revenue * 100
        if fcf is not None and net_income:
            fcf_to_net_income = fcf / net_income

    # --- Value-investing metrics (Graham / Buffett) ---
    shares_outstanding = _first_of(quote, "sharesOutstanding") or _first_of(
        key_metrics, "sharesOutstandingTTM"
    )
    market_cap = _first_of(quote, "marketCap") or _first_of(profile, "mktCap")
    price = price_data.get("close")
    if market_cap is None and price and shares_outstanding:
        market_cap = price * shares_outstanding
    if shares_outstanding is None and market_cap and price:
        shares_outstanding = market_cap / price

    book_value_per_share = _first_of(ratios, "bookValuePerShareTTM") or _first_of(
        key_metrics, "bookValuePerShareTTM"
    )
    balance0 = balance_stmts[0] if balance_stmts else {}
    if book_value_per_share is None and shares_outstanding:
        equity = _first_of(balance0, "totalStockholdersEquity")
        if equity is not None:
            book_value_per_share = equity / shares_outstanding

    pb_ratio = _first_of(ratios, "priceToBookRatioTTM")
    if pb_ratio is None and price and book_value_per_share:
        pb_ratio = price / book_value_per_share

    eps_ttm = _first_of(quote, "eps") or _first_of(income_stmts[0] if income_stmts else {}, "epsdiluted", "eps")
    graham_number = _graham_number(eps_ttm, book_value_per_share)
    graham_upside_pct = (graham_number - price) / price * 100 if graham_number and price else None
    graham_multiple = pe_ttm * pb_ratio if pe_ttm is not None and pb_ratio is not None else None

    ncav_margin_pct = None
    if balance0 and shares_outstanding and price:
        current_assets = _first_of(balance0, "totalCurrentAssets")
        total_liabilities = _first_of(balance0, "totalLiabilities")
        if current_assets is not None and total_liabilities is not None:
            ncav_per_share = (current_assets - total_liabilities) / shares_outstanding
            ncav_margin_pct = (ncav_per_share - price) / price * 100

    owner_earnings_yield_pct = None
    if cashflow_stmts and market_cap:
        d_and_a = _first_of(cashflow_stmts[0], "depreciationAndAmortization")
        capex = _first_of(cashflow_stmts[0], "capitalExpenditure")
        owner_earnings = _owner_earnings(net_income, d_and_a, capex)
        if owner_earnings is not None:
            owner_earnings_yield_pct = owner_earnings / market_cap * 100

    roic_pct = None
    if income_stmts and balance0:
        roic_pct = _roic_pct(
            operating_income=_first_of(income_stmts[0], "operatingIncome"),
            income_tax_expense=_first_of(income_stmts[0], "incomeTaxExpense"),
            income_before_tax=_first_of(income_stmts[0], "incomeBeforeTax"),
            total_debt=_first_of(balance0, "totalDebt"),
            total_equity=_first_of(balance0, "totalStockholdersEquity"),
            cash=_first_of(balance0, "cashAndCashEquivalents"),
        )

    # --- Volume: a supply/demand signal from our own price data, not
    # speculation about *why* - unusual volume relative to the stock's own
    # average suggests unusual accumulation/distribution interest. ---
    volume = _first_of(quote, "volume")
    avg_volume = _first_of(quote, "avgVolume")
    volume_vs_avg_ratio = volume / avg_volume if volume is not None and avg_volume else None

    metrics = {
        "return_1m_pct": price_data.get("return_1m_pct"),
        "return_3m_pct": price_data.get("return_3m_pct"),
        "price_vs_ma50_pct": price_data.get("price_vs_ma50_pct"),
        "price_vs_ma200_pct": price_data.get("price_vs_ma200_pct"),
        "rsi_distance_from_neutral": price_data.get("rsi_distance_from_neutral"),
        "earnings_surprise_pct": None,  # not covered by v1 FMP call set; scores as neutral
        "dcf_upside_pct": dcf_upside_pct,
        "pe_ttm": pe_ttm,
        "ev_ebitda": ev_ebitda,
        "revenue_growth_yoy_pct": revenue_growth["yoy_pct"],
        "revenue_cagr_3yr_pct": revenue_growth["cagr_3yr_pct"],
        "eps_growth_yoy_pct": eps_growth["yoy_pct"],
        "eps_growth_cagr_3yr_pct": eps_growth["cagr_3yr_pct"],
        "gross_margin_pct": gross_margin_pct,
        "roe_pct": roe_pct,
        "margin_trend_score": _MARGIN_TREND_SCORE[margin_trend],
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "interest_coverage": interest_coverage,
        "fcf_margin_pct": fcf_margin_pct,
        "fcf_to_net_income": fcf_to_net_income,
        "pb_ratio": pb_ratio,
        "graham_upside_pct": graham_upside_pct,
        "graham_multiple": graham_multiple,
        "roic_pct": roic_pct,
        "owner_earnings_yield_pct": owner_earnings_yield_pct,
        "volume_vs_avg_ratio": volume_vs_avg_ratio,
        # informational only, not fed into the weighted score - see
        # config/scoring_weights.yaml comment on ncav_margin_pct
        "ncav_margin_pct": ncav_margin_pct,
    }

    display = {
        "price": {
            "close": price_data.get("close"),
            "as_of": price_data.get("as_of"),
            "return_1m_pct": price_data.get("return_1m_pct"),
            "return_3m_pct": price_data.get("return_3m_pct"),
            "volume": volume,
            "avg_volume": avg_volume,
            "volume_vs_avg_ratio": volume_vs_avg_ratio,
        },
        "fundamentals": {
            "valuation": {
                "pe_ttm": pe_ttm,
                "pb_ratio": pb_ratio,
                "ev_ebitda": ev_ebitda,
                "dcf_fair_value": fair_value,
                "dcf_upside_pct": dcf_upside_pct,
                "graham_number": graham_number,
                "graham_upside_pct": graham_upside_pct,
                "graham_multiple": graham_multiple,
                "ncav_margin_pct": ncav_margin_pct,
            },
            "growth": {
                "revenue_growth_yoy_pct": revenue_growth["yoy_pct"],
                "revenue_cagr_3yr_pct": revenue_growth["cagr_3yr_pct"],
                "eps_growth_yoy_pct": eps_growth["yoy_pct"],
                "eps_growth_cagr_3yr_pct": eps_growth["cagr_3yr_pct"],
            },
            "profitability": {
                "gross_margin_pct": gross_margin_pct,
                "roe_pct": roe_pct,
                "roic_pct": roic_pct,
                "trend": margin_trend,
            },
            "balance_sheet": {
                "debt_to_equity": debt_to_equity,
                "current_ratio": current_ratio,
                "interest_coverage": interest_coverage,
            },
            "cash_flow": {
                "fcf_margin_pct": fcf_margin_pct,
                "fcf_to_net_income": fcf_to_net_income,
                "owner_earnings_yield_pct": owner_earnings_yield_pct,
            },
        },
    }

    profile_out = {
        "name": _first_of(profile, "companyName") or ticker,
        "sector": _first_of(profile, "sector"),
        "industry": _first_of(profile, "industry"),
        "cik": sec_data.get("cik"),
        "market_cap": market_cap,
    }

    return {
        "metrics": metrics,
        "display": display,
        "profile": profile_out,
        "raw": {"income_stmts": income_stmts, "balance_stmts": balance_stmts, "cashflow_stmts": cashflow_stmts},
    }
