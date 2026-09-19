# Watchlist Equity Research Tool

A minimal, explainable research dashboard for a curated stock watchlist, built around
the simplest question in investing: **does this company own more than it owes, and is
the price fair for that?** A scheduled pipeline fetches company fundamentals (Financial
Modeling Prep + SEC EDGAR) and macroeconomic indicators (FRED), runs them through a
transparent, balance-sheet-first scoring model — basic arithmetic, not growth
projections or opaque composites — and asks Claude to summarize what matters, grounded
strictly in the computed numbers. The result is published as a static site.

**This is not financial advice.** Every score and summary is an automated estimate
based on public data and may contain errors or delays.

## How it works

```
config/watchlist.yaml  →  pipeline (fetch → score → AI narrative)  →  data/*.json  →  site/ (static, no build step)
```

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
- **Value-investing checklists** (`pipeline/scoring/value_investing.py`): Graham's
  Defensive Investor criteria and the Piotroski F-Score, computed from the same fetched
  statements — no extra API calls. Both are simple pass/fail arithmetic, and together
  they're the two inputs to the Conviction Score (see "Conviction Score" below).
- **Layered analysis** (quant screen → qualitative → Graham Number valuation gate, see
  "Layered analysis" below): a deeper, opt-in-by-passing-the-quant-screen pass per
  company that reads the company's own 10-K text — the one place in this pipeline an
  AI call isn't grounded solely in pre-computed metrics.
- **Economic-cycle context**: the macro page frames the current regime against classic
  business-cycle/sector-rotation theory (which sectors have historically led/lagged in
  this phase) — textbook reference, explicitly not a prediction.
- **Site**: plain HTML/CSS/JS, no framework, no build step — reads the generated JSON
  directly. The dashboard groups companies by GICS-style sector and has a search box
  (instant filter of tracked companies; Enter jumps to any ticker).
- **On-demand lookup** (`api/lookup.py`, optional): a search for a ticker outside the
  tracked watchlist offers a live, on-demand run through the exact same pipeline code,
  via a small backend deployed separately (see "On-demand lookup deployment" below).
  The static site works fully without this — it's an opt-in extra.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in your API keys
```

Run the pipeline:

```bash
python -m pipeline.main --tickers AAPL,MSFT --dry-run   # writes to data/.dry-run/, doesn't touch tracked data/
python -m pipeline.main --skip-ai                        # fetch + score only, no Anthropic spend
python -m pipeline.main --ai-only --tickers AAPL          # re-run just the narrative for an already-scored company
python -m pipeline.main                                   # full run over the whole watchlist, writes data/
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
  assets/liabilities/equity figures, ratios, the Graham/Piotroski checklists) works
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

A number of more sophisticated frameworks (a discounted cash flow model, Fisher's
qualitative checklist, Greenblatt's Magic Formula, Lynch's growth categorization, a
synthesized investment thesis) were built and then deliberately retired in favor of
this — see "Which frameworks became which filters" below for the full reasoning. The
goal is a tool whose logic you could explain to someone with no finance background:
compare what's owned to what's owed, check whether the price is fair for that, and use
two simple checklists (Graham, Piotroski) to catch the rest.

## Layered analysis

A deeper pass per company, deliberately kept as separate layers rather than one
blended score — a great quant score with a broken moat should get flagged, not
averaged away, and a great business at a bad price still isn't a buy. Every company
detail page shows each layer, plus an `overall` synthesis and a `flags` list
explaining any disagreement between them.

1. **Quant screen** (`pipeline/scoring/quant_score.py`) — a fast, deterministic
   pass/fail filter, balance-sheet/cash only: current ratio, debt/EBITDA, and FCF
   margin against thresholds in `config/quant_score_thresholds.yaml`. No API calls,
   no AI. This gates the qualitative layer below — it only runs for a company that
   already clears this bar (deliberate cost control, not just a display filter).
