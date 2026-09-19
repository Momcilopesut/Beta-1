"""verdict_for: maps a 0-100 score to a plain-language band, driven by
config/conviction_score.yaml's verdict_bands so the bands are tunable
without code changes. The Conviction Score (pipeline/scoring/aggregation.py)
is the only score this pipeline computes, so this is the only consumer.
"""

from pipeline.utils.config import conviction_score_config


def verdict_for(score: float) -> str:
    for band in conviction_score_config()["verdict_bands"]:
        if score >= band["min"]:
            return band["label"]
    return conviction_score_config()["verdict_bands"][-1]["label"]
