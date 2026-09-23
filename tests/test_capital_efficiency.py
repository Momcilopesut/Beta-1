import pytest

from pipeline.scoring import capital_efficiency

CFG = {
    "equity_risk_premium_pct": 5.0,
    "assumed_tax_rate_pct": 21.0,
    "risk_free_rate_series": "DGS10",
    "roic_bands": {"good_pct": 15.0, "neutral_pct": 0.0},
    "expected_growth_bands": {"good_pct": 8.0, "neutral_pct": 0.0},
}


def _raw(operating_income=1000.0, pretax_income=900.0, tax_expense=189.0, interest_expense=50.0,
         total_debt=500.0, total_equity=1500.0, cash=200.0,
         capex=-300.0, depreciation=100.0,
         current_assets_0=800.0, current_liabilities_0=400.0,
         current_assets_1=700.0, current_liabilities_1=380.0):
    income0 = {
        "operatingIncome": operating_income,
        "incomeBeforeTax": pretax_income,
        "incomeTaxExpense": tax_expense,
        "interestExpense": interest_expense,
    }
    balance0 = {
        "totalDebt": total_debt,
        "totalStockholdersEquity": total_equity,
        "cashAndCashEquivalents": cash,
        "totalCurrentAssets": current_assets_0,
        "totalCurrentLiabilities": current_liabilities_0,
    }
    balance1 = {"totalCurrentAssets": current_assets_1, "totalCurrentLiabilities": current_liabilities_1}
    cashflow0 = {"capitalExpenditure": capex, "depreciationAndAmortization": depreciation}
    return {
        "income_stmts": [income0],
        "balance_stmts": [balance0, balance1],
        "cashflow_stmts": [cashflow0],
    }


def test_company_inputs_happy_path():
    raw = _raw()
    profile = {"market_cap": 5000.0}
    result = capital_efficiency.company_capital_efficiency_inputs(raw, profile)

    # effective tax rate = 189/900 = 0.21; NOPAT = 1000 * 0.79 = 790
    assert result["nopat"] == pytest.approx(790.0)
    # invested capital = 500 + 1500 - 200 = 1800
    assert result["invested_capital"] == pytest.approx(1800.0)
    assert result["capex"] == pytest.approx(300.0)  # sign normalized to a positive magnitude
    assert result["depreciation"] == pytest.approx(100.0)
    # working capital: (800-400) - (700-380) = 400 - 320 = 80
    assert result["change_in_working_capital"] == pytest.approx(80.0)
    assert result["total_debt"] == pytest.approx(500.0)
    assert result["market_cap"] == pytest.approx(5000.0)
    assert result["interest_expense"] == pytest.approx(50.0)


def test_company_inputs_missing_statements_returns_none():
    assert capital_efficiency.company_capital_efficiency_inputs(
        {"income_stmts": [], "balance_stmts": [{}], "cashflow_stmts": [{}]}, {}
    ) is None


def test_company_inputs_missing_tax_fields_leaves_nopat_none():
    raw = _raw(pretax_income=None, tax_expense=None)
    result = capital_efficiency.company_capital_efficiency_inputs(raw, {})
    assert result["nopat"] is None
    # other fields unaffected by the missing tax data
    assert result["invested_capital"] == pytest.approx(1800.0)


def test_company_inputs_single_balance_statement_leaves_wc_change_none():
    raw = _raw()
    raw["balance_stmts"] = [raw["balance_stmts"][0]]  # only one year on hand
    result = capital_efficiency.company_capital_efficiency_inputs(raw, {})
    assert result["change_in_working_capital"] is None


def test_company_inputs_no_profile_leaves_market_cap_none():
    raw = _raw()
    result = capital_efficiency.company_capital_efficiency_inputs(raw, None)
    assert result["market_cap"] is None


def _company_input(nopat, invested_capital, capex, depreciation, change_in_wc, total_debt, market_cap, interest_expense):
    return {
        "nopat": nopat,
        "invested_capital": invested_capital,
        "capex": capex,
        "depreciation": depreciation,
        "change_in_working_capital": change_in_wc,
        "total_debt": total_debt,
        "market_cap": market_cap,
        "interest_expense": interest_expense,
    }


