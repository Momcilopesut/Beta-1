# Weekly Stock Screener

This tool's primary purpose is a **weekly screen**: every Friday after the US market
closes, it scans a curated universe of companies and surfaces each sector's 5 best
price performers over five timeframes — weekly, monthly, quarterly, annual, and
5-year. This ranking is pure price return, deliberately independent of any
fundamentals check. Every company also gets its own full value-investing analysis on
its own detail page, asking one question three ways: **does this company own more
than it owes, is it a well-run business, and is the price fair for that?** — a
scheduled pipeline fetches company
fundamentals (Financial Modeling Prep + SEC EDGAR) and macroeconomic indicators (FRED)
and runs every company through a transparent, balance-sheet-first scoring model, basic
arithmetic, not growth projections or opaque composites, it just doesn't gate or
influence which tickers surface on the screen itself. The result is published as a
static site.

**This is not financial advice.** Every score is an automated estimate based on
public data and may contain errors or delays.

## How it works

```
config/watchlist.yaml (screening universe)  →  pipeline (screen → rank → AI-enrich finalists)  →  data/*.json  →  site/ (static, no build step)
```

- **Weekly Screener** (see the dedicated section below): the program's primary purpose.
  Every company in the screening universe gets its price return computed over 5
  timeframes; each sector's top 5 performers per timeframe become the site's homepage.
