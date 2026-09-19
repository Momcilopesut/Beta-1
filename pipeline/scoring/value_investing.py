"""Classic value-investing checklists: Benjamin Graham's Defensive Investor
criteria (from "The Intelligent Investor") and the Piotroski F-Score (a
quantitative quality screen built on the same balance-sheet-driven
tradition). Both are explicit pass/fail checklists, and together form the
Conviction Score's two components (see pipeline/scoring/aggregation.py) -
they're also rendered as their own checklist on the company detail page.

Every criterion is computed from data already fetched (income/balance/cash
flow statements, quote) - no new API calls. A criterion is `passed: None`
(not False) when the required field is missing, so a data gap never reads
as a failure.

Graham's originals assumed a 10-year lookback (earnings stability, dividend
record); we only have up to 5 annual statements, so those two criteria are
evaluated over whatever window is available and the checklist reports how
many years that actually was.
"""

from typing import Any


def _get(row: dict, *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _criterion(name: str, passed: bool | None, detail: str) -> dict:
    return {"criterion": name, "passed": passed, "detail": detail}


def graham_defensive_checklist(metrics: dict, profile: dict, raw: dict) -> dict:
    """The 7 criteria from Graham's "defensive investor" screen (Chapter 14,
    The Intelligent Investor), adapted where a modern equivalent is needed."""
    income_stmts = raw.get("income_stmts") or []
    balance_stmts = raw.get("balance_stmts") or []
    cashflow_stmts = raw.get("cashflow_stmts") or []
    balance0 = balance_stmts[0] if balance_stmts else {}

    criteria = []

    # 1. Adequate size (Graham used annual sales; modernized to market cap).
    market_cap = profile.get("market_cap")
    if market_cap is None:
        criteria.append(_criterion("Adequate size", None, "Market cap unavailable"))
    else:
        passed = market_cap >= 2_000_000_000
        criteria.append(
            _criterion(
                "Adequate size (market cap >= $2B)",
                passed,
                f"Market cap ${market_cap / 1e9:.1f}B",
            )
        )

    # 2. Strong financial condition: current ratio >= 2 and total debt <=
    # working capital.
    current_ratio = metrics.get("current_ratio")
    current_assets = _get(balance0, "totalCurrentAssets")
    current_liabilities = _get(balance0, "totalCurrentLiabilities")
    total_debt = _get(balance0, "totalDebt")
    if current_ratio is None or current_assets is None or current_liabilities is None or total_debt is None:
        criteria.append(_criterion("Strong financial condition", None, "Balance sheet data unavailable"))
    else:
        working_capital = current_assets - current_liabilities
        passed = current_ratio >= 2 and total_debt <= working_capital
        criteria.append(
            _criterion(
                "Strong financial condition (current ratio >= 2, debt <= working capital)",
                passed,
                f"Current ratio {current_ratio:.2f}, debt ${total_debt / 1e9:.1f}B vs working capital "
                f"${working_capital / 1e9:.1f}B",
            )
        )

    # 3. Earnings stability: positive net income in every available annual
    # statement.
    net_incomes = [_get(row, "netIncome") for row in income_stmts]
    net_incomes = [v for v in net_incomes if v is not None]
    if not net_incomes:
        criteria.append(_criterion("Earnings stability", None, "No annual net income data available"))
    else:
        passed = all(v > 0 for v in net_incomes)
        criteria.append(
            _criterion(
                "Earnings stability (positive net income every year)",
                passed,
                f"Positive in {sum(1 for v in net_incomes if v > 0)}/{len(net_incomes)} available years "
                "(Graham's original window was 10 years)",
            )
        )

    # 4. Dividend record (proxy: currently pays a dividend - not Graham's
    # original 20-year uninterrupted record, which this data can't check).
    # Sign convention varies by source (FMP reports a cash outflow as
    # negative; XBRL "Payments" concepts report a positive magnitude), so
    # this checks magnitude, not sign.
    dividends_paid = _get(cashflow_stmts[0], "dividendsPaid") if cashflow_stmts else None
    if dividends_paid is None:
        criteria.append(_criterion("Dividend record", None, "Dividend data unavailable"))
    else:
        passed = abs(dividends_paid) > 0
        criteria.append(
            _criterion(
                "Currently pays a dividend (proxy for Graham's 20yr record, unverifiable here)",
                passed,
                f"Most recent year dividends paid: {'yes' if passed else 'no'}",
            )
        )

    # 5. Earnings growth over the available window (Graham wanted >= 33%
    # over 10 years, roughly 2.9%/yr compounded).
    eps_cagr = metrics.get("eps_growth_cagr_3yr_pct")
    if eps_cagr is None:
        criteria.append(_criterion("Earnings growth", None, "Insufficient EPS history"))
    else:
        passed = eps_cagr >= 2.9
        criteria.append(
            _criterion(
                "Earnings growth (>= ~2.9%/yr, Graham's 33%/10yr pace)",
                passed,
                f"EPS 3yr CAGR {eps_cagr:.1f}%/yr",
            )
        )

    # 6. Moderate P/E.
    pe_ttm = metrics.get("pe_ttm")
    if pe_ttm is None:
        criteria.append(_criterion("Moderate P/E", None, "P/E unavailable"))
    else:
        passed = 0 < pe_ttm <= 15
        criteria.append(_criterion("Moderate P/E (<= 15)", passed, f"P/E {pe_ttm:.1f}"))

    # 7. Moderate combined multiple: P/E x P/B <= 22.5 (Graham's own stated
    # alternative to separate P/E and P/B ceilings).
    graham_multiple = metrics.get("graham_multiple")
    if graham_multiple is None:
        criteria.append(_criterion("Moderate P/E x P/B", None, "P/E or P/B unavailable"))
    else:
        passed = graham_multiple <= 22.5
        criteria.append(
            _criterion("Moderate P/E x P/B (<= 22.5)", passed, f"P/E x P/B = {graham_multiple:.1f}")
        )

    evaluated = [c for c in criteria if c["passed"] is not None]
    passed_count = sum(1 for c in evaluated if c["passed"])
    return {"criteria": criteria, "passed": passed_count, "evaluated": len(evaluated), "total": len(criteria)}


def piotroski_f_score(raw: dict) -> dict:
    """The 9-point Piotroski F-Score, comparing the two most recent annual
    statements. Each criterion is worth 1 point; a criterion that can't be
    evaluated (missing a required field in either year) is excluded from
    both the score and the max rather than counted as a failure."""
    income_stmts = raw.get("income_stmts") or []
    balance_stmts = raw.get("balance_stmts") or []
    cashflow_stmts = raw.get("cashflow_stmts") or []

    if len(income_stmts) < 2 or len(balance_stmts) < 2 or len(cashflow_stmts) < 2:
        return {"criteria": [], "score": 0, "evaluated": 0, "max": 9, "note": "Fewer than 2 years of statements available"}

    inc0, inc1 = income_stmts[0], income_stmts[1]
    bal0, bal1 = balance_stmts[0], balance_stmts[1]
    cf0 = cashflow_stmts[0]

    def g(row, *keys):
        return _get(row, *keys)

    criteria = []

    def add(name: str, value: bool | None):
        criteria.append({"criterion": name, "passed": value})

    net_income0 = g(inc0, "netIncome")
    total_assets0 = g(bal0, "totalAssets")
    total_assets1 = g(bal1, "totalAssets")
    op_cash_flow0 = g(cf0, "operatingCashFlow")

    roa0 = net_income0 / total_assets0 if net_income0 is not None and total_assets0 else None
    net_income1 = g(inc1, "netIncome")
    roa1 = net_income1 / total_assets1 if net_income1 is not None and total_assets1 else None

    add("Positive net income", net_income0 > 0 if net_income0 is not None else None)
    add("Positive operating cash flow", op_cash_flow0 > 0 if op_cash_flow0 is not None else None)
    add("ROA improving year over year", roa0 > roa1 if roa0 is not None and roa1 is not None else None)
    add(
        "Operating cash flow exceeds net income (earnings quality)",
        op_cash_flow0 > net_income0 if op_cash_flow0 is not None and net_income0 is not None else None,
    )

    debt0, debt1 = g(bal0, "totalDebt"), g(bal1, "totalDebt")
    leverage0 = debt0 / total_assets0 if debt0 is not None and total_assets0 else None
    leverage1 = debt1 / total_assets1 if debt1 is not None and total_assets1 else None
    add(
        "Leverage decreasing year over year",
        leverage0 < leverage1 if leverage0 is not None and leverage1 is not None else None,
    )

    ca0, cl0 = g(bal0, "totalCurrentAssets"), g(bal0, "totalCurrentLiabilities")
    ca1, cl1 = g(bal1, "totalCurrentAssets"), g(bal1, "totalCurrentLiabilities")
    cur0 = ca0 / cl0 if ca0 is not None and cl0 else None
    cur1 = ca1 / cl1 if ca1 is not None and cl1 else None
    add(
        "Current ratio improving year over year",
        cur0 > cur1 if cur0 is not None and cur1 is not None else None,
    )

    shares0 = g(inc0, "weightedAverageShsOutDil", "weightedAverageShsOut")
    shares1 = g(inc1, "weightedAverageShsOutDil", "weightedAverageShsOut")
    add(
        "No new shares issued (no dilution)",
        shares0 <= shares1 if shares0 is not None and shares1 is not None else None,
    )

    rev0, gp0 = g(inc0, "revenue"), g(inc0, "grossProfit")
    rev1, gp1 = g(inc1, "revenue"), g(inc1, "grossProfit")
    gm0 = gp0 / rev0 if gp0 is not None and rev0 else None
    gm1 = gp1 / rev1 if gp1 is not None and rev1 else None
    add(
        "Gross margin improving year over year",
        gm0 > gm1 if gm0 is not None and gm1 is not None else None,
    )

    turnover0 = rev0 / total_assets0 if rev0 is not None and total_assets0 else None
    turnover1 = rev1 / total_assets1 if rev1 is not None and total_assets1 else None
    add(
        "Asset turnover improving year over year",
        turnover0 > turnover1 if turnover0 is not None and turnover1 is not None else None,
    )

    evaluated = [c for c in criteria if c["passed"] is not None]
    score = sum(1 for c in evaluated if c["passed"])
    return {"criteria": criteria, "score": score, "evaluated": len(evaluated), "max": 9}


def build_checklist(metrics: dict, profile: dict, raw: dict) -> dict:
    return {
        "graham_defensive": graham_defensive_checklist(metrics, profile, raw),
        "piotroski_f_score": piotroski_f_score(raw),
    }
