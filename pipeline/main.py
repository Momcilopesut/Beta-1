"""CLI entrypoint for the weekly screening pipeline - this project's primary
purpose: scan a curated universe of stocks (config/watchlist.yaml) and
surface whichever ones come closest to satisfying the Graham/Buffett/Munger
criteria this pipeline scores on, per sector, every week.

Usage:
  python -m pipeline.main                         # full screen over the whole universe
  python -m pipeline.main --tickers AAPL,MSFT      # run over a subset
  python -m pipeline.main --dry-run                # write to data/ locally, no commit (commit is CI's job)
  python -m pipeline.main --skip-ai                 # fetch + score only, no Anthropic spend
  python -m pipeline.main --ai-only --tickers AAPL  # re-run just the narrative step for already-scored companies

Two phases (see run_full):
  1. A cheap screen (fetch_and_score_company + finalize_company with
     skip_ai=True) over the WHOLE universe - no Anthropic spend. The
     Investment Meter score is still meaningful here (a missing moat read
     just reads as a neutral multiplier - see aggregation.py), so this
     alone is enough to rank and select this week's top picks per sector
     (pipeline.scoring.screening.select_top_picks).
  2. AI enrichment (skip_ai=False) of just the selected finalists - the
     real narrative + 10-K moat read, the only place Anthropic budget gets
     spent.
"""

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from pipeline.build import qualitative_cache, writer
from pipeline.fetch import filing_text, fmp, fred, sec_edgar, stooq
from pipeline.narrative.anthropic_client import NarrativeError, generate_narrative
from pipeline.narrative.grounding import enforce_grounding
from pipeline.narrative.prompts import DISCLAIMER
from pipeline.narrative.qualitative_client import QualitativeError, generate_qualitative_assessment
from pipeline.scoring import aggregation, history, macro_regime, quant_score, screening, value_investing
from pipeline.scoring.fundamentals import build_metrics, normalize_price_rows
from pipeline.utils.config import macro_series, screening_config, watchlist
from pipeline.utils.paths import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PIPELINE_VERSION = "3.0.0"

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


def fetch_benchmark() -> list[dict]:
    """SPY's own daily price history - the "stock market average" the 5-year
    history charts compare every company's own yearly return against
    (pipeline.scoring.history). Fetched once per run/request, not once per
    company, since every company is compared to the same market. Falls back
    to an empty list (never crashes the run) if the fetch fails - the
    history builder already treats missing price data as None, not 0."""
    try:
        return normalize_price_rows(fmp.fetch_benchmark_prices())
    except Exception:
        logger.warning("Benchmark (SPY) price fetch failed; 5-year history will skip market comparison")
        return []


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


def fetch_and_score_company(company_cfg: dict, regime_info: dict, benchmark_prices: list[dict] | None = None) -> dict:
    """Fetch + score one company."""
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
    metrics["munger_quality_passed"] = checklist["munger_quality"]["passed"]
    metrics["munger_quality_evaluated"] = checklist["munger_quality"]["evaluated"]

    recent_filings = sec_edgar.recent_filings(sec_data["submissions"]) if sec_data.get("submissions") else []
    companyfacts_url = (
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{sec_data['cik']}.json" if sec_data.get("cik") else None
    )
    errors = {**fmp_data.get("_errors", {}), **{f"sec_{k}": v for k, v in sec_data.get("_errors", {}).items()}}
    if stooq_error:
        errors["stooq"] = stooq_error

    # Layer 2 (quant screen, pure function - see pipeline/scoring/quant_score.py).
    # Gates layer 3 below: the expensive AI call only runs on names that
    # already clear this bar (deliberate cost control, not just a display filter).
    quant_scorecard = quant_score.build_quant_scorecard(metrics)
    latest_10k = next((f for f in recent_filings if f["form"] == "10-K"), None)

    five_year_history = history.build_five_year_history(
        raw["income_stmts"], raw["balance_stmts"], raw["price_history"], benchmark_prices or []
    )

    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "profile": profile,
        "metrics": metrics,
        "display": display,
        "checklist": checklist,
        "quant_scorecard": quant_scorecard,
        "latest_10k": latest_10k,
        "raw": raw,
        "recent_filings": recent_filings,
        "companyfacts_url": companyfacts_url,
        "five_year_history": five_year_history,
        "errors": errors,
    }


