from pipeline.main import apply_magic_formula_rank


def _state(ticker: str, roic_pct: float | None, earnings_yield_pct: float | None) -> dict:
    return {"ticker": ticker, "metrics": {"roic_pct": roic_pct, "earnings_yield_pct": earnings_yield_pct}}


def test_ranks_combine_both_factors_lower_is_better():
    states = [
        _state("BEST", roic_pct=30.0, earnings_yield_pct=12.0),  # rank 1 + rank 1 = 2
        _state("MIDDLE", roic_pct=20.0, earnings_yield_pct=8.0),  # rank 2 + rank 2 = 4
        _state("WORST", roic_pct=5.0, earnings_yield_pct=2.0),  # rank 3 + rank 3 = 6
    ]
    apply_magic_formula_rank(states)

    by_ticker = {s["ticker"]: s["metrics"] for s in states}
    assert by_ticker["BEST"]["magic_formula_rank"] == 1
    assert by_ticker["MIDDLE"]["magic_formula_rank"] == 2
    assert by_ticker["WORST"]["magic_formula_rank"] == 3


def test_combines_tradeoffs_between_the_two_factors():
    # A and B have the same combined rank (1+2 vs 2+1 = 3 each) despite
    # being strong in different factors - Greenblatt's whole point is that
    # summing the two ranks lets different strengths add up to the same
    # overall standing. C and D are unambiguously worse at both.
    states = [
        _state("A", roic_pct=40.0, earnings_yield_pct=10.0),  # roic rank 1, ey rank 2
        _state("B", roic_pct=30.0, earnings_yield_pct=12.0),  # roic rank 2, ey rank 1
        _state("C", roic_pct=20.0, earnings_yield_pct=8.0),  # roic rank 3, ey rank 3
        _state("D", roic_pct=10.0, earnings_yield_pct=4.0),  # roic rank 4, ey rank 4
    ]
    apply_magic_formula_rank(states)
    by_ticker = {s["ticker"]: s["metrics"] for s in states}

    a_combined = by_ticker["A"]["magic_formula_roic_rank"] + by_ticker["A"]["magic_formula_earnings_yield_rank"]
    b_combined = by_ticker["B"]["magic_formula_roic_rank"] + by_ticker["B"]["magic_formula_earnings_yield_rank"]
    assert a_combined == b_combined == 3

    assert by_ticker["A"]["magic_formula_rank"] in (1, 2)
    assert by_ticker["B"]["magic_formula_rank"] in (1, 2)
    assert by_ticker["C"]["magic_formula_rank"] == 3
    assert by_ticker["D"]["magic_formula_rank"] == 4


def test_missing_either_input_leaves_company_unranked():
    states = [
        _state("FULL", roic_pct=20.0, earnings_yield_pct=8.0),
        _state("MISSING_ROIC", roic_pct=None, earnings_yield_pct=8.0),
        _state("MISSING_YIELD", roic_pct=20.0, earnings_yield_pct=None),
    ]
    apply_magic_formula_rank(states)
    by_ticker = {s["ticker"]: s["metrics"] for s in states}
    assert by_ticker["FULL"]["magic_formula_rank"] == 1
    assert by_ticker["MISSING_ROIC"]["magic_formula_rank"] is None
    assert by_ticker["MISSING_YIELD"]["magic_formula_rank"] is None


def test_empty_watchlist_does_not_crash():
    states: list[dict] = []
    apply_magic_formula_rank(states)  # should not raise
    assert states == []
