from pipeline.scoring.aggregation import build_layered_analysis


def test_all_layers_align():
    result = build_layered_analysis(
        {"gate_pass": True, "evaluated": 5}, {"moat_present": True, "red_flags": []}, {"margin_of_safety_pct": 25.0}
    )
    assert result == {
        "quant_gate_pass": True,
        "qualitative_moat_present": True,
        "valuation_gate_pass": True,
        "required_margin_of_safety_pct": 15.0,
        "overall": (
            "All three layers align: passes the quant screen, a moat was identified, and a margin of "
            "safety exists."
        ),
        "flags": [],
        "conviction_score": None,
        "conviction_verdict": None,
        "conviction_score_breakdown": None,
    }


def test_strong_quant_but_no_moat_is_flagged_not_averaged_away():
    result = build_layered_analysis(
        {"gate_pass": True}, {"moat_present": False, "red_flags": []}, {"margin_of_safety_pct": 25.0}
    )
    assert result["quant_gate_pass"] is True
    assert result["qualitative_moat_present"] is False
    assert any("no durable moat" in f for f in result["flags"])


def test_weak_quant_but_moat_present_is_flagged_not_dismissed():
    result = build_layered_analysis(
        {"gate_pass": False}, {"moat_present": True, "red_flags": []}, {"margin_of_safety_pct": 25.0}
    )
    assert any("weak quant screen" in f for f in result["flags"])


def test_expensive_valuation_flagged_even_with_good_quant_and_moat():
    result = build_layered_analysis(
        {"gate_pass": True}, {"moat_present": True, "red_flags": []}, {"margin_of_safety_pct": -40.0}
    )
    assert result["valuation_gate_pass"] is False
    assert any("no margin of safety" in f for f in result["flags"])


def test_thin_margin_of_safety_below_convention_flagged():
    result = build_layered_analysis(
        {"gate_pass": True}, {"moat_present": True, "red_flags": []}, {"margin_of_safety_pct": 5.0}
    )
    assert result["valuation_gate_pass"] is False
    assert any("Positive but thin" in f for f in result["flags"])


def test_red_flags_surfaced_regardless_of_other_layers():
    result = build_layered_analysis(
        {"gate_pass": True},
        {"moat_present": True, "red_flags": ["Customer concentration.", "Pending litigation."]},
        {"margin_of_safety_pct": 25.0},
    )
    assert any("2 red flag" in f for f in result["flags"])


def test_incomplete_when_any_layer_has_no_data():
    result = build_layered_analysis({"gate_pass": None}, None, {"margin_of_safety_pct": None})
    assert result["overall"].startswith("Incomplete")
    assert result["quant_gate_pass"] is None
    assert result["qualitative_moat_present"] is None
    assert result["valuation_gate_pass"] is None


def test_qualitative_none_when_layer_was_skipped_not_run():
    # quant passed but the qualitative layer never ran (e.g. gate failed
    # upstream in a different company, or an API error) - moat_present is
    # None, which must read as "incomplete", not as "no moat found".
    result = build_layered_analysis({"gate_pass": True}, None, {"margin_of_safety_pct": 25.0})
    assert result["qualitative_moat_present"] is None
    assert result["overall"].startswith("Incomplete")


# --- Klarman: margin of safety should scale with actual uncertainty ---


def test_required_margin_of_safety_bumped_by_thin_quant_coverage():
    thin = build_layered_analysis(
        {"gate_pass": True, "evaluated": 1}, {"moat_present": True, "red_flags": []}, {"margin_of_safety_pct": 20.0}
    )
    full = build_layered_analysis(
        {"gate_pass": True, "evaluated": 5}, {"moat_present": True, "red_flags": []}, {"margin_of_safety_pct": 20.0}
    )
    assert thin["required_margin_of_safety_pct"] > full["required_margin_of_safety_pct"]
    # 20% clears the base 15% requirement but not the thin-coverage-bumped one.
    assert full["valuation_gate_pass"] is True
    assert thin["valuation_gate_pass"] is False


def test_required_margin_of_safety_bumped_by_red_flags_and_capped():
    one_flag = build_layered_analysis(
        {"gate_pass": True, "evaluated": 5}, {"moat_present": True, "red_flags": ["a"]}, {"margin_of_safety_pct": 20.0}
    )
    many_flags = build_layered_analysis(
        {"gate_pass": True, "evaluated": 5},
        {"moat_present": True, "red_flags": ["a", "b", "c", "d", "e"]},
        {"margin_of_safety_pct": 20.0},
    )
    assert one_flag["required_margin_of_safety_pct"] == 20.0  # 15 base + 5 for one flag
    assert many_flags["required_margin_of_safety_pct"] == 30.0  # capped at +15 regardless of flag count


def test_required_margin_of_safety_bumped_by_fallback_extraction():
    clean = build_layered_analysis(
        {"gate_pass": True, "evaluated": 5},
        {"moat_present": True, "red_flags": [], "extraction_confidence": "section_match"},
        {"margin_of_safety_pct": 20.0},
    )
    fallback = build_layered_analysis(
        {"gate_pass": True, "evaluated": 5},
        {"moat_present": True, "red_flags": [], "extraction_confidence": "whole_document_fallback"},
        {"margin_of_safety_pct": 20.0},
    )
    assert fallback["required_margin_of_safety_pct"] == clean["required_margin_of_safety_pct"] + 5.0


def test_required_margin_of_safety_defaults_to_base_without_qualitative():
    result = build_layered_analysis({"gate_pass": True, "evaluated": 5}, None, {"margin_of_safety_pct": 20.0})
    assert result["required_margin_of_safety_pct"] == 15.0