def _narrative_payload(
    ticker: str, name: str, sector: str | None, metrics: dict, quant_scorecard: dict, regime_info: dict, macro_adj: dict
) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "metrics": {k: v for k, v in metrics.items() if v is not None},
        "quant_gate_pass": quant_scorecard.get("gate_pass"),
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
        "narrative": None,
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
    narrative_out["narrative"] = grounded.narrative
    for fact in grounded.facts:
        narrative_out["facts"][fact.tier].append(
            {"text": fact.text, "source_metric": fact.source_metric, "source_value": fact.source_value}
        )
    return narrative_out, dropped


def _run_qualitative(state: dict, quant_scorecard: dict, out_dir) -> tuple[dict | None, bool]:
    """Layer 3. Only runs when quant_scorecard's gate passed (deliberate
    cost control - see fetch_and_score_company's comment) and there's a
    10-K to read. Returns (qualitative, failed) - failed is True only when
    the layer was attempted and errored, never for a deliberate skip (gate
    not passed, no 10-K found), so callers can distinguish "nothing to do
    here" from "something broke"."""
    ticker, latest_10k = state["ticker"], state.get("latest_10k")
    if not quant_scorecard.get("gate_pass") or not latest_10k:
        return None, False

    cached = qualitative_cache.read(out_dir, ticker)
    if cached and cached.get("filing_url") == latest_10k["url"]:
        return cached["qualitative"], False

    try:
        sections = filing_text.fetch_filing_sections(latest_10k["url"])
        qualitative = generate_qualitative_assessment(ticker, sections, quant_scorecard)
    except (filing_text.FilingTextError, QualitativeError) as exc:
        logger.warning("Qualitative layer skipped for %s: %s", ticker, exc)
        return None, True

    qualitative_dict = qualitative.model_dump()
    qualitative_cache.write(out_dir, ticker, latest_10k["url"], qualitative_dict)
    return qualitative_dict, False


