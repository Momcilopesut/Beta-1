"""Generates synthetic seed data under data/ so the static site is browsable
before the real pipeline has ever run against live API keys.

Deterministic (fixed seed), and every generated file is clearly marked as
sample data (see meta.json's "note" field and each company's "_errors").
This is NOT a substitute for a real pipeline run - it exists purely so
`site/` has something realistic to render on day one. The first real
`python -m pipeline.main` run overwrites all of this.

Usage: python scripts/generate_sample_data.py
"""

import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.build import writer  # noqa: E402
from pipeline.main import build_macro_doc  # noqa: E402
from pipeline.scoring import aggregation, macro_regime, performance, value_investing  # noqa: E402
from pipeline.utils.config import macro_series, screening_config, watchlist  # noqa: E402
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
    "roe_pct": (-5, 35),
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
    "PAYEMS": 161_500.0,
    "ICSA": 220_000.0,
    "PCEPI": 124.5,
    "INDPRO": 103.5,
    "UMCSENT": 68.0,
    "M2SL": 21_800.0,
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


def synth_returns() -> dict:
    """Independent, deliberately wide-ranging synthetic price returns per
    lookback window (pipeline.scoring.performance.WINDOWS) - realistic
    enough that each window's top-5 genuinely differs from the others, the
    way real momentum data would."""
    return {
        "weekly": round(random.uniform(-6, 6), 2),
        "monthly": round(random.uniform(-12, 15), 2),
        "quarterly": round(random.uniform(-20, 25), 2),
        "annual": round(random.uniform(-35, 60), 2),
        "five_year": round(random.uniform(-20, 250), 2),
    }


def synth_five_year_history(market_cap: float, close_price: float) -> dict:
    """5 years of gently trending earnings/spending/cash/debt, plus how the
    stock did each year vs. a synthetic "market" - scaled off the same
    market_cap/close_price used elsewhere so the numbers stay proportionate
    to the rest of this company's sample data. The oldest year has no
    stock/market return, mirroring the real pipeline's own behavior (no
    earlier statement to anchor a year-over-year return against)."""
    revenue = market_cap * random.uniform(0.3, 1.2)
    earnings = revenue * random.uniform(0.05, 0.22)
    spending = revenue - earnings * random.uniform(0.8, 1.1)
    cash = market_cap * random.uniform(0.03, 0.15)
    debt = market_cap * random.uniform(0.05, 0.35)

    years = []
    for i in range(5):
        fiscal_year = f"{2021 + i}-12-31"
        years.append(
            {
                "fiscal_year": fiscal_year,
                "revenue": round(revenue, 0),
                "earnings": round(earnings, 0),
                "spending": round(spending, 0),
                "cash": round(cash, 0),
                "debt": round(debt, 0),
                "stock_return_pct": None if i == 0 else round(random.uniform(-25, 35), 1),
                "market_return_pct": None if i == 0 else round(random.uniform(-18, 24), 1),
            }
        )
        growth = random.uniform(-0.08, 0.18)
        revenue *= 1 + growth * random.uniform(0.7, 1.0)
        earnings *= 1 + growth
        spending *= 1 + growth * random.uniform(0.6, 1.1)
        cash *= 1 + random.uniform(-0.05, 0.15)
        debt *= 1 + random.uniform(-0.1, 0.1)

    return {"years": years}


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
                "roe_pct": metrics["roe_pct"],
            },
        },
    }


_SAMPLE_MOAT_TYPES = ["network_effects", "cost_advantage", "intangible_assets", "switching_costs", "efficient_scale"]

# Sample-data stand-in for pipeline.fetch.sec_edgar.latest_filings_by_form()'s
# real per-company URLs - a generic (but genuinely working) SEC EDGAR company
# search, parameterized by ticker and form type, rather than a fake
# accession-number URL that would 404. Newest-filed-first, matching the real
# pipeline's display order.
_SAMPLE_FILINGS = (("8-K", "2026-08-01"), ("10-Q", "2026-06-01"), ("10-K", "2026-02-15"))


def synth_sec_filings(ticker: str) -> list[dict]:
    return [
        {
            "form": form,
            "filed": filed,
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={quote(ticker)}&type={quote(form)}",
        }
        for form, filed in _SAMPLE_FILINGS
    ]


def synth_qualitative(name: str) -> dict | None:
    """Placeholder text, clearly labeled, not a real reading of any filing -
    stands in for pipeline/main.py's real Buffett moat read + filing
    summaries (only run for this week's finalists there; synthesized here
    for every sample company for simplicity). filing_summary_8k is
    occasionally None to demonstrate the "no recent 8-K found" case the real
    pipeline also produces."""
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
        "filing_summary_10k": f"[Sample data] Placeholder 10-K summary for {name}.",
        "filing_summary_10q": f"[Sample data] Placeholder 10-Q summary for {name}.",
        "filing_summary_8k": (
            f"[Sample data] Placeholder 8-K summary for {name}." if random.random() < 0.85 else None
        ),
    }


