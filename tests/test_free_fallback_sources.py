"""Tests for the free backup data chain: SEC XBRL statement synthesis and
Stooq price history, and the end-to-end scoring result when FMP is
completely unavailable (the scenario this chain exists for)."""

from unittest.mock import patch

from pipeline.fetch import sec_edgar, stooq
from pipeline.scoring.fundamentals import build_metrics


def _fact(end: str, filed: str, val: float) -> dict:
    return {"form": "10-K", "fp": "FY", "end": end, "filed": filed, "val": val}


def _company_facts() -> dict:
    """Two fiscal years of a synthetic, internally-consistent company:
    FY2025 revenue $1B, 40% gross margin, $150M net income, 50M diluted
    shares (EPS $3.00), $800M equity ($16.00 book value/share)."""

    def concept(tag: str, v2025: float, v2024: float, unit: str = "USD") -> tuple[str, dict]:
        return tag, {
            "units": {
                unit: [
                    _fact("2024-12-31", "2025-02-01", v2024),
                    _fact("2025-12-31", "2026-02-01", v2025),
                ]
            }
        }

    us_gaap = dict(
        [
            concept("Revenues", 1_000_000_000, 900_000_000),
            concept("GrossProfit", 400_000_000, 324_000_000),
            concept("NetIncomeLoss", 150_000_000, 120_000_000),
            concept("EarningsPerShareDiluted", 3.00, 2.40, unit="USD/shares"),
            concept("OperatingIncomeLoss", 200_000_000, 160_000_000),
            concept("IncomeTaxExpenseBenefit", 40_000_000, 32_000_000),
            concept(
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                190_000_000,
                152_000_000,
            ),
            concept("WeightedAverageNumberOfDilutedSharesOutstanding", 50_000_000, 50_000_000, unit="shares"),
            concept("InterestExpense", 10_000_000, 9_000_000),
            concept("Assets", 2_000_000_000, 1_800_000_000),
            concept("AssetsCurrent", 800_000_000, 700_000_000),
            concept("LiabilitiesCurrent", 300_000_000, 280_000_000),
            concept("Liabilities", 1_200_000_000, 1_100_000_000),
            concept("StockholdersEquity", 800_000_000, 700_000_000),
            concept("CashAndCashEquivalentsAtCarryingValue", 200_000_000, 150_000_000),
            concept("LongTermDebtNoncurrent", 400_000_000, 420_000_000),
            concept("DebtCurrent", 50_000_000, 60_000_000),
            concept("NetCashProvidedByUsedInOperatingActivities", 220_000_000, 190_000_000),
            concept("DepreciationDepletionAndAmortization", 60_000_000, 55_000_000),
            concept("PaymentsToAcquirePropertyPlantAndEquipment", 70_000_000, 65_000_000),
            concept("PaymentsOfDividendsCommonStock", 30_000_000, 28_000_000),
        ]
    )
    dei = {
        "EntityCommonStockSharesOutstanding": {
            "units": {"shares": [{"end": "2026-02-01", "val": 50_000_000}]}
        }
    }
    return {"facts": {"us-gaap": us_gaap, "dei": dei}}


def test_xbrl_fundamentals_synthesizes_fmp_shaped_rows():
    result = sec_edgar.xbrl_fundamentals(_company_facts())

    assert len(result["income_stmts"]) == 2
    latest = result["income_stmts"][0]
    assert latest["date"] == "2025-12-31"
    assert latest["revenue"] == 1_000_000_000
    assert latest["netIncome"] == 150_000_000
    assert latest["epsdiluted"] == 3.00

    balance_latest = result["balance_stmts"][0]
    assert balance_latest["totalDebt"] == 450_000_000  # 400M long-term + 50M current, summed
    assert balance_latest["totalStockholdersEquity"] == 800_000_000

    cashflow_latest = result["cashflow_stmts"][0]
    assert cashflow_latest["operatingCashFlow"] == 220_000_000