def test_aggregate_capital_efficiency_full_math():
    company_inputs = [
        _company_input(100, 500, 40, 10, 10, 200, 2000, 20),
        _company_input(300, 1500, 60, 20, -20, 300, 2500, 30),
    ]
    result = capital_efficiency.aggregate_capital_efficiency(company_inputs, risk_free_rate_pct=4.0, cfg=CFG)

    assert result["companies_covered"] == 2
    assert result["roic_pct"] == pytest.approx(20.0)  # 400 NOPAT / 2000 invested capital
    assert result["reinvestment_rate_pct"] == pytest.approx(15.0)  # (100-30+(-10))/400 = 60/400
    assert result["expected_growth_pct"] == pytest.approx(3.0)  # 20% * 15%
    assert result["cost_of_equity_pct"] == pytest.approx(9.0)  # 4.0 + 5.0
    assert result["cost_of_debt_pct"] == pytest.approx(7.9)  # (50/500*100) * (1-0.21)
    assert result["wacc_pct"] == pytest.approx(8.89)  # 0.9*9.0 + 0.1*7.9
    assert result["value_creation_pct"] == pytest.approx(11.11)  # 20.0 - 8.89
    assert result["totals"]["nopat"] == pytest.approx(400.0)
    assert result["coverage"]["nopat"] == 2
    assert result["sentiment"]["roic"] == "good"  # 20% >= roic_bands.good_pct (15.0)
    assert result["sentiment"]["expected_growth"] == "neutral"  # 3% < expected_growth_bands.good_pct (8.0), >= 0
    assert result["sentiment"]["value_creation"] == "good"  # 11.11pp of value creation
    assert result["sentiment"]["reinvestment_rate"] == "neutral"  # no inherent direction
    assert result["sentiment"]["wacc"] == "neutral"  # no inherent direction


def test_aggregate_capital_efficiency_skips_none_entries_and_tracks_coverage():
    company_inputs = [
        _company_input(100, 500, 40, 10, 10, 200, 2000, 20),
        _company_input(None, None, None, None, None, None, None, None),  # a company missing everything
    ]
    result = capital_efficiency.aggregate_capital_efficiency(company_inputs, risk_free_rate_pct=4.0, cfg=CFG)
    assert result["companies_covered"] == 2
    assert result["coverage"]["nopat"] == 1
    assert result["totals"]["nopat"] == pytest.approx(100.0)
    assert result["roic_pct"] == pytest.approx(20.0)  # 100/500


def test_aggregate_capital_efficiency_missing_risk_free_rate_leaves_wacc_none():
    company_inputs = [_company_input(100, 500, 40, 10, 10, 200, 2000, 20)]
    result = capital_efficiency.aggregate_capital_efficiency(company_inputs, risk_free_rate_pct=None, cfg=CFG)
    assert result["cost_of_equity_pct"] is None
    assert result["wacc_pct"] is None
    assert result["value_creation_pct"] is None
    assert result["sentiment"]["wacc"] is None
    assert result["sentiment"]["value_creation"] is None


def test_aggregate_capital_efficiency_empty_input():
    result = capital_efficiency.aggregate_capital_efficiency([], risk_free_rate_pct=4.0, cfg=CFG)
    assert result["companies_covered"] == 0
    assert result["roic_pct"] is None
    assert result["reinvestment_rate_pct"] is None
    assert result["expected_growth_pct"] is None
    assert result["wacc_pct"] is None
    assert result["value_creation_pct"] is None
    assert all(v is None for v in result["sentiment"].values())


def test_aggregate_capital_efficiency_bad_sentiment_when_value_destroying():
    # Negative NOPAT (roic below the neutral floor) paired with a
    # meaningful WACC should read as value-destroying, not just "neutral".
    company_inputs = [_company_input(-50, 1000, 5, 5, 0, 800, 200, 100)]
    result = capital_efficiency.aggregate_capital_efficiency(company_inputs, risk_free_rate_pct=4.0, cfg=CFG)
    assert result["roic_pct"] == pytest.approx(-5.0)
    assert result["sentiment"]["roic"] == "bad"
    assert result["value_creation_pct"] < -0.5
    assert result["sentiment"]["value_creation"] == "bad"