def finalize_company(
    state: dict, regime_info: dict, skip_ai: bool, out_dir, skip_qualitative: bool = False
) -> tuple[dict, dict, int, bool]:
    """Returns (company_doc, watchlist_summary, narrative_warnings, qualitative_failed).

    The narrative call and the qualitative call are independent (neither
    reads the other's output) and run concurrently to cut wall-clock time -
    this matters most for api/lookup.py's on-demand endpoint, which has a
    hard Vercel function timeout for a single request, but also just makes
    the batch pipeline faster.

    skip_qualitative: available for a caller that wants to skip layer 3
    entirely (e.g. if a deployment's Vercel timeout is too tight even with
    the concurrency above) - unused by default; both callers currently run
    the full analysis.
    """
    ticker, name, sector = state["ticker"], state["name"], state["sector"]
    metrics, display, profile = state["metrics"], state["display"], state["profile"]

    macro_adj = macro_regime.sector_adjustment(regime_info["regime"], sector)

    generated_at = writer.now_iso()
    clean_metrics = {k: v for k, v in metrics.items() if v is not None}

    quant_scorecard = state["quant_scorecard"]

    narrative_warnings = 0
    qualitative_failed = False
    if skip_ai:
        narrative_out = {
            "one_line_summary": None,
            "narrative": None,
            "facts": {k: [] for k in EMPTY_FACT_TIERS},
            "disclaimer": DISCLAIMER,
        }
        qualitative_out = None
    else:
        payload = _narrative_payload(ticker, name, sector, metrics, quant_scorecard, regime_info, macro_adj)
        if skip_qualitative:
            narrative_out, narrative_warnings = _run_narrative(ticker, payload)
            qualitative_out = None
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                narrative_future = pool.submit(_run_narrative, ticker, payload)
                qualitative_future = pool.submit(_run_qualitative, state, quant_scorecard, out_dir)
                narrative_out, narrative_warnings = narrative_future.result()
                qualitative_out, qualitative_failed = qualitative_future.result()

    layered_analysis = aggregation.build_layered_analysis(quant_scorecard, qualitative_out, metrics, state["checklist"])

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
        "macro_context": {
            "regime": regime_info["regime"],
            "sector_sensitivity": {
                "rate_sensitivity": macro_adj["rate_sensitivity"],
                "cyclicality": macro_adj["cyclicality"],
            },
        },
        "fundamentals": display["fundamentals"],
        "five_year_history": state["five_year_history"],
        "value_investing": state["checklist"],
        "narrative": narrative_out,
        "quant_score": quant_scorecard,
        "qualitative": qualitative_out,
        "layered_analysis": layered_analysis,
        "sources": {"sec_filings": state["recent_filings"], "sec_companyfacts_url": state["companyfacts_url"]},
        "_errors": state["errors"],
    }

    summary = {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "one_line_summary": narrative_out["one_line_summary"],
        "price": display["price"],
        "book_value_per_share": metrics.get("book_value_per_share"),
        "graham_criteria_passed": state["checklist"]["graham_defensive"]["passed"],
        "graham_criteria_total": state["checklist"]["graham_defensive"]["total"],
        "munger_quality_passed": state["checklist"]["munger_quality"]["passed"],
        "munger_quality_total": state["checklist"]["munger_quality"]["total"],
        "quant_gate_pass": layered_analysis["quant_gate_pass"],
        "qualitative_moat_present": layered_analysis["qualitative_moat_present"],
        "munger_quality_pass": layered_analysis["munger_quality_pass"],
        "valuation_gate_pass": layered_analysis["valuation_gate_pass"],
        "conviction_score": layered_analysis["conviction_score"],
        "conviction_verdict": layered_analysis["conviction_verdict"],
        "last_updated": generated_at,
    }

    return company_doc, summary, narrative_warnings, qualitative_failed


