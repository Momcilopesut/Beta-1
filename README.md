# Weekly Stock Screener

This tool's primary purpose is a **weekly screen**: it scans a curated universe of
companies and surfaces each sector's 5 best price performers over five timeframes —
weekly, monthly, quarterly, annual, and 5-year. This ranking is pure price return,
deliberately independent of any fundamentals check. Every company also gets its own
full value-investing analysis on its own detail page, asking one question three ways:
**does this company own more than it owes, is it a well-run business, and is the
price fair for that?** — a pipeline fetches company fundamentals (free by default:
SEC EDGAR + Stooq) and macroeconomic indicators (FRED) and runs every company through
a transparent, balance-sheet-first scoring model, basic arithmetic, not growth
projections or opaque composites, it just doesn't gate or influence which tickers
surface on the screen itself.

**Runs entirely on your own computer** (see "Running the app" below) - there's no
cloud automation, no hosted backend, and no third-party deployment to set up. Start
it, it serves the site and refreshes its own data, all from your machine.

**This is not financial advice.** Every score is an automated estimate based on
public data and may contain errors or delays.

## How it works

```
config/watchlist.yaml (screening universe)  →  pipeline (screen → rank → AI-enrich finalists)  →  data/*.json  →  site/ (served by app.py, no build step)
```

- **Weekly Screener** (see the dedicated section below): the program's primary purpose.
  Every company in the screening universe gets its price return computed over 5
  timeframes; each sector's top 5 performers per timeframe become the site's homepage.
- **Data sources**: [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation)
  (filings + XBRL fundamentals) and [Stooq](https://stooq.com) (price history) by
  default - both free, no API key; [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs)
  is an optional opt-in (`--use-fmp`) for extra precision; [FRED](https://fred.stlouisfed.org/docs/api/fred/)
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
  `--use-fmp` is set) and lists its latest 10-K/10-Q/8-K with a direct SEC link each.
- **On-demand lookup**: searching a ticker outside the screening universe immediately
  runs a live analysis through the exact same pipeline code, no extra click - the
  search *is* the request. Served by `app.py`'s own `/api/lookup` route, same-origin,
  on your own machine (see "Running the app" below) - no separate deployment, no
  configuration, no cross-origin setup.
- **Moat Deep-Dives** (see the dedicated section below): a hand-written, one-off
  reverse-engineering + Munger-style inversion analysis for a specific company, done
  on request rather than automatically — separate from, and complementary to, the
  automated Moat Signal and 10-K Filing Summaries.

## Weekly Screener

The program's primary purpose: run `python app.py --refresh-now` (or click "Refresh
Data" on the site, see "Running the app" below) and the pipeline runs a two-phase
screen over `config/watchlist.yaml`'s curated universe (906 companies as of this
writing - the original 88-company core, every S&P 500 constituent, and every S&P 400
MidCap constituent not already tracked, added in two staged tranches so each could be
validated against a real run before the next landed), ranking purely by price return,
not by any fundamentals check. A further tranche adding the S&P 600 SmallCap
constituents (toward full S&P 1500 coverage) is tracked as separate, pending follow-up
work, independent of the data-source questions this section used to describe:

