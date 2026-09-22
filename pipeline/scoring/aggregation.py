"""Combines Buffett's qualitative moat read, Munger's capital-efficiency
quality read, and Graham's valuation gate into one place WITHOUT averaging
them into a single score - each sub-score stays visible
(qualitative_moat_present, munger_quality_pass, valuation_gate_pass)
precisely so a reader can see *why* something ranked the way it did, not
just a blended number that hides a broken moat behind a strong balance
sheet. See README's layered-analysis section for the reasoning; this module
is a pure function over the other layers' already-computed output, no new
data or API calls.

Also computes the Investment Meter (see build_conviction_score, still keyed
as "conviction_score" in the output for continuity) - a single 0-100 number
per stock, config-driven via config/conviction_score.yaml. This DOES
produce one number, but not via a naive average: Graham's own Defensive
Investor checklist is the base score, and Buffett's moat read, Munger's
quality checklist, and Graham's own valuation gate each multiply that base
rather than blending into it - so a strong checklist score can't quietly
paper over "no durable moat," "earns poor returns on capital," or "no
margin of safety at this price." Exactly three investors, nothing else:
Piotroski's checklist and Klarman's risk-scaled margin of safety (from
earlier iterations of this tool) have both been retired - see README.
"""

from pipeline.scoring.thresholds import verdict_for
from pipeline.utils.config import conviction_score_config

# Graham's own margin-of-safety convention: a real discount to estimated
# intrinsic value, not just trading below it by any amount. 15% is a
# commonly-cited (not universal) baseline in that tradition. Compared
# against the Graham Number (metrics["graham_upside_pct"] -
# sqrt(22.5 x EPS x book value per share), a plain assets-and-earnings
# formula, not a growth projection). A single flat number, deliberately -
# an earlier version of this pipeline scaled this dynamically based on
# data coverage and filing red flags (Klarman's own risk-management framing
# of margin of safety), which isn't Graham's, Buffett's, or Munger's idea
# and has been removed.
REQUIRED_MARGIN_OF_SAFETY_PCT = 15.0

# Munger's quality checklist "passes" when a majority of its evaluated
# criteria pass - not unanimous, since a single missing or borderline
# criterion shouldn't flip the whole quality read.
_MUNGER_QUALITY_PASS_FRACTION = 0.5


def _munger_quality_pass(value_investing_checklist: dict | None) -> bool | None:
    munger = (value_investing_checklist or {}).get("munger_quality") or {}
    if not munger.get("evaluated"):
        return None
    return munger["passed"] / munger["evaluated"] >= _MUNGER_QUALITY_PASS_FRACTION


def build_conviction_score(
    value_investing_checklist: dict | None,
    moat_present: bool | None,
    munger_quality_pass: bool | None,
    valuation_gate: bool | None,
) -> dict:
    """Returns {"score": float|None, "verdict": str|None, "score_breakdown": dict|None}.
    None when Graham's checklist has no evaluated data at all - there's
    nothing to score, not a score of 0."""
    graham = (value_investing_checklist or {}).get("graham_defensive") or {}
    if not graham.get("evaluated"):
        return {"score": None, "verdict": None, "score_breakdown": None}

    base_score = graham["passed"] / graham["evaluated"] * 100

    cfg = conviction_score_config()

    def multiplier(block: dict, value: bool | None, pass_key: str, fail_key: str) -> float:
        if value is True:
            return block[pass_key]
        if value is False:
            return block[fail_key]
        return block["not_evaluated"]

    moat_multiplier = multiplier(cfg["buffett_moat_multiplier"], moat_present, "moat_present", "no_moat")
    munger_multiplier = multiplier(
        cfg["munger_quality_multiplier"], munger_quality_pass, "quality_present", "quality_absent"
    )
    valuation_multiplier = multiplier(cfg["graham_valuation_multiplier"], valuation_gate, "pass", "fail")

    score = max(0.0, min(100.0, base_score * moat_multiplier * munger_multiplier * valuation_multiplier))

    return {
        "score": round(score, 1),
        "verdict": verdict_for(score),
        "score_breakdown": {
            "base_score": round(base_score, 1),
            "components": {"graham_pct": round(base_score, 1)},
            "moat_multiplier": moat_multiplier,
            "munger_multiplier": munger_multiplier,
            "valuation_multiplier": valuation_multiplier,
        },
    }


def build_layered_analysis(
    qualitative: dict | None,
    metrics: dict,
    value_investing_checklist: dict | None = None,
) -> dict:
    flags: list[str] = []

    moat_present = qualitative.get("moat_present") if qualitative else None
    red_flags = (qualitative.get("red_flags") if qualitative else None) or []
    munger_quality_pass = _munger_quality_pass(value_investing_checklist)
    margin_of_safety = metrics.get("graham_upside_pct")
    valuation_gate = margin_of_safety >= REQUIRED_MARGIN_OF_SAFETY_PCT if margin_of_safety is not None else None

    if moat_present is False:
        flags.append(
            "The qualitative layer found no durable moat in the filing text - current quality may not be "
            "durable."
        )
    if munger_quality_pass is False:
        flags.append(
            "The quality checklist (return on equity, debt discipline, no dilution, stable margins) "
            "mostly fails - a statistically cheap stock isn't automatically a good value if it doesn't "
            "actually earn good returns on capital."
        )
    if red_flags:
        flags.append(f"{len(red_flags)} red flag(s) from the filing text - see qualitative.red_flags.")
    if margin_of_safety is not None and margin_of_safety < 0:
        flags.append(
            "Trading above the fair-value estimate (a simple estimate from earnings and book value) - "
            "no margin of safety by that measure."
        )
    elif valuation_gate is False:
        flags.append(
            f"Positive but thin margin of safety - {margin_of_safety:.0f}% is below the "
            f"{REQUIRED_MARGIN_OF_SAFETY_PCT:.0f}% convention used here."
        )

    if moat_present is None or munger_quality_pass is None or valuation_gate is None:
        overall = "Incomplete: one or more layers has insufficient data for this company."
    elif moat_present and munger_quality_pass and valuation_gate:
        overall = (
            "All three checks align: a moat was identified, the quality bar is met, and a "
            "margin of safety exists."
        )
    else:
        overall = "Layers disagree - see flags for specifics."

    conviction = build_conviction_score(value_investing_checklist, moat_present, munger_quality_pass, valuation_gate)

    return {
        "qualitative_moat_present": moat_present,
        "munger_quality_pass": munger_quality_pass,
        "valuation_gate_pass": valuation_gate,
        "required_margin_of_safety_pct": REQUIRED_MARGIN_OF_SAFETY_PCT,
        "overall": overall,
        "flags": flags,
        "conviction_score": conviction["score"],
        "conviction_verdict": conviction["verdict"],
        "conviction_score_breakdown": conviction["score_breakdown"],
    }
