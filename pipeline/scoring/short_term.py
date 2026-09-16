"""Short-term (0-100) score: price momentum, technical positioning,
earnings/guidance direction, and valuation extension, nudged by the macro
regime adjustment for the company's sector."""

from pipeline.scoring.thresholds import score_components, verdict_for
from pipeline.utils.config import scoring_weights


def score(metrics: dict, macro_delta: int) -> dict:
    components = scoring_weights()["short_term"]["components"]
    base = score_components(metrics, components)
    final_score = max(0.0, min(100.0, base["base_score"] + macro_delta))

    return {
        "base_score": base["base_score"],
        "macro_adjustment": macro_delta,
        "final_score": round(final_score, 1),
        "verdict": verdict_for(final_score),
        "subscores": base["subscores"],
    }
