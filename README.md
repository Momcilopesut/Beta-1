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
  Liabilities" and "Plain-Language Analysis" below. A rule-based macro regime
  classifier (`pipeline/scoring/macro_regime.py`) provides cycle context alongside
  the scores.
- **Value-investing checklists** (`pipeline/scoring/value_investing.py`): a Defensive
  Checklist and a Quality Checklist, computed from the same fetched statements — no
  extra API calls, simple pass/fail arithmetic. Still computed and written to every
  company's JSON (feeding the Key Metrics Reference's good/bad sentiment bands), but
  no longer rendered as its own section on the company page — "Assets vs. Liabilities"
  and "Plain-Language Analysis" carry that same information in plainer form. The
  weekly screen itself ranks by price return instead (see "Weekly Screener" below).
- **Plain-Language Analysis** (see the dedicated section below): a short, jargon-free
  "what's good / what to worry about" summary on every company page, written straight
  from the metrics above it — no AI, no blended score, one plain sentence per clear
  signal.
- **10-K read** (`pipeline/narrative/qualitative_client.py`): the only AI call in this
  pipeline. Reads the company's own most recent 10-K and writes short, neutral
  summaries of the company's latest 10-K, 10-Q, and 8-K, shown on its detail page's
  Recent Filings section and rolled up across every finalist on the **Filings
  Digest** page (see below). Only runs for tickers that make at least one timeframe's
  top-5 list — see "Weekly Screener" below.
- **Economic-cycle context**: the macro page frames the current regime against classic
  business-cycle/sector-rotation theory (which sectors have historically led/lagged in
  this phase) — textbook reference, explicitly not a prediction.
- **Site**: plain HTML/CSS/JS, no framework, no build step — reads the generated JSON
  directly. The homepage shows each sector's top performers across 5 timeframes,
  GICS-style sector by sector; the search box has a typeahead suggestion dropdown
  (`site/js/app.js::wireSearch`, ranked by `site/js/search-index.js`) — as you type, up
  to 8 matching tracked companies appear below the input, each showing ticker, name,
  and sector, navigable with arrow keys + Enter or a click. Enter with nothing
  highlighted still jumps straight to a single exact tracked match, or to the ticker as
  typed if it isn't tracked (see "On-demand lookup" below). Every company page also
  links to its own investor-facing corporate site (from FMP's profile data, when
  available) and lists its latest 10-K/10-Q/8-K with a direct SEC link each.
