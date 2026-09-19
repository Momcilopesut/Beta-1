"""Combines layers 2-4 into one place WITHOUT averaging them into a single
score - each sub-score stays visible (quant_gate_pass, qualitative_moat_present,
valuation_gate_pass) precisely so a reader can see *why* something ranked
the way it did, not just a blended number that hides a broken moat behind
a strong quant score. See README's layered-analysis section for the
reasoning; this module is a pure function over the other layers' already-
computed output, no new data or API calls.

Also computes the Conviction Score (see build_conviction_score) - a single
0-100 number per stock, config-driven via config/conviction_score.yaml.
This DOES produce one number, but not via a naive average: it's a weighted
base from the pass-rate checklists (quant screen, Graham, Piotroski,
Fisher), then the moat read and the valuation gate each multiply that base
rather than blending into it - the same gate/multiplier/final-gate design
as the rest of this module, just expressed as a number instead of only a
verdict and flags.
"""

from pipeline.scoring.thresholds import verdict_for
from pipeline.utils.config import conviction_score_config

# Classic value-investing convention: a "margin of safety" means a real
# discount to estimated intrinsic value, not just trading below it by any
# amount - 15% is a commonly-cited (not universal) baseline in that
# tradition. Compared against pipeline.scoring.valuation's own conservative
# DCF, not FMP's separate dcf_upside_pct.
_BASE_MARGIN_OF_SAFETY_THRESHOLD_PCT = 15.0

# Klarman's point about margin of safety is that it's a risk-management
# concept, not a fixed valuation number - a more uncertain read should
# demand a bigger discount, not the same flat one as a well-covered,
# clean-filing company. These are deliberately modest, documented bumps on
# top of the base threshold, not a precise risk model.
_THIN_QUANT_COVERAGE_THRESHOLD = 3  # fewer than this many evaluated quant metrics
_THIN_QUANT_COVERAGE_BUMP_PCT = 10.0
_RED_FLAG_BUMP_PCT = 5.0
_RED_FLAG_BUMP_CAP_PCT = 15.0
_FALLBACK_EXTRACTION_BUMP_PCT = 5.0


def _required_margin_of_safety_pct(quant_scorecard: dict, qualitative: dict | None) -> float:
    required = _BASE_MARGIN_OF_SAFETY_THRESHOLD_PCT
    evaluated = quant_scorecard.get("evaluated") or 0
    if evaluated and evaluated < _THIN_QUANT_COVERAGE_THRESHOLD:
        required += _THIN_QUANT_COVERAGE_BUMP_PCT
    if qualitative:
        red_flags = qualitative.get("red_flags") or []
        required += min(len(red_flags) * _RED_FLAG_BUMP_PCT, _RED_FLAG_BUMP_CAP_PCT)
        if qualitative.get("extraction_confidence") == "whole_document_fallback":
            required += _FALLBACK_EXTRACTION_BUMP_PCT
    return required


def _checklist_pass_rate_components(
    quant_scorecard: dict, qualitative: dict | None, value_investing_checklist: dict | None
) -> dict[str, float]:
    """Every pass-rate checklist this pipeline computes, as a 0-100 number,
    included only when it actually has data - a checklist the pipeline
    couldn't evaluate (e.g. Piotroski needs 2 years of statements) is left
    out entirely rather than counted as a failure."""
    components: dict[str, float] = {}

    if quant_scorecard.get("quant_score_pct") is not None:
        components["quant_score_pct"] = quant_scorecard["quant_score_pct"]

    checklist = value_investing_checklist or {}
    graham = checklist.get("graham_defensive") or {}
    if graham.get("evaluated"):
        components["graham_pct"] = graham["passed"] / graham["evaluated"] * 100

    piotroski = checklist.get("piotroski_f_score") or {}
    if piotroski.get("evaluated"):
        components["piotroski_pct"] = piotroski["score"] / piotroski["evaluated"] * 100

    fisher_items = (qualitative or {}).get("fisher_checklist") or []
    decided = [c for c in fisher_items if c.get("assessment") in ("yes", "no")]
    if decided:
        components["fisher_pct"] = sum(1 for c in decided if c["assessment"] == "yes") / len(decided) * 100

    return components


