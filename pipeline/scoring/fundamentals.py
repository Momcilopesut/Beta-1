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

    # Derived directly from whichever price source supplied `rows` (FMP or
    # the Stooq fallback), so a volume-vs-own-average signal is available
    # either way rather than only when FMP's `quote` endpoint works.
    volumes = [h.get("volume") for h in rows if h.get("volume") is not None]
    latest_volume = volumes[-1] if volumes else None
    avg_volume = sum(volumes) / len(volumes) if len(volumes) >= 20 else None

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
        "volume": latest_volume,
        "avg_volume": avg_volume,
    }


def _cagr(latest: float, base: float, periods: int) -> float | None:
    if not base or (latest / base) <= 0:
        return None
    return ((latest / base) ** (1 / periods) - 1) * 100


def _growth(statements: list[dict], *field_candidates: str) -> dict:
    """statements: annual statements, most-recent-first (FMP convention).
    cagr_5yr_pct needs 6 annual statements (this year + 5 years back) -
    fmp.py requests limit=6 and sec_edgar.xbrl_fundamentals defaults to
    years=6 for exactly this; either source may still return fewer, in
    which case it's left None rather than computed over a shorter window
    silently mislabeled "5yr"."""
    values = [v for row in statements if (v := _first_of(row, *field_candidates)) is not None]
    if len(values) < 2:
        return {"yoy_pct": None, "cagr_3yr_pct": None, "cagr_5yr_pct": None}
    yoy = (values[0] - values[1]) / abs(values[1]) * 100 if values[1] else None
    cagr_3yr = _cagr(values[0], values[3], 3) if len(values) >= 4 else None
    cagr_5yr = _cagr(values[0], values[5], 5) if len(values) >= 6 else None
    return {"yoy_pct": yoy, "cagr_3yr_pct": cagr_3yr, "cagr_5yr_pct": cagr_5yr}


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


