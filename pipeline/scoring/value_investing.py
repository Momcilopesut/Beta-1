"""Classic value-investing checklists: Benjamin Graham's Defensive Investor
criteria (from "The Intelligent Investor") and a Munger Quality Checklist -
Charlie Munger's most distinctly-his, most quotable idea made into simple
pass/fail arithmetic: a business's return on the capital it's given matters
more than how statistically cheap it looks ("if a business earns 18% on
capital over 20 or 30 years, even if you pay an expensive looking price,
you'll end up with a fine result"). Both are explicit pass/fail checklists;
Graham's is the Investment Meter's base score, Munger's is a multiplier on
top of it (see pipeline/scoring/aggregation.py) - they're also rendered as
their own checklist on the company detail page.

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
                f"Positive in {sum(1 for v in net_incomes if v > 0)}/{len(net_incomes)} available years",
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
                "Currently pays a dividend (a longer uninterrupted record can't be verified from this data)",
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
                "Earnings growth (>= ~2.9%/yr average pace)",
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


_MUNGER_ROE_THRESHOLD_PCT = 15.0  # Buffett/Munger's commonly-cited quality bar
_MUNGER_DEBT_TO_EQUITY_THRESHOLD = 1.0


def munger_quality_checklist(metrics: dict, raw: dict) -> dict:
    """Munger's own test, in basic arithmetic: does this business actually
    earn good returns on the capital it's given, without doing anything
    obviously reckless to get there? Each criterion is independently
    evaluated (unlike Piotroski's old all-or-nothing 2-year gate) - a
    missing single-year input doesn't block the other three."""
    income_stmts = raw.get("income_stmts") or []
    criteria = []

    def add(name: str, value: bool | None, detail: str):
        criteria.append({"criterion": name, "passed": value, "detail": detail})

    # 1. Return on equity - Munger's central point: a business that earns a
    # high return on shareholders' capital, sustained over time, is worth
    # far more than its statistical cheapness alone would suggest.
    roe_pct = metrics.get("roe_pct")
    if roe_pct is None:
        add(f"Strong return on equity (>= {_MUNGER_ROE_THRESHOLD_PCT:.0f}%)", None, "ROE unavailable")
    else:
        passed = roe_pct >= _MUNGER_ROE_THRESHOLD_PCT
        add(f"Strong return on equity (>= {_MUNGER_ROE_THRESHOLD_PCT:.0f}%)", passed, f"ROE {roe_pct:.1f}%")

    # 2. Not overloaded with debt - Munger repeatedly warned that leverage
    # turns an ordinary mistake into a fatal one.
    debt_to_equity = metrics.get("debt_to_equity")
    if debt_to_equity is None:
        add(f"Not overloaded with debt (debt/equity <= {_MUNGER_DEBT_TO_EQUITY_THRESHOLD:.1f})", None, "Debt/equity unavailable")
    else:
        passed = debt_to_equity <= _MUNGER_DEBT_TO_EQUITY_THRESHOLD
        add(
            f"Not overloaded with debt (debt/equity <= {_MUNGER_DEBT_TO_EQUITY_THRESHOLD:.1f})",
            passed,
            f"Debt/equity {debt_to_equity:.2f}",
        )

    # 3. Not diluting shareholders - reckless share issuance is exactly the
    # kind of "stupidity" Munger says is easier to avoid than brilliance is
    # to achieve.
    if len(income_stmts) < 2:
        add("Not diluting shareholders (share count flat or falling)", None, "Fewer than 2 years of share-count data")
    else:
        shares0 = _get(income_stmts[0], "weightedAverageShsOutDil", "weightedAverageShsOut")
        shares1 = _get(income_stmts[1], "weightedAverageShsOutDil", "weightedAverageShsOut")
        if shares0 is None or shares1 is None:
            add("Not diluting shareholders (share count flat or falling)", None, "Share count unavailable")
        else:
            passed = shares0 <= shares1
            add(
                "Not diluting shareholders (share count flat or falling)",
                passed,
                f"{shares0:,.0f} shares vs. {shares1:,.0f} a year earlier",
            )

    # 4. Margins stable or improving, not declining - a business with
    # eroding margins is losing whatever edge gave it good returns in the
    # first place. metrics["margin_trend_score"] defaults to a "stable"
    # reading when there's no real data to compute a trend from (see
    # fundamentals.py::_margin_trend) - checking for at least 2 years of
    # real revenue/gross-profit data directly, rather than trusting that
    # field's presence, avoids reading "no data" as "a real pass."
    margin_years = [
        row for row in income_stmts[:3] if _get(row, "revenue") and _get(row, "grossProfit") is not None
    ]
    if len(margin_years) < 2:
        add("Margins stable or improving (not declining)", None, "Margin trend unavailable")
    else:
        margin_trend_score = metrics.get("margin_trend_score")
        passed = margin_trend_score >= 60  # _MARGIN_TREND_SCORE: declining=20, stable=60, improving=100
        add("Margins stable or improving (not declining)", passed, f"Margin trend score {margin_trend_score}")

    evaluated = [c for c in criteria if c["passed"] is not None]
    passed_count = sum(1 for c in evaluated if c["passed"])
    return {"criteria": criteria, "passed": passed_count, "evaluated": len(evaluated), "total": len(criteria)}


def build_checklist(metrics: dict, profile: dict, raw: dict) -> dict:
    return {
        "graham_defensive": graham_defensive_checklist(metrics, profile, raw),
        "munger_quality": munger_quality_checklist(metrics, raw),
    }
