"""CLI entrypoint for the scheduled watchlist data-refresh pipeline.

Usage:
  python -m pipeline.main                         # full run over the whole watchlist
  python -m pipeline.main --tickers AAPL,MSFT      # run over a subset
  python -m pipeline.main --dry-run                # write to data/ locally, no commit (commit is CI's job)
  python -m pipeline.main --skip-ai                 # fetch + score only, no Anthropic spend
  python -m pipeline.main --ai-only --tickers AAPL  # re-run just the narrative step for already-scored companies

Runs in three phases so cross-company signals (currently: sector-relative
momentum) are available before any narrative is generated:
  1. fetch_and_score_company() for every ticker - fetch, quantitative
     scoring, and the Graham/Piotroski checklists.
  2. apply_sector_relative_momentum() - a pure in-memory pass over the
     collected results.
  3. finalize_company() for every ticker - AI narrative + final JSON
     assembly + write.
"""

import argparse
import json
import logging
import sys

from pipeline.build import writer
from pipeline.fetch import fmp, fred, sec_edgar, stooq
from pipeline.narrative.anthropic_client import NarrativeError, generate_narrative
from pipeline.narrative.grounding import enforce_grounding
from pipeline.narrative.prompts import DISCLAIMER
from pipeline.scoring import long_term, macro_regime, short_term, value_investing
from pipeline.scoring.fundamentals import build_metrics
from pipeline.utils.config import macro_series, watchlist
from pipeline.utils.paths import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.2.0"

EMPTY_FACT_TIERS = {"critical": [], "important": [], "minor": [], "noise": []}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Refresh watchlist data.")
    parser.add_argument("--tickers", help="Comma-separated tickers to run (default: full watchlist)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Write to data/ but skip anything CI would do (e.g. committing)"
    )
    parser.add_argument("--skip-ai", action="store_true", help="Fetch + score only, skip the Anthropic narrative call")
    parser.add_argument(
        "--ai-only", action="store_true", help="Re-run only the narrative step against already-written company JSON"
    )
    return parser.parse_args(argv)


def selected_companies(args) -> list[dict]:
    all_companies = watchlist()
    if not args.tickers:
        return all_companies
    wanted = {t.strip().upper() for t in args.tickers.split(",")}
    return [c for c in all_companies if c["ticker"].upper() in wanted]


def fetch_macro() -> tuple[dict, dict]:
    ids = [s["id"] for s in macro_series()["series"]]
    macro_data = fred.fetch_all(ids)
    regime_info = macro_regime.classify_regime(macro_data)
    return macro_data, regime_info


def build_macro_doc(macro_data: dict, regime_info: dict, generated_at: str) -> dict:
    series_cfg = {s["id"]: s for s in macro_series()["series"]}
    series_out = []
    for series_id, observations in macro_data.items():
        if series_id == "_errors":
            continue
        cfg = series_cfg.get(series_id, {})
        latest = observations[-1] if observations else None
        series_out.append(
            {
                "series_id": series_id,
                "label": cfg.get("label", series_id),
                "latest_value": latest["value"] if latest else None,
                "as_of": latest["date"] if latest else None,
                "history": observations,
                "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
            }
        )
    return {
        "generated_at": generated_at,
        "regime": regime_info["regime"],
        "signals": regime_info["signals"],
        "series": series_out,
        "cycle_context": macro_regime.cycle_context(regime_info["regime"]),
    }