def synth_macro_data(series_cfg: list[dict]) -> dict:
    """One history per configured series, spaced at that series' own
    obs_per_year cadence (daily/weekly/monthly/quarterly) rather than a
    fixed weekly interval - real pipeline.scoring.macro_mood.compute_mood
    needs a real ~1-year-back observation to compare against, so the
    sample data has to actually span a year at each series' real
    frequency, not just look busy."""
    end_date = datetime(2026, 9, 12, tzinfo=timezone.utc)
    out = {}
    for cfg in series_cfg:
        series_id = cfg["id"]
        base = MACRO_BASE_VALUES[series_id]
        history_limit = cfg.get("history_limit", 24)
        obs_per_year = cfg.get("obs_per_year", 12)
        interval_days = 365.25 / obs_per_year
        # Keep total drift across the window roughly constant regardless of
        # how many points it's spread over (260 daily steps vs. 5 quarterly
        # ones), so a daily series doesn't random-walk far more than a
        # quarterly one just because it has more steps.
        step_scale = math.sqrt(15 / history_limit)

        history = []
        value = base * 0.97
        for i in range(history_limit):
            value += random.uniform(-0.015, 0.02) * base * step_scale
            days_back = round((history_limit - 1 - i) * interval_days)
            date = (end_date - timedelta(days=days_back)).strftime("%Y-%m-%d")
            history.append({"date": date, "value": round(value, 3)})
        history[-1] = {"date": end_date.strftime("%Y-%m-%d"), "value": round(base, 3)}
        out[series_id] = history
    return out


def main() -> None:
    companies = watchlist()
    generated_at = writer.now_iso()

    macro_data = synth_macro_data(macro_series()["series"])
    regime_info = macro_regime.classify_regime(macro_data)
    # Reuses the real build_macro_doc (same function main.run_full calls) so
    # sample data gets the same mood computation, shape, and source URLs as
    # a real pipeline run - never a hand-duplicated second copy of that logic.
    macro_doc = build_macro_doc(macro_data, regime_info, generated_at)
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
        metrics["munger_quality_passed"] = checklist["munger_quality"]["passed"]
        metrics["munger_quality_evaluated"] = checklist["munger_quality"]["evaluated"]

        macro_adj = macro_regime.sector_adjustment(regime_info["regime"], sector)
        display = to_display(metrics, close_price)
        five_year_history = synth_five_year_history(market_cap, close_price)

        qualitative_out = synth_qualitative(company_cfg["name"])
        layered_analysis = aggregation.build_layered_analysis(qualitative_out, metrics, checklist)

        company_doc = {
            "ticker": ticker,
            "name": company_cfg["name"],
            "cik": None,
            "sector": sector,
            "industry": None,
            "market_cap": market_cap,
            "website": f"https://www.{ticker.lower().replace('.', '')}.example",
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
            "five_year_history": five_year_history,
            "value_investing": checklist,
            "qualitative": qualitative_out,
            "layered_analysis": layered_analysis,
            "sources": {"sec_filings": synth_sec_filings(ticker), "sec_companyfacts_url": None},
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
                "price": display["price"],
                "returns": synth_returns(),
                "book_value_per_share": metrics["book_value_per_share"],
                "graham_criteria_passed": checklist["graham_defensive"]["passed"],
                "graham_criteria_total": checklist["graham_defensive"]["total"],
                "munger_quality_passed": checklist["munger_quality"]["passed"],
                "munger_quality_total": checklist["munger_quality"]["total"],
                "qualitative_moat_present": layered_analysis["qualitative_moat_present"],
                "munger_quality_pass": layered_analysis["munger_quality_pass"],
                "valuation_gate_pass": layered_analysis["valuation_gate_pass"],
                "last_updated": generated_at,
            }
        )

    writer.write_watchlist(DATA_DIR, summaries, generated_at)
    top_n_per_sector = screening_config()["top_n_per_sector"]
    picks_by_sector = performance.select_top_performers(summaries, top_n_per_sector)
    writer.write_performance_picks(DATA_DIR, picks_by_sector, generated_at, len(companies), top_n_per_sector)
    writer.write_meta(
        DATA_DIR,
        {
            "generated_at": generated_at,
            "pipeline_version": "sample-data",
            "watchlist_size": len(companies),
            "sources_status": {"fmp": "sample", "sec_edgar": "sample", "fred": "sample", "anthropic": "sample"},
            "note": (
                "Placeholder demo data for local preview only. Run `python -m pipeline.main` "
                "with real API keys configured to replace it with live data."
            ),
        },
    )
    print(f"Wrote sample data for {len(companies)} companies to {DATA_DIR}")


if __name__ == "__main__":
    main()
