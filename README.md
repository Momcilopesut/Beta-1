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
  directly. The dashboard groups companies by GICS-style sector.

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

## Data source limits

FMP's free tier does not cover every `/stable/` endpoint this pipeline calls — in
practice, calls beyond a fairly small daily allowance return `402 Payment Required`
rather than data. When that happens the affected metrics show as missing (never
fabricated) and `data/meta.json`'s `sources_status.fmp` reads `"degraded"`; per-company
`_errors` now include the real HTTP status (e.g. `401`, `402`) so you can tell an
invalid-key problem from a plan-limit problem at a glance. Two options if you're
consistently hitting this: upgrade the FMP plan, or trim `config/watchlist.yaml` so a
full run uses fewer calls. SEC EDGAR's XBRL data is used as a fallback for some
fundamentals regardless.

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