1. **Cheap screen, whole universe** (`pipeline/main.py::run_full`, phase 1) — every
   company gets fetched and scored (full fundamentals scoring included, for its own
   detail page - including its quantitative Moat Signal, see "Moat Signal" below,
   which needs no AI call so it's available here too), with the AI qualitative
   (10-K filing-summary/moat-classification) layer skipped entirely.
   Fundamentals and price history come from free sources (SEC EDGAR XBRL + Stooq) by
   default - see "Data source limits and free backup chain" below. Each company's
   price return over 5 lookback windows
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
cp .env.example .env   # fill in whichever keys you actually need - see .env.example's own comments
```

For actually running the app day to day, see "Running the app" below - that's
`python app.py`. The CLI below is for scripted/manual pipeline runs and is what the
test suite exercises directly:

```bash
python -m pipeline.main --tickers AAPL,MSFT --dry-run   # writes to data/.dry-run/, doesn't touch tracked data/
python -m pipeline.main --skip-ai                        # cheap screen only, no Anthropic spend, no finalist enrichment
python -m pipeline.main                                   # full weekly screen over the whole universe, writes data/ (free sources only)
python -m pipeline.main --use-fmp                         # same, but also use FMP for price/quote/profile (needs FMP_API_KEY)
```

Run the tests (pure functions + fixtures, no network, no API keys needed):

```bash
pytest
```

Preview the site without the backend (static files only - no on-demand lookup, no
refresh button; use `python app.py` instead for those):

```bash
./scripts/dev_server.sh
# open http://localhost:8000/site/index.html
```

`data/` currently holds synthetic sample data (see `scripts/generate_sample_data.py`)
so the site is browsable before you've run the pipeline for real — running
`python app.py --refresh-now` (or `python -m pipeline.main`) overwrites it.

## Data source limits and free backup chain

Free by default, no API key needed for the numbers: `--use-fmp` is opt-in, off unless
you pass it.

- **SEC EDGAR XBRL** (`pipeline/fetch/sec_edgar.py::xbrl_fundamentals`) — synthesizes
  income statement, balance sheet, and cash flow rows directly from official filings,
  shaped to match FMP's own field names so every downstream calculation (the
  assets/liabilities/equity figures, ratios, the value-investing checklists) works
  unchanged regardless of which source populated it. Free, no API key, no documented
  daily cap (just a ~10 req/sec fair-use guideline this pipeline stays well under).
  Zero failures across a real 906-company run. Recognizes both a domestic filer's
  10-K and a foreign private issuer's 20-F as "annual report" forms (e.g.
  GlobalFoundries, which never files a 10-K at all) - a lookup for a ticker that only
  has 20-Fs would otherwise synthesize empty statement rows and cascade to a
  near-blank Key Metrics Reference on its page.
- **Stooq** (`pipeline/fetch/stooq.py`) — free price history, no API key. This used to
  be blocked almost entirely when this pipeline ran on GitHub Actions' shared runners
  (95%+ request failure in a real 906-company run - HTTP 404 escalating to connection
  timeouts, regardless of a browser User-Agent) - that block is tied to GitHub's
  runner IP ranges specifically, not to Stooq itself, so it doesn't apply running this
  from your own computer instead (see "Running the app" below). If you do see Stooq
  failures from your own connection, `data/meta.json`'s `sources_status.stooq` and
  each company's own `_errors.stooq` will say so.
- **FMP** (`pipeline/fetch/fmp.py`) — optional, `--use-fmp`, needs `FMP_API_KEY`.
  Used only for the fields above don't fully replace at the free tier: live
  quote/profile precision and the IR website link. Its free tier caps out around 250
  requests/day, nowhere near enough for this pipeline's ~900-company universe, so
  without a paid plan expect `sources_status.fmp` to read `"degraded"` partway
  through a full-universe `--use-fmp` run - normal, and the free-source fallback
  covers the gap either way.

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

## Moat Deep-Dives (hand-written, on request)

`data/moat_deep_dives.json` — a small, hand-curated file, separate from the
pipeline entirely: `{TICKER: {generated_at, verdict, moat_sources[], inversion_risks[],
sources[]}}`. Unlike everything else on this page, nothing here is computed
automatically or refreshed on a schedule — each entry is a one-off reverse-engineering
exercise (why does this business's edge actually exist) followed by a Munger-style
inversion (what would have to go wrong for that edge to break), done by hand in a
Claude Code session when specifically asked for, using real research rather than only
the numbers already in the pipeline. `site/js/company.js::renderMoatDeepDive` renders
it as a "Moat Deep-Dive" section (right after Plain-Language Analysis) whenever the
current ticker has an entry — present or not, absent for almost every ticker; that's
the normal case, not a bug. Looked up by ticker regardless of whether the company is
in the tracked universe or was reached through the on-demand lookup, since the two are
unrelated (this file doesn't care where the rest of the page's data came from).

This exists because it answers a different question than either of the two moat
features above: the Moat Signal is a fast, zero-cost, whole-universe number; a 10-K
Filing Summary is a cheap, automated, one-paragraph AI read. Neither actually
reasons through *why* an edge exists or stress-tests it against a real competitive
threat — that takes real research and judgment, which is exactly what this is for,
spent deliberately on one company at a time instead of automatically on all 906.

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

## Local generation with LM Studio (optional, manual)

`QUALITATIVE_PROVIDER=lmstudio` swaps the one AI call above (moat read + the three
filing summaries) from Anthropic's API to a model running locally in
[LM Studio](https://lmstudio.ai) — zero API spend, no rate limit, run as many times
as you want. Nothing else changes: the exact same prompt and JSON schema go to
whichever provider is configured, and every number on the page (price, P/E, assets,
etc.) still comes from FMP/SEC EDGAR/Stooq exactly as today — this only replaces the
filing-text reasoning step.

Setup:

1. In LM Studio, load a model and start its local server (the "Developer" tab →
   Start Server; default `http://localhost:1234`).
2. In `.env`: `QUALITATIVE_PROVIDER=lmstudio`. Override `LMSTUDIO_BASE_URL` /
   `LMSTUDIO_MODEL` if your server isn't on the default port or needs a specific
   model identifier (check LM Studio's own server tab for the exact string it
   expects). `LMSTUDIO_TIMEOUT_SECONDS` (default 300) and `LMSTUDIO_JSON_MODE`
   (default on; set to `0` if your server rejects the `response_format` field)
   are the two other knobs — see `.env.example`.
3. Run the pipeline locally as usual, e.g. `python -m pipeline.main --tickers GFS
   --dry-run`.

Everything in this app now runs on your own machine already (see "Running the app"
below), so this is just a choice of which provider handles that one AI call - set it
once in `.env` and both `app.py` and the `pipeline.main` CLI pick it up. A local model
has no code-verified grounding guarantee either (same caveat as the Anthropic path,
see `qualitative_schema.py`) and, being smaller, is more likely to drift from the
exact JSON shape asked for; a malformed response fails that one ticker's qualitative
layer only (same graceful degradation as an Anthropic error), not the whole run.

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

## Running the app

Everything - serving the site, on-demand ticker lookup, and refreshing the weekly
screen - runs from one process on your own computer, started with:

```bash
python app.py
```

This opens `http://127.0.0.1:5050/` in your browser automatically (bound to
localhost only - not your network; there's no login or access control of any kind,
by design, since nothing here is meant to be reachable from anywhere else). A few
flags:

```bash
python app.py --refresh-now      # run the full screen first (progress prints to this terminal), then serve
python app.py --no-browser       # don't auto-open a browser tab
python app.py --port 8080        # use a different port
python app.py --host 0.0.0.0     # expose it on your network too - only if you actually want that
```

Three things app.py does that used to be split across GitHub Actions and a separately
deployed Vercel function (both retired - see this file's git history if you need the
old setup):

- **Serves the site**: `site/` and `data/` at the same relative layout
  `scripts/dev_server.sh` always used, so every `../data/...` fetch in `site/js/*.js`
  resolves the same way it always has.
- **On-demand lookup** (`/api/lookup`, same-origin): searching a ticker outside the
  screening universe runs the full pipeline for it, right then - qualitative (10-K
  moat reasoning plus 10-K/10-Q/8-K summaries, or your own local LM Studio model, see
  "Local generation with LM Studio" above) and the complete fundamentals scoring,
  identical to a tracked company. A real 10-K fetch plus one AI call takes real time
  for a single request - the site shows an elapsed counter while it works, since a
  wait past "a few seconds" is expected here, not a sign something's stuck. Results
  are cached in `data/qualitative_cache/` exactly like a tracked company's, so
  searching the same ad-hoc ticker again reuses the AI read instead of re-running it.
- **Refresh Data button** (homepage header) / `/api/refresh`: runs the same two-phase
  weekly screen `.github/workflows/weekly-screen.yml` used to run on a schedule, now
  on demand, in a background thread (the button polls `/api/refresh/status` and
  reloads the page when it's done). Only one refresh runs at a time; a second request
  while one is already running gets `409 Already running` instead of queuing or
  stomping on it. There's no built-in scheduler - run it whenever you want fresh data
  (the button, `--refresh-now`, or your own OS scheduler, e.g. cron or Task Scheduler,
  calling `python app.py --refresh-now --no-browser` on whatever cadence you like).

Since this only ever talks to itself on localhost, there's no CORS, search-key, or
cross-origin configuration to set up - the config that used to matter for the Vercel
deployment (`SEARCH_API_KEY`, `vercel.json`'s timeout settings, GitHub Pages secrets)
no longer applies.

`.github/workflows/tests.yml` still runs `pytest` on every push/PR — no secrets or
network required; that part of CI hasn't changed.
