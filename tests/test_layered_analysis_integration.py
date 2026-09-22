"""End-to-end integration test for the layered-analysis wiring in
pipeline/main.py (qualitative -> aggregation). Mocks every network/API
boundary (FMP, SEC EDGAR, Stooq, filing text, and the Anthropic moat-read
call) and exercises the real fetch_and_score_company -> finalize_company
call chain used by the actual pipeline, to catch wiring bugs (wrong argument
order, missing dict keys, tuple-unpacking mismatches) that per-module unit
tests can't see."""

from unittest.mock import patch

from pipeline.fetch.filing_text import FilingTextError
from pipeline.main import fetch_and_score_company, finalize_company
from pipeline.narrative.qualitative_schema import QualitativeAssessment


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
    # Newest-first, as the real SEC API returns it - 8-K, then 10-Q, then
    # 10-K, so latest_filings_by_form's "first match per form wins" logic
    # picks each one's actual most recent filing.
    return {
        "cik": "320193",
        "sicDescription": "Widget Manufacturing",
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "10-K"],
                "accessionNumber": ["0000320193-26-000003", "0000320193-26-000002", "0000320193-26-000001"],
                "primaryDocument": ["aapl-8k.htm", "aapl-20260331.htm", "aapl-20251231.htm"],
                "filingDate": ["2026-06-01", "2026-05-01", "2026-02-01"],
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


def _mocked_qualitative() -> QualitativeAssessment:
    return QualitativeAssessment(
        moat_present=True,
        moat_type="switching_costs",
        moat_explanation="Excerpts describe high customer switching costs.",
        red_flags=["Customer concentration mentioned in risk factors."],
        extraction_confidence="section_match",
        filing_summary_10k="Revenue grew and the company returned cash to shareholders.",
        filing_summary_10q="Quarterly revenue grew 8% year over year.",
        filing_summary_8k="The company announced a new CEO.",
    )


@patch("pipeline.main.filing_text.fetch_plain_text")
@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.generate_qualitative_assessment")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_full_layered_pipeline_wiring(
    mock_fmp, mock_sec, mock_stooq, mock_qualitative, mock_filing_sections, mock_plain_text, tmp_path
):
    mock_fmp.return_value = _empty_fmp_data()
    mock_sec.return_value = _sec_data()
    mock_stooq.return_value = _stooq_prices()
    mock_qualitative.return_value = _mocked_qualitative()
    mock_filing_sections.return_value = {"business": "Business text.", "risk_factors": None, "mdna": "MD&A text.", "method": "section_match"}
    mock_plain_text.side_effect = ["10-Q plain text.", "8-K plain text."]

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    company_cfg = {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"}

    state = fetch_and_score_company(company_cfg, regime_info)
    assert state["latest_10k"]["form"] == "10-K"
    assert set(state["latest_filings"]) == {"10-K", "10-Q", "8-K"}

    company_doc, summary, qualitative_failed = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)

    assert qualitative_failed is False
    assert company_doc["metrics"]["total_assets"] == 2_000_000_000
    assert company_doc["metrics"]["total_liabilities"] == 1_200_000_000
    assert company_doc["metrics"]["shareholders_equity"] == 800_000_000
    assert company_doc["qualitative"]["moat_present"] is True
    assert company_doc["qualitative"]["filing_summary_10q"] == "Quarterly revenue grew 8% year over year."
    assert company_doc["qualitative"]["filing_summary_8k"] == "The company announced a new CEO."
    assert 0.0 <= company_doc["layered_analysis"]["conviction_score"] <= 100.0
    assert company_doc["layered_analysis"]["conviction_verdict"] in ("Strong", "Favorable", "Neutral", "Cautious", "Weak")
    assert summary["conviction_score"] == company_doc["layered_analysis"]["conviction_score"]

    # The 10-Q/8-K text was fetched and passed through to the Anthropic call
    # as filing_texts, alongside the 10-K sections.
    mock_qualitative.assert_called_once_with("AAPL", mock_filing_sections.return_value, {"10-Q": "10-Q plain text.", "8-K": "8-K plain text."})

    # The cache file should now exist and be reused on a second call without
    # calling the Anthropic-backed qualitative function, or re-fetching any
    # filing text, again.
    mock_qualitative.reset_mock()
    mock_filing_sections.reset_mock()
    mock_plain_text.reset_mock()
    company_doc2, *_ = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)
    assert company_doc2["qualitative"] == company_doc["qualitative"]
    mock_qualitative.assert_not_called()
    mock_filing_sections.assert_not_called()
    mock_plain_text.assert_not_called()


@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_qualitative_layer_skipped_when_no_10k_found(mock_fmp, mock_sec, mock_stooq, mock_filing_sections, tmp_path):
    """A company with no 10-K in its recent filings shouldn't trigger the
    filing fetch or any qualitative Claude call at all - the remaining
    gate on this layer (cost control against the whole universe now happens
    one level up, in run_full's two-phase screen: only this week's
    finalists reach finalize_company with skip_ai=False at all)."""
    mock_fmp.return_value = _empty_fmp_data()
    no_10k_sec = _sec_data()
    no_10k_sec["submissions"]["filings"]["recent"] = {
        "form": ["10-Q"],
        "accessionNumber": ["0000320193-26-000002"],
        "primaryDocument": ["aapl-20260331.htm"],
        "filingDate": ["2026-05-01"],
    }
    mock_sec.return_value = no_10k_sec
    mock_stooq.return_value = _stooq_prices()

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    state = fetch_and_score_company({"ticker": "ZZZZ", "name": "No 10-K Co", "sector": "Technology"}, regime_info)
    assert state["latest_10k"] is None

    company_doc, *_ = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)

    assert company_doc["qualitative"] is None
    mock_filing_sections.assert_not_called()