2. **Qualitative** (`pipeline/narrative/qualitative_client.py`) — Claude reads
   excerpts from the company's own most recent 10-K (Business, Risk Factors, and
   Management's Discussion and Analysis, extracted by
   `pipeline/fetch/filing_text.py`) plus the quant scorecard, and classifies the
   moat (network effects / cost advantage / intangible assets / switching costs /
   efficient scale / none — the classic Buffett/Munger/Morningstar categories) and
   lists any red flags the filing itself raises. **This is the one place in the
   whole pipeline where an AI call reads raw text instead of only pre-computed
   metrics.** Every other narrative call grounds each fact by requiring a real
   metric key (`pipeline/narrative/grounding.py` drops anything that doesn't
   resolve) — that mechanical check doesn't exist for free-form filing prose, so
   this layer's grounding is prompt discipline only, not code-verified.
   `qualitative.extraction_confidence` tells you whether the filing-text extraction
   itself found a clean Item 7 section match or fell back to a raw document prefix,
   so you know how much to trust it. Results are cached by 10-K URL under
   `data/qualitative_cache/` — since a 10-K only changes once a year, a weekly
   refresh skips both the filing fetch and the Claude call entirely once a company
   already has a current-filing assessment.
3. **Valuation gate** — not a separate module or AI call, just the Graham Number
   margin of safety already computed in `fundamentals.py`
   (`graham_upside_pct = sqrt(22.5 × EPS × book value/share)` vs. price). No growth
   projection or discount-rate assumption, unlike a DCF (see "Assets vs.
   Liabilities" above for why that trade-off was made deliberately).

`pipeline/scoring/aggregation.py` combines the three gates (quant pass/fail,
qualitative moat present/absent, valuation margin of safety above a required
threshold) into the `overall` summary and `flags` — e.g. a company that passes the
quant screen but shows no moat gets flagged explicitly rather than its strong quant
score quietly winning out in an average. The required margin of safety isn't a flat
number: it starts at the classic 15% convention and scales up with actual
uncertainty (thin quant data coverage, filing-stated red flags, a filing-text
extraction that fell back to a raw document prefix instead of a clean section
match) — Klarman's point that margin of safety is a risk-management concept, not a
fixed number every company gets held to equally. See `required_margin_of_safety_pct`
in the output.

### Conviction Score

A single 0-100 number per stock (`layered_analysis.conviction_score`, shown on every
card and at the top of the company detail page), built from the two basic checklists
this pipeline computes — but not via a naive average, which would let a passing
checklist quietly paper over a broken moat or an expensive price. The formula
(`pipeline/scoring/aggregation.py::build_conviction_score`, weights in
`config/conviction_score.yaml`):

1. **Weighted base score** — the Graham Defensive Investor checklist and the
   Piotroski F-Score pass rates, equally weighted. A checklist the pipeline couldn't
   evaluate (e.g. Piotroski needs 2 years of statements it doesn't have) is left out
   entirely and the remaining weight renormalizes — a data gap is never scored as a
   failure.
2. **Qualitative moat multiplier** — ×1.05 if a moat was identified, ×0.70 if the
   qualitative layer explicitly found none, ×1.0 if that layer never ran. Applied
   after the base score, not blended into it, so it can meaningfully move the result
   regardless of how strong the checklists look.
3. **Valuation gate multiplier** — ×1.0 if the Graham Number margin-of-safety gate
   passes (using the same Klarman risk-scaled threshold above), ×0.55 if it fails,
   ×1.0 if valuation couldn't be evaluated. The final gate: a wonderful business at a
   bad price still isn't a buy.

The result is clamped to 0-100 and banded into Strong/Favorable/Neutral/Cautious/Weak
verdicts (`pipeline/scoring/thresholds.py::verdict_for`). A company with no data in
either checklist gets `conviction_score: null`, never a misleading 0. The dashboard
sorts each sector group by this score (highest first); the full breakdown (base
score, each component, both multipliers) ships in the output and renders on the
company page so a high or low score is never just a number — you can always see why.

### Which frameworks became which filters

This project drew on ten value-investing thinkers across this tool's development.
After an early version grew data-heavy — multiple overlapping scores, a discounted
cash flow model, AI-judged qualitative checklists — it was deliberately trimmed back
to first-principles, balance-sheet-centered math (see "Assets vs. Liabilities"
above). Here's what survived that trim, what didn't, and why:

| Thinker | Framework | Status |
|---|---|---|
| **Benjamin Graham** | Defensive Investor checklist, Graham Number, NCAV, P/E×P/B ≤ 22.5 | **Kept** — the core of this tool. `pipeline/scoring/value_investing.py`, `pipeline/scoring/fundamentals.py` |
| **Warren Buffett** | Moat classification; "wonderful company at a fair price" | **Kept.** Moat classification lives in the qualitative layer; "wonderful company at a fair price" is the quant gate + Graham Number valuation gate combination in `aggregation.py`. Owner earnings was cut — redundant with the simpler FCF margin already kept |
| **Charlie Munger** | ROIC as a moat proxy; "invert, always invert" | **Cut.** ROIC needs an effective-tax-rate calculation across six inputs — not "basic math" a reader can verify by hand. The falsification/thesis layer that expressed "invert, always invert" was cut alongside it |
| **Philip Fisher** | 15-point checklist; "scuttlebutt" qualitative research | **Cut.** The single biggest driver of "data heavy": a 12-item AI-judged checklist per company, on top of everything else. True scuttlebutt (talking to customers/competitors) was never available here regardless |
| **Peter Lynch** | PEG ratio; six-way growth categorization | **Cut.** Abstract bucketing (fast grower/stalwart/etc.), not balance-sheet math, and the code itself admitted it couldn't reliably tell a turnaround from ordinary decline |
| **Joel Greenblatt** | Magic Formula (return on capital + earnings yield, ranked) | **Cut.** A cross-sectional ranking against watchlist peers, not "this company's own assets vs. liabilities" |
| **Aswath Damodaran** | Explicit-assumption DCF | **Cut.** The least "basic math" of everything here — a 5-year growth projection plus a discount-rate assumption, versus the Graham Number's single closed-form formula |
| **Seth Klarman** | Margin of safety as risk management, not just a valuation number | **Kept.** The risk-scaled `required_margin_of_safety_pct` in `aggregation.py` is simple threshold arithmetic, described above |
| **Howard Marks** | Risk, cycles, second-level thinking | **Partially kept.** Cycle awareness (`macro_regime.py`'s `cycle_context`) remains. Second-level thinking was never built as a field — it would require speculating about market psychology beyond the given data, which this project has refused throughout (see the earlier decision against a live geopolitics feed) |
| **James O'Shaughnessy** | Factor-based backtesting (*What Works on Wall Street*) | Not implemented. Backtesting needs long-run historical return data across many stocks this pipeline doesn't store, and wasn't asked to build |

## Configuration

- `config/watchlist.yaml` — tracked tickers. Edit freely.
- `config/sector_macro_sensitivity.yaml` — how much each sector's macro adjustment
  moves under each regime.
- `config/macro_series.yaml` — which FRED series are pulled and the regime
  classification thresholds.
- `config/quant_score_thresholds.yaml` — pass/fail thresholds for the quant screen
  (layer 1 above, balance-sheet/cash only) and the fraction of evaluated metrics that
  must pass to gate the qualitative layer.
- `config/conviction_score.yaml` — component weights for the Conviction Score's base
  score (Graham/Piotroski), the qualitative-moat/valuation-gate multipliers applied on
  top of it, and the verdict bands (Strong/Favorable/Neutral/Cautious/Weak).

## Deployment

`.github/workflows/refresh-data.yml` runs the pipeline on a schedule (Saturdays by
default — see the cron comment in that file), commits updated `data/*.json`, and
deploys `site/` + `data/` to GitHub Pages. It can also be triggered manually from the
Actions tab (`workflow_dispatch`), optionally with a `dry_run` flag or a specific
`tickers` list.

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

This runs the **full pipeline** for that one ticker, right then — quant screen,
qualitative (10-K moat reasoning), and the complete Conviction Score, identical to a
tracked company. The narrative and qualitative Claude calls run concurrently
(`pipeline/main.py::finalize_company`) to keep this as fast as possible, but it's
still a real 10-K fetch plus two Claude calls for one request, which takes real time.

**Timeout headroom:** `vercel.json` sets `maxDuration: 60` — the maximum a Vercel
Hobby (free) plan allows by default. If a lookup is timing out, you have two free
options before paying for anything: enable **Fluid Compute** (Vercel project →
**Settings → Functions** → toggle it on) to raise Hobby's ceiling to 300s, then bump
`maxDuration` in `vercel.json` to match and redeploy; or fall back to a faster,
partial analysis by passing `skip_qualitative=True` to `finalize_company` in
`api/lookup.py` (narrative + quant screen only, no 10-K fetch — sacrifices the
qualitative moat read and lowers the Conviction Score's data coverage, but removes
the slowest step). A Pro plan raises the ceiling further (300s by default, more with
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