def fetch_and_score_company(company_cfg: dict, regime_info: dict) -> dict:
    """Fetch + score one company. Does not generate its narrative yet -
    narratives happen after apply_sector_relative_momentum() so they can
    cite that cross-company signal too."""
    ticker = company_cfg["ticker"]
    logger.info("Processing %s", ticker)

    fmp_data = fmp.fetch_company(ticker)
    sec_data = sec_edgar.fetch_company(ticker)

    stooq_prices: list[dict] = []
    stooq_error: str | None = None
    if not fmp_data.get("historical_prices") and not fmp_data.get("quote"):
        try:
            stooq_prices = stooq.fetch_daily_prices(ticker)
        except stooq.StooqError as exc:
            stooq_error = str(exc)
            logger.warning("Stooq fallback failed for %s: %s", ticker, exc)

    built = build_metrics(ticker, fmp_data, sec_data, stooq_prices)
    metrics, display, profile, raw = built["metrics"], built["display"], built["profile"], built["raw"]

    name = company_cfg.get("name") or profile.get("name") or ticker
    sector = profile.get("sector") or company_cfg.get("sector")

    checklist = value_investing.build_checklist(metrics, profile, raw)
    metrics["graham_criteria_passed"] = checklist["graham_defensive"]["passed"]
    metrics["graham_criteria_evaluated"] = checklist["graham_defensive"]["evaluated"]
    metrics["piotroski_f_score"] = checklist["piotroski_f_score"]["score"]
    metrics["piotroski_evaluated"] = checklist["piotroski_f_score"]["evaluated"]

    recent_filings = sec_edgar.recent_filings(sec_data["submissions"]) if sec_data.get("submissions") else []
    companyfacts_url = (
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{sec_data['cik']}.json" if sec_data.get("cik") else None
    )
    errors = {**fmp_data.get("_errors", {}), **{f"sec_{k}": v for k, v in sec_data.get("_errors", {}).items()}}
    if stooq_error:
        errors["stooq"] = stooq_error

    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "profile": profile,
        "metrics": metrics,
        "display": display,
        "checklist": checklist,
        "recent_filings": recent_filings,
        "companyfacts_url": companyfacts_url,
        "errors": errors,
    }


def apply_sector_relative_momentum(states: list[dict]) -> None:
    """Mutates each state's metrics/display in place, adding
    sector_relative_momentum_pct: this company's 3-month return minus the
    average 3-month return of the other tracked companies in the same
    sector. A relative-strength (supply/demand) signal derived purely from
    our own price data - it notes *that* a stock is diverging from its
    peers, not a claimed *reason* why."""
    by_sector: dict[str, list[float]] = {}
    for state in states:
        r = state["metrics"].get("return_3m_pct")
        if r is not None:
            by_sector.setdefault(state["sector"], []).append(r)

    sector_avg = {sector: sum(vals) / len(vals) for sector, vals in by_sector.items()}

    for state in states:
        r = state["metrics"].get("return_3m_pct")
        avg = sector_avg.get(state["sector"])
        relative = (r - avg) if r is not None and avg is not None else None
        state["metrics"]["sector_relative_momentum_pct"] = relative
        state["display"]["price"]["sector_relative_momentum_pct"] = relative
        state["display"]["price"]["sector_avg_return_3m_pct"] = sector_avg.get(state["sector"])


def _narrative_payload(ticker: str, name: str, sector: str | None, metrics: dict, short: dict, long: dict, regime_info: dict, macro_adj: dict) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "metrics": {k: v for k, v in metrics.items() if v is not None},
        "scores": {
            "short_term": {"final_score": short["final_score"], "verdict": short["verdict"]},
            "long_term": {"final_score": long["final_score"], "verdict": long["verdict"]},
        },
        "macro": {
            "regime": regime_info["regime"],
            "rate_sensitivity": macro_adj["rate_sensitivity"],
            "cyclicality": macro_adj["cyclicality"],
        },
    }


def _run_narrative(ticker: str, payload: dict) -> tuple[dict, int]:
    """Returns (narrative_out_dict, dropped_fact_count). Falls back to an
    empty-but-valid narrative block (with the disclaimer still present) if
    the Anthropic call fails, rather than aborting the ticker."""
    narrative_out = {
        "one_line_summary": None,
        "short_term_narrative": None,
        "long_term_narrative": None,
        "facts": {k: [] for k in EMPTY_FACT_TIERS},
        "disclaimer": DISCLAIMER,
    }
    try:
        narrative = generate_narrative(ticker, payload)
    except NarrativeError as exc:
        logger.warning("Narrative generation skipped for %s: %s", ticker, exc)
        return narrative_out, 0

    grounded, dropped = enforce_grounding(narrative, payload["metrics"])
    narrative_out["one_line_summary"] = grounded.one_line_summary
    narrative_out["short_term_narrative"] = grounded.short_term_narrative
    narrative_out["long_term_narrative"] = grounded.long_term_narrative
    for fact in grounded.facts:
        narrative_out["facts"][fact.tier].append(
            {"text": fact.text, "source_metric": fact.source_metric, "source_value": fact.source_value}
        )
    return narrative_out, dropped


