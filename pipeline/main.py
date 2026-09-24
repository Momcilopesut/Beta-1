"""CLI entrypoint for the weekly screening pipeline - this project's primary
purpose: scan a curated universe of stocks (config/watchlist.yaml) and
surface each sector's 5 best price performers over five lookback windows
(weekly, monthly, quarterly, annual, 5-year), every week. This ranking is
pure price return - it does not use any fundamentals check. Every company
still gets the full fundamentals scoring on its own detail page; it just
doesn't gate or influence which tickers surface on the screen itself.

Usage:
  python -m pipeline.main                         # full screen over the whole universe
  python -m pipeline.main --tickers AAPL,MSFT      # run over a subset
  python -m pipeline.main --dry-run                # write to data/ locally, no commit (commit is CI's job)
  python -m pipeline.main --skip-ai                 # fetch + score only, no Anthropic spend

Two phases (see run_full). Originally designed to gate BOTH the paid
Anthropic call and FMP's request budget the same way - a small, bounded
finalist subset, never the whole universe - but Stooq (the free price
source phase 1 was meant to lean on instead of FMP) turned out to be
blocked from GitHub Actions runners in practice (see pipeline.fetch.stooq's
module docstring), so only the AI gating held up at full-universe scale:
  1. Fetch + score every company (fetch_and_score_company + finalize_company
     with skip_ai=True) over the WHOLE universe - no Anthropic spend.
     Statements come from SEC EDGAR XBRL, sector from the watchlist's own
     configured value where FMP's profile doesn't have it (see
     pipeline.scoring.fundamentals's fallback chain); price/quote/profile
     currently come from FMP for every company, not just finalists (use_fmp=
     True in both phases - the free-tier-budget design this pipeline was
     meant to have for price data is unfinished, tracked as known follow-up
     work, not solved - see pipeline.fetch.fmp's module docstring). Price
     returns come straight from that history
     (pipeline.scoring.performance.compute_returns), so this alone is enough
     to rank and select each window's top performers per sector
     (pipeline.scoring.performance.select_top_performers).
  2. Enrichment (skip_ai=False) of just the selected finalists: Buffett's
     10-K moat read plus short neutral summaries of the latest 10-K/10-Q/
     8-K - the only place Anthropic budget gets spent, and still gated to
     a small, bounded subset. Every company (finalist or not) still gets
     its latest 10-K/10-Q/8-K listed with a direct SEC link - it's the AI
     summary of each filing that's finalists-only.
"""

import argparse
import logging
import sys

from pipeline.build import qualitative_cache, writer
from pipeline.fetch import filing_text, fmp, fred, sec_edgar, stooq
from pipeline.narrative.qualitative_client import QualitativeError, generate_qualitative_assessment
from pipeline.scoring import capital_efficiency, history, macro_mood, macro_regime, performance, plain_analysis, value_investing
from pipeline.scoring.fundamentals import build_metrics, normalize_price_rows
from pipeline.utils.config import capital_efficiency_config, macro_series, screening_config, watchlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PIPELINE_VERSION = "3.2.0"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Refresh watchlist data.")
    parser.add_argument("--tickers", help="Comma-separated tickers to run (default: full watchlist)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Write to data/ but skip anything CI would do (e.g. committing)"
    )
    parser.add_argument(
        "--skip-ai", action="store_true", help="Fetch + score only, skip the Anthropic moat-read call"
    )
    return parser.parse_args(argv)


def selected_companies(args) -> list[dict]:
    all_companies = watchlist()
    if not args.tickers:
        return all_companies
    wanted = {t.strip().upper() for t in args.tickers.split(",")}
    return [c for c in all_companies if c["ticker"].upper() in wanted]


