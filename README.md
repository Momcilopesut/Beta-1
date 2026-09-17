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

## Configuration

- `config/watchlist.yaml` — tracked tickers. Edit freely.
- `config/scoring_weights.yaml` — component weights and threshold bands for both scores.
- `config/sector_macro_sensitivity.yaml` — how much each sector's score moves under
  each macro regime.
- `config/macro_series.yaml` — which FRED series are pulled and the regime
  classification thresholds.

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
