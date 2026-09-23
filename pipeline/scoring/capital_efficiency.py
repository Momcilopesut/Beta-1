"""Aggregate, market-wide capital-efficiency metrics: bottom-up ROIC,
reinvestment rate, and expected organic growth for the whole tracked
universe, built by summing each company's own already-fetched financial
statements - no aggregate data vendor (Compustat, FactSet, Bloomberg
terminal) needed, since this pipeline already fetches every one of these
companies' statements individually, every run.

    ROIC = NOPAT / Invested Capital
    Reinvestment Rate = (CapEx - Depreciation + Change in Working Capital) / NOPAT
    Expected Growth = ROIC x Reinvestment Rate

Deliberately no ML: WACC uses a simple CAPM proxy (risk-free rate = the
latest 10-year Treasury yield already tracked on the macro page, market
beta of 1.0 since this is being measured against the aggregate market
itself rather than one stock's volatility relative to it, plus a
configured equity risk premium) instead of a per-company beta regression,
which this pipeline has no broad enough price-return history to estimate
reliably. Every assumption lives in config/capital_efficiency.yaml.

"null not zero": a company missing any of the handful of fields this needs
(operating income, tax figures, capex, debt, equity) is simply excluded
from that one aggregate sum, not counted as a zero - see each aggregate's
own "_n" coverage count in the output.
"""

from typing import Any