def fetch_macro() -> tuple[dict, dict]:
    series_cfg = macro_series()["series"]
    ids = [s["id"] for s in series_cfg]
    limits = {s["id"]: s["history_limit"] for s in series_cfg if "history_limit" in s}
    macro_data = fred.fetch_all(ids, limit=limits)
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
    macro_cfg = macro_series()
    series_cfg = {s["id"]: s for s in macro_cfg["series"]}
    regime_rules = macro_cfg["regime_rules"]
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
                "mood": macro_mood.compute_mood(series_id, observations, cfg, regime_rules),
            }
        )
    return {
        "generated_at": generated_at,
        "regime": regime_info["regime"],
        "signals": regime_info["signals"],
        "series": series_out,
        "cycle_context": macro_regime.cycle_context(regime_info["regime"]),
    }


def _risk_free_rate_pct(macro_data: dict, series_id: str) -> float | None:
    observations = macro_data.get(series_id) or []
    return observations[-1]["value"] if observations else None


def digest_entry_from_doc(company_doc: dict) -> dict | None:
    """One finalists-digest entry from an already-finalized company_doc - no
    new fetching, just gathering the AI filing summaries finalize_company
    already generated (see _run_qualitative) into one rolled-up place
    instead of company-page by company-page. Returns None when this company
    has no filing summary at all (skip_ai runs, or no 10-K was found for
    it), so the digest never carries an empty-looking entry."""
    qualitative = company_doc.get("qualitative") or {}
    filing_summaries = {
        "filing_summary_10k": qualitative.get("filing_summary_10k"),
        "filing_summary_10q": qualitative.get("filing_summary_10q"),
        "filing_summary_8k": qualitative.get("filing_summary_8k"),
    }
    if not any(filing_summaries.values()):
        return None
    return {
        "ticker": company_doc["ticker"],
        "name": company_doc["name"],
        "sector": company_doc["sector"],
        # Shaped like a full "qualitative" object (just these 3 keys) so the
        # frontend can pass it straight into the same renderFilingCard the
        # company page itself uses (site/js/shared.js), no remapping needed.
        "qualitative": filing_summaries,
        "sec_filings": company_doc.get("sources", {}).get("sec_filings", []),
    }


def build_filings_digest(entries: list[dict], generated_at: str) -> dict:
    """entries: digest_entry_from_doc results (already filtered to non-None
    by the caller). A single rolled-up read of this week's top picks' AI
    filing summaries - reuses data finalize_company already generated, so
    this costs no extra fetching and no extra Anthropic spend."""
    return {
        "generated_at": generated_at,
        "tickers_covered": len(entries),
        "entries": sorted(entries, key=lambda e: e["ticker"]),
    }


def fetch_and_score_company(
    company_cfg: dict, regime_info: dict, benchmark_prices: list[dict] | None = None, use_fmp: bool = True
) -> dict:
    """Fetch + score one company. use_fmp=False skips FMP entirely -
    fundamentals.py falls back to free sources (SEC EDGAR XBRL, Stooq, the
    watchlist's own configured sector) for every field FMP would otherwise
    supply, so this still produces a complete, fully-scored company_doc,
    just without FMP's live-quote precision or website link for that run.
    run_full currently passes use_fmp=True in both phases (Stooq's free
    price history is unreliable from GitHub Actions in practice - see
    module docstring), but the flag itself still works standalone, e.g. for
    a from-scratch run against free sources only."""
    ticker = company_cfg["ticker"]
    logger.info("Processing %s", ticker)

    fmp_data = fmp.fetch_company(ticker) if use_fmp else {}
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

    latest_filings = sec_edgar.latest_filings_by_form(sec_data["submissions"]) if sec_data.get("submissions") else {}
    # Display order for the company page's Sources section - newest filing first.
    recent_filings = sorted(latest_filings.values(), key=lambda f: f["filed"], reverse=True)
    companyfacts_url = (
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{sec_data['cik']}.json" if sec_data.get("cik") else None
    )
    errors = {**fmp_data.get("_errors", {}), **{f"sec_{k}": v for k, v in sec_data.get("_errors", {}).items()}}
    if stooq_error:
        errors["stooq"] = stooq_error

    latest_10k = latest_filings.get("10-K")

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
        "latest_10k": latest_10k,
        "latest_filings": latest_filings,
        "raw": raw,
        "recent_filings": recent_filings,
        "companyfacts_url": companyfacts_url,
        "five_year_history": five_year_history,
        "errors": errors,
    }


