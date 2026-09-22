from pipeline.scoring.aggregation import build_layered_analysis

_MUNGER_PASS = {"munger_quality": {"passed": 4, "evaluated": 4}}
_MUNGER_FAIL = {"munger_quality": {"passed": 0, "evaluated": 4}}


def test_all_layers_align():
    result = build_layered_analysis(
        {"moat_present": True, "red_flags": []},
        {"graham_upside_pct": 25.0},
        _MUNGER_PASS,
    )
    assert result == {
        "qualitative_moat_present": True,
        "munger_quality_pass": True,
        "valuation_gate_pass": True,
        "required_margin_of_safety_pct": 15.0,
        "overall": (
            "All three checks align: a moat was identified (Buffett), Munger's "
            "quality bar is met, and a margin of safety exists (Graham)."
        ),
        "flags": [],
        "conviction_score": None,
        "conviction_verdict": None,
        "conviction_score_breakdown": None,
    }


def test_no_moat_is_flagged_not_averaged_away():
    result = build_layered_analysis({"moat_present": False, "red_flags": []}, {"graham_upside_pct": 25.0})
    assert result["qualitative_moat_present"] is False
    assert any("no durable moat" in f for f in result["flags"])


def test_munger_quality_failure_flagged():
    result = build_layered_analysis(None, {"graham_upside_pct": 25.0}, _MUNGER_FAIL)
    assert result["munger_quality_pass"] is False
    assert any("Munger's quality checklist" in f for f in result["flags"])


def test_expensive_valuation_flagged_even_with_moat():
    result = build_layered_analysis({"moat_present": True, "red_flags": []}, {"graham_upside_pct": -40.0})
    assert result["valuation_gate_pass"] is False
    assert any("no margin of safety" in f for f in result["flags"])


def test_thin_margin_of_safety_below_convention_flagged():
    result = build_layered_analysis({"moat_present": True, "red_flags": []}, {"graham_upside_pct": 5.0})
    assert result["valuation_gate_pass"] is False
    assert any("Positive but thin" in f for f in result["flags"])


def test_red_flags_surfaced_regardless_of_other_layers():
    result = build_layered_analysis(
        {"moat_present": True, "red_flags": ["Customer concentration.", "Pending litigation."]},
        {"graham_upside_pct": 25.0},
    )
    assert any("2 red flag" in f for f in result["flags"])


def test_incomplete_when_any_layer_has_no_data():
    result = build_layered_analysis(None, {"graham_upside_pct": None})
    assert result["overall"].startswith("Incomplete")
    assert result["qualitative_moat_present"] is None
    assert result["munger_quality_pass"] is None
    assert result["valuation_gate_pass"] is None


def test_qualitative_none_when_layer_was_skipped_not_run():
    # The qualitative layer never ran (e.g. no 10-K found, or an API error) -
    # moat_present is None, which must read as "incomplete", not as "no moat
    # found".
    result = build_layered_analysis(None, {"graham_upside_pct": 25.0}, _MUNGER_PASS)
    assert result["qualitative_moat_present"] is None
    assert result["overall"].startswith("Incomplete")


def test_required_margin_of_safety_is_a_flat_graham_convention():
    # No more Klarman-style dynamic risk scaling - always 15%, regardless of
    # qualitative red flags.
    thin = build_layered_analysis(
        {"moat_present": True, "red_flags": ["a", "b", "c"]}, {"graham_upside_pct": 20.0}
    )
    full = build_layered_analysis({"moat_present": True, "red_flags": []}, {"graham_upside_pct": 20.0})
    assert thin["required_margin_of_safety_pct"] == 15.0
    assert full["required_margin_of_safety_pct"] == 15.0
    assert thin["valuation_gate_pass"] is True
    assert full["valuation_gate_pass"] is True
