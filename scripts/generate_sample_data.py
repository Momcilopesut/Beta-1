"""Generates synthetic seed data under data/ so the static site is browsable
before the real pipeline has ever run against live API keys.

Deterministic (fixed seed), and every generated file is clearly marked as
sample data (see meta.json's "note" field and each company's "_errors").
This is NOT a substitute for a real pipeline run - it exists purely so
`site/` has something realistic to render on day one. The first real
`python -m pipeline.main` run overwrites all of this.

Usage: python scripts/generate_sample_data.py
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.build import writer  # noqa: E402
from pipeline.narrative.prompts import DISCLAIMER  # noqa: E402
from pipeline.scoring import (  # noqa: E402
    aggregation,
    long_term,
    lynch_category,
    macro_regime,
    quant_score,
    short_term,
    valuation,
    value_investing,
)
from pipeline.utils.config import macro_series, watchlist  # noqa: E402
from pipeline.utils.paths import DATA_DIR  # noqa: E402

random.seed(42)

METRIC_RANGES = {
    "return_1m_pct": (-15, 15),
    "return_3m_pct": (-25, 25),
    "price_vs_ma50_pct": (-12, 12),
    "price_vs_ma200_pct": (-18, 18),
    "rsi_distance_from_neutral": (0, 35),
    "earnings_surprise_pct": (-8, 8),
    "dcf_upside_pct": (-30, 30),
    "pe_ttm": (9, 45),
    "pb_ratio": (0.8, 8),
    "ev_ebitda": (6, 28),
    "revenue_growth_yoy_pct": (-8, 28),
    "revenue_cagr_3yr_pct": (-5, 22),
    "revenue_cagr_5yr_pct": (-5, 20),
    "eps_growth_yoy_pct": (-12, 32),
    "eps_growth_cagr_3yr_pct": (-8, 25),
    "eps_growth_cagr_5yr_pct": (-8, 22),
    "gross_margin_pct": (18, 65),
    "roe_pct": (-5, 35),
    "roic_pct": (-2, 22),
    "debt_to_equity": (0, 2.2),
    "debt_to_ebitda": (0, 4.5),
    "earnings_yield_pct": (2, 12),
    "peg_ratio": (0.5, 3.5),
    "r_and_d_to_revenue_pct": (0, 22),
    "current_ratio": (0.4, 2.8),
    "interest_coverage": (1, 22),
    "fcf_margin_pct": (-5, 32),
    "fcf_to_net_income": (0.3, 1.6),
    "owner_earnings_yield_pct": (-1, 9),
    "graham_upside_pct": (-45, 45),
    "graham_multiple": (8, 40),
    "ncav_margin_pct": (-95, -20),  # almost always sharply negative for a going-concern large-cap; see scoring_weights.yaml
    "volume_vs_avg_ratio": (0.5, 2.2),
}
MARGIN_TREND_LABEL = {20: "declining", 60: "stable", 100: "improving"}

MACRO_BASE_VALUES = {
    "DGS1MO": 4.30,
    "DGS3MO": 4.25,
    "DGS2": 3.85,
    "DGS10": 4.10,
    "DGS30": 4.35,
    "T10Y2Y": 0.25,
    "CPIAUCSL": 322.0,
    "UNRATE": 4.1,
    "FEDFUNDS": 4.25,
    "GDPC1": 23500.0,
}


def synth_metrics() -> dict:
    metrics = {k: round(random.uniform(*bounds), 2) for k, bounds in METRIC_RANGES.items()}
    metrics["margin_trend_score"] = random.choice([20, 60, 100])
    return metrics


def synth_raw_statements(market_cap: float, close_price: float) -> dict:
    """Two years of plausible annual statements, for the value-investing
    checklist (needs year-over-year comparisons) and the DCF (needs a real
    FCF dollar figure). Scaled off market_cap/close_price - a large-cap's
    revenue should be the same order of magnitude as its market cap, and
    its share count should roughly match market_cap/close_price - so the
    DCF's per-share intrinsic value lands somewhere plausible instead of a
    unit mismatch collapsing it to ~$0."""
    shares0 = market_cap / close_price
    revenue0 = market_cap * random.uniform(0.3, 1.2)  # plausible P/S range
    revenue1 = revenue0 / (1 + random.uniform(-0.05, 0.2))
    gm0, gm1 = random.uniform(0.25, 0.55), random.uniform(0.22, 0.52)
    assets0 = revenue0 * random.uniform(1.2, 2.5)
    assets1 = revenue1 * random.uniform(1.2, 2.5)
    net_income0 = revenue0 * random.uniform(0.05, 0.22)
    net_income1 = revenue1 * random.uniform(0.03, 0.20)

    income_stmts = [
        {
            "revenue": revenue0,
            "grossProfit": revenue0 * gm0,
            "netIncome": net_income0,
            "epsdiluted": round(net_income0 / shares0, 2),
            "operatingIncome": revenue0 * random.uniform(0.1, 0.3),
            "incomeBeforeTax": net_income0 * 1.25,
            "incomeTaxExpense": net_income0 * 0.25,
            "weightedAverageShsOutDil": shares0,
        },
        {
            "revenue": revenue1,
            "grossProfit": revenue1 * gm1,
            "netIncome": net_income1,
            "epsdiluted": round(net_income1 / shares0, 2),
            "operatingIncome": revenue1 * random.uniform(0.08, 0.28),
            "incomeBeforeTax": net_income1 * 1.25,
            "incomeTaxExpense": net_income1 * 0.25,
            "weightedAverageShsOutDil": shares0,
        },
    ]
    balance_stmts = [
        {
            "totalAssets": assets0,
            "totalDebt": assets0 * random.uniform(0.1, 0.4),
            "totalCurrentAssets": assets0 * random.uniform(0.3, 0.5),
            "totalCurrentLiabilities": assets0 * random.uniform(0.15, 0.3),
            "totalLiabilities": assets0 * random.uniform(0.35, 0.65),
            "totalStockholdersEquity": assets0 * random.uniform(0.35, 0.65),
            "cashAndCashEquivalents": assets0 * random.uniform(0.05, 0.2),
        },
        {
            "totalAssets": assets1,
            "totalDebt": assets1 * random.uniform(0.1, 0.45),
            "totalCurrentAssets": assets1 * random.uniform(0.28, 0.48),
            "totalCurrentLiabilities": assets1 * random.uniform(0.15, 0.3),
            "totalLiabilities": assets1 * random.uniform(0.35, 0.65),
            "totalStockholdersEquity": assets1 * random.uniform(0.35, 0.65),
            "cashAndCashEquivalents": assets1 * random.uniform(0.05, 0.2),
        },
    ]
    cashflow_stmts = [
        {
            "operatingCashFlow": net_income0 * random.uniform(0.9, 1.4),
            "dividendsPaid": -abs(net_income0 * random.uniform(0, 0.4)),
            "depreciationAndAmortization": revenue0 * random.uniform(0.02, 0.06),
            "capitalExpenditure": -revenue0 * random.uniform(0.03, 0.08),
        },
        {
            "operatingCashFlow": net_income1 * random.uniform(0.8, 1.3),
            "dividendsPaid": -abs(net_income1 * random.uniform(0, 0.4)),
            "depreciationAndAmortization": revenue1 * random.uniform(0.02, 0.06),
            "capitalExpenditure": -revenue1 * random.uniform(0.03, 0.08),
        },
    ]
    return {"income_stmts": income_stmts, "balance_stmts": balance_stmts, "cashflow_stmts": cashflow_stmts}


def to_display(metrics: dict, close_price: float) -> dict:
    return {
        "price": {
            "close": close_price,
            "as_of": "2026-09-12",
            "return_1m_pct": metrics["return_1m_pct"],
            "return_3m_pct": metrics["return_3m_pct"],
            "volume_vs_avg_ratio": metrics["volume_vs_avg_ratio"],
        },
        "fundamentals": {
            "valuation": {
                "pe_ttm": metrics["pe_ttm"],
                "pb_ratio": metrics["pb_ratio"],
                "ev_ebitda": metrics["ev_ebitda"],
                "dcf_fair_value": round(close_price * (1 + metrics["dcf_upside_pct"] / 100), 2),
                "dcf_upside_pct": metrics["dcf_upside_pct"],
                "graham_upside_pct": metrics["graham_upside_pct"],
                "graham_multiple": metrics["graham_multiple"],
                "ncav_margin_pct": metrics["ncav_margin_pct"],
            },
            "growth": {
                "revenue_growth_yoy_pct": metrics["revenue_growth_yoy_pct"],
                "revenue_cagr_3yr_pct": metrics["revenue_cagr_3yr_pct"],
                "eps_growth_yoy_pct": metrics["eps_growth_yoy_pct"],
                "eps_growth_cagr_3yr_pct": metrics["eps_growth_cagr_3yr_pct"],
            },
            "profitability": {
                "gross_margin_pct": metrics["gross_margin_pct"],
                "roe_pct": metrics["roe_pct"],
                "roic_pct": metrics["roic_pct"],
                "trend": MARGIN_TREND_LABEL[metrics["margin_trend_score"]],
            },
            "balance_sheet": {
                "debt_to_equity": metrics["debt_to_equity"],
                "current_ratio": metrics["current_ratio"],
                "interest_coverage": metrics["interest_coverage"],
            },
            "cash_flow": {
                "fcf_margin_pct": metrics["fcf_margin_pct"],
                "fcf_to_net_income": metrics["fcf_to_net_income"],
                "owner_earnings_yield_pct": metrics["owner_earnings_yield_pct"],
            },
        },
    }


def synth_narrative(name: str, short: dict, long_: dict, metrics: dict, checklist: dict) -> dict:
    def fact(text, tier, metric):
        return {"text": text, "tier": tier, "source_metric": metric, "source_value": str(metrics[metric])}

    facts = {
        "critical": [
            fact(
                f"Modeled fair value implies a {metrics['dcf_upside_pct']:+.1f}% gap to the current price.",
                "critical",
                "dcf_upside_pct",
            )
        ],
        "important": [
            fact(
                f"Revenue grew {metrics['revenue_growth_yoy_pct']:+.1f}% year over year.",
                "important",
                "revenue_growth_yoy_pct",
            ),
            fact(f"Return on invested capital stands at {metrics['roic_pct']:.1f}%.", "important", "roic_pct"),
            fact(
                f"Passes {metrics['graham_criteria_passed']}/{metrics['graham_criteria_evaluated']} evaluated "
                "Graham defensive-investor criteria.",
                "important",
                "graham_criteria_passed",
            ),
        ],
        "minor": [fact(f"Current ratio is {metrics['current_ratio']:.2f}.", "minor", "current_ratio")],
        "noise": [
            fact(
                f"14-day RSI sits {metrics['rsi_distance_from_neutral']:.0f} points from neutral.",
                "noise",
                "rsi_distance_from_neutral",
            )
        ],
    }
    summary = f"{name}: {short['verdict']} short-term, {long_['verdict']} long-term outlook on current fundamentals."
    return {
        "one_line_summary": summary[:140],
        "short_term_narrative": (
            f"Short-term positioning is {short['verdict'].lower()}, with momentum and technicals contributing "
            f"a base score of {short['base_score']:.0f} before a {short['macro_adjustment']:+d}-point macro adjustment."
        ),
        "long_term_narrative": (
            f"Longer-term fundamentals point to a {long_['verdict'].lower()} outlook, with a base score of "
            f"{long_['base_score']:.0f} driven by growth, margins, ROIC, and balance-sheet health. Piotroski "
            f"F-Score: {checklist['piotroski_f_score']['score']}/{checklist['piotroski_f_score']['evaluated']} "
            "evaluated criteria."
        ),
        "facts": facts,
        "disclaimer": DISCLAIMER,
    }


_SAMPLE_MOAT_TYPES = ["network_effects", "cost_advantage", "intangible_assets", "switching_costs", "efficient_scale"]


def synth_qualitative_and_thesis(name: str, quant_scorecard: dict, valuation_out: dict) -> tuple[dict | None, dict | None]:
    """Only synthesized when the quant gate passes, matching the real
    pipeline's cost-gated behavior (pipeline/main.py's
    _run_qualitative_and_thesis) - this is placeholder text, clearly
    labeled, not a real reading of any filing."""
    if not quant_scorecard.get("gate_pass"):
        return None, None

    moat_present = random.random() < 0.7
    moat_type = random.choice(_SAMPLE_MOAT_TYPES) if moat_present else "none"
    qualitative = {
        "moat_present": moat_present,
        "moat_type": moat_type,
        "moat_explanation": (
            f"[Sample data] Placeholder moat read for {name} - a real run reads this company's actual 10-K."
        ),
        "management_assessment": "[Sample data] Placeholder capital-allocation read - a real run reads this company's actual 10-K.",
        "red_flags": ["[Sample data] Placeholder red flag."] if random.random() < 0.3 else [],
        "fisher_checklist": [
            {
                "criterion": "Sufficient market potential for years of growth",
                "assessment": random.choice(["yes", "no", "unknown"]),
                "evidence": "[Sample data] Placeholder evidence - a real run cites this company's actual 10-K text.",
            },
            {
                "criterion": "Management talks candidly about problems, not just successes",
                "assessment": random.choice(["yes", "no", "unknown"]),
                "evidence": "[Sample data] Placeholder evidence - a real run cites this company's actual 10-K text.",
            },
        ],
        "extraction_confidence": "section_match",
    }
    margin = valuation_out.get("margin_of_safety_pct")
    margin_text = f"{margin:+.0f}% margin of safety" if margin is not None else "an unevaluated margin of safety"
    thesis = {
        "thesis": (
            f"[Sample data] Placeholder thesis for {name}, combining the quant screen, this placeholder "
            f"moat read, and a valuation showing {margin_text} by this pipeline's DCF - "
            "a real run generates this from the actual company data."
        ),
        "falsification_criteria": [
            "[Sample data] Placeholder falsification criterion A.",
            "[Sample data] Placeholder falsification criterion B.",
        ],
    }
    return qualitative, thesis


def synth_macro_data() -> dict:
    end_date = datetime(2026, 9, 12, tzinfo=timezone.utc)
    out = {}
    for series_id, base in MACRO_BASE_VALUES.items():
        history = []
        value = base * 0.97
        for i in range(15):
            value += random.uniform(-0.015, 0.02) * base
            date = (end_date - timedelta(weeks=(14 - i))).strftime("%Y-%m-%d")
            history.append({"date": date, "value": round(value, 3)})
        history[-1] = {"date": end_date.strftime("%Y-%m-%d"), "value": round(base, 3)}
        out[series_id] = history
    return out


def main() -> None:
    companies = watchlist()
    generated_at = writer.now_iso()

    macro_data = synth_macro_data()
    regime_info = macro_regime.classify_regime(macro_data)
    series_labels = {s["id"]: s["label"] for s in macro_series()["series"]}
    macro_doc = {
        "generated_at": generated_at,
        "regime": regime_info["regime"],
        "signals": regime_info["signals"],
        "cycle_context": macro_regime.cycle_context(regime_info["regime"]),
        "series": [
            {
                "series_id": sid,
                "label": series_labels.get(sid, sid),
                "latest_value": obs[-1]["value"],
                "as_of": obs[-1]["date"],
                "history": obs,
                "source_url": f"https://fred.stlouisfed.org/series/{sid}",
            }
            for sid, obs in macro_data.items()
        ],
    }
    writer.write_macro(DATA_DIR, macro_doc)

    # Phase 1: synthesize metrics + scores per company.
    states = []
    for company_cfg in companies:
        ticker = company_cfg["ticker"]
        sector = company_cfg["sector"]
        metrics = synth_metrics()
        market_cap = round(random.uniform(15_000_000_000, 900_000_000_000), 0)
        close_price = round(random.uniform(40, 550), 2)
        raw = synth_raw_statements(market_cap, close_price)

        checklist = value_investing.build_checklist(metrics, {"market_cap": market_cap}, raw)
        metrics["graham_criteria_passed"] = checklist["graham_defensive"]["passed"]
        metrics["graham_criteria_evaluated"] = checklist["graham_defensive"]["evaluated"]
        metrics["piotroski_f_score"] = checklist["piotroski_f_score"]["score"]
        metrics["piotroski_evaluated"] = checklist["piotroski_f_score"]["evaluated"]

        states.append(
            {
                "ticker": ticker,
                "name": company_cfg["name"],
                "sector": sector,
                "market_cap": market_cap,
                "metrics": metrics,
                "checklist": checklist,
                "raw": raw,
                "close_price": close_price,
            }
        )

    # Phase 2: sector-relative momentum + sector median multiples, same
    # logic as pipeline/main.py's apply_sector_relative_momentum/apply_sector_medians.
    by_sector: dict[str, list[float]] = {}
    by_sector_pe: dict[str, list[float]] = {}
    by_sector_ev: dict[str, list[float]] = {}
    for s in states:
        by_sector.setdefault(s["sector"], []).append(s["metrics"]["return_3m_pct"])
        by_sector_pe.setdefault(s["sector"], []).append(s["metrics"]["pe_ttm"])
        by_sector_ev.setdefault(s["sector"], []).append(s["metrics"]["ev_ebitda"])
    sector_avg = {sector: sum(vals) / len(vals) for sector, vals in by_sector.items()}

    def median(values):
        ordered = sorted(values)
        mid = len(ordered) // 2
        return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    for s in states:
        avg = sector_avg.get(s["sector"])
        s["metrics"]["sector_relative_momentum_pct"] = round(s["metrics"]["return_3m_pct"] - avg, 2) if avg is not None else None
        s["sector_medians"] = {
            "pe_ttm": median(by_sector_pe.get(s["sector"], [])),
            "ev_ebitda": median(by_sector_ev.get(s["sector"], [])),
        }

    # Greenblatt's Magic Formula rank, same logic as pipeline/main.py's apply_magic_formula_rank.
    roic_rank = {
        s["ticker"]: i + 1 for i, s in enumerate(sorted(states, key=lambda s: s["metrics"]["roic_pct"], reverse=True))
    }
    ey_rank = {
        s["ticker"]: i + 1
        for i, s in enumerate(sorted(states, key=lambda s: s["metrics"]["earnings_yield_pct"], reverse=True))
    }
    combined_rank = {t: roic_rank[t] + ey_rank[t] for t in roic_rank}
    overall_rank = {t: i + 1 for i, t in enumerate(sorted(combined_rank, key=lambda t: combined_rank[t]))}
    for s in states:
        s["metrics"]["magic_formula_rank"] = overall_rank.get(s["ticker"])
        s["metrics"]["magic_formula_roic_rank"] = roic_rank.get(s["ticker"])
        s["metrics"]["magic_formula_earnings_yield_rank"] = ey_rank.get(s["ticker"])

    # Phase 3: score + narrative + write.
    summaries = []
    for s in states:
        macro_adj = macro_regime.sector_adjustment(regime_info["regime"], s["sector"])
        short = short_term.score(s["metrics"], macro_adj["short"])
        long_ = long_term.score(s["metrics"], macro_adj["long"])
        narrative = synth_narrative(s["name"], short, long_, s["metrics"], s["checklist"])
        display = to_display(s["metrics"], s["close_price"])
        display["price"]["sector_relative_momentum_pct"] = s["metrics"]["sector_relative_momentum_pct"]

        quant_scorecard = quant_score.build_quant_scorecard(s["metrics"])
        lynch = lynch_category.classify(s["metrics"], s["sector"], s["market_cap"])
        shares_outstanding = s["market_cap"] / s["close_price"]
        valuation_out = valuation.build_valuation(
            s["metrics"], s["raw"], shares_outstanding, s["close_price"], s["sector_medians"]
        )
        qualitative_out, thesis_out = synth_qualitative_and_thesis(s["name"], quant_scorecard, valuation_out)
        layered_analysis = aggregation.build_layered_analysis(quant_scorecard, qualitative_out, valuation_out)

        company_doc = {
            "ticker": s["ticker"],
            "name": s["name"],
            "cik": None,
            "sector": s["sector"],
            "industry": None,
            "market_cap": s["market_cap"],
            "last_updated": generated_at,
            "price": display["price"],
            "metrics": s["metrics"],
            "scores": {"short_term": short, "long_term": long_},
            "macro_context": {
                "regime": regime_info["regime"],
                "sector_sensitivity": {
                    "rate_sensitivity": macro_adj["rate_sensitivity"],
                    "cyclicality": macro_adj["cyclicality"],
                },
            },
            "fundamentals": display["fundamentals"],
            "value_investing": s["checklist"],
            "narrative": narrative,
            "lynch_category": lynch,
            "quant_score": quant_scorecard,
            "qualitative": qualitative_out,
            "valuation": valuation_out,
            "thesis": thesis_out,
            "layered_analysis": layered_analysis,
            "sources": {"sec_filings": [], "sec_companyfacts_url": None},
            "_errors": {
                "_sample_data": "Synthetic demo data from scripts/generate_sample_data.py, not a real fetch."
            },
        }
        writer.write_company(DATA_DIR, s["ticker"], company_doc)

        summaries.append(
            {
                "ticker": s["ticker"],
                "name": s["name"],
                "sector": s["sector"],
                "short_term_score": short["final_score"],
                "short_term_verdict": short["verdict"],
                "long_term_score": long_["final_score"],
                "long_term_verdict": long_["verdict"],
                "one_line_summary": narrative["one_line_summary"],
                "graham_criteria_passed": s["checklist"]["graham_defensive"]["passed"],
                "graham_criteria_total": s["checklist"]["graham_defensive"]["total"],
                "piotroski_f_score": s["checklist"]["piotroski_f_score"]["score"],
                "quant_gate_pass": layered_analysis["quant_gate_pass"],
                "qualitative_moat_present": layered_analysis["qualitative_moat_present"],
                "valuation_gate_pass": layered_analysis["valuation_gate_pass"],
                "last_updated": generated_at,
            }
        )

    writer.write_watchlist(DATA_DIR, summaries, generated_at)
    writer.write_meta(
        DATA_DIR,
        {
            "generated_at": generated_at,
            "pipeline_version": "sample-data",
            "watchlist_size": len(companies),
            "sources_status": {"fmp": "sample", "sec_edgar": "sample", "fred": "sample", "anthropic": "sample"},
            "narrative_warnings": 0,
            "note": (
                "Placeholder demo data for local preview only. Run `python -m pipeline.main` "
                "with real API keys configured to replace it with live data."
            ),
        },
    )
    print(f"Wrote sample data for {len(companies)} companies to {DATA_DIR}")


if __name__ == "__main__":
    main()
