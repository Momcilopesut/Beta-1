# Watchlist Equity Research Tool

A minimal, explainable research dashboard for a curated stock watchlist. A scheduled
pipeline fetches company fundamentals (Financial Modeling Prep + SEC EDGAR) and
macroeconomic indicators (FRED), runs them through a transparent quantitative scoring
model, and asks Claude to summarize what matters and filter it by importance — all
grounded strictly in the computed numbers. The result is published as a static site.

**This is not financial advice.** Every score and summary is an automated estimate
based on public data and may contain errors or delays.

## How it works

```
config/watchlist.yaml  →  pipeline (fetch → score → AI narrative)  →  data/*.json  →  site/ (static, no build step)
```

- **Data sources**: [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs)
  (fundamentals, prices, DCF), [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation)
  (filings + XBRL fundamentals fallback), [FRED](https://fred.stlouisfed.org/docs/api/fred/)
  (treasury yields, CPI, unemployment, Fed funds rate).
- **Scoring**: deterministic, config-driven (see `config/scoring_weights.yaml`) —
  every sub-score shows its raw inputs, not just a number. A rule-based macro regime
  classifier (`pipeline/scoring/macro_regime.py`) nudges scores based on the company's
  sector sensitivity to the current rate/inflation/employment environment.
- **AI narrative**: Claude reads the already-computed metrics (never raw news) and
  produces a one-line summary plus facts tiered Critical → Important → Minor → Noise.
  Every fact must cite a real metric key from the payload; facts that don't are
  dropped in code (`pipeline/narrative/grounding.py`), not just discouraged by prompt.
- **Value-investing checklists** (`pipeline/scoring/value_investing.py`): Graham's
  Defensive Investor criteria and the Piotroski F-Score, computed from the same fetched
  statements — no extra API calls. Buffett/Munger-style metrics (owner earnings yield,
  ROIC as a moat proxy, the Graham Number/margin of safety) feed into the long-term
  score's existing components (see `config/scoring_weights.yaml`).
- **Layered analysis** (quant screen → qualitative → valuation → thesis, see
  "Layered analysis" below): a deeper, opt-in-by-passing-the-quant-screen pass per
  company that reads the company's own 10-K text — the one place in this pipeline an
  AI call isn't grounded solely in pre-computed metrics.
- **Supply/demand signal**: each company's 3-month return vs. the average of its sector
  peers in the watchlist, plus volume vs. its own average — reported as an observed
  divergence, never a claimed cause (no news/geopolitics feed is wired in, deliberately,
  to avoid a financial tool inventing plausible-sounding but unverifiable claims).
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
  shaped to match FMP's own field names so every downstream calculation (ratios, the
  Graham/Piotroski checklists, ROIC, owner earnings) works unchanged regardless of
  which source populated it.
- **Stooq** (`pipeline/fetch/stooq.py`) — free daily close/volume history, used only
  when FMP's price/quote data is missing, covering returns, moving averages, RSI, and
  the volume-vs-average signal.

