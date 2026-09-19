from pipeline.scoring.quant_score import build_quant_scorecard


def test_all_metrics_pass():
    metrics = {
        "current_ratio": 2.0,
        "debt_to_ebitda": 1.5,
        "fcf_margin_pct": 15.0,
    }
    result = build_quant_scorecard(metrics)
    assert result["evaluated"] == 3
    assert result["passed"] == 3
    assert result["quant_score_pct"] == 100.0
    assert result["gate_pass"] is True


def test_missing_metric_excluded_from_evaluated_not_counted_as_fail():
    metrics = {"debt_to_ebitda": 10.0}  # fails; everything else missing
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
    # 1/3 passing = 33%, below the configured 60% gate_pass_fraction.
    metrics = {
        "current_ratio": 0.5,
        "debt_to_ebitda": 1.5,
        "fcf_margin_pct": 1.0,
    }
    result = build_quant_scorecard(metrics)
    assert result["passed"] == 1
    assert result["gate_pass"] is False


def test_gate_passes_at_two_of_three():
    metrics = {
        "current_ratio": 2.0,
        "debt_to_ebitda": 1.5,
        "fcf_margin_pct": 1.0,  # fails
    }
    result = build_quant_scorecard(metrics)
    assert result["passed"] == 2
    assert result["gate_pass"] is True


def test_informational_metrics_never_counted():
    metrics = {"margin_trend_score": 100}
    result = build_quant_scorecard(metrics)
    assert result["evaluated"] == 0
    assert result["informational"]["margin_trend_score"] == 100
