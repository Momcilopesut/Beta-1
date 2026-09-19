"""Tests for the Conviction Score (pipeline.scoring.aggregation.build_conviction_score) -
the single 0-100 composite built from every pass-rate checklist this
pipeline computes, then gated by the moat read and the valuation margin
of safety. See config/conviction_score.yaml for the weights/multipliers
these tests assert against."""

from pipeline.scoring.aggregation import build_conviction_score


def _quant(pct):
    return {"quant_score_pct": pct}


def _checklist(graham_passed=None, graham_evaluated=None, piotroski_score=None, piotroski_evaluated=None):
    out = {}
    if graham_evaluated:
        out["graham_defensive"] = {"passed": graham_passed, "evaluated": graham_evaluated}
    if piotroski_evaluated:
        out["piotroski_f_score"] = {"score": piotroski_score, "evaluated": piotroski_evaluated}
    return out


def test_all_components_perfect_with_moat_and_margin_of_safety():
    result = build_conviction_score(
        _quant(100.0),
        {"fisher_checklist": [{"assessment": "yes"}] * 4},
        _checklist(7, 7, 9, 9),
        moat_present=True,
        valuation_gate=True,
    )
    # base = 100 (all components perfect) * 1.05 moat * 1.0 valuation = 105, clamped to 100
    assert result["score"] == 100.0
    assert result["verdict"] == "Strong"
    assert result["score_breakdown"]["moat_multiplier"] == 1.05
    assert result["score_breakdown"]["valuation_multiplier"] == 1.0


def test_no_moat_and_expensive_drags_a_strong_base_score_down_hard():
    result = build_conviction_score(
        _quant(100.0), {"fisher_checklist": []}, _checklist(7, 7, 9, 9), moat_present=False, valuation_gate=False
    )
    # base ~100 * 0.70 no-moat * 0.55 fails-valuation = ~38.5
    assert result["score"] < 45
    assert result["verdict"] in ("Cautious", "Weak")


def test_missing_checklist_renormalizes_over_available_components():
    # Only quant data available - its weight (0.30) should become the
    # entire base, not silently divided by the full 1.0 total.
    result = build_conviction_score(_quant(80.0), None, None, moat_present=None, valuation_gate=None)
    assert result["score_breakdown"]["base_score"] == 80.0
    assert result["score_breakdown"]["components"] == {"quant_score_pct": 80.0}


def test_fisher_checklist_only_counts_decided_items_not_unknown():
    qualitative = {
        "fisher_checklist": [
            {"assessment": "yes"},
            {"assessment": "yes"},
            {"assessment": "no"},
            {"assessment": "unknown"},
            {"assessment": "unknown"},
        ]
    }
    result = build_conviction_score(_quant(50.0), qualitative, None, moat_present=None, valuation_gate=None)
    # 2 yes / 3 decided (excluding the 2 unknowns) = 66.7%
    assert result["score_breakdown"]["components"]["fisher_pct"] == round(2 / 3 * 100, 1)


def test_no_data_anywhere_returns_none_not_zero():
    result = build_conviction_score({}, None, None, moat_present=None, valuation_gate=None)
    assert result["score"] is None
    assert result["verdict"] is None
    assert result["score_breakdown"] is None


def test_not_evaluated_multipliers_are_neutral():
    # moat/valuation never ran (e.g. quant gate failed upstream) - should
    # neither help nor hurt the base score.
    result = build_conviction_score(_quant(60.0), None, None, moat_present=None, valuation_gate=None)
    assert result["score"] == 60.0
    assert result["score_breakdown"]["moat_multiplier"] == 1.0
    assert result["score_breakdown"]["valuation_multiplier"] == 1.0


def test_score_never_exceeds_100_or_drops_below_0():
    high = build_conviction_score(
        _quant(100.0), {"fisher_checklist": [{"assessment": "yes"}]}, _checklist(7, 7, 9, 9),
        moat_present=True, valuation_gate=True,
    )
    assert 0.0 <= high["score"] <= 100.0

    low = build_conviction_score(
        _quant(0.0), {"fisher_checklist": [{"assessment": "no"}]}, _checklist(0, 7, 0, 9),
        moat_present=False, valuation_gate=False,
    )
    assert 0.0 <= low["score"] <= 100.0


def test_graham_and_piotroski_use_evaluated_not_total_as_denominator():
    # Graham has 7 total criteria but only 5 evaluated here (2 missing
    # data) - the pass rate should be passed/evaluated, not passed/total,
    # matching how the checklist itself already reports its own rate.
    result = build_conviction_score(
        {}, None, _checklist(graham_passed=4, graham_evaluated=5), moat_present=None, valuation_gate=None
    )
    assert result["score_breakdown"]["components"]["graham_pct"] == 80.0