Between the two, only FMP's proprietary DCF fair-value model has no free substitute —
Graham Number/margin of safety becomes the primary assumption-free valuation check in
that case. `sources_status.stooq` in `data/meta.json` reports whether the fallback
itself is working. If you still want fuller coverage: upgrade the FMP plan, trim
`config/watchlist.yaml` to use fewer calls per run, or swap in a different primary
provider (e.g. Finnhub's free tier) in `pipeline/fetch/`.

## Layered analysis

A deeper pass per company, deliberately kept as four separate layers rather than one
blended score — a great quant score with a broken moat should get flagged, not
averaged away, and a great business at a bad price still isn't a buy. Every company
detail page shows all four, plus an `overall` synthesis and a `flags` list explaining
any disagreement between them.

1. **Quant screen** (`pipeline/scoring/quant_score.py`) — a fast, deterministic
   pass/fail filter: ROIC, FCF margin, revenue/EPS growth (5yr CAGR, falling back to
   3yr), and debt/EBITDA against thresholds in `config/quant_score_thresholds.yaml`.
   No API calls, no AI. This gates layers 2 and 4 below — they only run for a company
   that already clears this bar (deliberate cost control, not just a display filter).
2. **Qualitative** (`pipeline/narrative/qualitative_client.py`) — Claude reads
   excerpts from the company's own most recent 10-K (Business, Risk Factors, and
   Management's Discussion and Analysis, extracted by
   `pipeline/fetch/filing_text.py`) plus the quant scorecard, and classifies the
   moat (network effects / cost advantage / intangible assets / switching costs /
   efficient scale / none — the classic Buffett/Munger/Morningstar categories),
   assesses management's capital allocation, and lists any red flags the filing
   itself raises. **This is the one place in the whole pipeline where an AI call
   reads raw text instead of only pre-computed metrics.** Every other narrative call
   grounds each fact by requiring a real metric key
   (`pipeline/narrative/grounding.py` drops anything that doesn't resolve) — that
   mechanical check doesn't exist for free-form filing prose, so this layer's
   grounding is prompt discipline only, not code-verified. `qualitative.extraction_confidence`
   tells you whether the filing-text extraction itself found a clean Item 7 section
   match or fell back to a raw document prefix, so you know how much to trust it.
   Results are cached by 10-K URL under `data/qualitative_cache/` — since a 10-K only
   changes once a year, a weekly refresh skips both the filing fetch and the two
   Claude calls entirely once a company already has a current-filing assessment.
3. **Valuation** (`pipeline/scoring/valuation.py`) — a Damodaran-style 2-stage DCF
   with every assumption computed and logged, never hidden behind a single
   "fair value" number: growth rate from the company's own trailing revenue CAGR
   (clamped to -10%/+20% so one outlier year can't compound forever), a fixed 9%
   discount rate and 2.5% terminal growth rate (documented as a deliberate
   simplification — this pipeline has no reliable beta/cost-of-debt source for a
   real CAPM/WACC build), for 5 years then a Gordon-growth terminal value. Expect
   this to show *no* margin of safety for expensive, high-growth names — that's the
   conservative model doing its job, not a bug. Cross-checked against P/E and
   EV/EBITDA vs. the median of the company's sector peers in this watchlist (FMP's
   own black-box DCF and the Graham Number remain available separately as further
   cross-checks, unchanged from before this feature).
4. **Thesis + falsification** (also `pipeline/narrative/qualitative_client.py`) — a
   second Claude call synthesizes layers 1-3 into a one-paragraph thesis and a list
   of specific, checkable conditions that would prove it wrong — the discipline step
   most screening tools skip. Grounded in the other three layers' own output, not in
   new information.

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
card and at the top of the company detail page), built by literally running the
company through every filter/checklist this pipeline computes — but not via a naive
average, which would let a strong quant score quietly paper over a broken moat or an
expensive price. The formula (`pipeline/scoring/aggregation.py::build_conviction_score`,
weights in `config/conviction_score.yaml`):

1. **Weighted base score** — the four pass-rate checklists (quant screen, Graham,
   Piotroski, Fisher), each already computed elsewhere, blended by configurable
   weight. A checklist the pipeline couldn't evaluate (e.g. Piotroski needs 2 years
   of statements it doesn't have) is left out entirely and the remaining weights
   renormalize — a data gap is never scored as a failure.
2. **Qualitative moat multiplier** — ×1.05 if a moat was identified, ×0.70 if the
   qualitative layer explicitly found none, ×1.0 if that layer never ran. Applied
   after the base score, not blended into it, so it can meaningfully move the result
   regardless of how strong the checklists look.
3. **Valuation gate multiplier** — ×1.0 if the margin-of-safety gate passes (using
   the same Klarman risk-scaled threshold above), ×0.55 if it fails, ×1.0 if
   valuation couldn't be evaluated. The final gate: a wonderful business at a bad
   price still isn't a buy.

The result is clamped to 0-100 and banded into the same Strong/Favorable/Neutral/
Cautious/Weak verdicts used elsewhere (`pipeline/scoring/thresholds.py`). A company
with no data in any of the four checklists gets `conviction_score: null`, never a
misleading 0. The dashboard sorts each sector group by this score (highest first);
the full breakdown (base score, each component, both multipliers) ships in the
output and renders on the company page so a high or low score is never just a
number — you can always see why.

### Which frameworks became which filters

This project draws on ten value-investing thinkers. Rather than list them as
inspiration, here's exactly what each one turned into in the code — and, just as
importantly, what didn't become a filter and why:

