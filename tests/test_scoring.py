import json
from pathlib import Path

from pipeline.scoring import long_term, macro_regime, short_term
from pipeline.scoring.fundamentals import build_metrics
from pipeline.scoring.thresholds import normalize, score_components, verdict_for
from pipeline.utils.config import scoring_weights

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    with open(FIXTURES / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _series(values):
    return [{"date": f"2026-01-{i + 1:02d}", "value": v} for i, v in enumerate(values)]


def test_normalize_higher_better_clamps():
    assert normalize("return_1m_pct", -100) == 0
    assert normalize("return_1m_pct", 100) == 100
    assert normalize("return_1m_pct", 0) == 50  # midpoint of the -10..10 band


def test_normalize_lower_better_inverts():
    assert normalize("pe_ttm", 10) == 100  # low end is "best" for a lower_better metric
    assert normalize("pe_ttm", 40) == 0


def test_normalize_missing_value_is_none():
    assert normalize("pe_ttm", None) is None


def test_score_components_missing_metrics_fall_back_to_neutral():
    components = scoring_weights()["long_term"]["components"]
    result = score_components({}, components)
    assert result["base_score"] == 50.0
    assert all(sub["score"] == 50.0 for sub in result["subscores"])


def test_score_components_best_case_metrics_score_100():
    components = scoring_weights()["long_term"]["components"]
    metrics = {
        "pe_ttm": 10,
        "ev_ebitda": 8,
        "dcf_upside_pct": 25,
        "revenue_growth_yoy_pct": 25,
        "revenue_cagr_3yr_pct": 20,
        "eps_growth_yoy_pct": 30,
        "gross_margin_pct": 60,
        "roe_pct": 30,
        "margin_trend_score": 100,
        "debt_to_equity": 0,
        "current_ratio": 2.5,
        "interest_coverage": 20,
        "fcf_margin_pct": 30,
        "fcf_to_net_income": 1.5,
    }
    result = score_components(metrics, components)
    assert result["base_score"] == 100.0


def test_verdict_bands():
    assert verdict_for(80) == "Strong"
    assert verdict_for(65) == "Favorable"
    assert verdict_for(50) == "Neutral"
    assert verdict_for(30) == "Cautious"
    assert verdict_for(10) == "Weak"


def test_short_term_score_applies_macro_delta_and_clamps():
    result = short_term.score({}, macro_delta=10)
    assert result["base_score"] == 50.0
    assert result["final_score"] == 60.0
    assert short_term.score({}, macro_delta=100)["final_score"] == 100.0


def test_long_term_score_applies_macro_delta_and_clamps():
    result = long_term.score({}, macro_delta=-10)
    assert result["final_score"] == 40.0
    assert long_term.score({}, macro_delta=-100)["final_score"] == 0.0


def test_macro_regime_classifies_restrictive_late_cycle():
    macro_data = {
        "T10Y2Y": _series([-0.20, -0.25, -0.30, -0.28]),  # inverted
        "FEDFUNDS": _series([5.25, 5.25, 5.25, 5.25]),  # flat, not cutting
        "CPIAUCSL": _series([300.0] * 12 + [312.0]),  # +4% YoY, above 2% target
        "UNRATE": _series([4.0, 4.0, 4.0, 4.0]),
    }
    result = macro_regime.classify_regime(macro_data)
    assert result["regime"] == "Restrictive/Late-cycle"
    assert result["signals"]["yield_curve_inverted"] is True
    assert result["signals"]["cpi_above_target"] is True


def test_macro_regime_classifies_easing_recovery():
    macro_data = {
        "T10Y2Y": _series([0.30, 0.35, 0.40, 0.45]),  # not inverted
        "FEDFUNDS": _series([5.25, 5.00, 4.75, 4.50]),  # cutting
        "CPIAUCSL": _series([300.0] * 12 + [304.0]),
        "UNRATE": _series([4.0, 4.1, 4.2, 4.3]),
    }
    result = macro_regime.classify_regime(macro_data)
    assert result["regime"] == "Easing/Recovery"


def test_macro_regime_defaults_to_neutral_expansion_without_signals():
    result = macro_regime.classify_regime({})
    assert result["regime"] == "Neutral/Expansion"


def test_sector_adjustment_bounded_by_clamp():
    adj = macro_regime.sector_adjustment("Restrictive/Late-cycle", "Technology")
    assert -15 <= adj["short"] <= 15
    assert -10 <= adj["long"] <= 10
    assert adj["rate_sensitivity"] == "high"


def test_sector_adjustment_unknown_sector_uses_default():
    adj = macro_regime.sector_adjustment("Neutral/Expansion", "Some Unmapped Sector")
    assert adj["rate_sensitivity"] == "medium"
    assert adj["cyclicality"] == "medium"


def test_build_metrics_from_fixtures():
    fmp_data = {
        "profile": load_fixture("fmp_profile_aapl.json"),
        "quote": [],
        "historical_prices": {"historical": []},
        "ratios_ttm": [{"peRatioTTM": 31.2, "currentRatioTTM": 0.98, "debtEquityRatioTTM": 0.7}],
        "key_metrics_ttm": [{"roeTTM": 0.184, "evToEBITDATTM": 22.1}],
        "income_statement": load_fixture("fmp_income_statement_aapl.json"),
        "balance_sheet": [],
        "cash_flow": [{"freeCashFlow": 100000000000}],
        "dcf": [{"dcf": 205.1, "Stock Price": 231.4}],
    }
    sec_data = {
        "cik": "0000320193",
        "submissions": None,
        "company_facts": load_fixture("sec_companyfacts_aapl_excerpt.json"),
    }

    built = build_metrics("AAPL", fmp_data, sec_data)
    metrics = built["metrics"]

    assert metrics["pe_ttm"] == 31.2
    assert metrics["debt_to_equity"] == 0.7
    assert round(metrics["roe_pct"], 1) == 18.4
    assert metrics["dcf_upside_pct"] is not None and metrics["dcf_upside_pct"] < 0
    assert built["profile"]["name"] == "Apple Inc."
    assert built["profile"]["sector"] == "Technology"
