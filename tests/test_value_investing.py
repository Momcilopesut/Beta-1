from pipeline.scoring.value_investing import build_checklist, graham_defensive_checklist, munger_quality_checklist


def _munger_raw_no_dilution(revenue=1000, gross_profit=500):
    row = {"weightedAverageShsOutDil": 100, "revenue": revenue, "grossProfit": gross_profit}
    return {"income_stmts": [dict(row), dict(row)]}


def test_munger_quality_all_criteria_pass():
    metrics = {"roe_pct": 20.0, "debt_to_equity": 0.5, "margin_trend_score": 100}
    result = munger_quality_checklist(metrics, _munger_raw_no_dilution())
    assert result["passed"] == 4
    assert result["evaluated"] == 4
    assert result["total"] == 4
    assert all(c["passed"] is True for c in result["criteria"])


def test_munger_quality_weak_business_fails_most_criteria():
    metrics = {"roe_pct": 4.0, "debt_to_equity": 2.5, "margin_trend_score": 20}
    raw = {
        "income_stmts": [
            {"weightedAverageShsOutDil": 130, "revenue": 1000, "grossProfit": 400},  # diluted vs a year earlier
            {"weightedAverageShsOutDil": 100, "revenue": 900, "grossProfit": 450},
        ]
    }
    result = munger_quality_checklist(metrics, raw)
    assert result["passed"] == 0
    assert result["evaluated"] == 4


def test_munger_quality_missing_data_is_unevaluated_not_failed():
    result = munger_quality_checklist({}, {})
    assert result["evaluated"] == 0
    assert result["passed"] == 0
    assert all(c["passed"] is None for c in result["criteria"])


def test_munger_quality_dilution_check_needs_two_years():
    metrics = {"roe_pct": 20.0, "debt_to_equity": 0.5, "margin_trend_score": 100}
    result = munger_quality_checklist(metrics, {"income_stmts": [{"weightedAverageShsOutDil": 100}]})
    dilution_check = next(c for c in result["criteria"] if "diluting" in c["criterion"])
    assert dilution_check["passed"] is None
    # The other three still evaluate independently, though margin also needs
    # real revenue/grossProfit data this fixture doesn't provide.
    margin_check = next(c for c in result["criteria"] if "Margins" in c["criterion"])
    assert margin_check["passed"] is None
    assert result["evaluated"] == 2


def test_munger_quality_margin_check_ignores_the_default_stable_reading_when_theres_no_real_data():
    # pipeline.scoring.fundamentals._margin_trend defaults to "stable" (score
    # 60) when there's no real revenue/grossProfit history - metrics dict
    # here simulates that default, exactly as the real pipeline would
    # produce it even for a ticker with zero fetched statements. The margin
    # criterion must still read as unevaluated, not a false pass, since
    # there's no real data behind that default.
    metrics = {"roe_pct": 20.0, "debt_to_equity": 0.5, "margin_trend_score": 60}
    result = munger_quality_checklist(metrics, {"income_stmts": []})
    margin_check = next(c for c in result["criteria"] if "Margins" in c["criterion"])
    assert margin_check["passed"] is None


def test_graham_defensive_checklist_all_pass():
    metrics = {"current_ratio": 2.5, "pe_ttm": 12, "graham_multiple": 15, "eps_growth_cagr_3yr_pct": 5}
    profile = {"market_cap": 5_000_000_000}
    raw = {
        "income_stmts": [{"netIncome": 100}, {"netIncome": 90}, {"netIncome": 80}],
        "balance_stmts": [
            {"totalCurrentAssets": 500, "totalCurrentLiabilities": 200, "totalDebt": 100},
        ],
        "cashflow_stmts": [{"dividendsPaid": -50}],
    }
    result = graham_defensive_checklist(metrics, profile, raw)
    assert result["passed"] == 7
    assert result["evaluated"] == 7
    assert result["total"] == 7


def test_graham_defensive_checklist_fails_on_high_valuation():
    metrics = {"current_ratio": 2.5, "pe_ttm": 45, "graham_multiple": 40, "eps_growth_cagr_3yr_pct": 5}
    profile = {"market_cap": 5_000_000_000}
    raw = {
        "income_stmts": [{"netIncome": 100}],
        "balance_stmts": [{"totalCurrentAssets": 500, "totalCurrentLiabilities": 200, "totalDebt": 100}],
        "cashflow_stmts": [{"dividendsPaid": -50}],
    }
    result = graham_defensive_checklist(metrics, profile, raw)
    pe_check = next(c for c in result["criteria"] if "Moderate P/E (" in c["criterion"])
    combined_check = next(c for c in result["criteria"] if "P/E x P/B" in c["criterion"])
    assert pe_check["passed"] is False
    assert combined_check["passed"] is False


def test_graham_defensive_checklist_missing_data_is_unevaluated_not_failed():
    result = graham_defensive_checklist({}, {}, {})
    assert result["evaluated"] == 0
    assert result["passed"] == 0
    assert all(c["passed"] is None for c in result["criteria"])


def test_build_checklist_combines_both():
    checklist = build_checklist(
        {"current_ratio": 2.5, "pe_ttm": 12, "graham_multiple": 15, "eps_growth_cagr_3yr_pct": 5, "roe_pct": 20.0, "debt_to_equity": 0.5, "margin_trend_score": 100},
        {"market_cap": 5_000_000_000},
        _munger_raw_no_dilution(),
    )
    assert "graham_defensive" in checklist
    assert "munger_quality" in checklist
