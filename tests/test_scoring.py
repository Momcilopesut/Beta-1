import json
from pathlib import Path

from pipeline.scoring import macro_regime
from pipeline.scoring.fundamentals import build_metrics

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    with open(FIXTURES / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _series(values):
    return [{"date": f"2026-01-{i + 1:02d}", "value": v} for i, v in enumerate(values)]


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
    assert built["profile"]["name"] == "Apple Inc."
    assert built["profile"]["sector"] == "Technology"