def _process_company(
    company_cfg: dict, regime_info: dict, benchmark_prices: list[dict], skip_ai: bool, out_dir
) -> tuple[dict | None, int, bool, dict]:
    """Fetch, score, finalize, and write one company end-to-end. Used for
    both the cheap screen (skip_ai=True, whole universe) and the AI-enriched
    finalist pass (skip_ai=False) - the same work either way, just whether
    finalize_company spends the Anthropic calls. Returns (summary, warnings,
    qualitative_skipped, errors); summary is None if fetching or finalizing
    failed outright for this ticker (already logged), in which case the
    other fields are empty/zero and the caller should just skip it."""
    ticker = company_cfg["ticker"]
    try:
        state = fetch_and_score_company(company_cfg, regime_info, benchmark_prices)
    except Exception:
        logger.exception("Failed to process %s entirely, skipping", ticker)
        return None, 0, False, {}

    try:
        company_doc, summary, warnings, qual_skipped = finalize_company(state, regime_info, skip_ai, out_dir)
    except Exception:
        logger.exception("Failed to finalize %s entirely, skipping", ticker)
        return None, 0, False, state["errors"]

    writer.write_company(out_dir, ticker, company_doc)
    return summary, warnings, qual_skipped, state["errors"]


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

    benchmark_prices = fetch_benchmark()

    out_dir = writer.output_dir(args.dry_run)
    macro_doc = build_macro_doc(macro_data, regime_info, generated_at)
    writer.write_macro(out_dir, macro_doc)

    fmp_error_count = 0
    sec_error_count = 0
    stooq_error_count = 0
    total_narrative_warnings = 0
    total_qualitative_skipped = 0

    def _track_errors(errs: dict) -> None:
        nonlocal fmp_error_count, sec_error_count, stooq_error_count
        if any(not k.startswith("sec_") and k != "stooq" for k in errs):
            fmp_error_count += 1
        if any(k.startswith("sec_") for k in errs):
            sec_error_count += 1
        if "stooq" in errs:
            stooq_error_count += 1

    # Phase 1: cheap screen over the WHOLE universe - no AI spend (see
    # module docstring). Every company still gets a full company_doc/detail
    # page; only the narrative/moat read is missing until (if) it becomes a
    # finalist below.
    summaries = []
    for company_cfg in companies:
        summary, warnings, qual_skipped, errs = _process_company(
            company_cfg, regime_info, benchmark_prices, skip_ai=True, out_dir=out_dir
        )
        _track_errors(errs)
        if summary is None:
            continue
        total_narrative_warnings += warnings
        total_qualitative_skipped += int(qual_skipped)
        summaries.append(summary)

    # Rank + select this week's top picks: highest Investment Meter score
    # per sector, from the cheap screen above.
    top_n_per_sector = screening_config()["top_n_per_sector"]
    picks_by_sector = screening.select_top_picks(summaries, top_n_per_sector)
    finalist_sector = {pick["ticker"]: sector for sector, picks in picks_by_sector.items() for pick in picks}

    # Phase 2: AI-enrich only the selected finalists - the only place
    # Anthropic budget gets spent, unless --skip-ai keeps the whole run
    # cheap. Re-fetches rather than reusing phase 1's state (simpler than
    # threading cached raw data through; finalists are a small fraction of
    # the universe). Selection/rank is NOT recomputed after enrichment - the
    # displayed score becomes the accurate one, but which companies made the
    # list stays traceable to the cheap score that actually selected them
    # (the moat multiplier swing is modest, +-10% - see conviction_score.yaml).
    if not args.skip_ai and finalist_sector:
        summaries_by_ticker = {s["ticker"]: s for s in summaries}
        companies_by_ticker = {c["ticker"]: c for c in companies}
        for ticker, sector in finalist_sector.items():
            summary, warnings, qual_skipped, errs = _process_company(
                companies_by_ticker[ticker], regime_info, benchmark_prices, skip_ai=False, out_dir=out_dir
            )
            _track_errors(errs)
            if summary is None:
                continue
            total_narrative_warnings += warnings
            total_qualitative_skipped += int(qual_skipped)
            summaries_by_ticker[ticker] = summary
            for i, pick in enumerate(picks_by_sector[sector]):
                if pick["ticker"] == ticker:
                    picks_by_sector[sector][i] = summary
                    break
        summaries = list(summaries_by_ticker.values())

    if fmp_error_count:
        sources_status["fmp"] = "degraded"
    if sec_error_count:
        sources_status["sec_edgar"] = "degraded"
    if stooq_error_count:
        sources_status["stooq"] = "degraded"

    writer.write_watchlist(out_dir, summaries, generated_at)
    writer.write_weekly_picks(out_dir, picks_by_sector, generated_at, len(companies), top_n_per_sector)
    writer.write_meta(
        out_dir,
        {
            "generated_at": generated_at,
            "pipeline_version": PIPELINE_VERSION,
            "watchlist_size": len(companies),
            "sources_status": sources_status,
            "narrative_warnings": total_narrative_warnings,
            "qualitative_layer_skipped": total_qualitative_skipped,
        },
    )

    logger.info(
        "Done. Screened %d/%d companies, enriched %d finalists.",
        len(summaries),
        len(companies),
        len(finalist_sector) if not args.skip_ai else 0,
    )
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
            "quant_gate_pass": company_doc.get("quant_score", {}).get("gate_pass"),
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
