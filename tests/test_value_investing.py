from pipeline.scoring.value_investing import build_checklist, graham_defensive_checklist, piotroski_f_score


def _piotroski_raw_all_improving():
    return {
        "income_stmts": [
            {"netIncome": 100, "revenue": 900, "grossProfit": 450, "weightedAverageShsOutDil": 100},
            {"netIncome": 80, "revenue": 800, "grossProfit": 360, "weightedAverageShsOutDil": 100},
        ],
        "balance_stmts": [
            {"totalAssets": 1000, "totalDebt": 200, "totalCurrentAssets": 400, "totalCurrentLiabilities": 200},
            {"totalAssets": 900, "totalDebt": 250, "totalCurrentAssets": 300, "totalCurrentLiabilities": 200},
        ],
        "cashflow_stmts": [{"operatingCashFlow": 120}, {"operatingCashFlow": 70}],
    }


def test_piotroski_all_nine_criteria_pass():
    result = piotroski_f_score(_piotroski_raw_all_improving())
    assert result["score"] == 9
    assert result["evaluated"] == 9
    assert result["max"] == 9
    assert all(c["passed"] is True for c in result["criteria"])


def test_piotroski_deteriorating_company_fails_most_criteria():
    raw = {
        "income_stmts": [
            {"netIncome": -10, "revenue": 700, "grossProfit": 280, "weightedAverageShsOutDil": 120},
            {"netIncome": 50, "revenue": 800, "grossProfit": 360, "weightedAverageShsOutDil": 100},
        ],
        "balance_stmts": [
            {"totalAssets": 1000, "totalDebt": 400, "totalCurrentAssets": 250, "totalCurrentLiabilities": 200},
            {"totalAssets": 900, "totalDebt": 200, "totalCurrentAssets": 300, "totalCurrentLiabilities": 200},
        ],
        "cashflow_stmts": [{"operatingCashFlow": -5}, {"operatingCashFlow": 60}],
    }
    result = piotroski_f_score(raw)
    # Only "operating cash flow exceeds net income" passes here (-5 > -10) -
    # correct per Piotroski's literal accrual-quality definition even though
    # both figures are negative; every other criterion fails.
    assert result["score"] == 1
    assert result["evaluated"] == 9


def test_piotroski_insufficient_history_reports_zero_max():
    result = piotroski_f_score({"income_stmts": [{"netIncome": 100}], "balance_stmts": [], "cashflow_stmts": []})
    assert result["score"] == 0
    assert result["evaluated"] == 0
    assert "note" in result


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
        {"current_ratio": 2.5, "pe_ttm": 12, "graham_multiple": 15, "eps_growth_cagr_3yr_pct": 5},
        {"market_cap": 5_000_000_000},
        _piotroski_raw_all_improving(),
    )
    assert "graham_defensive" in checklist
    assert "piotroski_f_score" in checklist