def _run_qualitative(state: dict, out_dir) -> tuple[dict | None, bool]:
    """Layer 3 (Buffett's moat read from the 10-K, plus short neutral
    summaries of the latest 10-K/10-Q/8-K - all one Anthropic call, see
    qualitative_client.py). Only runs when there's a 10-K to read - cost
    control already happens one level up (only this week's per-sector
    finalists get here at all, see run_full's two-phase docstring). Returns
    (qualitative, failed) - failed is True only when the layer was attempted
    and errored, never for a deliberate skip (no 10-K found), so callers can
    distinguish "nothing to do here" from "something broke"."""
    ticker = state["ticker"]
    latest_filings = state.get("latest_filings") or {}
    latest_10k = latest_filings.get("10-K")
    if not latest_10k:
        return None, False

    filing_urls = {form: f["url"] for form, f in latest_filings.items()}
    cached = qualitative_cache.read(out_dir, ticker)
    if cached and cached.get("filing_urls") == filing_urls:
        return cached["qualitative"], False

    try:
        sections = filing_text.fetch_filing_sections(latest_10k["url"])
        # 10-Q/8-K text is a bonus, not required - a fetch failure here
        # just means that one filing_summary_* field comes back null,
        # it shouldn't sink the whole moat-read call.
        filing_texts: dict[str, str] = {}
        for form in ("10-Q", "8-K"):
            filing = latest_filings.get(form)
            if not filing:
                continue
            try:
                filing_texts[form] = filing_text.fetch_plain_text(filing["url"])
            except filing_text.FilingTextError as exc:
                logger.warning("%s text fetch failed for %s, summarizing without it: %s", form, ticker, exc)
        qualitative = generate_qualitative_assessment(ticker, sections, filing_texts)
    except (filing_text.FilingTextError, QualitativeError) as exc:
        logger.warning("Qualitative layer skipped for %s: %s", ticker, exc)
        return None, True

    qualitative_dict = qualitative.model_dump()
    qualitative_cache.write(out_dir, ticker, filing_urls, qualitative_dict)
    return qualitative_dict, False


def finalize_company(state: dict, regime_info: dict, skip_ai: bool, out_dir) -> tuple[dict, dict, bool]:
    """Returns (company_doc, watchlist_summary, qualitative_failed).

    qualitative_failed is True only when this call actually attempted
    Buffett's moat read (skip_ai=False, a 10-K was found) and it errored -
    e.g. the Anthropic call failed (bad/missing key, no credit balance,
    rate limit) - never for a deliberate skip. This is what lets run_full
    report an honest sources_status["anthropic"] instead of just "ok"
    whenever --skip-ai wasn't passed, regardless of whether the call
    actually succeeded.
    """
    ticker, name, sector = state["ticker"], state["name"], state["sector"]
    metrics, display, profile = state["metrics"], state["display"], state["profile"]

    macro_adj = macro_regime.sector_adjustment(regime_info["regime"], sector)

    generated_at = writer.now_iso()
    clean_metrics = {k: v for k, v in metrics.items() if v is not None}

    if skip_ai:
        qualitative_out, qualitative_failed = None, False
    else:
        qualitative_out, qualitative_failed = _run_qualitative(state, out_dir)

    plain_analysis_doc = plain_analysis.build_plain_analysis(metrics)
    returns = performance.compute_returns(state["raw"]["price_history"])

    company_doc = {
        "ticker": ticker,
        "name": name,
        "cik": profile.get("cik"),
        "sector": sector,
        "industry": profile.get("industry"),
        "market_cap": profile.get("market_cap"),
        "website": profile.get("website"),
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
        "qualitative": qualitative_out,
        "plain_analysis": plain_analysis_doc,
        "sources": {"sec_filings": state["recent_filings"], "sec_companyfacts_url": state["companyfacts_url"]},
        "_errors": state["errors"],
    }

    summary = {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "price": display["price"],
        "returns": returns,
        "book_value_per_share": metrics.get("book_value_per_share"),
        "graham_criteria_passed": state["checklist"]["graham_defensive"]["passed"],
        "graham_criteria_total": state["checklist"]["graham_defensive"]["total"],
        "munger_quality_passed": state["checklist"]["munger_quality"]["passed"],
        "munger_quality_total": state["checklist"]["munger_quality"]["total"],
        "last_updated": generated_at,
    }

    return company_doc, summary, qualitative_failed


