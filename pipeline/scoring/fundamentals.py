"""Normalizes raw FMP + SEC EDGAR payloads into the flat metric dict the
scoring engine consumes, plus a grouped `display` dict for the output JSON.

FMP field names are matched defensively (a short list of candidate keys per
metric) since the exact free-tier response shape should be confirmed against
a live account before relying on this in production. Any metric that can't
be resolved from any candidate key, or whose source call failed upstream, is
left as None here — pipeline.scoring.thresholds treats a missing metric as
neutral rather than failing the run.
"""

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


def build_metrics(ticker: str, fmp_data: dict, sec_data: dict) -> dict:
    """Returns {"metrics": {...flat, scoring-ready...}, "display": {...grouped
    for output JSON...}, "profile": {name, sector, industry, cik}}."""
    profile = _first_row(fmp_data.get("profile"))
    quote = _first_row(fmp_data.get("quote"))
    ratios = _first_row(fmp_data.get("ratios_ttm"))
    key_metrics = _first_row(fmp_data.get("key_metrics_ttm"))
    dcf = _first_row(fmp_data.get("dcf"))
    income_stmts = fmp_data.get("income_statement") or []
    cashflow_stmts = fmp_data.get("cash_flow") or []
    historical = (fmp_data.get("historical_prices") or {}).get("historical") or []
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
        "gross_margin_pct": gross_margin_pct,
        "roe_pct": roe_pct,
        "margin_trend_score": _MARGIN_TREND_SCORE[margin_trend],
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "interest_coverage": interest_coverage,
        "fcf_margin_pct": fcf_margin_pct,
        "fcf_to_net_income": fcf_to_net_income,
    }

    display = {
        "price": {
            "close": price_data.get("close"),
            "as_of": price_data.get("as_of"),
            "return_1m_pct": price_data.get("return_1m_pct"),
            "return_3m_pct": price_data.get("return_3m_pct"),
        },
        "fundamentals": {
            "valuation": {
                "pe_ttm": pe_ttm,
                "ev_ebitda": ev_ebitda,
                "dcf_fair_value": fair_value,
                "dcf_upside_pct": dcf_upside_pct,
            },
            "growth": {
                "revenue_growth_yoy_pct": revenue_growth["yoy_pct"],
                "revenue_cagr_3yr_pct": revenue_growth["cagr_3yr_pct"],
                "eps_growth_yoy_pct": eps_growth["yoy_pct"],
            },
            "profitability": {
                "gross_margin_pct": gross_margin_pct,
                "roe_pct": roe_pct,
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
            },
        },
    }

    profile_out = {
        "name": _first_of(profile, "companyName") or ticker,
        "sector": _first_of(profile, "sector"),
        "industry": _first_of(profile, "industry"),
        "cik": sec_data.get("cik"),
    }

    return {"metrics": metrics, "display": display, "profile": profile_out}