- **Data sources**: [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs)
  (fundamentals, prices), [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation)
  (filings + XBRL fundamentals fallback), [FRED](https://fred.stlouisfed.org/docs/api/fred/)
  (16 series spanning yields, inflation, the labor market, GDP, and more — see "Macro
  Overview" below).
- **Assets vs. Liabilities** (see the dedicated section below): the company's actual
  net worth (assets minus liabilities), computed straight from the balance sheet, is
  the headline figure on every company page — not buried under a dozen other metrics.
- **Scoring**: deterministic, config-driven, and deliberately small — see "Assets vs.
  Liabilities" and "Layered analysis" below. A rule-based macro regime classifier
  (`pipeline/scoring/macro_regime.py`) provides cycle context alongside the scores.
- **Value-investing checklists** (`pipeline/scoring/value_investing.py`): a Defensive
  Checklist and a Quality Checklist, computed from the same fetched statements — no
  extra API calls, simple pass/fail arithmetic. Shown on every company's own detail
  page; the weekly screen itself ranks by price return instead (see "Weekly
  Screener" below).
- **Layered analysis** (a quality checklist read → a qualitative moat read →
  a fair-value margin-of-safety gate, see "Layered analysis" below): a deeper pass per
  company that reads the company's own 10-K text — the only AI call in this pipeline,
  and the only place it isn't grounded solely in pre-computed metrics. The same call
  also writes short, neutral summaries of the company's latest 10-K, 10-Q, and 8-K,
  shown on its detail page's Recent Filings section and rolled up across every
  finalist on the **Filings Digest** page (see below). Only runs for tickers that
  make at least one timeframe's top-5 list — see "Weekly Screener" below.
- **Economic-cycle context**: the macro page frames the current regime against classic
  business-cycle/sector-rotation theory (which sectors have historically led/lagged in
  this phase) — textbook reference, explicitly not a prediction.
- **Site**: plain HTML/CSS/JS, no framework, no build step — reads the generated JSON
  directly. The homepage shows each sector's top performers across 5 timeframes,
  GICS-style sector by sector; the search box reaches every company in the screening
  universe (instant filter; Enter jumps to any ticker, tracked or not). Every company
  page also links to its own investor-facing corporate site (from FMP's profile data,
  when available) and lists its latest 10-K/10-Q/8-K with a direct SEC link each.
- **On-demand lookup** (`api/lookup.py`, optional): a search for a ticker outside the
  screening universe offers a live, on-demand run through the exact same pipeline code,
  via a small backend deployed separately (see "On-demand lookup deployment" below).
  The static site works fully without this — it's an opt-in extra.

## Weekly Screener

The program's primary purpose: every Friday at 21:30 UTC (`.github/workflows/
weekly-screen.yml`) — genuinely "after the ~4pm ET close" year-round regardless of
DST — the pipeline runs a two-phase screen over `config/watchlist.yaml`'s curated
universe (88 companies, 8 per sector across 11 GICS-style sectors; not the full S&P
500, to stay well inside a free-tier API budget), ranking purely by price return, not
by any fundamentals check:

1. **Cheap screen, whole universe** (`pipeline/main.py::run_full`, phase 1) — every
   company gets fetched and scored (full fundamentals scoring included, for its own
   detail page), with the AI qualitative (moat read) layer skipped entirely. Each
   company's price return over 5 lookback windows
   (`pipeline/scoring/performance.py::compute_returns`) comes straight from price
   history already fetched for it - no extra API calls.
2. **Rank + select** (`pipeline/scoring/performance.py::select_top_performers`) —
   within each sector, companies are ranked by price return, independently for each of
   5 windows: weekly (7 days), monthly (30 days), quarterly (91 days), annual (365
   days), and 5-year (1825 days). A company missing a return for a given window (not
   enough price history) is excluded from that window's ranking only, never guessed
   at. The top `config/screening.yaml`'s `top_n_per_sector` (5 by default) per
   sector, per window become this week's finalists - a sector can show up to 25
   distinct tickers across its 5 windows, with overlap when the same stock leads more
   than one.
3. **AI-enrich finalists only** (phase 2) — every ticker that made at least one
   window's top-5 list gets re-scored with the moat read (plus short 10-K/
   10-Q/8-K summaries) turned on, so Anthropic spend scales with the number of
   tickers actually shown, not the size of the universe scanned.

Every scanned company — not just the picks — still gets a full `data/companies/
{ticker}.json` and detail page, complete with its own Layered Analysis;
`data/performance_picks.json` holds just the ranked selection the homepage
renders (plus each window's key/label), and `data/watchlist.json` keeps covering the
whole universe so the search box can still find anything scanned. Run it locally with
`python -m pipeline.main --dry-run` (see "Local development" below); pass `--tickers`
to test the two-phase flow on a small subset before running the real thing.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in your API keys
```

Run the pipeline:

```bash
python -m pipeline.main --tickers AAPL,MSFT --dry-run   # writes to data/.dry-run/, doesn't touch tracked data/
python -m pipeline.main --skip-ai                        # cheap screen only, no Anthropic spend, no finalist enrichment
python -m pipeline.main                                   # full weekly screen over the whole universe, writes data/
```

Run the tests (pure functions + fixtures, no network, no API keys needed):

```bash
pytest
```

Preview the site:

```bash
./scripts/dev_server.sh
# open http://localhost:8000/site/index.html
```

`data/` currently holds synthetic sample data (see `scripts/generate_sample_data.py`)
so the site is browsable before you've run the pipeline for real — running
`python -m pipeline.main` with real API keys overwrites it.

## Data source limits and free backup chain

FMP's free tier does not cover every `/stable/` endpoint this pipeline calls — in
practice, calls beyond a fairly small allowance return `402 Payment Required` rather
than data. `data/meta.json`'s `sources_status.fmp` reads `"degraded"` when that
happens, and per-company `_errors` include the real HTTP status (e.g. `401`, `402`) so
an invalid-key problem is distinguishable from a plan-limit problem at a glance.

Rather than requiring a paid plan, the pipeline falls back to two free, no-key sources
whenever FMP's own statement/price endpoints come back empty:

- **SEC EDGAR XBRL** (`pipeline/fetch/sec_edgar.py::xbrl_fundamentals`) — synthesizes
  income statement, balance sheet, and cash flow rows directly from official filings,
  shaped to match FMP's own field names so every downstream calculation (the
  assets/liabilities/equity figures, ratios, the value-investing checklists) works
  unchanged regardless of which source populated it.
- **Stooq** (`pipeline/fetch/stooq.py`) — free daily close price, used only when FMP's
  price/quote data is missing, so the price side of every valuation check still works.

`sources_status.stooq` in `data/meta.json` reports whether the fallback itself is
working. If you still want fuller coverage: upgrade the FMP plan, trim
`config/watchlist.yaml` to use fewer calls per run, or swap in a different primary
provider (e.g. Finnhub's free tier) in `pipeline/fetch/`.

## Assets vs. Liabilities

The most basic question in investing, and the one this whole tool is organized
around: if a company sold everything it owns and paid off everything it owes, would
there be anything left over — and is the stock price fair for that?

- **Total assets, total liabilities, shareholders' equity (net worth), book value per
  share** — computed straight from the latest balance sheet in
  `pipeline/scoring/fundamentals.py`, no derived assumptions. This is the first thing
  shown on every company page.
- **NCAV margin** (`ncav_margin_pct`) — the strictest test here: even just the
  company's *current* assets (cash, receivables, inventory), after paying off *every*
  liability, compared against the whole stock's price. Almost always sharply negative
  for a normal large-cap — a rare positive reading is itself the interesting fact.
- **Fair-value estimate** (`graham_number`/`graham_upside_pct`) — `sqrt(22.5 × EPS ×
  book value per share)`, a single closed-form formula combining earnings and net
  worth per share. This is the pipeline's valuation check — no multi-year growth
  projection or discount-rate assumption, unlike a DCF.
- **Debt/equity, debt/EBITDA, current ratio** — how much of the company is borrowed vs.
  actually owned, and whether short-term assets cover short-term debts.
- **P/E and P/B** — the two simplest "is the price fair" ratios, kept alongside the
  fair-value estimate rather than instead of it.

A number of more sophisticated frameworks — a discounted cash flow model, a
qualitative checklist, a cross-sectional ranking formula, a growth-type
categorization, a synthesized investment thesis, the academic Piotroski F-Score, a
dynamic margin-of-safety scaling — were built across earlier iterations of this tool
and then deliberately retired, leaving a deliberately small set of checks. The goal is
a tool whose logic you could explain to someone with no finance background: compare
what's owned to what's owed, check whether the price is fair for that, and use two
simple checklists to catch the rest.

## 5-Year Trend

A single snapshot hides whether a company's numbers are getting better or worse, and
whether a good (or bad) year was really about the company, or just the whole market
moving. Every company page also charts the last 5 fiscal years (`pipeline/scoring/
history.py`, from the same annual statements FMP already provides — no extra API
calls per company):

- **Total revenue, net profit, debt, spending, and cash reserve, year by year** — each
  straight off that year's income statement or balance sheet, shown as five small
  multiples you tap to compare. Select 2–5 metrics and they overlay in one chart, each
  independently scaled to its own range (so a $400B and a $30B metric can share the
  same picture) and kept in its own color. Tap a year along the bottom to pop up every
  metric you're currently comparing at that year — its value and year-over-year change,
  side by side — rather than one point at a time.
- **This stock's return vs. the market, same years** — each fiscal year's stock price
  change compared against **SPY** (an S&P 500 index fund) over that same period, so a
  bad year for the stock can be read against whether the whole market was also down
  that year, or whether it lagged (or beat) everyone else. SPY was chosen because it's
  a single, well-known ticker that trades like any other US equity on FMP's free tier —
  unlike a raw index symbol, it needs no special plan access, and it's fetched once per
  pipeline run (not once per company) since every company is compared to the same
  market.
- Any year or value that can't be computed (a missing statement, no price data close
  enough to a fiscal year end) shows as genuinely missing, never a guessed or
  zero-filled number — the same rule the rest of this pipeline follows.

## Layered analysis

A deeper pass per company, deliberately kept as separate layers rather than one
blended score — a great quality checklist with a broken moat should get flagged, not
averaged away, and a great business at a bad price still isn't a buy. Every company
detail page shows each layer, plus an `overall` synthesis and a `flags` list
explaining any disagreement between them. Exactly three investors, nothing else —
easy-to-check fundamentals throughout, not exotic ratios (no ROIC, no DCF, no
EV/EBITDA — see "Assets vs. Liabilities" above for why).

1. **Quality checklist** (`pipeline/scoring/value_investing.py::munger_quality_checklist`) —
   return on equity ≥ 15%, debt/equity ≤ 1.0, no shareholder dilution, and margins
   stable or improving. Pure arithmetic, no AI.
2. **Moat read** (`pipeline/narrative/qualitative_client.py`) — Claude reads
   excerpts from the company's own most recent 10-K (Business, Risk Factors, and
   Management's Discussion and Analysis, extracted by
   `pipeline/fetch/filing_text.py`) and classifies the moat (network effects / cost
   advantage / intangible assets / switching costs / efficient scale / none — the
   classic moat-investing categories) and lists any red flags the filing
   itself raises. **This is the only AI call in the whole pipeline, and the one place
   it reads raw text instead of only pre-computed metrics** — there's no mechanical
   fact-checking possible for free-form filing prose the way there would be for a
   fixed metrics dict, so this layer's grounding is prompt discipline only, not
   code-verified. `qualitative.extraction_confidence` tells you whether the
   filing-text extraction itself found a clean Item 7 section match or fell back to a
   raw document prefix, so you know how much to trust it.

   The same call also writes short, neutral 2-4 sentence summaries of the company's
   latest 10-K, 10-Q, and 8-K (`qualitative.filing_summary_10k`/`_10q`/`_8k`, shown on
   the company page's Recent Filings section, one Anthropic call handles all of it
   rather than three) — grounded the same way, and left `null` (never guessed) for a
   filing type the company hasn't recently filed. `pipeline/fetch/sec_edgar.py::
   latest_filings_by_form` finds each of the three independently, so a burst of
   recent 8-Ks (a company can file 10-20+/year, vs. one 10-K and ~3 10-Qs) can't crowd
   out the latest 10-Q/10-K. Results are cached by all three filing URLs together
   under `data/qualitative_cache/` — a weekly refresh skips the filing fetch and the
   Claude call entirely only when none of the three have changed since the last run,
   so a fresh 10-Q or 8-K correctly invalidates the cache even when the 10-K itself
   hasn't. Only runs for a company that has a 10-K on file — cost control against the
   whole universe happens one level up, in the weekly screen's two-phase design (see
   "Weekly Screener" above): this layer, filing summaries included, only ever runs
   for that week's per-sector finalists. Every company (finalist or not) still gets
   its latest 10-K/10-Q/8-K listed with a direct SEC link on its own page — it's just
   the AI summary of each that's finalists-only.
3. **Valuation gate** — not a separate module or AI call, just the fair-value
   estimate's margin of safety already computed in `fundamentals.py`
   (`graham_upside_pct = sqrt(22.5 × EPS × book value/share)` vs. price). No growth
   projection or discount-rate assumption, unlike a DCF (see "Assets vs.
   Liabilities" above for why that trade-off was made deliberately).

`pipeline/scoring/aggregation.py` combines the three gates (quality checklist
present/absent, qualitative moat present/absent, valuation margin of safety) into
the `overall` summary and `flags` — e.g. a company with a strong quality checklist
but no moat gets flagged explicitly rather than the checklist quietly winning out in
an average. The required margin of safety is a single flat number, a 15% convention
used throughout this tool — an earlier version of this pipeline scaled it
dynamically with data coverage and filing red flags, which has been removed for
simplicity. See `required_margin_of_safety_pct` in the output.

Each company page shows these three gates (and the checklists behind them)
separately — deliberately not combined into a single blended score.

## Macro Overview

The macro page (`site/macro.html`) tracks 16 FRED series across the indicators that
move the broad economy most: the full Treasury yield curve plus the 10Y-2Y spread,
both inflation gauges (CPI and the Fed's own preferred PCE Price Index), the labor
market (unemployment rate, nonfarm payrolls, initial jobless claims), the Fed funds
rate, real GDP, industrial production, consumer sentiment, and M2 money supply.

Each series carries a rule-based **mood** — an emoji + short label summarizing
whether its trajectory over the past year reads as favorable, mixed, or concerning
(`pipeline/scoring/macro_mood.py`). Mood is deliberately not a single "up = good"
rule: a series' `mood.direction` in `config/macro_series.yaml` classifies it as
`higher_better` (payrolls, GDP, industrial production, consumer sentiment —
growth is generically good), `lower_better` (unemployment, jobless claims — fewer
is generically better), `target` (CPI and PCE — the Fed targets ~2%, not 0%, and
outright deflation is flagged as its own concerning case), or `context` (Treasury
yields, the Fed funds rate, M2 — direction is genuinely ambiguous among economists,
so mood instead reads how much the series moved, calm vs. volatile). One
structural exception: the 10Y-2Y spread's mood overrides its ordinary banding
entirely when the curve is inverted, reusing the same "yield curve inverted"
concept `macro_regime.py`'s regime classifier already treats as a recession-risk
signal, rather than a second copy of that rule. Every threshold lives in each
series' own `mood` block in `config/macro_series.yaml` — no ML, fully inspectable
and tunable without touching code.

Fetch history is sized per series to its own calendar frequency
(`history_limit`/`obs_per_year` in `config/macro_series.yaml`) rather than one flat
observation count — a flat count would starve the daily Treasury-yield series of a
real year of history while over-fetching the quarterly GDP series.

Tapping any series card ("What is this?") expands its glossary entry
(`site/js/macro-glossary.js`) — what the series is, why it's economically
significant, and how its volatility specifically affects the broader economy —
the same tap-to-expand pattern the company page's Key Metrics Reference uses.

### Market Capital Efficiency

The macro page also shows a bottom-up, market-wide read on capital efficiency —
**ROIC**, **Reinvestment Rate**, **Expected Growth**, **WACC**, and **Value
Creation** (ROIC − WACC) — computed across every tracked company's own latest
financial statements (`pipeline/scoring/capital_efficiency.py`). No aggregate data
vendor (Compustat, FactSet, a Bloomberg terminal) is needed: this pipeline already
fetches every one of these companies' statements individually, every run, so the
aggregate is just those same numbers summed.

```
ROIC = aggregate NOPAT / aggregate Invested Capital
Reinvestment Rate = (aggregate CapEx - aggregate Depreciation + aggregate Change in Working Capital) / aggregate NOPAT
Expected Growth = ROIC x Reinvestment Rate
```

A company missing any one input (operating income, tax figures, CapEx, debt, ...) is
simply excluded from that one sum, never counted as a zero — each aggregate's own
`coverage` count in `data/macro.json` says how many companies it was actually built
from. **WACC** is a deliberately simplified CAPM proxy: the latest 10-year Treasury
yield (already tracked above) plus a configured equity risk premium as the cost of
equity, with beta assumed to be 1.0 — this is being measured against the aggregate
market itself, not one stock's volatility relative to it — blended with an
after-tax cost of debt, weighted by aggregate market cap vs. aggregate debt. Both
the equity risk premium and the fallback tax rate are documented, adjustable
estimates in `config/capital_efficiency.yaml`, not values derived from live data.

Each card is color-coded green/yellow/red the same way the company page's Key
Metrics Reference is, using thresholds from that same config file — Reinvestment
Rate and WACC are always shown neutral, since neither has an inherent "good"
direction on its own (a high reinvestment rate is only good or bad relative to the
growth it buys, which Expected Growth already captures).

## Filings Digest

`site/filings-digest.html` rolls up this week's per-sector finalists' AI-summarized
SEC filings (`qualitative.filing_summary_10k`/`_10q`/`_8k`, see "Layered analysis"
above) into a single page, instead of reading them one company page at a time. It
does no new fetching and spends no extra Anthropic budget — it's built directly from
`build_filings_digest`/`digest_entry_from_doc` in `pipeline/main.py`, which just
gather the filing summaries `finalize_company` already generated for that week's
finalists and write them to `data/filings_digest.json` alongside everything else the
weekly screen produces. A company that isn't a finalist that week (or has no 10-K on
file at all) simply doesn't appear — see its own company page for its filing list
either way.

## Metrics Glossary

Every metric this tool scores on (`site/js/metrics-glossary.js`) carries a short
explanation, its economic significance, and how swings in it actually affect the
business — not just the number. Shown as a **Key Metrics Reference** section on
every company page — this company's own current value next to each explanation,
tap any row to expand it. A standalone, no-per-company-numbers version of the same
content still exists at `site/glossary.html`, just no longer linked from the nav —
the per-company view already covers the same explanations in context.

## Configuration

- `config/watchlist.yaml` — the screening universe. Edit freely.
- `config/sector_macro_sensitivity.yaml` — how much each sector's macro adjustment
  moves under each regime.
- `config/macro_series.yaml` — which FRED series are pulled, how much history each
  one fetches, the regime classification thresholds, and each series' mood
  direction/thresholds (see "Macro Overview" above).
- `config/screening.yaml` — `top_n_per_sector`, how many companies the weekly screen
  surfaces per sector, per timeframe (see "Weekly Screener" above).
- `config/capital_efficiency.yaml` — the equity risk premium and fallback tax rate
  used by the Market Capital Efficiency WACC estimate, plus its ROIC/Expected
  Growth color-band thresholds (see "Macro Overview" above).

## Deployment

`.github/workflows/weekly-screen.yml` runs the pipeline on a schedule (Fridays at
21:30 UTC by default — see the cron comment in that file), commits updated
`data/*.json`, and deploys `site/` + `data/` to GitHub Pages. It can also be triggered
manually from the Actions tab (`workflow_dispatch`), optionally with a `dry_run` flag
or a specific `tickers` list (handy for testing the two-phase screen on a small subset
before running it over the whole universe).

One-time setup required in the repo's GitHub settings:

1. **Settings → Pages → Source: GitHub Actions.**
2. **Settings → Secrets and variables → Actions**, add secrets `FMP_API_KEY`,
   `FRED_API_KEY`, `ANTHROPIC_API_KEY`, and a repo **variable**
   `SEC_EDGAR_USER_AGENT` (a descriptive contact string SEC EDGAR requires on every
   request — do not put a personal email in a public repo's variables/logs).

Once deployed, the dashboard lives at `<pages-url>/site/index.html` (the Pages root
redirects there automatically).

`.github/workflows/tests.yml` runs `pytest` on every push/PR — no secrets or network
required.

## On-demand lookup deployment (optional)

Searching a ticker that isn't tracked offers a live analysis via `api/lookup.py`, a
small Flask app deployed as a [Vercel](https://vercel.com) Python serverless function
— GitHub Pages can't run server code, so this needs separate hosting. Skipping this
section is fine; the rest of the site works without it, and an untracked search will
just say live lookup isn't configured.

This runs the **full pipeline** for that one ticker, right then — qualitative (10-K
moat reasoning plus 10-K/10-Q/8-K summaries) and the complete fundamentals scoring,
identical to a tracked company. It's a real 10-K (plus 10-Q/8-K, when found) fetch
plus one Claude call for a single request, which takes real
time.

**Timeout headroom:** `vercel.json` sets `maxDuration: 60` — the maximum a Vercel
Hobby (free) plan allows by default. If a lookup is timing out, you have two free
options before paying for anything: enable **Fluid Compute** (Vercel project →
**Settings → Functions** → toggle it on) to raise Hobby's ceiling to 300s, then bump
`maxDuration` in `vercel.json` to match and redeploy; or pass `?ai=0` to skip the
qualitative moat read entirely (removes the slowest step, at the cost of that
layer showing as not evaluated). A Pro plan raises the ceiling further (300s by
default, more with Fluid Compute) if you have one.

**Why a separate deployment, and why it's gated:** every live lookup spends real FMP/
Anthropic API budget (it runs the full pipeline for one ticker, right then). Left
open with no key, anyone who finds the URL could run up your usage. Set
`SEARCH_API_KEY` to require a shared secret; if you leave it unset, the endpoint is
open to anyone with the URL — only reasonable for a private deployment you don't share.

**Setup:**

1. Create a free [Vercel](https://vercel.com) account and import this repository as a
   new project (Vercel auto-detects `api/lookup.py` as a Python serverless function
   and `vercel.json` for its config — no build settings to change).
2. In the Vercel project's **Settings → Environment Variables**, add the same keys as
   the GitHub Actions secrets (these are separate stores — copy the values over):
   `FMP_API_KEY`, `FRED_API_KEY`, `ANTHROPIC_API_KEY`, `SEC_EDGAR_USER_AGENT`, plus a
   new `SEARCH_API_KEY` (any string you choose — this is the shared secret from above).
3. Deploy. Note the resulting URL (e.g. `https://your-project.vercel.app`).
4. On the live site, search for a ticker that isn't tracked and click "Run live
   analysis" — the first time, it'll prompt for the Vercel URL and your
   `SEARCH_API_KEY` value, then remember both in the browser's local storage (per
   browser/device — visitors without the key just get a 401 from the API).

Local dev: `python api/lookup.py` runs a dev server at `http://localhost:5328`; point
`lookupApiBase` (see `site/js/shared.js`) at that instead of a Vercel URL to test
end-to-end without deploying.
