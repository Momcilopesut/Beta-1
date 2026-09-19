"""Tests for the Investment Meter (pipeline.scoring.aggregation.build_conviction_score,
still keyed "conviction_score" in the output for continuity) - a single
0-100 composite built from exactly three investors: Graham's Defensive
checklist as the base score, then Buffett's moat read, Munger's quality
checklist, and Graham's own Graham Number valuation gate each multiply that
base. See config/conviction_score.yaml for the multipliers these tests
assert against."""

from pipeline.scoring.aggregation import build_conviction_score


def _checklist(graham_passed=None, graham_evaluated=None):
    out = {}
    if graham_evaluated:
        out["graham_defensive"] = {"passed": graham_passed, "evaluated": graham_evaluated}
    return out


def test_all_multipliers_positive_clamps_at_100():
    result = build_conviction_score(_checklist(7, 7), moat_present=True, munger_quality_pass=True, valuation_gate=True)
    # base = 100 (Graham perfect) * 1.05 moat * 1.10 munger * 1.0 valuation = 115.5, clamped to 100
    assert result["score"] == 100.0
    assert result["verdict"] == "Strong"
    assert result["score_breakdown"]["moat_multiplier"] == 1.05
    assert result["score_breakdown"]["munger_multiplier"] == 1.10
    assert result["score_breakdown"]["valuation_multiplier"] == 1.0


def test_no_moat_no_quality_and_expensive_drags_a_strong_base_score_down_hard():
    result = build_conviction_score(_checklist(7, 7), moat_present=False, munger_quality_pass=False, valuation_gate=False)
    # base 100 * 0.70 no-moat * 0.75 no-quality * 0.55 fails-valuation = ~28.9
    assert result["score"] < 35
    assert result["verdict"] == "Cautious"


def test_cheap_but_low_quality_is_penalized_not_rewarded():
    # Munger's whole point: statistically cheap alone (a perfect Graham base)
    # isn't enough if the business earns poor returns on capital.
    cheap_high_quality = build_conviction_score(_checklist(7, 7), moat_present=None, munger_quality_pass=True, valuation_gate=None)
    cheap_low_quality = build_conviction_score(_checklist(7, 7), moat_present=None, munger_quality_pass=False, valuation_gate=None)
    assert cheap_low_quality["score"] < cheap_high_quality["score"]


def test_no_graham_data_returns_none_not_zero():
    result = build_conviction_score(None, moat_present=None, munger_quality_pass=None, valuation_gate=None)
    assert result["score"] is None
    assert result["verdict"] is None
    assert result["score_breakdown"] is None


def test_not_evaluated_multipliers_are_neutral():
    # moat/munger/valuation never ran (e.g. quant gate failed upstream) -
    # should neither help nor hurt the base score.
    result = build_conviction_score(_checklist(3, 5), moat_present=None, munger_quality_pass=None, valuation_gate=None)
    assert result["score"] == 60.0
    assert result["score_breakdown"]["moat_multiplier"] == 1.0
    assert result["score_breakdown"]["munger_multiplier"] == 1.0
    assert result["score_breakdown"]["valuation_multiplier"] == 1.0


def test_score_never_exceeds_100_or_drops_below_0():
    high = build_conviction_score(_checklist(7, 7), moat_present=True, munger_quality_pass=True, valuation_gate=True)
    assert 0.0 <= high["score"] <= 100.0

    low = build_conviction_score(_checklist(0, 7), moat_present=False, munger_quality_pass=False, valuation_gate=False)
    assert 0.0 <= low["score"] <= 100.0


def test_graham_uses_evaluated_not_total_as_denominator():
    # Graham has 7 total criteria but only 5 evaluated here (2 missing
    # data) - the pass rate should be passed/evaluated, not passed/total,
    # matching how the checklist itself already reports its own rate.
    result = build_conviction_score(
        _checklist(graham_passed=4, graham_evaluated=5), moat_present=None, munger_quality_pass=None, valuation_gate=None
    )
    assert result["score_breakdown"]["base_score"] == 80.0
    assert result["score_breakdown"]["components"] == {"graham_pct": 80.0}