- **On-demand lookup** (`api/lookup.py`, optional): searching a ticker outside the
  screening universe immediately runs a live analysis through the exact same pipeline
  code, no extra click - the search *is* the request. Backed by a small Python server
  function on Vercel; this repo ships with a working deployment already wired in as a
  fallback, so it works from GitHub Pages too with zero setup (see "On-demand lookup
  deployment" below). The static site works fully without this — it's an opt-in extra.

## Weekly Screener

The program's primary purpose: every Friday at 21:30 UTC (`.github/workflows/
weekly-screen.yml`) — genuinely "after the ~4pm ET close" year-round regardless of
DST — the pipeline runs a two-phase screen over `config/watchlist.yaml`'s curated
universe (906 companies as of this writing - the original 88-company core, every S&P
500 constituent, and every S&P 400 MidCap constituent not already tracked, added in
two staged tranches so each could be validated against a real run before the next
landed), ranking purely by price return, not by any fundamentals check. A further
tranche adding the S&P 600 SmallCap constituents (toward full S&P 1500 coverage) was
evaluated and deliberately held off for now - the universe already requires an active
paid/free-trial FMP plan to run reliably (see "Data source limits and free backup
chain" below), and doubling it again would roughly double that weekly request volume
and the run's GitHub Actions time before that tradeoff is settled:

1. **Cheap screen, whole universe** (`pipeline/main.py::run_full`, phase 1) — every
   company gets fetched and scored (full fundamentals scoring included, for its own
   detail page - including its quantitative Moat Signal, see "Moat Signal" below,
   which needs no AI call so it's available here too), with the AI qualitative
   (10-K filing-summary/moat-classification) layer skipped entirely.
   Fundamentals lean on SEC EDGAR XBRL where possible; price/quote/profile currently
   come from FMP for every company in this phase, not just finalists - the free-tier
   design this pipeline was meant to have here is unfinished (see "Data source limits
   and free backup chain" below), so a paid or free-trial FMP plan is currently
   required to run the whole universe reliably. Each company's price return over 5
   lookback windows (`pipeline/scoring/performance.py::compute_returns`) comes
   straight from price history already fetched for it - no extra API calls.
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
   window's top-5 list gets re-scored with the moat read (plus short 10-K/10-Q/8-K
   summaries) turned on, so Anthropic spend scales with the number of tickers actually
   shown, not the size of the universe scanned.

Anything not in the tracked universe is reachable through the search box instead
(see "On-demand lookup" above) - searching pools that company's data live, within
about 5 minutes, rather than waiting for it to be added to a future tranche.

Every scanned company — not just the picks — still gets a full `data/companies/
{ticker}.json` and detail page, complete with its own Plain-Language Analysis;
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

FMP's free tier caps out around 250 requests/day - nowhere near enough to run FMP's
full statement/ratio set (or even just its price/quote endpoints) against a
several-hundred-company universe every week. `pipeline/fetch/fmp.py::fetch_company`
used to also pull ratios, key metrics, and all three financial statements directly
from FMP; every one of those already has a complete fallback formula computed locally
from SEC EDGAR's raw statement data (see `pipeline/scoring/fundamentals.py`), so those
calls were pure request-budget cost with no accuracy benefit and have been dropped -
FMP is reserved for the one thing only it reliably provides at this pipeline's scale:
live price/quote and profile data.

**This was designed to be free-tier sustainable, and currently isn't.** The plan was
free, no-key sources covering the whole tracked universe, with FMP's budget reserved
for just the small finalist subset phase 2 enriches:

- **SEC EDGAR XBRL** (`pipeline/fetch/sec_edgar.py::xbrl_fundamentals`) — synthesizes
  income statement, balance sheet, and cash flow rows directly from official filings,
  shaped to match FMP's own field names so every downstream calculation (the
  assets/liabilities/equity figures, ratios, the value-investing checklists) works
  unchanged regardless of which source populated it. Free, no API key, no documented
  daily cap (just a ~10 req/sec fair-use guideline this pipeline stays well under).
  This part of the plan works fine - zero failures across a real 906-company run.
- **Stooq** (`pipeline/fetch/stooq.py`) — was meant to be the free price history
  source covering phase 1's whole scanned universe. **In practice it's blocked from
  GitHub Actions runners almost entirely** - a real run against 906 companies saw 95%+
  of requests fail (HTTP 404 escalating to connection timeouts, regardless of a
  browser User-Agent), leaving the whole weekly screen with no price data and empty
  performance picks. `pipeline.main.fetch_and_score_company`'s `use_fmp` flag still
  exists and works (set it `False` to skip FMP and rely on free sources only, e.g. for
  local testing without a key), but `run_full` currently passes `use_fmp=True` in
  *both* phases - FMP covers price/quote/profile for the whole universe, not just
  finalists, because Stooq can't be trusted to.

**What this means in practice:** the weekly screen currently requires an active FMP
plan (paid or free-trial) with enough daily quota for the whole tracked universe (900+
requests/week at present) - the free tier alone won't cover it. `data/meta.json`'s
`sources_status.fmp` reads `"degraded"` when FMP calls fail outright (missing key,
`402 Payment Required`, etc.), and per-company `_errors` include the real HTTP status
so an invalid-key problem is distinguishable from a plan-limit problem at a glance;
`sources_status.stooq` reports the free fallback's own (currently poor) health. Fixing
this for real needs either a different free price-history provider that isn't blocked
from GitHub Actions, or a design that spreads FMP's request volume across multiple
runs per week to stay inside its free-tier budget - tracked as known follow-up work,
not solved. In the meantime, the on-demand search (see "On-demand lookup" above)
already uses FMP per-lookup rather than per-universe, so its budget stays naturally
bounded regardless of this.

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

## Plain-Language Analysis

A short "what's good / what to worry about" summary on every company page, computed
straight from the metrics above it (`pipeline/scoring/plain_analysis.py`) — no AI
call, no blended score, and deliberately written in plain, everyday words rather than
finance terminology, the way you'd explain it to someone who's never read a balance
sheet. This replaced an earlier "Layered Analysis" section that combined the quality
checklist, an AI-generated moat read, and the valuation gate into one page section
with a blended `overall` verdict and `flags` list — this section does something
narrower instead: it only looks at plain numbers already sitting in the metrics dict,
never AI-generated text, and never blends more than one number into a single
judgment.

Ten independent checks, each gated by its own threshold, matching the same bands
`site/js/company.js::metricSentiment` uses to color the Key Metrics Reference table
green/red:

| What it checks | Metric | Good (👍) | Worry (⚠️) |
| --- | --- | --- | --- |
| Does it own more than it owes? | `shareholders_equity` | > $0 | ≤ $0 |
| Has it borrowed too much? | `debt_to_equity` | ≤ 1.0 | > 2.0 |
| Can it pay its bills soon? | `current_ratio` | ≥ 2.0 | < 1.0 |
| Does it earn a good return on everything it uses to run the business? | `roic_pct` | ≥ 15% | < 0% |
| Room to raise prices / absorb rising costs? | `gross_margin_pct` | ≥ 40% | < 15% |
| Is its profit per share growing? | `eps_growth_cagr_3yr_pct` | ≥ 10%/yr | < 0%/yr |
| Real cash left over after running the business? | `fcf_margin_pct` | ≥ 15% | < 0% |
| Is its profit margin getting better or worse? | `margin_trend_score` | Improving | Declining |
| Is the price fair for what it roughly owns and earns? | `graham_upside_pct` | ≥ 15% | < 0% |
| Does it earn more than its money actually costs to raise? ("moat") | `value_creation_pct` | > 0.5pp | < -0.5pp |

A metric with no data, or a reading that's genuinely in between (e.g. debt/equity of
1.5 — above the "good" bar but not yet at the "worry" one), produces neither a
positive nor a worry — a company doesn't have to be praised or criticized on every
single number just to fill out a list. A company with too little data, or one that's
simply unremarkable on every check, can end up with an empty (or short) list on
either side; that's the honest answer, not a bug.

**The moat check (`value_creation_pct`) is this pipeline's quantitative stand-in for
"does this business have a moat", built specifically to cost no AI spend** — see
"Moat Signal" below for the full formula and why it replaced an AI-read moat
classification.

## Moat Signal (quantitative, no AI)

`pipeline/scoring/capital_efficiency.py::company_value_creation_pct` — ROIC minus
this one company's own WACC (weighted average cost of capital: a blend of the cost of
raising money through debt and through investors, using the 10-year Treasury yield
plus `config/capital_efficiency.yaml`'s equity risk premium). A business earning more
than its capital actually costs is creating economic value competitors haven't
managed to compete away yet — that's what a durable competitive edge looks like in
the numbers, without reading a single word of the filing.

This is the per-company version of the exact same formula the market-wide aggregate
on the macro page already computes (`aggregate_capital_efficiency`'s own
`value_creation_pct`) — same cost-of-capital assumptions, just not summed across
companies first. It needs `risk_free_rate_pct` (from the same FRED fetch the rest of
the macro page uses) and `capital_efficiency.company_capital_efficiency_inputs` (NOPAT,
invested capital, total debt, market cap, interest expense — all already computed for
every company, not just finalists, so this metric is available for the **whole
tracked universe**, unlike the AI-read moat classification it replaced, which only
ever ran for that week's finalists). Shown on the Key Metrics Reference table as
"Moat Signal (Value Created Above Cost of Capital)" and fed into the Plain-Language
Analysis section above as a positive/worry sentence, the same ±0.5 percentage-point
dead zone as the macro page's own read (a gap that small isn't worth calling a real
signal either way).

**What this deliberately doesn't do:** name what *kind* of moat a company has —
network effects, cost advantage, intangible assets, switching costs, or efficient
scale. That classification genuinely needs to read the business's own story, which is
exactly what the (optional) 10-K Filing Summaries AI call below still does internally
(`qualitative.moat_present`/`moat_type`/`moat_explanation`/`red_flags`) — that data is
still fetched and stored in every finalist's JSON (e.g.
`data/companies/{ticker}.json`), it's just not shown anywhere on the site any more.
The Moat Signal above answers a narrower, more fundamental question instead — is
whatever edge a company has, if any, still showing up in the numbers — and it answers
it for every company in the tracked universe, at zero ongoing AI cost.

## 10-K Filing Summaries

`pipeline/narrative/qualitative_client.py` — **the only AI call in the whole
pipeline**. Claude reads excerpts from the company's own most recent 10-K (Business,
Risk Factors, and Management's Discussion and Analysis, extracted by
`pipeline/fetch/filing_text.py`) and writes short, neutral 2-4 sentence summaries of
the company's latest 10-K, 10-Q, and 8-K (`qualitative.filing_summary_10k`/`_10q`/
`_8k`, shown on the company page's Recent Filings section, one Anthropic call handles
all of it rather than three) — grounded in the filing text itself, not code-verified
against a fixed metrics dict the way the checklists and Plain-Language Analysis above
are, and left `null` (never guessed) for a filing type the company hasn't recently
filed. `qualitative.extraction_confidence` tells you whether the filing-text
extraction itself found a clean section match or fell back to a raw document prefix,
so you know how much to trust it.

The same call also classifies the company's moat type (network effects / cost
advantage / intangible assets / switching costs / efficient scale / none) and lists
any red flags the filing raises — see "Moat Signal" above for why this data is still
fetched but no longer shown on the site.

`pipeline/fetch/sec_edgar.py::latest_filings_by_form` finds each of the three filing
types independently, so a burst of recent 8-Ks (a company can file 10-20+/year, vs.
one 10-K and ~3 10-Qs) can't crowd out the latest 10-Q/10-K. Results are cached by
all three filing URLs together under `data/qualitative_cache/` — a weekly refresh
skips the filing fetch and the Claude call entirely only when none of the three have
changed since the last run, so a fresh 10-Q or 8-K correctly invalidates the cache
even when the 10-K itself hasn't. Only runs for a company that has a 10-K on file —
cost control against the whole universe happens one level up, in the weekly screen's
two-phase design (see "Weekly Screener" above): this call, filing summaries
included, only ever runs for that week's per-sector finalists. Every company
(finalist or not) still gets its latest 10-K/10-Q/8-K listed with a direct SEC link
on its own page — it's just the AI summary of each that's finalists-only.

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
SEC filings (`qualitative.filing_summary_10k`/`_10q`/`_8k`, see "10-K Filing
Summaries" above) into a single page, instead of reading them one company page at a time. It
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

Searching a ticker that isn't tracked immediately runs a live analysis via
`api/lookup.py`, a small Flask app deployed as a [Vercel](https://vercel.com) Python
serverless function — GitHub Pages can't run server code, so this needs a deployment
that can. Skipping this section is fine; the rest of the site works without it, and an
untracked search will just say live lookup isn't configured.

**This repo already has a working Vercel deployment wired in as a built-in fallback,
so search works out of the box from GitHub Pages too — no setup required to use it.**
`site/js/shared.js::lookupTicker` tries, in order: (1) same-origin `/api/lookup` — the
zero-config path when the whole repo is deployed to one Vercel project (recommended
setup below); (2) `DEFAULT_API_BASE` in `shared.js`, a specific always-on Vercel
deployment of this repo, tried automatically with no prompt at all when (1) 404s (e.g.
because you're on GitHub Pages, which can't run `/api/lookup` itself); (3) only if
*both* of those fail does it fall back to the older manual flow, prompting for a
separately-hosted API's URL. If you fork this repo to deploy your own copy, replace
`DEFAULT_API_BASE` with your own Vercel URL (or clear it to `""` to disable step 2 and
get the manual prompt instead).

**Deploying the whole repo to one Vercel project is still worth doing anyway** — it
gives you a single URL with the site and search on the same origin (no cross-origin
request at all for step 1 above), and lets you set your own `SEARCH_API_KEY` rather
than relying on the shared fallback deployment's budget.

This runs the **full pipeline** for that one ticker, right then — qualitative (10-K
moat reasoning plus 10-K/10-Q/8-K summaries) and the complete fundamentals scoring,
identical to a tracked company, using FMP as the primary price/profile source (the
same reliable path finalists get during the weekly screen's phase 2 - see "Data source
limits and free backup chain"). It's a real 10-K (plus 10-Q/8-K, when found) fetch plus
one Claude call for a single request, which takes real time - the site shows an elapsed
counter while it works, since a wait past "a few seconds" is expected here, not a sign
something's stuck.

**Timeout headroom (required setup, not just a troubleshooting tip):** `vercel.json`
sets `maxDuration: 300` (5 minutes) - safely above what a real lookup needs, but past
what a Vercel Hobby (free) plan allows *by default* (60s). Enable **Fluid Compute**
(Vercel project → **Settings → Functions** → toggle it on) before your first deploy -
it's free and raises Hobby's ceiling to 300s to match. Skip this and the deploy will
either fail or silently cap at 60s, and most real lookups (10-K fetch + a Claude call)
won't reliably finish in that window. If you still see timeouts after enabling it,
`?ai=0` skips the AI-read 10-K filing summaries/moat classification (the slowest step,
at the cost of that layer showing as not evaluated) as a fallback - the quantitative
Moat Signal (see "Moat Signal" above) needs no AI call, so it's computed either way. A
Pro plan raises the ceiling further if you have one, but isn't required.

**Why it's gated:** every live lookup spends real FMP/Anthropic API budget (it runs
the full pipeline for one ticker, right then). Left open with no key, anyone who
finds the URL could run up your usage. Set `SEARCH_API_KEY` to require a shared
secret; if you leave it unset, the endpoint is open to anyone with the URL — only
reasonable for a private deployment you don't share.

**Setup (deploy the whole repo — this replaces GitHub Pages as your main URL):**

1. Create a free [Vercel](https://vercel.com) account and import this repository as a
   new project (Vercel auto-detects `api/lookup.py` as a Python serverless function,
   serves everything else — `site/`, `data/`, etc. — as plain static files, and reads
   `vercel.json` for the function's config and the `/` → `/site/index.html` redirect —
   no build settings to change, no framework preset needed).
2. Before deploying, enable **Fluid Compute** (project **Settings → Functions**) so
   `vercel.json`'s `maxDuration: 300` actually takes effect instead of failing or
   silently capping at 60s.
3. In the Vercel project's **Settings → Environment Variables**, add the same keys as
   the GitHub Actions secrets (these are separate stores — copy the values over):
   `FMP_API_KEY`, `FRED_API_KEY`, `ANTHROPIC_API_KEY`, `SEC_EDGAR_USER_AGENT`, plus a
   new `SEARCH_API_KEY` (any string you choose — this is the shared secret from above;
   leave it unset for a private deployment you're not sharing the URL to).
4. Deploy. Note the resulting URL (e.g. `https://your-project.vercel.app`) — this is
   now your main site, replacing the GitHub Pages one.
5. On the live site, search for a ticker that isn't tracked — **if you left
   `SEARCH_API_KEY` unset, this just works immediately**, no prompt at all
   (`lookupTicker` calls same-origin `/api/lookup`, which now genuinely exists on this
   domain). If you did set `SEARCH_API_KEY`, the first same-origin attempt gets a 401
   and falls back to the older prompt flow once — enter this exact same
   `https://your-project.vercel.app` URL and your `SEARCH_API_KEY` value when asked,
   and it's remembered (with the key, sent as a header) for every search after that.

Local dev: `python api/lookup.py` runs a dev server at `http://localhost:5328`; point
`lookupApiBase` (see `site/js/shared.js`) at that instead of a Vercel URL to test
end-to-end without deploying.
