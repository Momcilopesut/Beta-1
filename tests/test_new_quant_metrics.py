"""Direct, fully-controlled tests for the metrics added this session:
Greenblatt's earnings yield (EBIT/EV), Fisher's R&D/revenue, Lynch's PEG
ratio, and debt/EBITDA - using a fully-populated synthetic FMP payload
(not the fallback-tolerant fixtures in test_scoring.py) so every input is
known and the expected output is exact, not just "not None"."""

import pytest

from pipeline.scoring.fundamentals import build_metrics


def _fmp_data() -> dict:
    # market_cap = 50B, total_debt = 10B, cash = 5B -> enterprise_value = 55B
    # operating_income (EBIT proxy) = 5.5B -> earnings_yield_pct = 5.5/55*100 = 10.0%
    # revenue = 20B, R&D = 2B -> r_and_d_to_revenue_pct = 10.0%
    # d_and_a = 1B -> ebitda = 5.5B + 1B = 6.5B -> debt_to_ebitda = 10/6.5
    # epsdiluted 1.331 (latest) vs 1.0 (3 periods back) -> exact 10% 3yr CAGR
    # pe_ttm fixed at 20.0 via ratios_ttm -> peg_ratio = 20.0 / 10.0 = 2.0
    income_row = {
        "revenue": 20_000_000_000,
        "operatingIncome": 5_500_000_000,
        "researchAndDevelopmentExpenses": 2_000_000_000,
        "grossProfit": 8_000_000_000,
        "netIncome": 4_000_000_000,
    }
    income_stmts = [
        {**income_row, "epsdiluted": 1.331},
        {**income_row, "epsdiluted": 1.2},
        {**income_row, "epsdiluted": 1.1},
        {**income_row, "epsdiluted": 1.0},
    ]
    return {
        "profile": [{"companyName": "Test Co", "sector": "Technology", "industry": "Software"}],
        "quote": [{"sharesOutstanding": 1_000_000_000, "marketCap": 50_000_000_000, "price": 50.0, "eps": 1.331}],
        "historical_prices": {"historical": []},
        "ratios_ttm": [{"priceToEarningsRatioTTM": 20.0}],
        "key_metrics_ttm": [],
        "income_statement": income_stmts,
        "balance_sheet": [{"totalDebt": 10_000_000_000, "cashAndCashEquivalents": 5_000_000_000}],
        "cash_flow": [{"depreciationAndAmortization": 1_000_000_000}],
        "dcf": [],
    }


def test_earnings_yield_and_rd_and_peg_and_debt_to_ebitda():
    metrics = build_metrics("TEST", _fmp_data(), {"cik": None, "submissions": None, "company_facts": None})["metrics"]

    assert metrics["earnings_yield_pct"] == pytest.approx(10.0)
    assert metrics["r_and_d_to_revenue_pct"] == pytest.approx(10.0)
    assert metrics["eps_growth_cagr_3yr_pct"] == pytest.approx(10.0)
    assert metrics["peg_ratio"] == pytest.approx(2.0)
    assert metrics["debt_to_ebitda"] == pytest.approx(10_000_000_000 / 6_500_000_000)


def test_earnings_yield_none_without_enterprise_value_inputs():
    fmp_data = _fmp_data()
    fmp_data["balance_sheet"] = []  # no total_debt/cash -> no enterprise_value
    metrics = build_metrics("TEST", fmp_data, {"cik": None, "submissions": None, "company_facts": None})["metrics"]
    assert metrics["earnings_yield_pct"] is None


def test_peg_none_for_negative_growth():
    fmp_data = _fmp_data()
    fmp_data["income_statement"][3]["epsdiluted"] = 2.0  # makes 3yr growth negative
    metrics = build_metrics("TEST", fmp_data, {"cik": None, "submissions": None, "company_facts": None})["metrics"]
    assert metrics["eps_growth_cagr_3yr_pct"] < 0
    assert metrics["peg_ratio"] is None


def test_r_and_d_to_revenue_none_when_not_reported():
    fmp_data = _fmp_data()
    for row in fmp_data["income_statement"]:
        row.pop("researchAndDevelopmentExpenses")
    metrics = build_metrics("TEST", fmp_data, {"cik": None, "submissions": None, "company_facts": None})["metrics"]
    assert metrics["r_and_d_to_revenue_pct"] is None