| Thinker | Framework | Where it lives |
|---|---|---|
| **Benjamin Graham** | Defensive Investor checklist, Graham Number, NCAV, P/E×P/B ≤ 22.5 | `pipeline/scoring/value_investing.py` |
| **Warren Buffett** | Owner earnings, moat classification, "wonderful company at a fair price" | Owner earnings in `fundamentals.py`; moat in the qualitative layer; "wonderful company at a fair price" is literally the quant gate + valuation gate combination in `aggregation.py` |
| **Charlie Munger** | ROIC as a moat proxy; "invert, always invert" | ROIC in `fundamentals.py`; inversion is the falsification-criteria field in the thesis layer — asking what would prove the thesis wrong *is* inversion applied to a stock |
| **Philip Fisher** | 15-point checklist; "scuttlebutt" qualitative research | An adapted ~12-item checklist in the qualitative layer's `fisher_checklist` field, assessed from the 10-K text this pipeline already reads. True scuttlebutt (talking to customers/competitors) has no equivalent here — that gap is stated in the prompt itself (`qualitative_prompts.py`), and items it can't support from the filing come back `"unknown"` rather than a guess |
| **Peter Lynch** | PEG ratio; six-way growth categorization | `peg_ratio` in `fundamentals.py`; `pipeline/scoring/lynch_category.py` classifies each company as fast grower / stalwart / slow grower / cyclical / turnaround / asset play. Can't reliably tell a genuine turnaround from ordinary decline without Lynch's own on-the-ground judgment — the code says so in both places rather than pretending confidence it doesn't have |
| **Joel Greenblatt** | Magic Formula (return on capital + earnings yield, ranked) | `earnings_yield_pct` (EBIT/EV) in `fundamentals.py`; `apply_magic_formula_rank()` in `pipeline/main.py` ranks the whole watchlist by combined ROIC + earnings-yield rank, same pattern as the sector-median computation |
| **Aswath Damodaran** | Explicit-assumption DCF, narrative-to-numbers discipline | The whole valuation layer (`pipeline/scoring/valuation.py`) |
| **Seth Klarman** | Margin of safety as risk management, not just a valuation number | The risk-scaled `required_margin_of_safety_pct` in `aggregation.py`, described above |
| **Howard Marks** | Risk, cycles, second-level thinking | Cycle awareness: `macro_regime.py`'s `cycle_context` (already existed). Second-level thinking deliberately did **not** become a new field — this pipeline's AI layers are built to never speculate about market consensus or psychology beyond what's in the given data/text, and a "what does the market believe vs. what's true" field would cross that line into exactly the kind of unverifiable narrative-building this project has refused before (see the earlier decision against a live geopolitics feed). The existing thesis layer already surfaces disagreement *between this pipeline's own layers* (quant vs. qualitative vs. valuation), which is as far as this can go without speculating |
| **James O'Shaughnessy** | Factor-based backtesting (*What Works on Wall Street*) | Not implemented. Backtesting needs long-run historical return data across many stocks to validate which factors actually predicted performance — real infrastructure (historical storage, a backtest engine) this pipeline doesn't have and wasn't asked to build. His broader methodology — combining several factors into one score rather than trusting any single metric — is already what `quant_score.py` does; that's the connection without the unbuilt validation machinery behind it |

## Configuration

- `config/watchlist.yaml` — tracked tickers. Edit freely.
- `config/scoring_weights.yaml` — component weights and threshold bands for both scores.
- `config/sector_macro_sensitivity.yaml` — how much each sector's score moves under
  each macro regime.
- `config/macro_series.yaml` — which FRED series are pulled and the regime
  classification thresholds.
- `config/quant_score_thresholds.yaml` — pass/fail thresholds for the quant screen
  (layer 1 above) and the fraction of evaluated metrics that must pass to gate the
  deeper layers.
- `config/conviction_score.yaml` — component weights for the Conviction Score's base
  score, and the qualitative-moat / valuation-gate multipliers applied on top of it.

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
qualitative (10-K reasoning, Fisher checklist), valuation, thesis, and the complete
Conviction Score, identical to a tracked company. The narrative and qualitative/
thesis Claude calls run concurrently (`pipeline/main.py::finalize_company`) to keep
this as fast as possible, but it's still a real 10-K fetch plus multiple Claude calls
for one request, which takes real time.

**Timeout headroom:** `vercel.json` sets `maxDuration: 60` — the maximum a Vercel
Hobby (free) plan allows by default. If a lookup is timing out, you have two free
options before paying for anything: enable **Fluid Compute** (Vercel project →
**Settings → Functions** → toggle it on) to raise Hobby's ceiling to 300s, then bump
`maxDuration` in `vercel.json` to match and redeploy; or fall back to a faster,
partial analysis by passing `skip_qualitative=True` to `finalize_company` in
`api/lookup.py` (narrative + quant + valuation only, no 10-K fetch — sacrifices the
qualitative/Fisher/thesis layers and lowers the Conviction Score's data coverage,
but removes the two slowest steps). A Pro plan raises the ceiling further (300s by
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
