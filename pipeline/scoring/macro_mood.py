"""Rule-based "mood" for each macro series: a quick emoji + label
summarizing whether a series' trajectory over the past year reads as
favorable, mixed, or concerning - in the context of what that particular
series' direction actually means. A rising unemployment rate is bad; rising
real GDP is good; a rising Fed funds rate is neither on its own, just
policy moving faster - forcing a universal "up = good" rule onto every
series would misread exactly the ones where direction is genuinely
ambiguous among economists (rates, money supply).

Deliberately no ML, same philosophy as macro_regime.py: every threshold
lives in config/macro_series.yaml, under each series' own `mood` block, so
the rules stay inspectable and tunable without touching this file.

"null not zero": a series without enough history for a real year-over-year
comparison returns mood None, never a guessed reading.
"""

_EMOJI = {
    "favorable": "🙂",
    "neutral": "😐",
    "unfavorable": "😟",
    "alarm": "😰",
}


def _level_change(observations: list[dict], obs_per_year: int) -> float | None:
    """Latest value minus the value from `obs_per_year` observations back -
    i.e. roughly one year ago, at this series' own native frequency."""
    if len(observations) <= obs_per_year:
        return None
    return observations[-1]["value"] - observations[-1 - obs_per_year]["value"]


def _pct_change(observations: list[dict], obs_per_year: int) -> float | None:
    if len(observations) <= obs_per_year:
        return None
    year_ago = observations[-1 - obs_per_year]["value"]
    if not year_ago:
        return None
    return (observations[-1]["value"] - year_ago) / abs(year_ago) * 100


def _mood_higher_better(trend: float, thresholds: dict, unit: str) -> dict:
    if trend >= thresholds["favorable"]:
        return {"key": "favorable", "label": "Improving", "detail": f"Up {trend:.1f}{unit} over the past year"}
    if trend <= thresholds["unfavorable"]:
        return {
            "key": "unfavorable",
            "label": "Weakening",
            "detail": f"Down {abs(trend):.1f}{unit} over the past year",
        }
    return {"key": "neutral", "label": "Roughly flat", "detail": f"Changed {trend:+.1f}{unit} over the past year"}


def _mood_lower_better(trend: float, thresholds: dict, unit: str) -> dict:
    if trend <= thresholds["favorable"]:
        return {
            "key": "favorable",
            "label": "Improving",
            "detail": f"Down {abs(trend):.1f}{unit} over the past year",
        }
    if trend >= thresholds["unfavorable"]:
        return {"key": "unfavorable", "label": "Worsening", "detail": f"Up {trend:.1f}{unit} over the past year"}
    return {"key": "neutral", "label": "Roughly stable", "detail": f"Changed {trend:+.1f}{unit} over the past year"}


def _mood_target(yoy_pct: float, target_pct: float, thresholds: dict) -> dict:
    if yoy_pct < 0:
        return {
            "key": "unfavorable",
            "label": "Deflationary reading",
            "detail": f"Down {abs(yoy_pct):.1f}% year-over-year - falling prices carry their own risks",
        }
    distance = yoy_pct - target_pct
    if abs(distance) <= thresholds["near"]:
        return {
            "key": "favorable",
            "label": "Near target",
            "detail": f"{yoy_pct:.1f}% year-over-year, close to the {target_pct:.0f}% target",
        }
    if distance <= thresholds["far"]:
        return {
            "key": "neutral",
            "label": "Above target",
            "detail": f"{yoy_pct:.1f}% year-over-year, running above the {target_pct:.0f}% target",
        }
    return {
        "key": "unfavorable",
        "label": "Well above target",
        "detail": f"{yoy_pct:.1f}% year-over-year, well above the {target_pct:.0f}% target",
    }


def _mood_context(volatility: float, thresholds: dict, unit: str) -> dict:
    if volatility <= thresholds["calm"]:
        return {"key": "favorable", "label": "Calm", "detail": f"Moved {volatility:.1f}{unit} over the past year"}
    if volatility <= thresholds["elevated"]:
        return {
            "key": "neutral",
            "label": "Moving",
            "detail": f"Moved {volatility:.1f}{unit} over the past year",
        }
    return {
        "key": "unfavorable",
        "label": "Volatile",
        "detail": f"Moved {volatility:.1f}{unit} over the past year - a fast swing",
    }


def compute_mood(series_id: str, observations: list[dict], series_cfg: dict, regime_rules: dict) -> dict | None:
    """observations: [{"date", "value"}, ...] oldest-first, as returned by
    pipeline.fetch.fred.fetch_series. series_cfg: this series' own entry
    from config/macro_series.yaml (must carry a `mood` block and
    `obs_per_year`, or None is returned). Returns {"emoji", "label",
    "detail"} or None when there isn't a year of history to compare
    against yet.
    """
    mood_cfg = series_cfg.get("mood") if series_cfg else None
    if not mood_cfg or not observations:
        return None

    obs_per_year = series_cfg.get("obs_per_year", 12)
    direction = mood_cfg["direction"]
    metric = mood_cfg.get("metric", "pct_change")
    thresholds = mood_cfg.get("thresholds", {})

    # Yield-curve inversion is a structural signal, not a magnitude-of-move
    # one - it overrides the ordinary volatility banding below entirely.
    # Reuses the exact "curve inverted" concept macro_regime.classify_regime
    # already applies (yield_curve_series, value < 0), rather than a second
    # copy of that rule.
    if series_id == regime_rules.get("yield_curve_series") and observations[-1]["value"] < 0:
        return {
            "emoji": _EMOJI["alarm"],
            "sentiment": "alarm",
            "label": "Inverted",
            "detail": "Yield curve is inverted - historically a recession-risk warning sign",
        }

    if direction in ("higher_better", "lower_better"):
        trend = _level_change(observations, obs_per_year) if metric == "level_change" else _pct_change(
            observations, obs_per_year
        )
        if trend is None:
            return None
        unit = "pp" if metric == "level_change" else "%"
        mood_fn = _mood_higher_better if direction == "higher_better" else _mood_lower_better
        result = mood_fn(trend, thresholds, unit)
    elif direction == "target":
        yoy_pct = _pct_change(observations, obs_per_year)
        if yoy_pct is None:
            return None
        result = _mood_target(yoy_pct, regime_rules.get("cpi_target_yoy_pct", 2.0), thresholds)
    elif direction == "context":
        trend = _level_change(observations, obs_per_year) if metric == "level_change" else _pct_change(
            observations, obs_per_year
        )
        if trend is None:
            return None
        unit = "pp" if metric == "level_change" else "%"
        result = _mood_context(abs(trend), thresholds, unit)
    else:
        return None

    return {
        "emoji": _EMOJI[result["key"]],
        "sentiment": result["key"],
        "label": result["label"],
        "detail": result["detail"],
    }
