from pipeline.scoring.lynch_category import classify


def test_fast_grower():
    result = classify({"eps_growth_cagr_3yr_pct": 25.0}, "Technology", 500_000_000_000)
    assert result["category"] == "fast_grower"


def test_slow_grower_large_cap_low_growth():
    result = classify({"eps_growth_cagr_3yr_pct": 4.0}, "Consumer Defensive", 200_000_000_000)
    assert result["category"] == "slow_grower"


def test_stalwart_moderate_growth():
    result = classify({"eps_growth_cagr_3yr_pct": 12.0}, "Healthcare", 50_000_000_000)
    assert result["category"] == "stalwart"


def test_cyclical_sector_overrides_growth_rate():
    result = classify({"eps_growth_cagr_3yr_pct": 15.0}, "Energy", 80_000_000_000)
    assert result["category"] == "cyclical"


def test_turnaround_for_negative_growth():
    result = classify({"eps_growth_cagr_3yr_pct": -5.0}, "Technology", 10_000_000_000)
    assert result["category"] == "turnaround"


def test_asset_play_overrides_everything_else():
    # Even with fast-grower-level growth and a cyclical sector, an unusually
    # small NCAV discount takes priority - it's Lynch's point that the
    # balance sheet alone can make the stock interesting.
    result = classify({"eps_growth_cagr_3yr_pct": 30.0, "ncav_margin_pct": -2.0}, "Energy", 5_000_000_000)
    assert result["category"] == "asset_play"


def test_none_without_growth_data():
    result = classify({}, "Technology", 50_000_000_000)
    assert result["category"] is None


def test_small_cap_moderate_growth_is_stalwart_not_slow_grower():
    # slow_grower requires BOTH large market cap AND growth below 10% -
    # a small-cap with the same growth rate should land as stalwart instead.
    result = classify({"eps_growth_cagr_3yr_pct": 4.0}, "Consumer Defensive", 1_000_000_000)
    assert result["category"] == "stalwart"
