"""Tests for pipeline.scoring.plain_analysis - the plain-language positives/
worries summary that replaced the old Layered Analysis section. Every check
is independent, so each is tested in isolation (a metrics dict with only
that one field set) plus a couple of combined "healthy company" /
"struggling company" cases to prove they compose correctly."""

from pipeline.scoring.plain_analysis import build_plain_analysis


def test_empty_metrics_produce_no_positives_or_worries():
    result = build_plain_analysis({})
    assert result == {"positives": [], "worries": []}


def test_positive_net_worth_is_a_positive():
    result = build_plain_analysis({"shareholders_equity": 1.0})
    assert len(result["positives"]) == 1
    assert "left over" in result["positives"][0]
    assert result["worries"] == []


def test_negative_net_worth_is_a_worry():
    result = build_plain_analysis({"shareholders_equity": -1.0})
    assert result["positives"] == []
    assert len(result["worries"]) == 1
    assert "nothing left over" in result["worries"][0]


def test_low_debt_is_a_positive():
    result = build_plain_analysis({"debt_to_equity": 0.5})
    assert len(result["positives"]) == 1
    assert result["worries"] == []


def test_high_debt_is_a_worry():
    result = build_plain_analysis({"debt_to_equity": 2.5})
    assert result["positives"] == []
    assert len(result["worries"]) == 1


def test_mid_range_debt_is_neither():
    # Above the 1.0 "good" bar but not above the 2.0 "worry" bar - a
    # genuinely in-between reading shouldn't be forced into either list.
    result = build_plain_analysis({"debt_to_equity": 1.5})
    assert result == {"positives": [], "worries": []}


def test_strong_current_ratio_is_a_positive():
    result = build_plain_analysis({"current_ratio": 3.0})
    assert len(result["positives"]) == 1


def test_weak_current_ratio_is_a_worry():
    result = build_plain_analysis({"current_ratio": 0.5})
    assert len(result["worries"]) == 1


def test_strong_roic_is_a_positive():
    result = build_plain_analysis({"roic_pct": 20.0})
    assert len(result["positives"]) == 1


def test_negative_roic_is_a_worry():
    result = build_plain_analysis({"roic_pct": -5.0})
    assert len(result["worries"]) == 1


def test_high_gross_margin_is_a_positive():
    result = build_plain_analysis({"gross_margin_pct": 55.0})
    assert len(result["positives"]) == 1


def test_low_gross_margin_is_a_worry():
    result = build_plain_analysis({"gross_margin_pct": 8.0})
    assert len(result["worries"]) == 1


def test_strong_eps_growth_is_a_positive():
    result = build_plain_analysis({"eps_growth_cagr_3yr_pct": 15.0})
    assert len(result["positives"]) == 1


def test_shrinking_eps_is_a_worry():
    result = build_plain_analysis({"eps_growth_cagr_3yr_pct": -3.0})
    assert len(result["worries"]) == 1


def test_strong_fcf_margin_is_a_positive():
    result = build_plain_analysis({"fcf_margin_pct": 20.0})
    assert len(result["positives"]) == 1


def test_negative_fcf_margin_is_a_worry():
    result = build_plain_analysis({"fcf_margin_pct": -4.0})
    assert len(result["worries"]) == 1


def test_improving_margin_trend_is_a_positive():
    result = build_plain_analysis({"margin_trend_score": 100})
    assert len(result["positives"]) == 1


def test_declining_margin_trend_is_a_worry():
    result = build_plain_analysis({"margin_trend_score": 20})
    assert len(result["worries"]) == 1


def test_stable_margin_trend_is_neither():
    result = build_plain_analysis({"margin_trend_score": 60})
    assert result == {"positives": [], "worries": []}


def test_real_margin_of_safety_is_a_positive():
    result = build_plain_analysis({"graham_upside_pct": 25.0})
    assert len(result["positives"]) == 1


def test_overpriced_stock_is_a_worry():
    result = build_plain_analysis({"graham_upside_pct": -20.0})
    assert len(result["worries"]) == 1


def test_healthy_company_across_every_metric_produces_nine_positives_and_no_worries():
    metrics = {
        "shareholders_equity": 500_000_000,
        "debt_to_equity": 0.4,
        "current_ratio": 2.5,
        "roic_pct": 18.0,
        "gross_margin_pct": 50.0,
        "eps_growth_cagr_3yr_pct": 12.0,
        "fcf_margin_pct": 22.0,
        "margin_trend_score": 100,
        "graham_upside_pct": 30.0,
    }
    result = build_plain_analysis(metrics)
    assert len(result["positives"]) == 9
    assert result["worries"] == []


def test_struggling_company_across_every_metric_produces_nine_worries_and_no_positives():
    metrics = {
        "shareholders_equity": -50_000_000,
        "debt_to_equity": 3.0,
        "current_ratio": 0.6,
        "roic_pct": -8.0,
        "gross_margin_pct": 5.0,
        "eps_growth_cagr_3yr_pct": -15.0,
        "fcf_margin_pct": -10.0,
        "margin_trend_score": 20,
        "graham_upside_pct": -35.0,
    }
    result = build_plain_analysis(metrics)
    assert result["positives"] == []
    assert len(result["worries"]) == 9


def test_sentences_are_plain_english_not_metric_jargon():
    # Loose smoke test for the "no fancy jargon" requirement - the raw
    # metric keys/acronyms this pipeline uses internally (ROIC, P/E, EPS
    # growth CAGR, gross margin, current ratio, debt/equity) should never
    # leak into the generated sentences themselves. \b word-boundary regex
    # so a short term like "EPS" doesn't false-positive on "keEPS".
    import re

    metrics = {
        "shareholders_equity": 1.0,
        "debt_to_equity": 0.5,
        "current_ratio": 2.5,
        "roic_pct": 20.0,
        "gross_margin_pct": 50.0,
        "eps_growth_cagr_3yr_pct": 12.0,
        "fcf_margin_pct": 20.0,
        "margin_trend_score": 100,
        "graham_upside_pct": 25.0,
    }
    result = build_plain_analysis(metrics)
    banned_terms = ["ROIC", "P/E", "CAGR", "EPS", "gross margin", "current ratio", "debt/equity", "debt-to-equity"]
    for sentence in result["positives"] + result["worries"]:
        for term in banned_terms:
            pattern = r"\b" + re.escape(term.lower()) + r"\b"
            assert not re.search(pattern, sentence.lower()), f"'{term}' leaked into: {sentence}"
