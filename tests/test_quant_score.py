from pipeline.scoring.quant_score import build_quant_scorecard


def test_all_metrics_pass():
    metrics = {
        "roic_pct": 22.0,
        "fcf_margin_pct": 15.0,
        "revenue_cagr_5yr_pct": 8.0,
        "eps_growth_cagr_5yr_pct": 12.0,
        "debt_to_ebitda": 1.5,
    }
    result = build_quant_scorecard(metrics)
    assert result["evaluated"] == 5
    assert result["passed"] == 5
    assert result["quant_score_pct"] == 100.0
    assert result["gate_pass"] is True


def test_revenue_and_eps_cagr_fall_back_to_3yr_when_5yr_missing():
    metrics = {"revenue_cagr_3yr_pct": 6.0, "eps_growth_cagr_3yr_pct": 6.0}
    result = build_quant_scorecard(metrics)
    assert result["metrics"]["revenue_cagr_pct"]["value"] == 6.0
    assert result["metrics"]["eps_growth_cagr_pct"]["value"] == 6.0


def test_missing_metric_excluded_from_evaluated_not_counted_as_fail():
    metrics = {"roic_pct": 5.0}  # fails; everything else missing
    result = build_quant_scorecard(metrics)
    assert result["evaluated"] == 1
    assert result["passed"] == 0
    assert result["metrics"]["fcf_margin_pct"]["pass"] is None


def test_no_data_at_all_returns_none_gate():
    result = build_quant_scorecard({})
    assert result["evaluated"] == 0
    assert result["quant_score_pct"] is None
    assert result["gate_pass"] is None


def test_gate_fails_below_pass_fraction():
    # 1/5 passing = 20%, below the configured 60% gate_pass_fraction.
    metrics = {
        "roic_pct": 22.0,
        "fcf_margin_pct": 1.0,
        "revenue_cagr_5yr_pct": -5.0,
        "eps_growth_cagr_5yr_pct": -5.0,
        "debt_to_ebitda": 10.0,
    }
    result = build_quant_scorecard(metrics)
    assert result["passed"] == 1
    assert result["gate_pass"] is False


def test_informational_metrics_never_counted():
    metrics = {"insider_ownership_pct": 0.01, "margin_trend_score": 100}
    result = build_quant_scorecard(metrics)
    assert result["evaluated"] == 0
    assert result["informational"]["insider_ownership_pct"] == 0.01
