# Weekly Stock Screener

This tool's primary purpose is a **weekly screen**: every Friday after the US market
closes, it scans a curated universe of companies and surfaces whichever ones come
closest to satisfying Graham's, Buffett's, and Munger's investing criteria — the same
question underneath all three: **does this company own more than it owes, is it a
well-run business, and is the price fair for that?** A scheduled pipeline fetches
company fundamentals (Financial Modeling Prep + SEC EDGAR) and macroeconomic indicators
(FRED), runs every company through a transparent, balance-sheet-first scoring model —
basic arithmetic, not growth projections or opaque composites — ranks them, and asks
Claude to summarize what matters for the week's top picks, grounded strictly in the
computed numbers. The result is published as a static site.

**This is not financial advice.** Every score and summary is an automated estimate
based on public data and may contain errors or delays.

## How it works

```
config/watchlist.yaml (screening universe)  →  pipeline (screen → rank → AI-enrich finalists)  →  data/*.json  →  site/ (static, no build step)
```

- **Weekly Screener** (see the dedicated section below): the program's primary purpose.
  Every company in the screening universe gets scored; the top-ranked companies per
  sector become the site's homepage.
- **Data sources**: [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs)
  (fundamentals, prices), [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation)
  (filings + XBRL fundamentals fallback), [FRED](https://fred.stlouisfed.org/docs/api/fred/)
  (treasury yields, CPI, unemployment, Fed funds rate).
- **Assets vs. Liabilities** (see the dedicated section below): the company's actual
  net worth (assets minus liabilities), computed straight from the balance sheet, is
  the headline figure on every company page — not buried under a dozen other metrics.
- **Scoring**: deterministic, config-driven, and deliberately small — see "Assets vs.
  Liabilities" and "Layered analysis" below. A rule-based macro regime classifier
  (`pipeline/scoring/macro_regime.py`) provides cycle context alongside the scores.
- **AI narrative**: Claude reads the already-computed metrics (never raw news) and
  produces a one-line summary plus facts tiered Critical → Important → Minor → Noise.
  Every fact must cite a real metric key from the payload; facts that don't are
  dropped in code (`pipeline/narrative/grounding.py`), not just discouraged by prompt.
  Only runs for the week's finalists — see "Weekly Screener" below.
- **Value-investing checklists** (`pipeline/scoring/value_investing.py`): Graham's
  Defensive Investor criteria and a Munger Quality Checklist, computed from the same
  fetched statements — no extra API calls. Both are simple pass/fail arithmetic, and
  together they anchor the Investment Meter (see "Investment Meter" below) — built
  from exactly three investors: Graham, Buffett, Munger. This Meter is also exactly
  what the weekly screen ranks companies by.
- **Layered analysis** (Munger's quality read → Buffett's qualitative moat read →
  Graham Number valuation gate, see "Layered analysis" below): a deeper pass per
  company that reads the company's own 10-K text — the one place in this pipeline an
  AI call isn't grounded solely in pre-computed metrics. Only runs for the week's
  finalists, same as the narrative above.
- **Economic-cycle context**: the macro page frames the current regime against classic
  business-cycle/sector-rotation theory (which sectors have historically led/lagged in
  this phase) — textbook reference, explicitly not a prediction.
- **Site**: plain HTML/CSS/JS, no framework, no build step — reads the generated JSON
  directly. The homepage shows this week's top picks grouped by GICS-style sector; the
  search box reaches every company in the screening universe (instant filter; Enter
  jumps to any ticker, tracked or not).
- **On-demand lookup** (`api/lookup.py`, optional): a search for a ticker outside the
  screening universe offers a live, on-demand run through the exact same pipeline code,
  via a small backend deployed separately (see "On-demand lookup deployment" below).
  The static site works fully without this — it's an opt-in extra.

## Weekly Screener

The program's primary purpose: every Friday at 21:30 UTC (`.github/workflows/
weekly-screen.yml`) — genuinely "after the ~4pm ET close" year-round regardless of
DST — the pipeline runs a two-phase screen over `config/watchlist.yaml`'s curated
universe (88 companies, 8 per sector across 11 GICS-style sectors; not the full S&P
500, to stay well inside a free-tier API budget):

1. **Cheap screen, whole universe** (`pipeline/main.py::run_full`, phase 1) — every
   company gets fetched and scored, including a full Investment Meter reading, with
   the AI narrative/qualitative layer skipped entirely. This is not a degraded score:
   a missing moat read just leaves that multiplier at a neutral 1.0 (see
   `config/conviction_score.yaml`), so the Graham/Munger checklist math alone is
   already meaningful enough to rank on.
2. **Rank + select** (`pipeline/scoring/screening.py::select_top_picks`) — within each
   sector, companies are sorted by Investment Meter score (highest first); companies
   with no score at all are excluded rather than guessed at. The top
   `config/screening.yaml`'s `top_n_per_sector` (5 by default) per sector become this
   week's finalists.
3. **AI-enrich finalists only** (phase 2) — only the selected finalists get re-scored
   with the AI narrative and Buffett moat read turned on, so Anthropic spend scales
   with the number of picks shown, not the size of the universe scanned.

Every scanned company — not just the picks — still gets a full `data/companies/
{ticker}.json` and detail page; `data/weekly_picks.json` holds just the ranked
selection the homepage renders, and `data/watchlist.json` keeps covering the whole
universe so the search box can still find anything scanned. Run it locally with
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
python -m pipeline.main --ai-only --tickers AAPL          # re-run just the narrative for an already-scored company
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
  assets/liabilities/equity figures, ratios, the Graham/Munger checklists) works
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
- **NCAV margin** (`ncav_margin_pct`) — Graham's strictest test: even just the
  company's *current* assets (cash, receivables, inventory), after paying off *every*
  liability, compared against the whole stock's price. Almost always sharply negative
  for a normal large-cap — a rare positive reading is itself the interesting fact.
- **Graham Number** (`graham_number`/`graham_upside_pct`) — `sqrt(22.5 × EPS × book
  value per share)`, a single closed-form formula combining earnings and net worth per
  share. This is the pipeline's valuation check — no multi-year growth projection or
  discount-rate assumption, unlike a DCF.
- **Debt/equity, debt/EBITDA, current ratio** — how much of the company is borrowed vs.
  actually owned, and whether short-term assets cover short-term debts.
- **P/E and P/B** — the two simplest "is the price fair" ratios, kept alongside the
  Graham Number rather than instead of it.

A number of more sophisticated frameworks — a discounted cash flow model, Fisher's
qualitative checklist, Greenblatt's Magic Formula, Lynch's growth categorization, a
synthesized investment thesis, the academic Piotroski F-Score, Klarman's dynamic
margin-of-safety scaling — were built across earlier iterations of this tool and then
deliberately retired, leaving exactly three investors: Graham, Buffett, and Munger
(see "Which frameworks became which filters" below for the full reasoning). The goal
is a tool whose logic you could explain to someone with no finance background: compare
what's owned to what's owed, check whether the price is fair for that, and use two
simple checklists (Graham, Munger) to catch the rest.

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

1. **Munger's quality checklist** (`pipeline/scoring/value_investing.py::munger_quality_checklist`) —
   return on equity ≥ 15%, debt/equity ≤ 1.0, no shareholder dilution, and margins
   stable or improving. Pure arithmetic, no AI. See "Investment Meter" below for why
   this specific set of four checks.
2. **Buffett's moat read** (`pipeline/narrative/qualitative_client.py`) — Claude reads
   excerpts from the company's own most recent 10-K (Business, Risk Factors, and
   Management's Discussion and Analysis, extracted by
   `pipeline/fetch/filing_text.py`) and classifies the moat (network effects / cost
   advantage / intangible assets / switching costs / efficient scale / none — the
   classic Buffett/Munger/Morningstar categories) and lists any red flags the filing
   itself raises. **This is the one place in the whole pipeline where an AI call
   reads raw text instead of only pre-computed metrics.** Every other narrative call
   grounds each fact by requiring a real metric key (`pipeline/narrative/grounding.py`
   drops anything that doesn't resolve) — that mechanical check doesn't exist for
   free-form filing prose, so this layer's grounding is prompt discipline only, not
   code-verified. `qualitative.extraction_confidence` tells you whether the
   filing-text extraction itself found a clean Item 7 section match or fell back to a
   raw document prefix, so you know how much to trust it. Results are cached by 10-K
   URL under `data/qualitative_cache/` — since a 10-K only changes once a year, a
   weekly refresh skips both the filing fetch and the Claude call entirely once a
   company already has a current-filing assessment. Only runs for a company that has
   a 10-K on file — cost control against the whole universe happens one level up, in
   the weekly screen's two-phase design (see "Weekly Screener" above): this layer
   only ever runs for that week's per-sector finalists.
3. **Graham's valuation gate** — not a separate module or AI call, just the Graham
   Number margin of safety already computed in `fundamentals.py`
   (`graham_upside_pct = sqrt(22.5 × EPS × book value/share)` vs. price). No growth
   projection or discount-rate assumption, unlike a DCF (see "Assets vs.
   Liabilities" above for why that trade-off was made deliberately).

`pipeline/scoring/aggregation.py` combines the three gates (Munger's quality
checklist, Buffett's qualitative moat present/absent, Graham's valuation margin of
safety) into the `overall` summary and `flags` — e.g. a company with a strong quality
checklist but no moat gets flagged explicitly rather than the checklist quietly
winning out in an average. The required margin of safety is a single flat number,
Graham's own 15% convention — an earlier version of this pipeline scaled it
dynamically with data coverage and filing red flags (Seth Klarman's risk-management
framing of margin of safety), which has been removed along with everything else not
attributable to Graham, Buffett, or Munger specifically. See
`required_margin_of_safety_pct` in the output.

### Investment Meter

**The deep dive.** Graham, Buffett, and Munger aren't interchangeable — each is
known for a distinct, well-documented lens on a stock, and the meter keeps each one
visible rather than blending them into a number no one can trace back:

- **Graham — is it cheap and safe?** His own quantitative domain: the Defensive
  Investor checklist (size, financial strength, earnings stability, dividend
  record, earnings growth, moderate P/E, moderate P/E×P/B) plus the Graham Number
  margin of safety. This is the meter's **base score** — Graham's own checklist
  pass rate, undiluted by anything else.
- **Buffett — is it a wonderful business?** His most distinctive, quotable
  contribution: durable competitive advantage, the "moat." Read from the company's
  own 10-K by the qualitative AI layer above. A **multiplier** on Graham's base
  score, not blended into it — Buffett's own point was that quality should gate the
  decision ("a wonderful company at a fair price").
- **Munger — does it actually earn good returns on capital, without stupidity?**
  Munger's single most-quoted, most distinctly-his idea: *"Over the long term, it's
  hard for a stock to earn a much better return than the business which underlies
  it earns... if a business earns 18% on capital over 20 or 30 years, even if you
  pay an expensive looking price, you'll end up with a fine result."* Also a
  **multiplier**: a statistically cheap stock that earns poor returns on capital,
  carries heavy debt, dilutes shareholders, or has eroding margins is a warning,
  not a wash.

**Formula** (`pipeline/scoring/aggregation.py::build_conviction_score`, multipliers
in `config/conviction_score.yaml`, still keyed `conviction_score`/
`conviction_verdict` in the output JSON for continuity):

```
meter score = Graham checklist pass rate
              × Buffett moat multiplier      (1.05 present / 0.70 absent / 1.0 not evaluated)
              × Munger quality multiplier    (1.10 present / 0.75 absent / 1.0 not evaluated)
              × Graham valuation multiplier  (1.0 pass / 0.55 fail / 1.0 not evaluated)
```

Clamped to 0-100 and banded into Strong/Favorable/Neutral/Cautious/Weak verdicts
(`pipeline/scoring/thresholds.py::verdict_for`). A company with no evaluated Graham
checklist data gets `conviction_score: null`, never a misleading 0. The company
detail page renders this as an actual gauge (`site/js/company.js::renderMeterGauge`
— an inline SVG semi-circle, colored bands matching the verdict thresholds, a
needle at the score's position), not just a number in a box; the dashboard sorts
each sector group by the score (highest first).

### Which frameworks became which filters

Earlier iterations of this tool drew on ten value-investing thinkers. It's now
built from exactly three — Graham, Buffett, Munger — with everything else
deliberately removed:

| Thinker | Framework | Where it lives |
|---|---|---|
| **Benjamin Graham** | Defensive Investor checklist, Graham Number, NCAV, P/E×P/B ≤ 22.5, margin-of-safety convention | The meter's base score and valuation gate. `pipeline/scoring/value_investing.py`, `pipeline/scoring/fundamentals.py`, `pipeline/scoring/aggregation.py` |
| **Warren Buffett** | Moat classification; "wonderful company at a fair price" | The meter's moat multiplier. `pipeline/narrative/qualitative_client.py` |
| **Charlie Munger** | Return on capital over statistical cheapness; avoiding leverage/dilution "stupidity" | The meter's quality multiplier — a 4-criterion checklist (ROE, debt/equity, dilution, margin trend). `pipeline/scoring/value_investing.py::munger_quality_checklist` |

Removed, and why: **Owner earnings** (Buffett) and **ROIC** (Munger) — cut for
needing more inputs than a reader could verify by hand; ROE (net income ÷ equity)
does the same job in two inputs. **Piotroski F-Score** — never one of the named
thinkers, replaced by Munger's own checklist. **Fisher's 15-point checklist** — the
single biggest driver of "data heavy": a 12-item AI-judged checklist per company.
**Lynch's PEG ratio and growth categorization** — abstract bucketing, not balance-
sheet math. **Greenblatt's Magic Formula** — a cross-sectional ranking against
watchlist peers, not this company's own assets vs. liabilities. **Damodaran's DCF**
— the least "basic math" of anything here: a multi-year growth projection plus a
discount-rate assumption, versus the Graham Number's single closed-form formula.
**Klarman's risk-scaled margin of safety** — a real, useful idea, but not Graham's,
Buffett's, or Munger's; the margin of safety is now Graham's own flat convention.
**Marks' cycle awareness** — the macro page's business-cycle context
(`macro_regime.py::cycle_context`) stays, since it's generic textbook
sector-rotation reference rather than something specifically Marks', but it's no
longer credited to him and plays no part in the meter. **O'Shaughnessy's
backtesting** — never implemented; needs historical infrastructure this pipeline
doesn't have.

## Metrics Glossary + What-If Calculator

Every metric this tool scores on (`site/js/metrics-glossary.js`) carries a short
explanation, its economic significance, and how swings in it actually affect the
business — not just the number. It's shown two ways: a **Key Metrics Reference**
section on every company page (this company's own current value next to each
explanation), and a standalone **Metrics Glossary** page (`site/glossary.html`,
linked from the nav on every page) with the full reference, no per-company numbers.

The company page also has a **What-If: Investment Meter Calculator** —
drag a metric and watch the Investment Meter score recompute live, right in the
browser, to build intuition for how much (or how little) one number actually
moves the overall score. This is a pure client-side port of the real scoring chain
(`site/js/meter-calculator.js`, mirroring `pipeline/scoring/value_investing.py`'s
two checklists and `pipeline/scoring/aggregation.py::build_conviction_score`),
seeded from the company's real data so it starts in exact agreement with the
page's own displayed score. Two things worth knowing about it:

- It's a **client-side approximation**, kept in sync with the Python scoring
  logic by hand — a real change to the multipliers in `config/conviction_score.yaml`
  or the checklist thresholds needs the same change made in
  `meter-calculator.js`, documented at the top of that file.
- One criterion is **intentionally simplified**: Graham's "strong financial
  condition" check is `current ratio >= 2` alone here, since the real backend's
  second condition (debt vs. working capital) needs raw dollar figures that
  aren't part of the JSON this page already has. Criteria with no single numeric
  driver at all (earnings stability, dividend record, dilution, Buffett's moat
  read) are direct Pass/Fail/Unknown toggles instead of sliders.

## Configuration

- `config/watchlist.yaml` — the screening universe. Edit freely.
- `config/sector_macro_sensitivity.yaml` — how much each sector's macro adjustment
  moves under each regime.
- `config/macro_series.yaml` — which FRED series are pulled and the regime
  classification thresholds.
- `config/conviction_score.yaml` — the Investment Meter's three multipliers
  (Buffett's moat, Munger's quality checklist, Graham's valuation gate) applied to
  Graham's checklist base score, and the verdict bands (Strong/Favorable/Neutral/
  Cautious/Weak).
- `config/screening.yaml` — `top_n_per_sector`, how many companies the weekly screen
  surfaces per sector (see "Weekly Screener" above).

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

This runs the **full pipeline** for that one ticker, right then — narrative,
qualitative (10-K moat reasoning), and the complete Investment Meter, identical to a
tracked company. The narrative and qualitative Claude calls run concurrently
(`pipeline/main.py::finalize_company`) to keep this as fast as possible, but it's
still a real 10-K fetch plus two Claude calls for one request, which takes real time.

**Timeout headroom:** `vercel.json` sets `maxDuration: 60` — the maximum a Vercel
Hobby (free) plan allows by default. If a lookup is timing out, you have two free
options before paying for anything: enable **Fluid Compute** (Vercel project →
**Settings → Functions** → toggle it on) to raise Hobby's ceiling to 300s, then bump
`maxDuration` in `vercel.json` to match and redeploy; or fall back to a faster,
partial analysis by passing `skip_qualitative=True` to `finalize_company` in
`api/lookup.py` (narrative only, no 10-K fetch — sacrifices the qualitative moat read
and lowers the Investment Meter's data coverage, but removes the slowest step). A Pro
plan raises the ceiling further (300s by default, more with
Fluid Compute) if you have one.

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
