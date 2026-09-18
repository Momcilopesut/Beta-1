from pipeline.scoring.valuation import build_dcf, build_relative_multiples, build_valuation


def test_dcf_computes_intrinsic_value_from_base_fcf_and_growth():
    metrics = {"revenue_cagr_5yr_pct": 8.0}
    raw = {"cashflow_stmts": [{"operatingCashFlow": 100_000_000_000, "capitalExpenditure": -20_000_000_000}]}
    result = build_dcf(metrics, raw, shares_outstanding=15_000_000_000, price=190.0)

    assert result["assumptions"]["base_fcf"] == 80_000_000_000
    assert result["assumptions"]["growth_rate_source"] == "trailing_5yr_revenue_cagr"
    assert result["intrinsic_value_per_share"] > 0
    assert result["margin_of_safety_pct"] == (
        (result["intrinsic_value_per_share"] - 190.0) / 190.0 * 100
    )


def test_dcf_growth_rate_clamped_to_sane_range():
    metrics = {"revenue_cagr_5yr_pct": 500.0}  # an outlier year shouldn't extrapolate forever
    raw = {"cashflow_stmts": [{"operatingCashFlow": 10_000_000, "capitalExpenditure": -1_000_000}]}
    result = build_dcf(metrics, raw, shares_outstanding=1_000_000, price=50.0)
    assert result["assumptions"]["growth_rate_pct"] == 20.0  # upper clamp


def test_dcf_falls_back_to_default_growth_when_no_history():
    raw = {"cashflow_stmts": [{"operatingCashFlow": 10_000_000, "capitalExpenditure": -1_000_000}]}
    result = build_dcf({}, raw, shares_outstanding=1_000_000, price=50.0)
    assert result["assumptions"]["growth_rate_source"] == "default_conservative"
    assert result["assumptions"]["growth_rate_pct"] == 3.0


def test_dcf_none_when_fcf_unavailable():
    result = build_dcf({}, {"cashflow_stmts": []}, shares_outstanding=1_000_000, price=50.0)
    assert result["intrinsic_value_per_share"] is None
    assert result["margin_of_safety_pct"] is None


def test_dcf_none_when_price_or_shares_missing():
    raw = {"cashflow_stmts": [{"operatingCashFlow": 10_000_000, "capitalExpenditure": -1_000_000}]}
    assert build_dcf({}, raw, shares_outstanding=None, price=50.0)["intrinsic_value_per_share"] is None
    assert build_dcf({}, raw, shares_outstanding=1_000_000, price=None)["intrinsic_value_per_share"] is None


def test_relative_multiples_computed_against_sector_median():
    metrics = {"pe_ttm": 20.0, "ev_ebitda": 14.0}
    result = build_relative_multiples(metrics, {"pe_ttm": 22.0, "ev_ebitda": 15.0})
    assert result["pe_vs_sector_median_pct"] < 0
    assert result["ev_ebitda_vs_sector_median_pct"] < 0


def test_relative_multiples_none_without_sector_data():
    result = build_relative_multiples({"pe_ttm": 20.0}, None)
    assert result["sector_median_pe_ttm"] is None
    assert result["pe_vs_sector_median_pct"] is None


def test_build_valuation_combines_dcf_and_relative():
    metrics = {"revenue_cagr_5yr_pct": 8.0, "pe_ttm": 20.0, "ev_ebitda": 14.0}
    raw = {"cashflow_stmts": [{"operatingCashFlow": 100_000_000_000, "capitalExpenditure": -20_000_000_000}]}
    result = build_valuation(metrics, raw, 15_000_000_000, 190.0, {"pe_ttm": 22.0, "ev_ebitda": 15.0})
    assert result["margin_of_safety_pct"] == result["dcf"]["margin_of_safety_pct"]
    assert result["relative"]["sector_median_pe_ttm"] == 22.0
