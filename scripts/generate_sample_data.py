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
from pipeline.scoring import aggregation, macro_regime, quant_score, value_investing  # noqa: E402
from pipeline.utils.config import macro_series, watchlist  # noqa: E402
from pipeline.utils.paths import DATA_DIR  # noqa: E402

random.seed(42)

# Balance-sheet-first: only the metrics this pipeline actually scores on -
# see README's "Assets vs Liabilities" section for why the rest were cut.
METRIC_RANGES = {
    "pe_ttm": (9, 45),
    "pb_ratio": (0.8, 8),
    "graham_upside_pct": (-45, 45),
    "graham_multiple": (8, 40),
    "ncav_margin_pct": (-95, -20),  # almost always sharply negative for a going-concern large-cap
    "debt_to_equity": (0, 2.2),
    "debt_to_ebitda": (0, 4.5),
    "current_ratio": (0.4, 2.8),
    "fcf_margin_pct": (-5, 32),
    "eps_growth_cagr_3yr_pct": (-8, 25),
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
    checklist (needs year-over-year comparisons) and the balance-sheet-
    basics figures. Scaled off market_cap/close_price - a large-cap's
    revenue should be the same order of magnitude as its market cap, and
    its share count should roughly match market_cap/close_price."""
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
        },
        "fundamentals": {
            "balance_sheet_basics": {
                "total_assets": metrics["total_assets"],
                "total_liabilities": metrics["total_liabilities"],
                "shareholders_equity": metrics["shareholders_equity"],
                "book_value_per_share": metrics["book_value_per_share"],
            },
            "valuation": {
                "pe_ttm": metrics["pe_ttm"],
                "pb_ratio": metrics["pb_ratio"],
                "graham_number": round(close_price * (1 + metrics["graham_upside_pct"] / 100), 2),
                "graham_upside_pct": metrics["graham_upside_pct"],
                "graham_multiple": metrics["graham_multiple"],
                "ncav_margin_pct": metrics["ncav_margin_pct"],
            },
            "balance_sheet": {
                "debt_to_equity": metrics["debt_to_equity"],
                "debt_to_ebitda": metrics["debt_to_ebitda"],
                "current_ratio": metrics["current_ratio"],
            },
            "cash_flow": {
                "fcf_margin_pct": metrics["fcf_margin_pct"],
            },
            "growth": {
                "eps_growth_cagr_3yr_pct": metrics["eps_growth_cagr_3yr_pct"],
            },
            "profitability": {
                "trend": MARGIN_TREND_LABEL[metrics["margin_trend_score"]],
            },
        },
    }


def synth_narrative(name: str, metrics: dict, checklist: dict) -> dict:
    def fact(text, tier, metric):
        return {"text": text, "tier": tier, "source_metric": metric, "source_value": str(metrics[metric])}

    facts = {
        "critical": [
            fact(
                f"The Graham Number implies a {metrics['graham_upside_pct']:+.1f}% margin of safety.",
                "critical",
                "graham_upside_pct",
            )
        ],
        "important": [
            fact(
                f"Passes {metrics['graham_criteria_passed']}/{metrics['graham_criteria_evaluated']} evaluated "
                "Graham defensive-investor criteria.",
                "important",
                "graham_criteria_passed",
            ),
            fact(f"Current ratio is {metrics['current_ratio']:.2f}.", "important", "current_ratio"),
        ],
        "minor": [fact(f"Free cash flow margin is {metrics['fcf_margin_pct']:.1f}%.", "minor", "fcf_margin_pct")],
        "noise": [],
    }
    summary = f"{name}: net worth of {metrics['shareholders_equity']:,.0f}, trading at {metrics['pb_ratio']:.2f}x book value."
    return {
        "one_line_summary": summary[:140],
        "narrative": (
            f"{name} owns {metrics['total_assets']:,.0f} in assets against {metrics['total_liabilities']:,.0f} in "
            f"liabilities - a net worth of {metrics['shareholders_equity']:,.0f}. It passes "
            f"{metrics['graham_criteria_passed']}/{metrics['graham_criteria_evaluated']} evaluated Graham "
            f"defensive-investor criteria and scores {checklist['piotroski_f_score']['score']}/"
            f"{checklist['piotroski_f_score']['evaluated']} on the Piotroski F-Score."
        ),
        "facts": facts,
        "disclaimer": DISCLAIMER,
    }


_SAMPLE_MOAT_TYPES = ["network_effects", "cost_advantage", "intangible_assets", "switching_costs", "efficient_scale"]


def synth_qualitative(name: str, quant_scorecard: dict) -> dict | None:
    """Only synthesized when the quant gate passes, matching the real
    pipeline's cost-gated behavior (pipeline/main.py's _run_qualitative) -
    this is placeholder text, clearly labeled, not a real reading of any
    filing."""
    if not quant_scorecard.get("gate_pass"):
        return None

    moat_present = random.random() < 0.7
    moat_type = random.choice(_SAMPLE_MOAT_TYPES) if moat_present else "none"
    return {
        "moat_present": moat_present,
        "moat_type": moat_type,
        "moat_explanation": (
            f"[Sample data] Placeholder moat read for {name} - a real run reads this company's actual 10-K."
        ),
        "red_flags": ["[Sample data] Placeholder red flag."] if random.random() < 0.3 else [],
        "extraction_confidence": "section_match",
    }


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

    summaries = []
    for company_cfg in companies:
        ticker = company_cfg["ticker"]
        sector = company_cfg["sector"]
        metrics = synth_metrics()
        market_cap = round(random.uniform(15_000_000_000, 900_000_000_000), 0)
        close_price = round(random.uniform(40, 550), 2)
        raw = synth_raw_statements(market_cap, close_price)

        balance0 = raw["balance_stmts"][0]
        shares_outstanding = market_cap / close_price
        metrics["total_assets"] = round(balance0["totalAssets"], 0)
        metrics["total_liabilities"] = round(balance0["totalLiabilities"], 0)
        metrics["shareholders_equity"] = round(balance0["totalStockholdersEquity"], 0)
        metrics["book_value_per_share"] = round(balance0["totalStockholdersEquity"] / shares_outstanding, 2)

        checklist = value_investing.build_checklist(metrics, {"market_cap": market_cap}, raw)
        metrics["graham_criteria_passed"] = checklist["graham_defensive"]["passed"]
        metrics["graham_criteria_evaluated"] = checklist["graham_defensive"]["evaluated"]
        metrics["piotroski_f_score"] = checklist["piotroski_f_score"]["score"]
        metrics["piotroski_evaluated"] = checklist["piotroski_f_score"]["evaluated"]

        macro_adj = macro_regime.sector_adjustment(regime_info["regime"], sector)
        narrative = synth_narrative(company_cfg["name"], metrics, checklist)
        display = to_display(metrics, close_price)

        quant_scorecard = quant_score.build_quant_scorecard(metrics)
        qualitative_out = synth_qualitative(company_cfg["name"], quant_scorecard)
        layered_analysis = aggregation.build_layered_analysis(quant_scorecard, qualitative_out, metrics, checklist)

        company_doc = {
            "ticker": ticker,
            "name": company_cfg["name"],
            "cik": None,
            "sector": sector,
            "industry": None,
            "market_cap": market_cap,
            "last_updated": generated_at,
            "price": display["price"],
            "metrics": metrics,
            "macro_context": {
                "regime": regime_info["regime"],
                "sector_sensitivity": {
                    "rate_sensitivity": macro_adj["rate_sensitivity"],
                    "cyclicality": macro_adj["cyclicality"],
                },
            },
            "fundamentals": display["fundamentals"],
            "value_investing": checklist,
            "narrative": narrative,
            "quant_score": quant_scorecard,
            "qualitative": qualitative_out,
            "layered_analysis": layered_analysis,
            "sources": {"sec_filings": [], "sec_companyfacts_url": None},
            "_errors": {
                "_sample_data": "Synthetic demo data from scripts/generate_sample_data.py, not a real fetch."
            },
        }
        writer.write_company(DATA_DIR, ticker, company_doc)

        summaries.append(
            {
                "ticker": ticker,
                "name": company_cfg["name"],
                "sector": sector,
                "one_line_summary": narrative["one_line_summary"],
                "book_value_per_share": metrics["book_value_per_share"],
                "graham_criteria_passed": checklist["graham_defensive"]["passed"],
                "graham_criteria_total": checklist["graham_defensive"]["total"],
                "piotroski_f_score": checklist["piotroski_f_score"]["score"],
                "quant_gate_pass": layered_analysis["quant_gate_pass"],
                "qualitative_moat_present": layered_analysis["qualitative_moat_present"],
                "valuation_gate_pass": layered_analysis["valuation_gate_pass"],
                "conviction_score": layered_analysis["conviction_score"],
                "conviction_verdict": layered_analysis["conviction_verdict"],
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
