"""Price-performance screen: for each sector, the 5 best performers over
five fixed lookback windows (weekly, monthly, quarterly, annual, 5-year) -
a pure price-return ranking, deliberately independent of the Investment
Meter or any Graham/Buffett/Munger check. This is what the homepage ranks
companies by; the fundamentals-based scoring elsewhere in this pipeline
still runs for every company and still drives its own detail page, it just
doesn't gate or influence which tickers surface here.

Every return is computed from price history already fetched elsewhere in
the pipeline (pipeline.fetch.fmp/stooq via pipeline.scoring.fundamentals) -
no new API calls per company. A window with no close near enough to its
target date is left as None, never a guessed or interpolated number - the
same "null not zero" rule pipeline.scoring.history already follows for the
same reason (a short trading history, a fetch gap).
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

_UNCATEGORIZED = "Uncategorized"

# (key, label, calendar days back from the latest close, matching tolerance).
# Tolerance scales with the window: a few days' slack is fine for "weekly"
# only because it's checked against a short window; the same slack would be
# meaningless for "5-year", so each window gets its own.
WINDOWS = [
    ("weekly", "Weekly", 7, 3),
    ("monthly", "Monthly", 30, 5),
    ("quarterly", "Quarterly", 91, 7),
    ("annual", "Annual", 365, 10),
    ("five_year", "5-Year", 365 * 5, 10),
]


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except ValueError:
        return None


def _closest_close(price_rows: list[dict], target: date, tolerance_days: int) -> float | None:
    """Nearest trading-day close within `tolerance_days` of `target` - a
    calendar-day offset (e.g. exactly 7 days back) rarely lands on an actual
    trading day, so an exact-date match would miss almost everything.
    Returns None (not a guess) when nothing is close enough."""
    best_close = None
    best_gap = None
    for row in price_rows:
        row_date = _parse_date(row.get("date"))
        close = row.get("close")
        if row_date is None or close is None:
            continue
        gap = abs((row_date - target).days)
        if gap > tolerance_days:
            continue
        if best_gap is None or gap < best_gap:
            best_gap, best_close = gap, close
    return best_close


def _latest_row(price_rows: list[dict]) -> tuple[date, float] | None:
    best: tuple[date, float] | None = None
    for row in price_rows:
        row_date = _parse_date(row.get("date"))
        close = row.get("close")
        if row_date is None or close is None:
            continue
        if best is None or row_date > best[0]:
            best = (row_date, close)
    return best


def compute_returns(price_rows: list[dict]) -> dict[str, Any]:
    """Returns {"as_of": iso date|None, "latest_close": float|None, and one
    key per WINDOWS entry -> percent return|None}. price_rows: normalized
    [{"date", "close"}, ...] (pipeline.scoring.fundamentals.normalize_price_rows)."""
    empty = {key: None for key, *_ in WINDOWS}
    latest = _latest_row(price_rows)
    if latest is None:
        return {"as_of": None, "latest_close": None, **empty}

    latest_date, latest_close = latest
    out: dict[str, Any] = {"as_of": latest_date.isoformat(), "latest_close": latest_close}
    for key, _label, days_back, tolerance in WINDOWS:
        target = latest_date - timedelta(days=days_back)
        past_close = _closest_close(price_rows, target, tolerance)
        if not past_close:
            out[key] = None
        else:
            out[key] = (latest_close - past_close) / past_close * 100
    return out


def select_top_performers(summaries: list[dict], top_n: int = 5) -> dict[str, dict[str, list[dict]]]:
    """summaries: the same per-company summary dicts written to
    watchlist.json, each carrying "sector" and a "returns" dict from
    compute_returns(). Returns {sector: {window_key: [top_n summaries,
    highest return first]}} - every sector present in the input gets an
    entry for every window, independently ranked and independently capped,
    so the same ticker can (and often will) lead more than one window.
    A summary missing a return for a given window is excluded from that
    window's ranking only, not from the others."""
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for summary in summaries:
        sector = summary.get("sector") or _UNCATEGORIZED
        by_sector[sector].append(summary)

    result: dict[str, dict[str, list[dict]]] = {}
    for sector, sector_summaries in by_sector.items():
        result[sector] = {}
        for key, *_ in WINDOWS:
            eligible = [s for s in sector_summaries if (s.get("returns") or {}).get(key) is not None]
            eligible.sort(key=lambda s: s["returns"][key], reverse=True)
            result[sector][key] = eligible[:top_n]

    return result
