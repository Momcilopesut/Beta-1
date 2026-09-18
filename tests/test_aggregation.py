from pipeline.scoring.aggregation import build_layered_analysis


def test_all_layers_align():
    result = build_layered_analysis(
        {"gate_pass": True}, {"moat_present": True, "red_flags": []}, {"margin_of_safety_pct": 25.0}
    )
    assert result == {
        "quant_gate_pass": True,
        "qualitative_moat_present": True,
        "valuation_gate_pass": True,
        "overall": (
            "All three layers align: passes the quant screen, a moat was identified, and a margin of "
            "safety exists."
        ),
        "flags": [],
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
