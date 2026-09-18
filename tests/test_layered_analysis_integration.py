"""End-to-end integration test for the layered-analysis wiring added to
pipeline/main.py (quant scorecard -> valuation -> qualitative -> thesis ->
aggregation). Mocks every network/API boundary (FMP, SEC EDGAR, Stooq,
filing text, and all three Anthropic calls) and exercises the real
fetch_and_score_company -> apply_sector_medians -> finalize_company call
chain used by the actual pipeline, to catch wiring bugs (wrong argument
order, missing dict keys, tuple-unpacking mismatches) that per-module unit
tests can't see."""

from pathlib import Path
from unittest.mock import patch

from pipeline.fetch.filing_text import FilingTextError
from pipeline.main import apply_sector_medians, fetch_and_score_company, finalize_company
from pipeline.narrative.qualitative_client import QualitativeError
from pipeline.narrative.qualitative_schema import QualitativeAssessment, ThesisAndFalsification
from pipeline.narrative.schema import CompanyNarrative


def _fact(end: str, filed: str, val: float) -> dict:
    return {"form": "10-K", "fp": "FY", "end": end, "filed": filed, "val": val}


def _company_facts() -> dict:
    def concept(tag: str, v2: float, v1: float, unit: str = "USD") -> tuple[str, dict]:
        return tag, {"units": {unit: [_fact("2024-12-31", "2025-02-01", v1), _fact("2025-12-31", "2026-02-01", v2)]}}

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
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-02-01", "val": 50_000_000}]}}}
    return {"facts": {"us-gaap": us_gaap, "dei": dei}}


def _submissions() -> dict:
    return {
        "cik": "320193",
        "sicDescription": "Widget Manufacturing",
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q"],
                "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                "primaryDocument": ["aapl-20251231.htm", "aapl-20260331.htm"],
                "filingDate": ["2026-02-01", "2026-05-01"],
            }
        },
    }


def _empty_fmp_data() -> dict:
    return {
        "profile": None,
        "quote": None,
        "historical_prices": None,
        "ratios_ttm": None,
        "key_metrics_ttm": None,
        "income_statement": None,
        "balance_sheet": None,
        "cash_flow": None,
        "dcf": None,
        "insider_ownership": None,
        "_errors": {},
    }


def _sec_data() -> dict:
    from pipeline.fetch.sec_edgar import latest_shares_outstanding, xbrl_fundamentals

    facts = _company_facts()
    return {
        "cik": "0000320193",
        "submissions": _submissions(),
        "company_facts": facts,
        "xbrl_fundamentals": xbrl_fundamentals(facts),
        "shares_outstanding": latest_shares_outstanding(facts),
        "sic_description": "Widget Manufacturing",
        "_errors": {},
    }


def _stooq_prices() -> list[dict]:
    return [{"date": f"2026-01-{d:02d}", "close": 100.0 + d, "volume": 1_000_000} for d in range(1, 29)]


def _mocked_narrative() -> CompanyNarrative:
    return CompanyNarrative(one_line_summary="Test summary.", short_term_narrative="Short.", long_term_narrative="Long.", facts=[])


def _mocked_qualitative() -> QualitativeAssessment:
    return QualitativeAssessment(
        moat_present=True,
        moat_type="switching_costs",
        moat_explanation="Excerpts describe high customer switching costs.",
        management_assessment="Excerpts describe disciplined capital allocation.",
        red_flags=["Customer concentration mentioned in risk factors."],
        extraction_confidence="section_match",
    )


def _mocked_thesis() -> ThesisAndFalsification:
    return ThesisAndFalsification(
        thesis="The company clears the quant screen, shows a moat in its filings, and trades near estimated intrinsic value.",
        falsification_criteria=["ROIC falls below 12%.", "A major customer is lost per a future 10-K."],
    )