def build_metrics(
    ticker: str, fmp_data: dict, sec_data: dict, stooq_prices: list[dict] | None = None
) -> dict:
    """Returns {"metrics": {...flat, scoring-ready...}, "display": {...grouped
    for output JSON...}, "profile": {name, sector, industry, cik}}.

    Falls back to free sources when FMP's own endpoint failed outright
    (empty/None) rather than just being missing one field: SEC XBRL company
    facts (already fetched for filing links, see pipeline/fetch/sec_edgar.py)
    for statements, and Stooq (pipeline/fetch/stooq.py, called by the
    pipeline only when FMP's price data is missing) for price/volume
    history. Every downstream calculation below is source-agnostic - it
    just reads whichever statement/price rows ended up populated.
    """
    profile = _first_row(fmp_data.get("profile"))
    quote = _first_row(fmp_data.get("quote"))
    ratios = _first_row(fmp_data.get("ratios_ttm"))
    key_metrics = _first_row(fmp_data.get("key_metrics_ttm"))
    dcf = _first_row(fmp_data.get("dcf"))

    xbrl = sec_data.get("xbrl_fundamentals") or {}
    income_stmts = fmp_data.get("income_statement") or xbrl.get("income_stmts") or []
    balance_stmts = fmp_data.get("balance_sheet") or xbrl.get("balance_stmts") or []
    cashflow_stmts = fmp_data.get("cash_flow") or xbrl.get("cashflow_stmts") or []
    historical = _historical_rows(fmp_data.get("historical_prices")) or (stooq_prices or [])

    price_data = _returns_from_history(historical)
    if not price_data:
        price_data = {"close": _first_of(quote, "price"), "as_of": None}

    price = price_data.get("close")
    balance0 = balance_stmts[0] if balance_stmts else {}
    income0 = income_stmts[0] if income_stmts else {}

    pe_ttm = _first_of(ratios, "priceToEarningsRatioTTM", "peRatioTTM")
    fair_value = _first_of(dcf, "dcf", "equityValuePerShare")
    price_for_dcf = _first_of(dcf, "Stock Price", "stockPrice") or price
    dcf_upside_pct = (
        (fair_value - price_for_dcf) / price_for_dcf * 100 if fair_value and price_for_dcf else None
    )

    revenue_growth = _growth(income_stmts, "revenue")
    eps_growth = _growth(income_stmts, "epsdiluted", "eps")

    gross_margin_pct = None
    net_income = None
    revenue = None
    if income_stmts:
        revenue = _first_of(income0, "revenue")
        gross_profit = _first_of(income0, "grossProfit")
        net_income = _first_of(income0, "netIncome")
        if revenue and gross_profit is not None:
            gross_margin_pct = gross_profit / revenue * 100

    margin_trend = _margin_trend(income_stmts)

    total_equity = _first_of(balance0, "totalStockholdersEquity")
    total_debt = _first_of(balance0, "totalDebt")
    current_assets = _first_of(balance0, "totalCurrentAssets")
    current_liabilities = _first_of(balance0, "totalCurrentLiabilities")
    cash = _first_of(balance0, "cashAndCashEquivalents")

    roe_pct = _pct(_first_of(key_metrics, "roeTTM", "returnOnEquityTTM"))
    if roe_pct is None and net_income is not None and total_equity:
        roe_pct = net_income / total_equity * 100

    debt_to_equity = _first_of(ratios, "debtToEquityRatioTTM", "debtEquityRatioTTM")
    if debt_to_equity is None and total_debt is not None and total_equity:
        debt_to_equity = total_debt / total_equity

    current_ratio = _first_of(ratios, "currentRatioTTM")
    if current_ratio is None and current_assets is not None and current_liabilities:
        current_ratio = current_assets / current_liabilities

    interest_coverage = _first_of(ratios, "interestCoverageTTM", "interestCoverageRatioTTM")
    if interest_coverage is None:
        operating_income_0 = _first_of(income0, "operatingIncome")
        interest_expense = _first_of(income0, "interestExpense")
        if operating_income_0 is not None and interest_expense:
            interest_coverage = operating_income_0 / abs(interest_expense)

    fcf_ttm = None
    fcf_margin_pct = None
    fcf_to_net_income = None
    if cashflow_stmts:
        fcf_ttm = _first_of(cashflow_stmts[0], "freeCashFlow")
        if fcf_ttm is None:
            ocf = _first_of(cashflow_stmts[0], "operatingCashFlow")
            capex0 = _first_of(cashflow_stmts[0], "capitalExpenditure")
            if ocf is not None and capex0 is not None:
                fcf_ttm = ocf - abs(capex0)
        if fcf_ttm is not None and revenue:
            fcf_margin_pct = fcf_ttm / revenue * 100
        if fcf_ttm is not None and net_income:
            fcf_to_net_income = fcf_ttm / net_income

    ev_ebitda = _first_of(key_metrics, "evToEBITDATTM", "enterpriseValueOverEBITDATTM")

    ebitda_0 = None
    if income_stmts:
        operating_income_for_ebitda = _first_of(income0, "operatingIncome")
        d_and_a_for_ebitda = _first_of(cashflow_stmts[0], "depreciationAndAmortization") if cashflow_stmts else None
        if operating_income_for_ebitda is not None and d_and_a_for_ebitda is not None:
            ebitda_0 = operating_income_for_ebitda + d_and_a_for_ebitda
    debt_to_ebitda = total_debt / ebitda_0 if total_debt is not None and ebitda_0 and ebitda_0 > 0 else None

    # --- Value-investing metrics (Graham / Buffett) ---
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

    enterprise_value = (
        market_cap + total_debt - cash
        if market_cap is not None and total_debt is not None and cash is not None
        else None
    )

    if ev_ebitda is None and enterprise_value is not None:
        d_and_a_0 = _first_of(cashflow_stmts[0], "depreciationAndAmortization") if cashflow_stmts else None
        operating_income_0 = _first_of(income0, "operatingIncome")
        if operating_income_0 is not None and d_and_a_0 is not None:
            ebitda = operating_income_0 + d_and_a_0
            if ebitda > 0:
                ev_ebitda = enterprise_value / ebitda

    # Greenblatt's earnings yield: EBIT / enterprise value (EBIT approximated
    # as operating income - close enough for this pipeline's purposes, and
    # consistent with how operating income already stands in for EBIT in
    # the ev_ebitda fallback above).
    operating_income_0 = _first_of(income0, "operatingIncome") if income_stmts else None
    earnings_yield_pct = (
        operating_income_0 / enterprise_value * 100
        if operating_income_0 is not None and enterprise_value and enterprise_value > 0
        else None
    )

    # Fisher's R&D commitment - a company under-investing in its own future
    # relative to revenue is a concern his framework flags explicitly.
    r_and_d_0 = _first_of(income0, "researchAndDevelopmentExpenses", "researchAndDevelopment") if income_stmts else None
    r_and_d_to_revenue_pct = r_and_d_0 / revenue * 100 if r_and_d_0 is not None and revenue else None

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

    # Lynch's PEG ratio: P/E divided by the growth rate (as a plain number,
    # not a percentage) - prefers the 3yr EPS CAGR (a steadier trailing
    # growth figure than one noisy year-over-year print), falling back to
    # YoY growth when that's all that's available. Undefined (None) for a
    # non-positive P/E or non-positive growth rate - PEG isn't meaningful
    # for a loss-making or shrinking company.
    peg_growth_pct = eps_growth["cagr_3yr_pct"] if eps_growth["cagr_3yr_pct"] is not None else eps_growth["yoy_pct"]
    peg_ratio = pe_ttm / peg_growth_pct if pe_ttm is not None and pe_ttm > 0 and peg_growth_pct and peg_growth_pct > 0 else None

    ncav_margin_pct = None
    total_liabilities = _first_of(balance0, "totalLiabilities")
    if shares_outstanding and price and current_assets is not None and total_liabilities is not None:
        ncav_per_share = (current_assets - total_liabilities) / shares_outstanding
        ncav_margin_pct = (ncav_per_share - price) / price * 100

    owner_earnings_yield_pct = None
    if cashflow_stmts and market_cap:
        d_and_a = _first_of(cashflow_stmts[0], "depreciationAndAmortization")
        capex = _first_of(cashflow_stmts[0], "capitalExpenditure")
        owner_earnings = _owner_earnings(net_income, d_and_a, capex)
        if owner_earnings is not None:
            owner_earnings_yield_pct = owner_earnings / market_cap * 100

    roic_pct = _roic_pct(
        operating_income=_first_of(income0, "operatingIncome"),
        income_tax_expense=_first_of(income0, "incomeTaxExpense"),
        income_before_tax=_first_of(income0, "incomeBeforeTax"),
        total_debt=total_debt,
        total_equity=total_equity,
        cash=cash,
    )

    # --- Volume: a supply/demand signal from our own price data, not
    # speculation about *why* - unusual volume relative to the stock's own
    # average suggests unusual accumulation/distribution interest. Falls
    # back to volume derived from the price history itself (works for both
    # FMP and Stooq rows) when FMP's `quote` endpoint didn't supply it. ---
    volume = _first_of(quote, "volume") or price_data.get("volume")
    avg_volume = _first_of(quote, "avgVolume") or price_data.get("avg_volume")
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
        "revenue_cagr_5yr_pct": revenue_growth["cagr_5yr_pct"],
        "eps_growth_yoy_pct": eps_growth["yoy_pct"],
        "eps_growth_cagr_3yr_pct": eps_growth["cagr_3yr_pct"],
        "eps_growth_cagr_5yr_pct": eps_growth["cagr_5yr_pct"],
        "gross_margin_pct": gross_margin_pct,
        "roe_pct": roe_pct,
        "margin_trend_score": _MARGIN_TREND_SCORE[margin_trend],
        "debt_to_equity": debt_to_equity,
        "debt_to_ebitda": debt_to_ebitda,
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
        "earnings_yield_pct": earnings_yield_pct,
        "peg_ratio": peg_ratio,
        "r_and_d_to_revenue_pct": r_and_d_to_revenue_pct,
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
                "earnings_yield_pct": earnings_yield_pct,
                "peg_ratio": peg_ratio,
            },
            "growth": {
                "revenue_growth_yoy_pct": revenue_growth["yoy_pct"],
                "revenue_cagr_3yr_pct": revenue_growth["cagr_3yr_pct"],
                "revenue_cagr_5yr_pct": revenue_growth["cagr_5yr_pct"],
                "eps_growth_yoy_pct": eps_growth["yoy_pct"],
                "eps_growth_cagr_3yr_pct": eps_growth["cagr_3yr_pct"],
                "eps_growth_cagr_5yr_pct": eps_growth["cagr_5yr_pct"],
                "r_and_d_to_revenue_pct": r_and_d_to_revenue_pct,
            },
            "profitability": {
                "gross_margin_pct": gross_margin_pct,
                "roe_pct": roe_pct,
                "roic_pct": roic_pct,
                "trend": margin_trend,
            },
            "balance_sheet": {
                "debt_to_equity": debt_to_equity,
                "debt_to_ebitda": debt_to_ebitda,
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

    # SEC's SIC description (e.g. "Motor Vehicles & Passenger Car Bodies")
    # is not the same taxonomy as FMP's GICS-style sector, so it's only used
    # as an "industry" fallback, purely for display. "sector" is left None
    # here when FMP's profile call fails - pipeline/main.py then falls back
    # to the watchlist's own hand-set sector, which matches the scoring
    # config's sector table; a SIC string wouldn't.
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
        "raw": {"income_stmts": income_stmts, "balance_stmts": balance_stmts, "cashflow_stmts": cashflow_stmts},
    }