def build_conviction_score(
    quant_scorecard: dict,
    qualitative: dict | None,
    value_investing_checklist: dict | None,
    moat_present: bool | None,
    valuation_gate: bool | None,
) -> dict:
    """Returns {"score": float|None, "verdict": str|None, "score_breakdown": dict|None}.
    None across the board when none of the pass-rate checklists have any
    data at all - there's nothing to score, not a score of 0."""
    cfg = conviction_score_config()
    weights = cfg["component_weights"]
    components = _checklist_pass_rate_components(quant_scorecard, qualitative, value_investing_checklist)

    if not components:
        return {"score": None, "verdict": None, "score_breakdown": None}

    total_weight = sum(weights[key] for key in components)
    base_score = sum(components[key] * weights[key] for key in components) / total_weight

    moat_multipliers = cfg["qualitative_moat_multiplier"]
    if moat_present is True:
        moat_multiplier = moat_multipliers["moat_present"]
    elif moat_present is False:
        moat_multiplier = moat_multipliers["no_moat"]
    else:
        moat_multiplier = moat_multipliers["not_evaluated"]

    valuation_multipliers = cfg["valuation_gate_multiplier"]
    if valuation_gate is True:
        valuation_multiplier = valuation_multipliers["pass"]
    elif valuation_gate is False:
        valuation_multiplier = valuation_multipliers["fail"]
    else:
        valuation_multiplier = valuation_multipliers["not_evaluated"]

    score = max(0.0, min(100.0, base_score * moat_multiplier * valuation_multiplier))

    return {
        "score": round(score, 1),
        "verdict": verdict_for(score),
        "score_breakdown": {
            "base_score": round(base_score, 1),
            "components": {key: round(value, 1) for key, value in components.items()},
            "moat_multiplier": moat_multiplier,
            "valuation_multiplier": valuation_multiplier,
        },
    }


def build_layered_analysis(
    quant_scorecard: dict,
    qualitative: dict | None,
    valuation: dict,
    value_investing_checklist: dict | None = None,
) -> dict:
    flags: list[str] = []

    quant_gate = quant_scorecard.get("gate_pass")
    moat_present = qualitative.get("moat_present") if qualitative else None
    red_flags = (qualitative.get("red_flags") if qualitative else None) or []
    margin_of_safety = valuation.get("margin_of_safety_pct")
    required_margin_of_safety_pct = _required_margin_of_safety_pct(quant_scorecard, qualitative)
    valuation_gate = margin_of_safety >= required_margin_of_safety_pct if margin_of_safety is not None else None

    if quant_gate is False:
        flags.append("Fails the quant screen - below threshold on more metrics than it passes.")
    if quant_gate and moat_present is False:
        flags.append(
            "Passes the quant screen, but the qualitative layer found no durable moat in the filing "
            "text - current quality may not be durable."
        )
    if quant_gate is False and moat_present:
        flags.append(
            "A moat was identified despite a weak quant screen - may reflect a temporary setback or a "
            "data gap rather than a broken business; worth a closer look, not a straight pass."
        )
    if red_flags:
        flags.append(f"{len(red_flags)} red flag(s) from the filing text - see qualitative.red_flags.")
    if margin_of_safety is not None and margin_of_safety < 0:
        flags.append(
            "Trading above this pipeline's conservative DCF estimate - no margin of safety by that measure "
            "(expected for expensive, high-growth names against a deliberately conservative model - see "
            "valuation.dcf.assumptions.note)."
        )
    elif valuation_gate is False:
        flags.append(
            f"Positive but thin margin of safety - {margin_of_safety:.0f}% is below the "
            f"{required_margin_of_safety_pct:.0f}% this company's uncertainty calls for (Klarman: margin of "
            "safety should scale with risk, not stay flat - see required_margin_of_safety_pct)."
        )

    if quant_gate is None or moat_present is None or valuation_gate is None:
        overall = "Incomplete: one or more layers has insufficient data for this company."
    elif quant_gate and moat_present and valuation_gate:
        overall = "All three layers align: passes the quant screen, a moat was identified, and a margin of safety exists."
    else:
        overall = "Layers disagree - see flags for specifics."

    conviction = build_conviction_score(quant_scorecard, qualitative, value_investing_checklist, moat_present, valuation_gate)

    return {
        "quant_gate_pass": quant_gate,
        "qualitative_moat_present": moat_present,
        "valuation_gate_pass": valuation_gate,
        "required_margin_of_safety_pct": required_margin_of_safety_pct,
        "overall": overall,
        "flags": flags,
        "conviction_score": conviction["score"],
        "conviction_verdict": conviction["verdict"],
        "conviction_score_breakdown": conviction["score_breakdown"],
    }
