"""Combines layers 2-4 into one place WITHOUT averaging them into a single
score - each sub-score stays visible (quant_gate_pass, qualitative_moat_present,
valuation_gate_pass) precisely so a reader can see *why* something ranked
the way it did, not just a blended number that hides a broken moat behind
a strong quant score. See README's layered-analysis section for the
reasoning; this module is a pure function over the other layers' already-
computed output, no new data or API calls.
"""

# Classic value-investing convention: a "margin of safety" means a real
# discount to estimated intrinsic value, not just trading below it by any
# amount - 15% is a commonly-cited (not universal) threshold in that
# tradition. Compared against pipeline.scoring.valuation's own conservative
# DCF, not FMP's separate dcf_upside_pct.
_MARGIN_OF_SAFETY_THRESHOLD_PCT = 15.0


def build_layered_analysis(quant_scorecard: dict, qualitative: dict | None, valuation: dict) -> dict:
    flags: list[str] = []

    quant_gate = quant_scorecard.get("gate_pass")
    moat_present = qualitative.get("moat_present") if qualitative else None
    red_flags = (qualitative.get("red_flags") if qualitative else None) or []
    margin_of_safety = valuation.get("margin_of_safety_pct")
    valuation_gate = margin_of_safety >= _MARGIN_OF_SAFETY_THRESHOLD_PCT if margin_of_safety is not None else None

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
        flags.append("Positive but thin margin of safety (below the 15% convention) by this pipeline's DCF estimate.")

    if quant_gate is None or moat_present is None or valuation_gate is None:
        overall = "Incomplete: one or more layers has insufficient data for this company."
    elif quant_gate and moat_present and valuation_gate:
        overall = "All three layers align: passes the quant screen, a moat was identified, and a margin of safety exists."
    else:
        overall = "Layers disagree - see flags for specifics."

    return {
        "quant_gate_pass": quant_gate,
        "qualitative_moat_present": moat_present,
        "valuation_gate_pass": valuation_gate,
        "overall": overall,
        "flags": flags,
    }
