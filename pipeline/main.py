"""CLI entrypoint for the weekly screening pipeline - this project's primary
purpose: scan a curated universe of stocks (config/watchlist.yaml) and
surface each sector's 5 best price performers over five lookback windows
(weekly, monthly, quarterly, annual, 5-year), every week. This ranking is
pure price return - it does not use the Investment Meter or any Graham/
Buffett/Munger check. Every company still gets the full fundamentals
scoring on its own detail page; it just doesn't gate or influence which
tickers surface on the screen itself.

Usage:
  python -m pipeline.main                         # full screen over the whole universe
  python -m pipeline.main --tickers AAPL,MSFT      # run over a subset
  python -m pipeline.main --dry-run                # write to data/ locally, no commit (commit is CI's job)
  python -m pipeline.main --skip-ai                 # fetch + score only, no Anthropic spend

Two phases (see run_full):
  1. A cheap screen (fetch_and_score_company + finalize_company with
     skip_ai=True) over the WHOLE universe - no Anthropic spend. Price
     returns come straight from history already fetched for every company
     (pipeline.scoring.performance.compute_returns), so this alone is
     enough to rank and select each window's top performers per sector
     (pipeline.scoring.performance.select_top_performers).
  2. AI enrichment (skip_ai=False) of just the selected finalists - Buffett's
     10-K moat read plus short neutral summaries of the latest 10-K/10-Q/8-K,
     the only place Anthropic budget gets spent. Every company (finalist or
     not) still gets its latest 10-K/10-Q/8-K listed with a direct SEC link
     and, when available, a company-website link - it's just the AI summary
     of each filing that's finalists-only.
"""

import argparse
import logging
import sys

from pipeline.build import qualitative_cache, writer
from pipeline.fetch import filing_text, fmp, fred, sec_edgar, stooq
from pipeline.narrative.qualitative_client import QualitativeError, generate_qualitative_assessment
from pipeline.scoring import aggregation, history, macro_regime, performance, value_investing
from pipeline.scoring.fundamentals import build_metrics, normalize_price_rows
from pipeline.utils.config import macro_series, screening_config, watchlist

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

    layered_analysis = aggregation.build_layered_analysis(qualitative_out, metrics, state["checklist"])
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
        "layered_analysis": layered_analysis,
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
        "qualitative_moat_present": layered_analysis["qualitative_moat_present"],
        "munger_quality_pass": layered_analysis["munger_quality_pass"],
        "valuation_gate_pass": layered_analysis["valuation_gate_pass"],
        "conviction_score": layered_analysis["conviction_score"],
        "conviction_verdict": layered_analysis["conviction_verdict"],
        "last_updated": generated_at,
    }

    return company_doc, summary, qualitative_failed


def _process_company(
    company_cfg: dict, regime_info: dict, benchmark_prices: list[dict], skip_ai: bool, out_dir
) -> tuple[dict | None, bool, dict]:
    """Fetch, score, finalize, and write one company end-to-end. Used for
    both the cheap screen (skip_ai=True, whole universe) and the AI-enriched
    finalist pass (skip_ai=False) - the same work either way, just whether
    finalize_company spends the Anthropic call. Returns (summary,
    qualitative_failed, errors); summary is None if fetching or finalizing
    failed outright for this ticker (already logged), in which case the
    other fields are empty/zero and the caller should just skip it."""
    ticker = company_cfg["ticker"]
    try:
        state = fetch_and_score_company(company_cfg, regime_info, benchmark_prices)
    except Exception:
        logger.exception("Failed to process %s entirely, skipping", ticker)
        return None, False, {}

    try:
        company_doc, summary, qualitative_failed = finalize_company(state, regime_info, skip_ai, out_dir)
    except Exception:
        logger.exception("Failed to finalize %s entirely, skipping", ticker)
        return None, False, state["errors"]

    writer.write_company(out_dir, ticker, company_doc)
    return summary, qualitative_failed, state["errors"]


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
    total_qualitative_failed = 0

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
    # page; only the moat read is missing until (if) it becomes a finalist
    # below.
    summaries = []
    for company_cfg in companies:
        summary, _qualitative_failed, errs = _process_company(
            company_cfg, regime_info, benchmark_prices, skip_ai=True, out_dir=out_dir
        )
        _track_errors(errs)
        if summary is None:
            continue
        summaries.append(summary)

    # Rank + select each window's top performers per sector, from the cheap
    # screen above - pure price return, independent of the Investment Meter.
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
    if not args.skip_ai and finalist_tickers:
        summaries_by_ticker = {s["ticker"]: s for s in summaries}
        companies_by_ticker = {c["ticker"]: c for c in companies}
        for ticker in finalist_tickers:
            summary, qualitative_failed, errs = _process_company(
                companies_by_ticker[ticker], regime_info, benchmark_prices, skip_ai=False, out_dir=out_dir
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

    writer.write_watchlist(out_dir, summaries, generated_at)
    writer.write_performance_picks(out_dir, picks_by_sector, generated_at, len(companies), top_n_per_sector)
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
