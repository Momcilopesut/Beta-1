"""Direct, fully-controlled tests for the balance-sheet-first metrics this
pipeline centers on - the raw assets/liabilities/equity figures and
debt/EBITDA - using a fully-populated synthetic FMP payload (not the
fallback-tolerant fixtures in test_scoring.py) so every input is known and
the expected output is exact, not just "not None"."""

import pytest

from pipeline.scoring.fundamentals import build_metrics


def _fmp_data() -> dict:
    # total_debt = 10B, d_and_a = 1B, operating_income = 5.5B ->
    # ebitda = 6.5B -> debt_to_ebitda = 10/6.5
    # total_assets = 100B, total_liabilities = 40B -> shareholders_equity = 60B
    # shares_outstanding = 1B -> book_value_per_share = 60.0
    # current_assets = 30B, current_liabilities = 15B -> current_ratio = 2.0
    # incomeBeforeTax = 5B, incomeTaxExpense = 1B -> effective tax rate 20% ->
    # NOPAT = 5.5B * 0.8 = 4.4B; invested_capital = 10B + 60B - 5B(cash) = 65B
    # -> roic_pct = 4.4B / 65B * 100
    income_row = {
        "revenue": 20_000_000_000,
        "operatingIncome": 5_500_000_000,
        "grossProfit": 8_000_000_000,
        "netIncome": 4_000_000_000,
        "incomeBeforeTax": 5_000_000_000,
        "incomeTaxExpense": 1_000_000_000,
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
        "balance_sheet": [
            {
                "totalAssets": 100_000_000_000,
                "totalLiabilities": 40_000_000_000,
                "totalStockholdersEquity": 60_000_000_000,
                "totalDebt": 10_000_000_000,
                "cashAndCashEquivalents": 5_000_000_000,
                "totalCurrentAssets": 30_000_000_000,
                "totalCurrentLiabilities": 15_000_000_000,
            }
        ],
        "cash_flow": [{"depreciationAndAmortization": 1_000_000_000, "freeCashFlow": 3_000_000_000}],
    }


def test_balance_sheet_basics_are_exact():
    metrics = build_metrics("TEST", _fmp_data(), {"cik": None, "submissions": None, "company_facts": None})["metrics"]

    assert metrics["total_assets"] == 100_000_000_000
    assert metrics["total_liabilities"] == 40_000_000_000
    assert metrics["shareholders_equity"] == 60_000_000_000
    assert metrics["book_value_per_share"] == pytest.approx(60.0)
    assert metrics["current_ratio"] == pytest.approx(2.0)
    assert metrics["debt_to_ebitda"] == pytest.approx(10_000_000_000 / 6_500_000_000)
    assert metrics["eps_growth_cagr_3yr_pct"] == pytest.approx(10.0)
    assert metrics["fcf_margin_pct"] == pytest.approx(3_000_000_000 / 20_000_000_000 * 100)
    assert metrics["roe_pct"] == pytest.approx(4_000_000_000 / 60_000_000_000 * 100)
    assert metrics["roic_pct"] == pytest.approx(4_400_000_000 / 65_000_000_000 * 100)
    assert metrics["gross_margin_pct"] == pytest.approx(8_000_000_000 / 20_000_000_000 * 100)


def test_ncav_margin_reflects_current_assets_minus_all_liabilities():
    metrics = build_metrics("TEST", _fmp_data(), {"cik": None, "submissions": None, "company_facts": None})["metrics"]

    # (current_assets - total_liabilities) / shares = (30B - 40B) / 1B = -10/share.
    # Against a $50 price: (-10 - 50) / 50 * 100 = -120% - typically sharply
    # negative for a normal going-concern company; that's expected, not a bug.
    assert metrics["ncav_margin_pct"] == pytest.approx(-120.0)


def test_balance_sheet_basics_none_without_balance_sheet_data():
    fmp_data = _fmp_data()
    fmp_data["balance_sheet"] = []
    metrics = build_metrics("TEST", fmp_data, {"cik": None, "submissions": None, "company_facts": None})["metrics"]

    assert metrics["total_assets"] is None
    assert metrics["total_liabilities"] is None
    assert metrics["shareholders_equity"] is None
    assert metrics["ncav_margin_pct"] is None
    assert metrics["roe_pct"] is None
    assert metrics["roic_pct"] is None
    assert metrics["reinvestment_rate_pct"] is None


def test_reinvestment_rate_reflects_capex_depreciation_and_working_capital_change():
    # nopat = 4.4B (see _fmp_data()'s own comment). capex = 2B, depreciation
    # = 1B (already in the fixture). Working capital: period 0 (the shared
    # fixture's balance0) = 30B - 15B = 15B; period 1 (added here) = 25B -
    # 12B = 13B -> change_in_working_capital = 15B - 13B = 2B.
    # reinvestment_rate_pct = (2B - 1B + 2B) / 4.4B * 100
    fmp_data = _fmp_data()
    fmp_data["cash_flow"][0]["capitalExpenditure"] = -2_000_000_000  # outflow, sign per FMP's own convention
    fmp_data["balance_sheet"].append(
        {"totalCurrentAssets": 25_000_000_000, "totalCurrentLiabilities": 12_000_000_000}
    )
    metrics = build_metrics("TEST", fmp_data, {"cik": None, "submissions": None, "company_facts": None})["metrics"]

    assert metrics["reinvestment_rate_pct"] == pytest.approx(3_000_000_000 / 4_400_000_000 * 100)


def test_reinvestment_rate_none_without_a_second_balance_sheet_period():
    fmp_data = _fmp_data()
    fmp_data["cash_flow"][0]["capitalExpenditure"] = -2_000_000_000
    metrics = build_metrics("TEST", fmp_data, {"cik": None, "submissions": None, "company_facts": None})["metrics"]

    assert metrics["reinvestment_rate_pct"] is None
