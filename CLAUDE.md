# Developer protocol for this repo

Read automatically by Claude Code at the start of every session here. It
exists to carry lessons from real incidents forward, so the same mistake
doesn't ship twice.

## Protocol: changing or narrowing a fetch/fallback data source

**Incident (2026-10):** FMP's statement endpoints (income/balance/cash
flow, ratios, key-metrics) were dropped in favor of SEC EDGAR XBRL as "a
complete fallback chain" (see README's free-tier-sustainability section).
The fallback's annual-fact filter was hardcoded to `form == "10-K"`.
GlobalFoundries (GFS) and every other foreign private issuer files Form
20-F instead of 10-K, so the fallback silently returned empty statement
rows for them - cascading into a near-totally-blank Key Metrics Reference
for any such ticker. Nobody caught it before shipping because the tracked
watchlist (`data/companies/*.json`) only contains domestic 10-K filers;
the gap only surfaced on an arbitrary on-demand lookup
(`api/lookup.py`), which the weekly pipeline run and its tests never
exercise. Fixed in `pipeline/fetch/sec_edgar.py::_ANNUAL_REPORT_FORMS`
(now accepts both `10-K` and `20-F`).

Before dropping, consolidating, or re-scoping ANY fetch source (FMP, SEC
EDGAR, Stooq, FRED, ...) in favor of a fallback - or narrowing what a
fallback matches on (a form type, a field name, a unit) - do this:

1. Enumerate what the fallback does *not* cover - not just missing
   fields, but missing filer shapes: foreign private issuers (20-F annual
   / 6-K interim, instead of 10-K/10-Q/8-K), non-USD reporters, ADRs,
   recent IPOs with under a year of filing history.
2. If the change touches `pipeline/fetch/sec_edgar.py`, test it against
   at least one known non-10-K filer in addition to a normal domestic
   one. GFS (CIK 1709048) is the known case on file - see
   `tests/test_free_fallback_sources.py::test_xbrl_fundamentals_synthesizes_rows_for_20f_foreign_private_issuer`.
3. Remember the on-demand lookup path reaches *any* ticker a user types,
   not just the ~900 in `config/watchlist.yaml`. A fix or test that only
   covers the watchlist universe can still ship a total-blankness bug for
   every other ticker on earth - verify both paths, not just the batch
   pipeline.
4. Add a regression test with a concrete edge-case fixture before
   shipping - don't just eyeball one real-world ticker in a browser and
   call it done.

## Known, intentionally-deferred gap (as of 2026-10)

`pipeline/fetch/sec_edgar.py::latest_filings_by_form()`'s default form
tuple is still `("10-K", "10-Q", "8-K")` only - a foreign private
issuer's Recent Filings section renders empty (not broken, just empty)
since 20-F/6-K aren't recognized there. Extending it would also need new
`qualitative.filing_summary_20f`/`_6k` AI-summary fields end-to-end
(schema, prompt, cache keys, frontend `FILING_SUMMARY_KEY`) - a bigger
change than the metrics fix above. Don't do this speculatively; only pick
it up if the user actually asks for foreign filers' filing summaries.