def finalize_company(state: dict, regime_info: dict, skip_ai: bool) -> tuple[dict, dict, int]:
    """Returns (company_doc, watchlist_summary, narrative_warnings)."""
    ticker, name, sector = state["ticker"], state["name"], state["sector"]
    metrics, display, profile = state["metrics"], state["display"], state["profile"]

    macro_adj = macro_regime.sector_adjustment(regime_info["regime"], sector)
    short = short_term.score(metrics, macro_adj["short"])
    long = long_term.score(metrics, macro_adj["long"])

    generated_at = writer.now_iso()
    clean_metrics = {k: v for k, v in metrics.items() if v is not None}

    narrative_warnings = 0
    if skip_ai:
        narrative_out = {
            "one_line_summary": None,
            "short_term_narrative": None,
            "long_term_narrative": None,
            "facts": {k: [] for k in EMPTY_FACT_TIERS},
            "disclaimer": DISCLAIMER,
        }
    else:
        payload = _narrative_payload(ticker, name, sector, metrics, short, long, regime_info, macro_adj)
        narrative_out, narrative_warnings = _run_narrative(ticker, payload)

    company_doc = {
        "ticker": ticker,
        "name": name,
        "cik": profile.get("cik"),
        "sector": sector,
        "industry": profile.get("industry"),
        "market_cap": profile.get("market_cap"),
        "last_updated": generated_at,
        "price": display["price"],
        "metrics": clean_metrics,
        "scores": {"short_term": short, "long_term": long},
        "macro_context": {
            "regime": regime_info["regime"],
            "sector_sensitivity": {
                "rate_sensitivity": macro_adj["rate_sensitivity"],
                "cyclicality": macro_adj["cyclicality"],
            },
        },
        "fundamentals": display["fundamentals"],
        "value_investing": state["checklist"],
        "narrative": narrative_out,
        "sources": {"sec_filings": state["recent_filings"], "sec_companyfacts_url": state["companyfacts_url"]},
        "_errors": state["errors"],
    }

    summary = {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "short_term_score": short["final_score"],
        "short_term_verdict": short["verdict"],
        "long_term_score": long["final_score"],
        "long_term_verdict": long["verdict"],
        "one_line_summary": narrative_out["one_line_summary"],
        "graham_criteria_passed": state["checklist"]["graham_defensive"]["passed"],
        "graham_criteria_total": state["checklist"]["graham_defensive"]["total"],
        "piotroski_f_score": state["checklist"]["piotroski_f_score"]["score"],
        "last_updated": generated_at,
    }

    return company_doc, summary, narrative_warnings


