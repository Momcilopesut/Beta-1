from datetime import date, timedelta

import pytest

from pipeline.scoring.performance import WINDOWS, compute_returns, select_top_performers


def _rows(latest: date, num_days: int, price_at) -> list[dict]:
    return [
        {"date": (latest - timedelta(days=i)).isoformat(), "close": price_at(i)}
        for i in range(num_days + 1)
    ]


def test_compute_returns_all_windows_present():
    latest = date(2026, 9, 22)
    price_at = lambda days_ago: 1000.0 - days_ago  # close decreases by 1 per day further back
    rows = _rows(latest, 365 * 5 + 15, price_at)

    result = compute_returns(rows)

    assert result["as_of"] == latest.isoformat()
    assert result["latest_close"] == 1000.0
    for key, _label, days_back, _tolerance in WINDOWS:
        past_price = price_at(days_back)
        expected = (1000.0 - past_price) / past_price * 100
        assert result[key] == pytest.approx(expected)


def test_compute_returns_missing_window_is_none_not_guessed():
    latest = date(2026, 9, 22)
    rows = _rows(latest, 10, lambda days_ago: 100.0 - days_ago)  # only 10 days of history

    result = compute_returns(rows)

    assert result["weekly"] is not None  # 7 days back, within the 10-day history
    assert result["monthly"] is None
    assert result["quarterly"] is None
    assert result["annual"] is None
    assert result["five_year"] is None


def test_compute_returns_empty_price_rows():
    result = compute_returns([])
    assert result["as_of"] is None
    assert result["latest_close"] is None
    for key, *_ in WINDOWS:
        assert result[key] is None


def test_compute_returns_zero_past_close_does_not_divide_by_zero():
    latest = date(2026, 9, 22)
    rows = [
        {"date": latest.isoformat(), "close": 50.0},
        {"date": (latest - timedelta(days=7)).isoformat(), "close": 0.0},
    ]
    result = compute_returns(rows)
    assert result["weekly"] is None


def test_compute_returns_matches_closest_trading_day_within_tolerance():
    latest = date(2026, 9, 22)
    rows = [
        {"date": latest.isoformat(), "close": 110.0},
        # 1 day short of the weekly target (7 days back) - within its 3-day tolerance.
        {"date": (latest - timedelta(days=6)).isoformat(), "close": 100.0},
    ]
    result = compute_returns(rows)
    assert result["weekly"] == pytest.approx((110.0 - 100.0) / 100.0 * 100)


def test_compute_returns_beyond_tolerance_returns_none():
    latest = date(2026, 9, 22)
    rows = [
        {"date": latest.isoformat(), "close": 110.0},
        # Far outside weekly's 3-day tolerance around its 7-day target.
        {"date": (latest - timedelta(days=20)).isoformat(), "close": 100.0},
    ]
    result = compute_returns(rows)
    assert result["weekly"] is None


def _summary(ticker: str, sector: str | None, **returns) -> dict:
    return {"ticker": ticker, "sector": sector, "returns": returns}


def test_select_top_performers_ranks_each_window_independently():
    summaries = [
        _summary("A", "Tech", weekly=5, monthly=1, quarterly=None, annual=None, five_year=None),
        _summary("B", "Tech", weekly=1, monthly=5, quarterly=None, annual=None, five_year=None),
    ]
    result = select_top_performers(summaries, top_n=5)
    assert [s["ticker"] for s in result["Tech"]["weekly"]] == ["A", "B"]
    assert [s["ticker"] for s in result["Tech"]["monthly"]] == ["B", "A"]


def test_select_top_performers_excludes_null_returns_per_window():
    summaries = [
        _summary("A", "Tech", weekly=5, monthly=None, quarterly=None, annual=None, five_year=None),
        _summary("B", "Tech", weekly=None, monthly=None, quarterly=None, annual=None, five_year=None),
    ]
    result = select_top_performers(summaries, top_n=5)
    assert [s["ticker"] for s in result["Tech"]["weekly"]] == ["A"]
    assert result["Tech"]["monthly"] == []


def test_select_top_performers_caps_at_top_n():
    summaries = [
        _summary(f"T{i}", "Tech", weekly=i, monthly=None, quarterly=None, annual=None, five_year=None)
        for i in range(10)
    ]
    result = select_top_performers(summaries, top_n=5)
    assert len(result["Tech"]["weekly"]) == 5
    assert [s["ticker"] for s in result["Tech"]["weekly"]] == ["T9", "T8", "T7", "T6", "T5"]


def test_select_top_performers_sectors_independent():
    summaries = [
        _summary("A", "Tech", weekly=10, monthly=None, quarterly=None, annual=None, five_year=None),
        _summary("B", "Energy", weekly=1, monthly=None, quarterly=None, annual=None, five_year=None),
    ]
    result = select_top_performers(summaries, top_n=5)
    assert [s["ticker"] for s in result["Tech"]["weekly"]] == ["A"]
    assert [s["ticker"] for s in result["Energy"]["weekly"]] == ["B"]


def test_select_top_performers_missing_sector_falls_back_to_uncategorized():
    summaries = [
        {"ticker": "A", "returns": {"weekly": 1, "monthly": None, "quarterly": None, "annual": None, "five_year": None}}
    ]
    result = select_top_performers(summaries, top_n=5)
    assert "Uncategorized" in result
    assert result["Uncategorized"]["weekly"][0]["ticker"] == "A"


def test_select_top_performers_empty_input():
    assert select_top_performers([], top_n=5) == {}
