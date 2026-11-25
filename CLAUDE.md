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
the gap only surfaced on an arbitrary on-demand lookup (at the time,
`api/lookup.py`, a Vercel function - since retired, see the 2026-11
addendum below; the same on-demand route now lives in `app.py`), which
the weekly pipeline run and its tests never exercise. Fixed in
`pipeline/fetch/sec_edgar.py::_ANNUAL_REPORT_FORMS` (now accepts both
`10-K` and `20-F`).

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

## Addendum (2026-11): moved to a local-only desktop app

GitHub Actions' scheduled weekly screen and the Vercel on-demand lookup
function (`api/lookup.py`, `vercel.json`) were both retired in favor of
`app.py` - a single local Flask app the user runs on their own computer
(`python app.py`), which serves the site, answers on-demand lookups at
`/api/lookup`, and runs full refreshes on demand at `/api/refresh` (see
README's "Running the app"). `pipeline/main.py`'s `--use-fmp` flag is now
off by default - free sources (SEC EDGAR + Stooq) cover the whole
universe, and Stooq's GitHub-Actions-runner block (see
`pipeline/fetch/stooq.py`'s module docstring) doesn't apply when running
from a home connection instead. Anything in this file referring to
`api/lookup.py`, a scheduled/cloud run, or FMP as the default path is
describing history, not the current architecture.

## Addendum (2026-11): SEC's Akamai front end TLS-fingerprints plain requests/curl as non-browser traffic

**Incident:** First real-machine run of `app.py` (a user's own Mac, not CI) got a
403 "Request Rate Threshold Exceeded" from SEC's Akamai front end on *every*
www.sec.gov/data.sec.gov endpoint tried - the ticker map, the submissions API,
even a plain Archives text file - with a fully compliant User-Agent and
browser-like headers (`Accept`, `Accept-Language`, etc. added and still 403'd).
The same exact URLs loaded fine in an actual browser on the same machine, same
network, same minute. Diagnosis went through several wrong turns before this:
first assumed it was the documented ~10 req/sec EDGAR fair-access limit (ruled
out - way under it); then assumed it was a stricter Akamai threshold specific to
the one large `company_tickers.json` static file (ruled out - `data.sec.gov`'s
small per-company submissions API 403'd too); then confirmed definitively with
`curl_cffi.requests.get(url, impersonate="chrome")` returning 200 on the exact
URL plain `requests`/curl had just 403'd. That's TLS/HTTP2 fingerprinting:
Akamai distinguishing a real browser's TLS handshake from `requests`/urllib3's
(or curl's) own distinguishable one, independent of headers or request volume.

**Fixed** by adding `impersonate` support to `pipeline/utils/http.py` (routes
through `curl_cffi` instead of plain `requests` when set) and setting
`impersonate: "chrome"` on every SEC EDGAR call (`pipeline/fetch/sec_edgar.py`
and `pipeline/fetch/filing_text.py`'s shared `_RATE` dict). FMP/FRED/Stooq
haven't shown this problem, so they're untouched - plain `requests`, no
behavior change. The ticker-map disk-caching fix below is still worth keeping
(re-fetching a large rarely-changing file on every lookup is wasteful
regardless), but it was NOT the actual fix for this 403 - don't re-attribute
this incident to "just a rate/caching problem" the way the first pass at it did.

**Lesson for any future SEC EDGAR (or similar gov/enterprise-WAF-fronted) 403
that survives a compliant User-Agent and full browser-like headers:** test
whether a real browser can load the exact same URL from the exact same
machine/network before assuming it's rate- or header-based. If the browser
succeeds and `curl`/`requests` don't, it's almost certainly TLS/HTTP2
fingerprinting (Akamai, Cloudflare, and similar WAFs all do this) - confirm
with `curl_cffi.requests.get(url, impersonate="chrome")` before building a
caching/backoff fix that won't actually address the real cause.

## Known, intentionally-deferred gap (as of 2026-10)

`pipeline/fetch/sec_edgar.py::latest_filings_by_form()`'s default form
tuple is still `("10-K", "10-Q", "8-K")` only - a foreign private
issuer's Recent Filings section renders empty (not broken, just empty)
since 20-F/6-K aren't recognized there. Extending it would also need new
`qualitative.filing_summary_20f`/`_6k` AI-summary fields end-to-end
(schema, prompt, cache keys, frontend `FILING_SUMMARY_KEY`) - a bigger
change than the metrics fix above. Don't do this speculatively; only pick
it up if the user actually asks for foreign filers' filing summaries.
