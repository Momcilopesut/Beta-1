"""Peter Lynch's growth-type categorization (One Up on Wall Street) - a
descriptive lens for reading a company's numbers in context, not a score.
Pure function over data already fetched; no new API calls.

This is a rule-based heuristic, not Lynch's own judgment (which relied on
qualitative research/"scuttlebutt" this pipeline doesn't have access to).
In particular it CANNOT reliably distinguish a genuine "turnaround" (a
struggling company about to recover) from a business in ordinary decline -
both show negative recent EPS growth, and telling them apart needs the
kind of forward-looking judgment Lynch made in person, not a formula. Both
land in "turnaround" here with that ambiguity stated plainly in the
reasoning, rather than the code pretending to a confidence it doesn't have.
"""

CYCLICAL_SECTORS = {"Energy", "Basic Materials", "Industrials"}
LARGE_CAP_THRESHOLD = 10_000_000_000  # $10B - roughly Lynch's "big, mature" framing
FAST_GROWER_THRESHOLD_PCT = 20.0
SLOW_GROWER_THRESHOLD_PCT = 10.0


def classify(metrics: dict, sector: str | None, market_cap: float | None) -> dict:
    """Returns {"category": str|None, "reasoning": str}. category is one of
    fast_grower/stalwart/slow_grower/cyclical/turnaround/asset_play, or None
    if there isn't enough data to classify at all."""
    growth = metrics.get("eps_growth_cagr_3yr_pct")
    ncav_margin = metrics.get("ncav_margin_pct")

    # An asset play check comes first regardless of growth - Lynch's point
    # is that the balance sheet alone can make the stock interesting.
    # ncav_margin_pct is "almost always sharply negative" for a going
    # concern (see config/scoring_weights.yaml); a value close to or above
    # zero is a genuinely unusual signal worth flagging ahead of anything else.
    if ncav_margin is not None and ncav_margin > -10:
        return {
            "category": "asset_play",
            "reasoning": (
                f"Net current asset value is unusually close to the price (NCAV margin "
                f"{ncav_margin:+.1f}%) - Lynch's 'asset play' signal, ahead of the growth rate."
            ),
        }

    if sector in CYCLICAL_SECTORS:
        return {
            "category": "cyclical",
            "reasoning": f"{sector} - earnings here typically track the economic cycle rather than compound steadily.",
        }

    if growth is None:
        return {"category": None, "reasoning": "Not enough EPS growth history to classify."}

    if growth < 0:
        return {
            "category": "turnaround",
            "reasoning": (
                f"Negative EPS growth ({growth:+.1f}%/yr) - either an ongoing decline or, if this "
                "marks a trough, a Lynch-style turnaround candidate; this pipeline can't distinguish "
                "the two from data alone, unlike Lynch's own on-the-ground research."
            ),
        }

    if growth >= FAST_GROWER_THRESHOLD_PCT:
        return {
            "category": "fast_grower",
            "reasoning": f"EPS growing {growth:.1f}%/yr - Lynch's 'fast grower' territory (roughly 20%+).",
        }

    if market_cap is not None and market_cap >= LARGE_CAP_THRESHOLD and growth < SLOW_GROWER_THRESHOLD_PCT:
        return {
            "category": "slow_grower",
            "reasoning": (
                f"Large (${market_cap / 1e9:.0f}B) with EPS growing just {growth:.1f}%/yr - "
                "Lynch's 'slow grower' territory."
            ),
        }

    return {
        "category": "stalwart",
        "reasoning": f"Moderate, steady EPS growth ({growth:.1f}%/yr) - Lynch's 'stalwart' territory.",
    }