def _process_company(
    company_cfg: dict, regime_info: dict, benchmark_prices: list[dict], skip_ai: bool, out_dir, use_fmp: bool = True
) -> tuple[dict | None, bool, dict, dict | None, dict | None]:
    """Fetch, score, finalize, and write one company end-to-end. Used for
    both the cheap screen (skip_ai=True, whole universe) and the enriched
    finalist pass (skip_ai=False) - the same work either way, just whether
    finalize_company spends the Anthropic call (see module docstring - only
    the AI call is still gated to the small finalist subset; use_fmp is
    True in both phases in practice). Returns (summary, qualitative_failed,
    errors, company_doc, capital_efficiency_inputs); summary/company_doc/
    capital_efficiency_inputs
    are None if fetching or finalizing failed outright for this ticker
    (already logged), in which case the other fields are empty/zero and the
    caller should just skip it. company_doc lets callers pull the AI filing
    summaries back out for the finalists digest (build_filings_digest)
    without a second read from disk. capital_efficiency_inputs feeds the
    market-wide aggregate on the macro page
    (pipeline.scoring.capital_efficiency) - computed here, once per company,
    from the same raw statements already fetched for scoring, regardless of
    skip_ai/use_fmp (it needs no AI call and no FMP data)."""
    ticker = company_cfg["ticker"]
    try:
        state = fetch_and_score_company(company_cfg, regime_info, benchmark_prices, use_fmp=use_fmp)
    except Exception:
        logger.exception("Failed to process %s entirely, skipping", ticker)
        return None, False, {}, None, None

    capital_efficiency_inputs = capital_efficiency.company_capital_efficiency_inputs(
        state["raw"], state["profile"]
    )

    try:
        company_doc, summary, qualitative_failed = finalize_company(state, regime_info, skip_ai, out_dir)
    except Exception:
        logger.exception("Failed to finalize %s entirely, skipping", ticker)
        return None, False, state["errors"], None, None

    writer.write_company(out_dir, ticker, company_doc)
    return summary, qualitative_failed, state["errors"], company_doc, capital_efficiency_inputs


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

    fmp_error_count = 0
    sec_error_count = 0
    stooq_error_count = 0
    total_qualitative_failed = 0

    def _track_errors(errs: dict) -> None:
        nonlocal fmp_error_count, sec_error_count, stooq_error_count
        if any(not k.startswith("sec_") and k != "stooq" for k in errs):
            fmp_error_count += 1
        if any(k.startswith("sec_") for k in errs):
            sec_error_count += 1
        if "stooq" in errs:
            stooq_error_count += 1

    # Phase 1: cheap (no AI spend) screen over the WHOLE universe - see
    # module docstring. Every company still gets a full company_doc/detail
    # page; only the moat read is missing until (if) it becomes a finalist
    # below. use_fmp=True here too: Stooq (the free price source this was
    # designed to lean on for the whole universe) turned out to be blocked
    # from GitHub Actions runners in practice - see pipeline.fetch.stooq's
    # module docstring - so FMP is back to covering price for every company,
    # not just finalists, until a working free alternative exists.
    summaries = []
    capital_efficiency_inputs = []
    for company_cfg in companies:
        summary, _qualitative_failed, errs, _company_doc, ce_inputs = _process_company(
            company_cfg, regime_info, benchmark_prices, skip_ai=True, out_dir=out_dir, use_fmp=True
        )
        _track_errors(errs)
        if ce_inputs:
            capital_efficiency_inputs.append(ce_inputs)
        if summary is None:
            continue
        summaries.append(summary)

    # Rank + select each window's top performers per sector, from the cheap
    # screen above - pure price return, independent of any fundamentals check.
    top_n_per_sector = screening_config()["top_n_per_sector"]
    picks_by_sector = performance.select_top_performers(summaries, top_n_per_sector)
    finalist_tickers = {
        pick["ticker"] for windows in picks_by_sector.values() for picks in windows.values() for pick in picks
    }

    # Phase 2: AI-enrich only the selected finalists - the only place
    # Anthropic budget gets spent, unless --skip-ai keeps the whole run
    # cheap. Re-fetches rather than reusing phase 1's state (simpler than
    # threading cached raw data through; finalists are a small fraction of
    # the universe). A ticker can lead more than one window (and appear in
    # more than one of picks_by_sector's window lists within its sector), so
    # enrichment patches every slot it occupies, not just the first found.
    digest_entries = []
    if not args.skip_ai and finalist_tickers:
        summaries_by_ticker = {s["ticker"]: s for s in summaries}
        companies_by_ticker = {c["ticker"]: c for c in companies}
        for ticker in finalist_tickers:
            summary, qualitative_failed, errs, company_doc, _ce_inputs = _process_company(
                companies_by_ticker[ticker], regime_info, benchmark_prices, skip_ai=False, out_dir=out_dir, use_fmp=True
            )
            _track_errors(errs)
            if summary is None:
                continue
            total_qualitative_failed += int(qualitative_failed)
            summaries_by_ticker[ticker] = summary
            for windows in picks_by_sector.values():
                for picks in windows.values():
                    for i, pick in enumerate(picks):
                        if pick["ticker"] == ticker:
                            picks[i] = summary
            digest_entry = digest_entry_from_doc(company_doc)
            if digest_entry:
                digest_entries.append(digest_entry)
        summaries = list(summaries_by_ticker.values())

    if fmp_error_count:
        sources_status["fmp"] = "degraded"
    if sec_error_count:
        sources_status["sec_edgar"] = "degraded"
    if stooq_error_count:
        sources_status["stooq"] = "degraded"
    # Reflects whether Buffett's moat read actually succeeded, not just
    # whether it was attempted - a run with --skip-ai stays "skipped", but
    # otherwise this only reads "ok" when every finalist's call actually
    # came back with a result (e.g. a bad/expired key or an empty Anthropic
    # credit balance shows up here as "failed" rather than a misleading
    # "ok").
    if not args.skip_ai and finalist_tickers:
        if total_qualitative_failed >= len(finalist_tickers):
            sources_status["anthropic"] = "failed"
        elif total_qualitative_failed:
            sources_status["anthropic"] = "degraded"

    ce_cfg = capital_efficiency_config()
    risk_free_rate_pct = _risk_free_rate_pct(macro_data, ce_cfg["risk_free_rate_series"])
    macro_doc["capital_efficiency"] = capital_efficiency.aggregate_capital_efficiency(
        capital_efficiency_inputs, risk_free_rate_pct, ce_cfg
    )
    writer.write_macro(out_dir, macro_doc)

    writer.write_watchlist(out_dir, summaries, generated_at)
    writer.write_performance_picks(out_dir, picks_by_sector, generated_at, len(companies), top_n_per_sector)
    writer.write_filings_digest(out_dir, build_filings_digest(digest_entries, generated_at))
    writer.write_meta(
        out_dir,
        {
            "generated_at": generated_at,
            "pipeline_version": PIPELINE_VERSION,
            "watchlist_size": len(companies),
            "sources_status": sources_status,
            "qualitative_layer_failed": total_qualitative_failed,
        },
    )

    logger.info(
        "Done. Screened %d/%d companies, enriched %d finalists.",
        len(summaries),
        len(companies),
        len(finalist_tickers) if not args.skip_ai else 0,
    )
    return 0 if summaries else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    return run_full(args)


if __name__ == "__main__":
    sys.exit(main())
