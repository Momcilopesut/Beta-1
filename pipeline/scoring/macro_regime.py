"""Rule-based macro regime classifier + sector-adjustment lookup.

Deliberately no ML: every threshold lives in config/macro_series.yaml and
config/sector_macro_sensitivity.yaml so the rules stay inspectable and
tunable without touching code, and every intermediate signal is returned so
the output JSON can show exactly why a regime was picked.
"""

from pipeline.utils.config import macro_series, sector_macro_sensitivity

# Static reference table: how each of our 4 regimes maps to the classic
# business-cycle phase, and which GICS-style sectors have *historically*
# led/lagged in that phase (long-run sector-rotation research, e.g. the
# style of analysis published by Fidelity and S&P Dow Jones Indices on
# GICS sector cyclicality). This is textbook historical pattern
# information, not a prediction about this specific cycle, and it names no
# current event - every cycle plays out differently, and it's presented as
# context, never as investment advice.
CYCLE_CONTEXT = {
    "Restrictive/Late-cycle": {
        "phase_name": "Late-cycle expansion / monetary tightening",
        "description": (
            "Growth is still positive but the yield curve is inverted and policy is restrictive - the "
            "classic late-cycle setup that has historically preceded a slowdown, though the lag varies "
            "widely cycle to cycle."
        ),
        "historically_favored_sectors": ["Energy", "Healthcare", "Consumer Defensive"],
        "historically_lagging_sectors": ["Real Estate", "Utilities", "Technology"],
    },
    "Contractionary Risk": {
        "phase_name": "Contraction / recession risk",
        "description": (
            "Yield curve inversion paired with a rising unemployment trend - historically the phase where "
            "defensive, non-cyclical demand holds up best relative to cyclical and credit-sensitive sectors."
        ),
        "historically_favored_sectors": ["Consumer Defensive", "Healthcare", "Utilities"],
        "historically_lagging_sectors": ["Consumer Cyclical", "Industrials", "Financial Services"],
    },
    "Easing/Recovery": {
        "phase_name": "Early-cycle recovery",
        "description": (
            "The Fed is cutting - historically the phase where rate-sensitive and higher-beta sectors have "
            "tended to lead as cheaper capital and improving sentiment favor risk-taking."
        ),
        "historically_favored_sectors": ["Consumer Cyclical", "Financial Services", "Real Estate"],
        "historically_lagging_sectors": ["Consumer Defensive", "Utilities"],
    },
    "Neutral/Expansion": {
        "phase_name": "Mid-cycle expansion",
        "description": (
            "No stress signal is currently flashing - broad-based growth conditions have historically "
            "favored cyclical and growth-oriented sectors over defensives."
        ),
        "historically_favored_sectors": ["Technology", "Industrials", "Communication Services"],
        "historically_lagging_sectors": ["Utilities", "Consumer Defensive"],
    },
}

CYCLE_CONTEXT_NOTE = (
    "Historical tendencies from long-run sector-rotation research, not a prediction - every cycle differs, "
    "and this names no current event or company-specific catalyst."
)


def cycle_context(regime: str) -> dict:
    context = CYCLE_CONTEXT.get(regime, CYCLE_CONTEXT["Neutral/Expansion"])
    return {**context, "note": CYCLE_CONTEXT_NOTE}


def _latest(series: list[dict]) -> float | None:
    return series[-1]["value"] if series else None


def _trend(series: list[dict], lookback_obs: int) -> float | None:
    """Change in value over the last `lookback_obs` observations."""
    if len(series) <= lookback_obs:
        return None
    return series[-1]["value"] - series[-1 - lookback_obs]["value"]


def _cpi_yoy(series: list[dict]) -> float | None:
    """CPIAUCSL is monthly; year-over-year change is 12 observations back."""
    if len(series) < 13:
        return None
    year_ago = series[-13]["value"]
    if not year_ago:
        return None
    return (series[-1]["value"] - year_ago) / year_ago * 100


def classify_regime(macro_data: dict) -> dict:
    """macro_data: {series_id: [{"date","value"}, ...]} (oldest first), as
    returned by pipeline.fetch.fred.fetch_all. Returns {"regime": str,
    "signals": {...}} applying, in order:
      1. Restrictive/Late-cycle: yield curve inverted AND fed funds not
         cutting AND CPI YoY above target
      2. Contractionary Risk: yield curve inverted AND unemployment rising
      3. Easing/Recovery: fed funds trending down
      4. Neutral/Expansion: fallback
    """
    rules = macro_series()["regime_rules"]

    curve_value = _latest(macro_data.get(rules["yield_curve_series"], []))
    curve_inverted = curve_value is not None and curve_value < 0

    fed_trend = _trend(macro_data.get("FEDFUNDS", []), rules["fed_funds_trend_lookback_obs"])
    cutting = fed_trend is not None and fed_trend <= rules["fed_funds_cut_threshold_pct"]

    cpi_yoy = _cpi_yoy(macro_data.get("CPIAUCSL", []))
    cpi_above_target = cpi_yoy is not None and cpi_yoy > rules["cpi_target_yoy_pct"]

    unemployment_trend = _trend(
        macro_data.get("UNRATE", []), rules["unemployment_trend_lookback_obs"]
    )
    unemployment_rising = (
        unemployment_trend is not None
        and unemployment_trend >= rules["unemployment_rising_threshold_pct"]
    )

    signals = {
        "yield_curve_value": curve_value,
        "yield_curve_inverted": curve_inverted,
        "fed_funds_trend_pct": fed_trend,
        "fed_funds_cutting": cutting,
        "cpi_yoy_pct": cpi_yoy,
        "cpi_above_target": cpi_above_target,
        "unemployment_trend_pct": unemployment_trend,
        "unemployment_rising": unemployment_rising,
    }

    if curve_inverted and not cutting and cpi_above_target:
        regime = "Restrictive/Late-cycle"
    elif curve_inverted and unemployment_rising:
        regime = "Contractionary Risk"
    elif cutting:
        regime = "Easing/Recovery"
    else:
        regime = "Neutral/Expansion"

    return {"regime": regime, "signals": signals}


def sector_adjustment(regime: str, sector: str | None) -> dict:
    """Returns {"short": int, "long": int, "rate_sensitivity": str,
    "cyclicality": str} for a company in the given sector under the given
    regime, bounded by config/sector_macro_sensitivity.yaml's clamp values."""
    cfg = sector_macro_sensitivity()
    sensitivity = cfg["sectors"].get(sector, cfg["default_sector"])
    table = cfg["adjustments"].get(regime, {})
    clamp_cfg = cfg["clamp"]

    rate_delta = table.get("rate_sensitivity", {}).get(
        sensitivity["rate_sensitivity"], {"short": 0, "long": 0}
    )
    cyclicality_delta = table.get("cyclicality", {}).get(
        sensitivity["cyclicality"], {"short": 0, "long": 0}
    )

    short = rate_delta["short"] + cyclicality_delta["short"]
    long = rate_delta["long"] + cyclicality_delta["long"]
    short = max(-clamp_cfg["short"], min(clamp_cfg["short"], short))
    long = max(-clamp_cfg["long"], min(clamp_cfg["long"], long))

    return {
        "short": short,
        "long": long,
        "rate_sensitivity": sensitivity["rate_sensitivity"],
        "cyclicality": sensitivity["cyclicality"],
    }
