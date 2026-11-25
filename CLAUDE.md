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

**Follow-up incident, same feature:** the first version of
`_solve_stooq_challenge` had no upper bound on its brute-force loop - a fixed
difficulty was assumed. On a real run the loop hung with no error and no log
output, blocking the single-threaded Flask dev server from answering *any*
request (including an unrelated `curl` to `/api/lookup` made in a separate
terminal) until manually killed. Any CPU-bound "solve a puzzle" loop like this
one needs a wall-clock cap (`_MAX_CHALLENGE_SECONDS`, currently 20s) that gives
up and raises a normal, catchable error instead of trusting the difficulty will
always be small - the source serving the puzzle can raise its own difficulty at
any time, for any reason, with no warning.

**Resolution: Stooq was dropped entirely, not fixed further.** Even after
solving the puzzle correctly, the actual data request started coming back with
a flat "Access denied" - and critically, the *exact same URL in an actual
browser, on the same connection, got the same denial*. That's the signal that
ends the "find a cleverer workaround" loop: once a real browser is denied too,
there is no client-side fix left to try, scripted or not - continuing to probe
the same endpoint would have just kept adding failed attempts against
whatever's blocking it. `scraper.py::fetch_price` now uses Yahoo Finance's
`v8/finance/chart` JSON endpoint instead (the same one most free stock-data
tools use); `_solve_stooq_challenge` and the proof-of-work code above no
longer exist in this codebase - the lessons above are kept as general guidance
for a *different* future scrape target, not as a description of current code.
If Yahoo's endpoint ever shows the same "even a real browser gets denied"
symptom, apply the same test (real browser, same connection, same URL) before
spending time on a workaround - and if confirmed, switch sources again rather
than escalating tooling against a site-level block.

## Lesson: not every network failure is the remote site's fault - check which HTTP client is actually making the call

**Incident:** `fetch_news()`'s RSS feeds (`scraper.py::_parse_feed`) came back
empty with no error visible anywhere, on the same real machine where the price
fetch (via `requests`) worked fine. Adding logging (see the lesson above about
always logging an unexpected empty result) revealed the real cause:
`SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`.
`feedparser.parse(url)` fetches the URL itself through Python's stdlib
`urllib`, which uses the system/Python installation's own default SSL
context - on this machine, that context had no usable CA bundle configured.
`requests` never hit this because it bundles its own CA bundle via `certifi`
and doesn't depend on the system of being configured correctly at all.

**Fix:** have `requests` (`_session.get`) fetch the feed content, and pass
`feedparser.parse()` the raw bytes instead of a URL - feedparser then only
parses, never fetches, so every network call in this app now goes through the
one HTTP client already known to work reliably on this machine.

**Lesson:** when two pieces of code hit the same kind of resource (both are
"just fetching a URL") but only one fails, don't assume the site itself is at
fault - check whether they're actually using the same underlying HTTP client.
A library that does its own networking under the hood (feedparser, or any
other pre-`requests`-era or stdlib-based library) can have a completely
different, separately-configured network/SSL stack from the rest of the app,
even when it looks like "just another web request" from the outside.
