# Developer protocol for this repo

Read automatically by Claude Code at the start of every session here. It exists to
carry lessons from real incidents forward, so the same mistake doesn't ship twice.

## Project reset (2026-11)

This repo was a much larger stock-screening project before this point (a scored
watchlist, value-investing checklists, a macro overview page, moat analysis, a
filings digest, Buffett/Graham/Munger-style scoring - ~170 completed build tasks).
It was deliberately wiped and rebuilt from scratch as a small, local-only tool:
search a ticker, scrape free price + news data for it, summarize it with a local
LLM. If you're looking for any of the old features, they're gone on purpose, not
missing by accident - don't try to resurrect them unless the user explicitly asks.
The one piece of that project worth carrying forward is the lesson below, which
applies to scraping any site, not just the one that taught it.

## Lesson: a real anti-bot 403 can be TLS fingerprinting, not a rate or header problem

**Incident:** The old project's SEC EDGAR fetching got 403 "Request Rate Threshold
Exceeded" from SEC's Akamai front end on a real user's machine - on every
www.sec.gov/data.sec.gov endpoint tried, well under the documented ~10 req/sec
limit, with a fully compliant User-Agent and complete browser-like headers
(`Accept`, `Accept-Language`, etc.). The identical URL loaded fine in an actual
browser on the same machine, same network, same minute. Several wrong diagnoses
were tried first (rate limiting, then a stricter per-file threshold on one large
static file) before confirming the real cause: `curl_cffi.requests.get(url,
impersonate="chrome")` returned 200 on the exact URL plain `requests`/`curl` had
just 403'd. That's TLS/HTTP2 fingerprinting - Akamai (and Cloudflare and similar
enterprise WAFs) can distinguish a real browser's TLS handshake from
`requests`/urllib3's or curl's own distinguishable one, independent of headers or
request volume.

A second trap on the way to the real fix: merging a caller's own identifying
header (e.g. a `User-Agent` naming this tool) on top of an impersonated Chrome TLS
handshake *still* got 403'd - a TLS fingerprint that looks like Chrome paired with
a header set that doesn't is its own inconsistency, possibly more obvious than an
honest non-browser signature alone. The fix was to let curl_cffi's impersonate
preset own the entire header set, not just the TLS layer, when impersonating.

**If a future scrape target in this app returns a 403 that survives a compliant
User-Agent and full browser-like headers:**

1. Test whether a real browser can load the exact same URL from the exact same
   machine/network before assuming it's rate- or header-based.
2. If the browser succeeds and `curl`/`requests` don't, confirm with
   `curl_cffi.requests.get(url, impersonate="chrome")` before building anything
   else - a caching or backoff fix won't address TLS fingerprinting.
3. If that confirms it, use `curl_cffi` for that call and let it set its own
   headers - don't merge a custom User-Agent or other identifying header on top of
   an impersonated handshake. `curl_cffi` is NOT currently a dependency of this
   app (it was removed in the project reset above along with the code that needed
   it) - add it to `requirements.txt` if this ever comes up again here.
4. This app currently uses RSS feeds for news specifically *because* RSS is built
   for automated readers and doesn't hit this problem - prefer a source like that
   over scraping a site's HTML pages when one exists, rather than reaching for
   TLS impersonation as the first move.

## Lesson: a 403/challenge page isn't always unsolvable - check if it's a real, computable puzzle first

**Incident:** Stooq's free daily-CSV price endpoint (`scraper.py::fetch_price`)
was observed, on a real user's machine, returning an HTML page instead of CSV -
a client-side proof-of-work challenge: find `n` such that `sha256(challenge + n)`
has a given number of leading hex-zero characters, then POST `{c: challenge, n}`
to `/__verify` before the real content is served. Unlike SEC EDGAR's TLS
fingerprinting above, this is NOT "look like a browser" - it's a literal puzzle
with a literal answer, fully visible in the page's own inline `<script>`. Fixed by
replicating that exact algorithm in Python (`scraper.py::_solve_stooq_challenge`)
and reusing a `requests.Session()` so the verification cookie persists across
later lookups in the same run, rather than switching to a different price source.

**Lesson:** before concluding a scrape target needs a heavier workaround (TLS
impersonation, a browser automation tool, or abandoning the source entirely), read
what the blocking page actually contains. A "please enable JavaScript" page with
an inline script computing a hash and POSTing the result is a solvable puzzle, not
a wall - replicate the algorithm server-side instead of reaching for a browser.
Save the heavier tools for when the page genuinely requires rendering (real
CAPTCHAs, or a check that depends on browser-only APIs/behavior a script can't
replicate).
