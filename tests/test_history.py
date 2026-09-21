import pytest

from pipeline.scoring.history import build_five_year_history


def _income_row(d, net_income, **spending_fields):
    return {"date": d, "netIncome": net_income, **spending_fields}


def _balance_row(d, cash, debt):
    return {"date": d, "cashAndCashEquivalents": cash, "totalDebt": debt}


def _price_row(d, close):
    return {"date": d, "close": close}


# 5 annual statements, most-recent-first (FMP convention) - exactly enough
# for 5 years shown but only 4 of them get a year-over-year return (the
# oldest has no earlier statement to anchor against).
INCOME_STMTS = [
    _income_row("2025-12-31", 500, costAndExpenses=350),
    _income_row("2024-12-31", 400, costOfRevenue=200, operatingExpenses=80),
    _income_row("2023-12-31", 300),  # no spending fields at all
    _income_row("2022-12-31", 200, costAndExpenses=150),
    _income_row("2021-12-31", 100, costAndExpenses=90),
]
BALANCE_STMTS = [
    _balance_row("2025-12-31", 50, 5),
    _balance_row("2024-12-31", 40, 10),
    _balance_row("2023-12-31", 30, 15),
    _balance_row("2022-12-31", 20, 20),
    _balance_row("2021-12-31", 10, 25),
]
PRICE_ROWS = [
    _price_row("2025-12-31", 200),
    _price_row("2024-12-31", 150),
    _price_row("2023-12-31", 120),
    _price_row("2022-12-31", 100),
    _price_row("2021-12-31", 90),
]
BENCHMARK_ROWS = [
    _price_row("2025-12-31", 420),
    _price_row("2024-12-31", 400),
    _price_row("2023-12-31", 380),
    _price_row("2022-12-31", 360),
    _price_row("2021-12-31", 340),
]


def test_shape_and_oldest_first_order():
    result = build_five_year_history(INCOME_STMTS, BALANCE_STMTS, PRICE_ROWS, BENCHMARK_ROWS)
    years = result["years"]
    assert len(years) == 5
    assert [y["fiscal_year"] for y in years] == [
        "2021-12-31",
        "2022-12-31",
        "2023-12-31",
        "2024-12-31",
        "2025-12-31",
    ]
    assert years[-1]["earnings"] == 500
    assert years[-1]["cash"] == 50
    assert years[-1]["debt"] == 5


def test_return_pct_arithmetic():
    result = build_five_year_history(INCOME_STMTS, BALANCE_STMTS, PRICE_ROWS, BENCHMARK_ROWS)
    latest = result["years"][-1]  # 2025: stock 150->200, market 400->420
    assert latest["stock_return_pct"] == pytest.approx((200 - 150) / 150 * 100)
    assert latest["market_return_pct"] == pytest.approx((420 - 400) / 400 * 100)


def test_oldest_year_has_no_return_without_an_earlier_anchor():
    result = build_five_year_history(INCOME_STMTS, BALANCE_STMTS, PRICE_ROWS, BENCHMARK_ROWS)
    oldest = result["years"][0]  # 2021 - no statement before it in the fixture
    assert oldest["fiscal_year"] == "2021-12-31"
    assert oldest["stock_return_pct"] is None
    assert oldest["market_return_pct"] is None


def test_spending_uses_combined_field_then_falls_back_then_none():
    result = build_five_year_history(INCOME_STMTS, BALANCE_STMTS, PRICE_ROWS, BENCHMARK_ROWS)
    by_year = {y["fiscal_year"]: y for y in result["years"]}
    assert by_year["2025-12-31"]["spending"] == 350  # direct costAndExpenses
    assert by_year["2024-12-31"]["spending"] == 280  # costOfRevenue + operatingExpenses fallback
    assert by_year["2023-12-31"]["spending"] is None  # neither field present - not guessed as 0


def test_missing_price_near_a_fiscal_year_end_is_none_not_zero():
    # Drop the 2024 close entirely (and give it nothing within the +/-7-day
    # tolerance) - the 2024 and 2025 returns that depend on it must read as
    # None, not silently compute against some unrelated price.
    sparse_prices = [p for p in PRICE_ROWS if p["date"] != "2024-12-31"]
    result = build_five_year_history(INCOME_STMTS, BALANCE_STMTS, sparse_prices, BENCHMARK_ROWS)
    by_year = {y["fiscal_year"]: y for y in result["years"]}
    assert by_year["2025-12-31"]["stock_return_pct"] is None
    assert by_year["2024-12-31"]["stock_return_pct"] is None
    # Unaffected years still compute normally.
    assert by_year["2023-12-31"]["stock_return_pct"] is not None
    # Market return is independent of the stock's own price gap.
    assert by_year["2024-12-31"]["market_return_pct"] is not None


def test_caps_at_five_years_even_with_more_statements():
    six_income = INCOME_STMTS + [_income_row("2020-12-31", 50, costAndExpenses=45)]
    six_balance = BALANCE_STMTS + [_balance_row("2020-12-31", 5, 30)]
    six_prices = PRICE_ROWS + [_price_row("2020-12-31", 80)]
    six_benchmark = BENCHMARK_ROWS + [_price_row("2020-12-31", 320)]
    result = build_five_year_history(six_income, six_balance, six_prices, six_benchmark)
    assert len(result["years"]) == 5
    # The 6th (oldest) statement is used only as the 2021 return's anchor,
    # not surfaced as its own year.
    assert result["years"][0]["fiscal_year"] == "2021-12-31"
    assert result["years"][0]["stock_return_pct"] == pytest.approx((90 - 80) / 80 * 100)


@pytest.mark.parametrize(
    "income_stmts,balance_stmts",
    [
        ([], []),
        (INCOME_STMTS[:1], BALANCE_STMTS[:1]),
        (INCOME_STMTS, BALANCE_STMTS[:1]),
    ],
)
def test_returns_none_with_fewer_than_two_statements(income_stmts, balance_stmts):
    assert build_five_year_history(income_stmts, balance_stmts, PRICE_ROWS, BENCHMARK_ROWS) is None
