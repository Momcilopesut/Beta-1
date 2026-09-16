"""Generic value -> 0-100 scoring engine, driven entirely by
config/scoring_weights.yaml so bands and weights are tunable without code
changes, and every sub-score stays inspectable (raw value + band -> score).
"""

from pipeline.utils.config import scoring_weights


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def normalize(metric_key: str, value: float | None) -> float | None:
    """Map a raw metric value to a 0-100 score via its configured threshold
    band. Returns None if the value itself is missing."""
    if value is None:
        return None
    band = scoring_weights()["thresholds"].get(metric_key)
    if band is None:
        raise KeyError(f"No threshold band configured for metric '{metric_key}'")
    lo, hi, direction = band["low"], band["high"], band["direction"]
    if hi == lo:
        return 50.0
    pct = clamp((value - lo) / (hi - lo), 0.0, 1.0) * 100
    return pct if direction == "higher_better" else 100 - pct


def score_components(metrics: dict, components: dict) -> dict:
    """components: the 'components' mapping for one bucket (short_term or
    long_term) from scoring_weights.yaml. Each component's score is the
    average of its metrics' normalized scores, with a missing metric falling
    back to the configured neutral score rather than breaking the average.
    The bucket's base_score is the weight-average of its components, using
    whatever weights are configured (they need not sum to exactly 100).
    """
    cfg = scoring_weights()
    neutral = cfg["neutral_score"]

    subscores = []
    weighted_sum = 0.0
    weight_total = 0.0

    for key, comp in components.items():
        raw_entries = []
        metric_scores = []
        for metric_key in comp["metrics"]:
            raw_value = metrics.get(metric_key)
            metric_score = normalize(metric_key, raw_value)
            raw_entries.append({"metric": metric_key, "raw_value": raw_value, "score": metric_score})
            metric_scores.append(metric_score if metric_score is not None else neutral)

        component_score = sum(metric_scores) / len(metric_scores) if metric_scores else neutral
        weight = comp["weight"]
        weighted_sum += component_score * weight
        weight_total += weight

        subscores.append(
            {
                "key": key,
                "label": comp["label"],
                "weight_pct": weight,
                "score": round(component_score, 1),
                "raw_metrics": raw_entries,
            }
        )

    base_score = weighted_sum / weight_total if weight_total else neutral
    return {"base_score": round(base_score, 1), "subscores": subscores}


def verdict_for(score: float) -> str:
    for band in scoring_weights()["verdict_bands"]:
        if score >= band["min"]:
            return band["label"]
    return scoring_weights()["verdict_bands"][-1]["label"]