@patch("pipeline.main.filing_text.fetch_plain_text")
@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.generate_qualitative_assessment")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_qualitative_layer_handles_missing_10q_and_8k(
    mock_fmp, mock_sec, mock_stooq, mock_qualitative, mock_filing_sections, mock_plain_text, tmp_path
):
    """A company with only a 10-K in its recent filings (no 10-Q/8-K found -
    e.g. a fresh IPO) must still run the moat read, just with filing_texts
    empty - never a fetch attempt for a filing type that doesn't exist, and
    never a guessed summary for it either (see qualitative_schema.py)."""
    mock_fmp.return_value = _empty_fmp_data()
    only_10k_sec = _sec_data()
    only_10k_sec["submissions"]["filings"]["recent"] = {
        "form": ["10-K"],
        "accessionNumber": ["0000320193-26-000001"],
        "primaryDocument": ["aapl-20251231.htm"],
        "filingDate": ["2026-02-01"],
    }
    mock_sec.return_value = only_10k_sec
    mock_stooq.return_value = _stooq_prices()
    mock_qualitative.return_value = _mocked_qualitative()
    mock_filing_sections.return_value = {"business": "b", "risk_factors": None, "mdna": "m", "method": "section_match"}

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    state = fetch_and_score_company({"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"}, regime_info)
    assert set(state["latest_filings"]) == {"10-K"}

    company_doc, _summary, qualitative_failed = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)

    assert qualitative_failed is False
    mock_plain_text.assert_not_called()
    mock_qualitative.assert_called_once_with("AAPL", mock_filing_sections.return_value, {})


@patch("pipeline.main.filing_text.fetch_plain_text")
@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.generate_qualitative_assessment")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_qualitative_layer_continues_when_one_filing_text_fetch_fails(
    mock_fmp, mock_sec, mock_stooq, mock_qualitative, mock_filing_sections, mock_plain_text, tmp_path
):
    """A 10-Q or 8-K text fetch failing (e.g. SEC EDGAR hiccup on that one
    document) is a bonus that's missing, not a reason to sink the whole moat
    read - only the 10-K's own section fetch is load-bearing for the call."""
    mock_fmp.return_value = _empty_fmp_data()
    mock_sec.return_value = _sec_data()
    mock_stooq.return_value = _stooq_prices()
    mock_qualitative.return_value = _mocked_qualitative()
    mock_filing_sections.return_value = {"business": "b", "risk_factors": None, "mdna": "m", "method": "section_match"}
    # 10-Q text fetch fails, 8-K text fetch succeeds.
    mock_plain_text.side_effect = [FilingTextError("timeout"), "8-K plain text."]

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    state = fetch_and_score_company({"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"}, regime_info)

    company_doc, _summary, qualitative_failed = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)

    assert qualitative_failed is False
    mock_qualitative.assert_called_once_with("AAPL", mock_filing_sections.return_value, {"8-K": "8-K plain text."})


@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_qualitative_layer_failure_degrades_gracefully(mock_fmp, mock_sec, mock_stooq, mock_filing_sections, tmp_path):
    mock_fmp.return_value = _empty_fmp_data()
    mock_sec.return_value = _sec_data()
    mock_stooq.return_value = _stooq_prices()
    mock_filing_sections.side_effect = FilingTextError("SEC EDGAR unreachable")

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    state = fetch_and_score_company({"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"}, regime_info)

    company_doc, summary, qualitative_failed = finalize_company(state, regime_info, skip_ai=False, out_dir=tmp_path)

    assert company_doc["qualitative"] is None
    assert qualitative_failed is True


@patch("pipeline.main.filing_text.fetch_filing_sections")
@patch("pipeline.main.stooq.fetch_daily_prices")
@patch("pipeline.main.sec_edgar.fetch_company")
@patch("pipeline.main.fmp.fetch_company")
def test_skip_ai_leaves_qualitative_unattempted(mock_fmp, mock_sec, mock_stooq, mock_filing_sections, tmp_path):
    """skip_ai=True (Phase 1's cheap screen over the whole universe) must
    never touch the filing fetch or the Anthropic call at all, regardless of
    whether a 10-K exists."""
    mock_fmp.return_value = _empty_fmp_data()
    mock_sec.return_value = _sec_data()
    mock_stooq.return_value = _stooq_prices()

    regime_info = {"regime": "Neutral/Expansion", "signals": {}}
    state = fetch_and_score_company({"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"}, regime_info)

    company_doc, summary, qualitative_failed = finalize_company(state, regime_info, skip_ai=True, out_dir=tmp_path)

    assert company_doc["qualitative"] is None
    assert qualitative_failed is False
    mock_filing_sections.assert_not_called()
