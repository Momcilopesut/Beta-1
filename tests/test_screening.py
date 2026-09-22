from pipeline.scoring.screening import select_top_picks


def _summary(ticker, sector, score):
    return {"ticker": ticker, "sector": sector, "conviction_score": score}


def test_selects_highest_scores_first_within_each_sector():
    summaries = [
        _summary("A", "Technology", 40.0),
        _summary("B", "Technology", 80.0),
        _summary("C", "Technology", 60.0),
    ]
    picks = select_top_picks(summaries, top_n_per_sector=5)
    assert [s["ticker"] for s in picks["Technology"]] == ["B", "C", "A"]


def test_caps_at_top_n_per_sector():
    summaries = [_summary(f"T{i}", "Technology", float(i)) for i in range(10)]
    picks = select_top_picks(summaries, top_n_per_sector=3)
    assert len(picks["Technology"]) == 3
    assert [s["ticker"] for s in picks["Technology"]] == ["T9", "T8", "T7"]


def test_excludes_companies_with_no_score_rather_than_ranking_them():
    summaries = [
        _summary("A", "Energy", 70.0),
        _summary("B", "Energy", None),
    ]
    picks = select_top_picks(summaries, top_n_per_sector=5)
    tickers = [s["ticker"] for s in picks["Energy"]]
    assert tickers == ["A"]


def test_groups_independently_per_sector():
    summaries = [
        _summary("A", "Energy", 90.0),
        _summary("B", "Technology", 50.0),
    ]
    picks = select_top_picks(summaries, top_n_per_sector=5)
    assert set(picks.keys()) == {"Energy", "Technology"}
    assert [s["ticker"] for s in picks["Energy"]] == ["A"]
    assert [s["ticker"] for s in picks["Technology"]] == ["B"]


def test_missing_sector_falls_back_to_uncategorized():
    summaries = [_summary("A", None, 55.0)]
    picks = select_top_picks(summaries, top_n_per_sector=5)
    assert [s["ticker"] for s in picks["Uncategorized"]] == ["A"]


def test_empty_summaries_returns_empty_dict():
    assert select_top_picks([], top_n_per_sector=5) == {}
