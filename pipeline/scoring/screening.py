"""Selects each week's top picks from the whole scanned universe.

Pure ranking, no I/O and no new scoring logic - it just reads the Investment
Meter score (conviction_score) pipeline.scoring.aggregation already computes
for every company, so "closest to satisfying the Graham/Buffett/Munger
criteria" is exactly the same number already shown on every company page.
"""

from collections import defaultdict

_UNCATEGORIZED = "Uncategorized"


def select_top_picks(summaries: list[dict], top_n_per_sector: int) -> dict[str, list[dict]]:
    """summaries: the same per-company summary dicts written to
    watchlist.json (each with "sector" and "conviction_score"). A summary
    with conviction_score is None is excluded - there is nothing to rank it
    against, and a null score reading as "worst" or "best" would be a guess,
    not a ranking. Returns {sector: [top summaries, highest score first]},
    each list capped at top_n_per_sector."""
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for summary in summaries:
        if summary.get("conviction_score") is None:
            continue
        sector = summary.get("sector") or _UNCATEGORIZED
        by_sector[sector].append(summary)

    for sector_summaries in by_sector.values():
        sector_summaries.sort(key=lambda s: s["conviction_score"], reverse=True)

    return {sector: sector_summaries[:top_n_per_sector] for sector, sector_summaries in by_sector.items()}