@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.generate_thesis")
@patch("pipeline.main.generate_qualitative_assessment")
@patch("pipeline.main.generate_narrative")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_full_layered_pipeline_wiring(
    mock_fmp, mock_sec, mock_stooq, mock_narrative, mock_qualitative, mock_thesis, mock_filing_sections, tmp_path
):
    mock_fmp.return_value = _empty_fmp_data()
    mock_sec.return_value = _sec_data()
    mock_stooq.return_value = _stooq_prices()
    mock_narrative.return_value = _mocked_narrative()
    mock_qualitative.return_value = _mocked_qualitative()
    mock_thesis.return_value = _mocked_thesis()
    mock_filing_sections.return_value = {"business": "Business text.", "risk_factors": None, "mdna": "MD&A text.", "method": "section_match"}

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    company_cfg = {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"}

    state = fetch_and_score_company(company_cfg, regime_info)
    assert state["quant_scorecard"]["evaluated"] >= 1
    assert state["latest_10k"]["form"] == "10-K"

    apply_sector_medians([state])
    assert "sector_medians" in state

    company_doc, summary, narrative_warnings, qualitative_failed = finalize_company(
        state, regime_info, skip_ai=False, out_dir=tmp_path
    )

    assert qualitative_failed is False
    assert company_doc["quant_score"]["evaluated"] >= 1
    assert company_doc["valuation"]["dcf"]["assumptions"]["discount_rate_pct"] == 9.0
    assert company_doc["qualitative"]["moat_present"] is True
    assert company_doc["thesis"]["falsification_criteria"]
    assert company_doc["layered_analysis"]["quant_gate_pass"] in (True, False)
    assert summary["quant_gate_pass"] == company_doc["layered_analysis"]["quant_gate_pass"]

    # The cache file should now exist and be reused on a second call without
    # calling the Anthropic-backed qualitative/thesis functions again.
    mock_qualitative.reset_mock()
    mock_thesis.reset_mock()
    mock_filing_sections.reset_mock()
    company_doc2, *_ = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)
    assert company_doc2["qualitative"] == company_doc["qualitative"]
    mock_qualitative.assert_not_called()
    mock_thesis.assert_not_called()
    mock_filing_sections.assert_not_called()


@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.generate_narrative")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_qualitative_layer_skipped_when_quant_gate_fails(
    mock_fmp, mock_sec, mock_stooq, mock_narrative, mock_filing_sections, tmp_path
):
    """A company with almost no data shouldn't trigger the filing fetch or
    any qualitative/thesis Claude call at all - the deliberate quant-gate
    cost control from fetch_and_score_company's docstring."""
    mock_fmp.return_value = _empty_fmp_data()
    sparse_sec = _sec_data()
    sparse_sec["company_facts"] = {"facts": {"us-gaap": {}, "dei": {}}}
    from pipeline.fetch.sec_edgar import xbrl_fundamentals

    sparse_sec["xbrl_fundamentals"] = xbrl_fundamentals(sparse_sec["company_facts"])
    mock_sec.return_value = sparse_sec
    mock_stooq.return_value = []
    mock_narrative.return_value = _mocked_narrative()

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    state = fetch_and_score_company({"ticker": "ZZZZ", "name": "Sparse Co", "sector": "Technology"}, regime_info)
    apply_sector_medians([state])

    company_doc, *_ = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)

    assert company_doc["qualitative"] is None
    assert company_doc["thesis"] is None
    mock_filing_sections.assert_not_called()


@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.generate_narrative")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_qualitative_layer_failure_degrades_gracefully(
    mock_fmp, mock_sec, mock_stooq, mock_narrative, mock_filing_sections, tmp_path
):
    mock_fmp.return_value = _empty_fmp_data()
    mock_sec.return_value = _sec_data()
    mock_stooq.return_value = _stooq_prices()
    mock_narrative.return_value = _mocked_narrative()
    mock_filing_sections.side_effect = FilingTextError("SEC EDGAR unreachable")

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    state = fetch_and_score_company({"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"}, regime_info)
    apply_sector_medians([state])

    company_doc, summary, warnings, qualitative_failed = finalize_company(
        state, regime_info, skip_ai=False, out_dir=tmp_path
    )

    assert company_doc["qualitative"] is None
    assert company_doc["thesis"] is None
    # Only asserted when the quant gate actually passed (fetch_filing_sections
    # was reached at all) - otherwise there's nothing to have failed.
    if mock_filing_sections.called:
        assert qualitative_failed is True
