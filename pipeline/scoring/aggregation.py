"""Combines the qualitative moat read, the quality checklist read, and the
valuation gate into one place WITHOUT averaging them into a single score -
each sub-score stays visible (qualitative_moat_present, munger_quality_pass,
valuation_gate_pass) precisely so a reader can see *why* something ranked
the way it did, not just a blended number that hides a broken moat behind a
strong balance sheet. See README's layered-analysis section for the
reasoning; this module is a pure function over the other layers'
already-computed output, no new data or API calls.
"""

# A real discount to estimated intrinsic value, not just trading below it
# by any amount. 15% is a commonly-cited (not universal) baseline. Compared
# against the fair-value estimate (metrics["graham_upside_pct"] -
# sqrt(22.5 x EPS x book value per share), a plain assets-and-earnings
# formula, not a growth projection). A single flat number, deliberately -
# an earlier version of this pipeline scaled this dynamically based on
# data coverage and filing red flags, which has been removed for
# simplicity.
REQUIRED_MARGIN_OF_SAFETY_PCT = 15.0

# The quality checklist "passes" when a majority of its evaluated criteria
# pass - not unanimous, since a single missing or borderline criterion
# shouldn't flip the whole quality read.
_MUNGER_QUALITY_PASS_FRACTION = 0.5


def _munger_quality_pass(value_investing_checklist: dict | None) -> bool | None:
    munger = (value_investing_checklist or {}).get("munger_quality") or {}
    if not munger.get("evaluated"):
        return None
    return munger["passed"] / munger["evaluated"] >= _MUNGER_QUALITY_PASS_FRACTION


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

    return {
        "qualitative_moat_present": moat_present,
        "munger_quality_pass": munger_quality_pass,
        "valuation_gate_pass": valuation_gate,
        "required_margin_of_safety_pct": REQUIRED_MARGIN_OF_SAFETY_PCT,
        "overall": overall,
        "flags": flags,
    }