def test_xbrl_fundamentals_handles_missing_company_facts():
    result = sec_edgar.xbrl_fundamentals(None)
    assert result == {"income_stmts": [], "balance_stmts": [], "cashflow_stmts": []}


def test_latest_shares_outstanding():
    assert sec_edgar.latest_shares_outstanding(_company_facts()) == 50_000_000
    assert sec_edgar.latest_shares_outstanding(None) is None


def test_stooq_parses_csv_into_fmp_compatible_rows():
    csv_text = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-08-01,58.0,59.0,57.5,58.5,1200000\n"
        "2026-08-02,58.5,60.0,58.0,59.8,1500000\n"
    )
    with patch("pipeline.fetch.stooq.get_text", return_value=csv_text):
        rows = stooq.fetch_daily_prices("TEST")

    assert rows == [
        {"date": "2026-08-01", "close": 58.5, "volume": 1200000.0},
        {"date": "2026-08-02", "close": 59.8, "volume": 1500000.0},
    ]


def test_stooq_no_data_response_returns_empty_list():
    with patch("pipeline.fetch.stooq.get_text", return_value="No data"):
        assert stooq.fetch_daily_prices("BADTICKER") == []


def test_build_metrics_falls_back_fully_to_sec_and_stooq_when_fmp_is_empty():
    """The scenario this whole chain exists for: every FMP call failed
    (empty dicts, as pipeline.fetch.fmp.fetch_company returns on total
    failure), but SEC XBRL + Stooq data is available."""
    fmp_data = {
        "profile": None,
        "quote": None,
        "ratios_ttm": None,
        "key_metrics_ttm": None,
        "dcf": None,
        "income_statement": None,
        "balance_sheet": None,
        "cash_flow": None,
        "historical_prices": None,
        "_errors": {"profile": "402 Payment Required", "quote": "402 Payment Required"},
    }
    company_facts = _company_facts()
    sec_data = {
        "cik": "0000000001",
        "company_facts": company_facts,
        "xbrl_fundamentals": sec_edgar.xbrl_fundamentals(company_facts),
        "shares_outstanding": sec_edgar.latest_shares_outstanding(company_facts),
        "sic_description": "Test Industry",
        "_errors": {},
    }
    # 70 trading days of synthetic prices ending at a close of 60.00, so
    # return_3m_pct (63 trading days back) is computable.
    stooq_prices = [
        {"date": f"2026-{(1 + i // 28):02d}-{(1 + i % 28):02d}", "close": round(50 + i * (10 / 69), 2), "volume": 1_000_000 + i * 1000}
        for i in range(70)
    ]
    stooq_prices[-1]["close"] = 60.0  # pin the latest close for round-number assertions

    built = build_metrics("TEST", fmp_data, sec_data, stooq_prices)
    metrics = built["metrics"]

    # Statement-derived ratios, computed entirely from the XBRL fallback.
    assert metrics["gross_margin_pct"] == 40.0
    assert metrics["roe_pct"] == 150_000_000 / 800_000_000 * 100
    assert metrics["debt_to_equity"] == 450_000_000 / 800_000_000
    assert metrics["current_ratio"] == 800_000_000 / 300_000_000
    assert metrics["interest_coverage"] == 200_000_000 / 10_000_000
    assert metrics["fcf_margin_pct"] == (220_000_000 - 70_000_000) / 1_000_000_000 * 100

    # Price-derived metrics, from the Stooq fallback.
    assert built["display"]["price"]["close"] == 60.0
    assert metrics["return_3m_pct"] is not None

    # Metrics that need BOTH a fallback price and fallback statement data.
    assert metrics["pe_ttm"] == 60.0 / 3.00
    assert built["profile"]["market_cap"] == 60.0 * 50_000_000
    assert metrics["graham_upside_pct"] is not None
    assert metrics["roic_pct"] is not None
    assert metrics["ev_ebitda"] is not None

    # profile fields: sector left None (main.py falls back to the
    # watchlist's own sector), industry uses the SIC description.
    assert built["profile"]["sector"] is None
    assert built["profile"]["industry"] == "Test Industry"