def _get(row: dict, *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _working_capital(row: dict) -> float | None:
    current_assets = _get(row, "totalCurrentAssets")
    current_liabilities = _get(row, "totalCurrentLiabilities")
    if current_assets is None or current_liabilities is None:
        return None
    return current_assets - current_liabilities


def company_capital_efficiency_inputs(raw: dict, profile: dict) -> dict | None:
    """raw: {"income_stmts", "balance_stmts", "cashflow_stmts"} as returned
    by pipeline.scoring.fundamentals.build_metrics (real FMP or the SEC XBRL
    fallback - both share these field names). profile: build_metrics'
    profile dict (for market_cap). Returns None when there isn't even one
    full set of annual statements to read from; otherwise a dict of raw
    inputs (each individually None when its own source field is missing) -
    aggregation happens across companies in aggregate_capital_efficiency."""
    income_stmts = raw.get("income_stmts") or []
    balance_stmts = raw.get("balance_stmts") or []
    cashflow_stmts = raw.get("cashflow_stmts") or []
    if not income_stmts or not balance_stmts or not cashflow_stmts:
        return None

    income0, balance0, cashflow0 = income_stmts[0], balance_stmts[0], cashflow_stmts[0]

    operating_income = _get(income0, "operatingIncome")
    pretax_income = _get(income0, "incomeBeforeTax")
    tax_expense = _get(income0, "incomeTaxExpense")
    effective_tax_rate = tax_expense / pretax_income if tax_expense is not None and pretax_income else None
    nopat = (
        operating_income * (1 - effective_tax_rate)
        if operating_income is not None and effective_tax_rate is not None
        else None
    )

    total_debt = _get(balance0, "totalDebt")
    total_equity = _get(balance0, "totalStockholdersEquity")
    non_operating_cash = _get(balance0, "cashAndCashEquivalents", "cashAndShortTermInvestments")
    invested_capital = (
        total_debt + total_equity - non_operating_cash
        if total_debt is not None and total_equity is not None and non_operating_cash is not None
        else None
    )

    capex = _get(cashflow0, "capitalExpenditure")
    if capex is not None:
        capex = abs(capex)  # sign convention varies by source; magnitude is what this formula wants
    depreciation = _get(cashflow0, "depreciationAndAmortization")

    change_in_working_capital = None
    if len(balance_stmts) >= 2:
        wc0 = _working_capital(balance0)
        wc1 = _working_capital(balance_stmts[1])
        if wc0 is not None and wc1 is not None:
            change_in_working_capital = wc0 - wc1

    interest_expense = _get(income0, "interestExpense")
    market_cap = profile.get("market_cap") if profile else None

    return {
        "nopat": nopat,
        "invested_capital": invested_capital,
        "capex": capex,
        "depreciation": depreciation,
        "change_in_working_capital": change_in_working_capital,
        "total_debt": total_debt,
        "market_cap": market_cap,
        "interest_expense": interest_expense,
    }


def _banded_sentiment(value: float | None, bands: dict) -> str | None:
    if value is None:
        return None
    if value >= bands["good_pct"]:
        return "good"
    if value >= bands["neutral_pct"]:
        return "neutral"
    return "bad"


def _value_creation_sentiment(value_creation_pct: float | None) -> str | None:
    """ROIC - WACC: the framework's own central insight, so unlike
    reinvestment rate/WACC this always has a clear direction - positive
    means the tracked universe is creating value above its cost of
    capital, negative means it's destroying value. A +/-0.5pp dead zone
    around zero reads as "neutral" rather than a hair-trigger flip."""
    if value_creation_pct is None:
        return None
    if value_creation_pct > 0.5:
        return "good"
    if value_creation_pct < -0.5:
        return "bad"
    return "neutral"


def _sum_field(company_inputs: list[dict], key: str) -> tuple[float | None, int]:
    values = [c[key] for c in company_inputs if c and c.get(key) is not None]
    if not values:
        return None, 0
    return sum(values), len(values)


def aggregate_capital_efficiency(
    company_inputs: list[dict], risk_free_rate_pct: float | None, cfg: dict
) -> dict:
    """company_inputs: company_capital_efficiency_inputs results (None
    entries are fine, filtered out here). risk_free_rate_pct: latest value
    of cfg["risk_free_rate_series"] (e.g. DGS10), from the same macro fetch
    the rest of the macro page already uses. cfg: capital_efficiency.yaml.
    """
    total_nopat, nopat_n = _sum_field(company_inputs, "nopat")
    total_invested_capital, invested_capital_n = _sum_field(company_inputs, "invested_capital")
    total_capex, capex_n = _sum_field(company_inputs, "capex")
    total_depreciation, depreciation_n = _sum_field(company_inputs, "depreciation")
    total_change_in_wc, change_in_wc_n = _sum_field(company_inputs, "change_in_working_capital")
    total_debt, debt_n = _sum_field(company_inputs, "total_debt")
    total_market_cap, market_cap_n = _sum_field(company_inputs, "market_cap")
    total_interest_expense, interest_expense_n = _sum_field(company_inputs, "interest_expense")

    roic_pct = (
        total_nopat / total_invested_capital * 100
        if total_nopat is not None and total_invested_capital
        else None
    )

    reinvestment_rate_pct = None
    if (
        total_nopat
        and total_capex is not None
        and total_depreciation is not None
        and total_change_in_wc is not None
    ):
        reinvestment_rate_pct = (total_capex - total_depreciation + total_change_in_wc) / total_nopat * 100

    expected_growth_pct = (
        roic_pct * reinvestment_rate_pct / 100 if roic_pct is not None and reinvestment_rate_pct is not None else None
    )

    cost_of_equity_pct = (
        risk_free_rate_pct + cfg["equity_risk_premium_pct"] if risk_free_rate_pct is not None else None
    )
    cost_of_debt_pct = None
    if total_interest_expense is not None and total_debt:
        pretax_cost_of_debt_pct = total_interest_expense / total_debt * 100
        cost_of_debt_pct = pretax_cost_of_debt_pct * (1 - cfg["assumed_tax_rate_pct"] / 100)

    wacc_pct = None
    if cost_of_equity_pct is not None and total_market_cap and total_debt is not None:
        equity_weight = total_market_cap / (total_market_cap + total_debt)
        debt_weight = 1 - equity_weight
        wacc_pct = equity_weight * cost_of_equity_pct + debt_weight * (cost_of_debt_pct or 0)

    value_creation_pct = roic_pct - wacc_pct if roic_pct is not None and wacc_pct is not None else None

    return {
        "companies_covered": len(company_inputs),
        "roic_pct": roic_pct,
        "reinvestment_rate_pct": reinvestment_rate_pct,
        "expected_growth_pct": expected_growth_pct,
        "wacc_pct": wacc_pct,
        "value_creation_pct": value_creation_pct,
        "cost_of_equity_pct": cost_of_equity_pct,
        "cost_of_debt_pct": cost_of_debt_pct,
        # Same red/yellow/green vocabulary as the company page's
        # metricSentiment (site/js/company.js): "good"/"neutral"/"bad", or
        # None when the underlying value itself is None. Computed here
        # (not in the frontend) so every threshold stays in one
        # inspectable, config-driven place - the same reasoning
        # macro_mood.py already applies to the per-series mood emoji.
        # Reinvestment rate and WACC have no inherent good/bad direction on
        # their own (see module docstring) so they're always "neutral" when
        # a value exists, never colored as good or bad.
        "sentiment": {
            "roic": _banded_sentiment(roic_pct, cfg["roic_bands"]),
            "reinvestment_rate": "neutral" if reinvestment_rate_pct is not None else None,
            "expected_growth": _banded_sentiment(expected_growth_pct, cfg["expected_growth_bands"]),
            "wacc": "neutral" if wacc_pct is not None else None,
            "value_creation": _value_creation_sentiment(value_creation_pct),
        },
        "totals": {
            "nopat": total_nopat,
            "invested_capital": total_invested_capital,
            "capex": total_capex,
            "depreciation": total_depreciation,
            "change_in_working_capital": total_change_in_wc,
            "total_debt": total_debt,
            "market_cap": total_market_cap,
            "interest_expense": total_interest_expense,
        },
        "coverage": {
            "nopat": nopat_n,
            "invested_capital": invested_capital_n,
            "capex": capex_n,
            "depreciation": depreciation_n,
            "change_in_working_capital": change_in_wc_n,
            "total_debt": debt_n,
            "market_cap": market_cap_n,
            "interest_expense": interest_expense_n,
        },
    }