def run_full(args) -> int:
    companies = selected_companies(args)
    if not companies:
        logger.error("No matching companies in watchlist for --tickers=%s", args.tickers)
        return 1

    generated_at = writer.now_iso()
    sources_status = {
        "fmp": "ok",
        "sec_edgar": "ok",
        "stooq": "ok",
        "fred": "ok",
        "anthropic": "skipped" if args.skip_ai else "ok",
    }

    try:
        macro_data, regime_info = fetch_macro()
        if any(macro_data.get("_errors", {}).values()):
            sources_status["fred"] = "degraded"
    except Exception:
        logger.exception("Macro fetch failed entirely; proceeding with a neutral regime")
        macro_data, regime_info = {}, {"regime": "Neutral/Expansion", "signals": {}}
        sources_status["fred"] = "failed"

    out_dir = writer.output_dir(args.dry_run)
    macro_doc = build_macro_doc(macro_data, regime_info, generated_at)
    writer.write_macro(out_dir, macro_doc)

    # Phase 1: fetch + score every company (no narrative yet).
    states = []
    fmp_error_count = 0
    sec_error_count = 0
    stooq_error_count = 0
    for company_cfg in companies:
        try:
            state = fetch_and_score_company(company_cfg, regime_info)
        except Exception:
            logger.exception("Failed to process %s entirely, skipping", company_cfg["ticker"])
            continue

        errs = state["errors"]
        if any(not k.startswith("sec_") and k != "stooq" for k in errs):
            fmp_error_count += 1
        if any(k.startswith("sec_") for k in errs):
            sec_error_count += 1
        if "stooq" in errs:
            stooq_error_count += 1
        states.append(state)

    # Phase 2: cross-company signals.
    apply_sector_relative_momentum(states)

    # Phase 3: narrative + final assembly + write.
    summaries = []
    total_narrative_warnings = 0
    for state in states:
        company_doc, summary, warnings = finalize_company(state, regime_info, args.skip_ai)
        total_narrative_warnings += warnings
        writer.write_company(out_dir, state["ticker"], company_doc)
        summaries.append(summary)

    if fmp_error_count:
        sources_status["fmp"] = "degraded"
    if sec_error_count:
        sources_status["sec_edgar"] = "degraded"
    if stooq_error_count:
        sources_status["stooq"] = "degraded"

    writer.write_watchlist(out_dir, summaries, generated_at)
    writer.write_meta(
        out_dir,
        {
            "generated_at": generated_at,
            "pipeline_version": PIPELINE_VERSION,
            "watchlist_size": len(companies),
            "sources_status": sources_status,
            "narrative_warnings": total_narrative_warnings,
        },
    )

    logger.info("Done. Processed %d/%d companies.", len(summaries), len(companies))
    return 0 if summaries else 1


def run_ai_only(args) -> int:
    companies = selected_companies(args)
    generated_at = writer.now_iso()
    total_warnings = 0
    updated: dict[str, str | None] = {}
    out_dir = writer.output_dir(args.dry_run)

    for company_cfg in companies:
        ticker = company_cfg["ticker"]
        path = DATA_DIR / "companies" / f"{ticker}.json"
        if not path.exists():
            logger.warning("No existing data/companies/%s.json - run a full pass first", ticker)
            continue

        with open(path, "r", encoding="utf-8") as f:
            company_doc = json.load(f)

        payload = {
            "ticker": ticker,
            "name": company_doc.get("name", ticker),
            "sector": company_doc.get("sector"),
            "metrics": company_doc.get("metrics", {}),
            "scores": {
                "short_term": {
                    "final_score": company_doc["scores"]["short_term"]["final_score"],
                    "verdict": company_doc["scores"]["short_term"]["verdict"],
                },
                "long_term": {
                    "final_score": company_doc["scores"]["long_term"]["final_score"],
                    "verdict": company_doc["scores"]["long_term"]["verdict"],
                },
            },
            "macro": company_doc.get("macro_context", {}),
        }

        narrative_out, dropped = _run_narrative(ticker, payload)
        total_warnings += dropped
        if narrative_out["one_line_summary"] is None:
            continue  # generation failed; leave existing data untouched

        company_doc["narrative"] = narrative_out
        company_doc["last_updated"] = generated_at
        writer.write_company(out_dir, ticker, company_doc)
        updated[ticker] = narrative_out["one_line_summary"]

    if updated:
        watchlist_path = DATA_DIR / "watchlist.json"
        if watchlist_path.exists():
            with open(watchlist_path, "r", encoding="utf-8") as f:
                watchlist_doc = json.load(f)
            for entry in watchlist_doc.get("companies", []):
                if entry["ticker"] in updated:
                    entry["one_line_summary"] = updated[entry["ticker"]]
                    entry["last_updated"] = generated_at
            writer.write_watchlist(out_dir, watchlist_doc["companies"], generated_at)

    logger.info("ai-only: updated %d companies (%d facts dropped by grounding check)", len(updated), total_warnings)
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.ai_only:
        return run_ai_only(args)
    return run_full(args)


if __name__ == "__main__":
    sys.exit(main())
