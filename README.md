# Stock Lookup

A small personal tool that runs entirely on your own computer: search a ticker, and
it scrapes free price and news data for it, hands that to a local LLM (via
[Ollama](https://ollama.com) - [LM Studio](https://lmstudio.ai) also works, same
OpenAI-compatible API) to summarize, and shows you the result. No cloud APIs, no
API keys, no subscriptions - everything happens on your machine.

**This is not financial advice.** Price/news data comes from free public sources
and may be delayed, incomplete, or wrong; the summary is written by a local model
from whatever it's given and can be wrong too.

## How it works

```
your ticker  →  scraper.py (Yahoo Finance chart data + RSS news)  →  llm_client.py (your local LLM, via Ollama/LM Studio)  →  app.py (Flask)  →  your browser
```

- **Price** (`scraper.py::fetch_price`) — Yahoo Finance's free chart JSON endpoint, no
  API key. Stooq's CSV endpoint was tried first and abandoned after it started
  denying access even to a real browser on the same connection - see `CLAUDE.md`
  for that story and why that specific symptom means "switch sources," not "try
  harder."
- **News** (`scraper.py::fetch_news`) — Yahoo Finance's per-ticker RSS feed, falling
  back to a Google News RSS search if that one's empty. RSS feeds are built for
  automated readers, which matters: this project's earlier attempt to fetch SEC
  filing data ran straight into SEC's anti-bot system blocking non-browser traffic
  at the TLS level (see `CLAUDE.md` for the full story) - RSS sidesteps that
  entirely rather than needing a workaround for it.
- **Summary** (`llm_client.py::summarize`) — sends the scraped price + headlines to
  your local LLM server and asks for a short, grounded summary. Never invents
  facts beyond what it was given; if the server isn't running or returns something
  unusable, the lookup still succeeds, just without a summary (never a crash).
  Originally built against LM Studio; switched to Ollama after LM Studio's local
  server proved unstable under sustained batch load (see `CLAUDE.md`) - both speak
  the same API, so either works, just point `LLM_BASE_URL`/`LLM_MODEL` at whichever
  one you're running.
- **App** (`app.py`) — one Flask process serves the page and the `/api/lookup`
  endpoint that ties the above together.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust if your local LLM setup differs from the defaults
```

Install [Ollama](https://ollama.com), pull a model, and make sure it's running
(defaults to `http://localhost:11434`):

```bash
ollama pull qwen2.5:7b
ollama serve   # if it isn't already running as a background service
```

(LM Studio works too - load a model and start its local server from the
"Developer" tab, then set `LLM_BASE_URL=http://localhost:1234/v1` in `.env`.)
Then:

```bash
python app.py
```

This opens a real app window (no address bar, no browser tabs - via
[pywebview](https://pywebview.flowrl.com)), backed by a Flask server on
`http://127.0.0.1:5050/`. Type a ticker and hit "Look up." A few flags:

```bash
python app.py --browser        # open in your default browser instead (fallback)
python app.py --port 8080      # use a different port
```

Binds to `127.0.0.1` only by default - not your network, no login of any kind, since
this is a personal tool, not something meant to be reachable from anywhere else.

## Package as a Mac app (optional)

```bash
./build_app.sh
```

Builds `dist/Stock Lookup.app` (via PyInstaller - `app.spec`) - a real, double-click
app bundle, no terminal needed after this. Drag it into `/Applications`, or leave it
in `dist/`. **First launch:** since it isn't signed by Apple, Gatekeeper will block a
plain double-click - right-click the app -> **Open** once (or approve it in **System
Settings -> Privacy & Security**) to get past that; every launch after is normal.

Config for the packaged app lives at `~/.stocklookup.env` (copy `.env.example`
there) rather than a local `.env` - a double-clicked app's working directory isn't
predictable the way running `python app.py` from this folder is, so the packaged app
always checks that fixed path first.

## Building the market-wide company directory (new, in progress)

This project is growing beyond one-ticker-at-a-time lookups into a local database
covering the whole market, sector by sector - starting with Technology. This part
is a set of standalone scripts, separate from the live app above, meant to be run
once in a while (not on every app launch) and left running in the background since
there's no rush:

```bash
cp .env.example .env   # if you haven't already - set SEC_CONTACT_EMAIL in it
python3 directory.py          # pulls the full NYSE/Nasdaq company list from SEC (fast, one request)
python3 sector_classify.py --limit 20   # test on a small batch first
python3 sector_classify.py              # then the rest - thousands of requests, so this takes a while
python3 list_sector.py Technology       # see what's been tagged so far
```

- `directory.py` — the company/ticker/CIK universe, from SEC EDGAR's bulk file.
- `sector_classify.py` — tags every company with its sector/industry (via Yahoo
  Finance), one at a time. Every sector gets tagged here, not just Technology - this
  only has to run once, and later sectors are then just a database query
  (`list_sector.py "Healthcare"`, etc.) instead of a new batch job.
- Both are safe to stop (Ctrl+C) and re-run - progress is saved per company as it
  happens, not just at the end.
- The database lives at `~/.stocklookup/market.db`, outside the repo (it'll grow
  into real data over time, and a packaged `.app`'s working directory isn't
  predictable - same reasoning as `~/.stocklookup.env`).
- SEC requires a real, reachable contact (name + email) in the request header for
  every call to their servers - that's `SEC_CONTACT_EMAIL` in `.env`/`~/.stocklookup.env`.
  It's sent to SEC, nowhere else, and is never committed to this repo.

## Building the filing index (Phase 2, new, in progress)

Once a sector is classified above, this pulls each of its companies' actual
10-K/10-Q filings from the past 5 years - metadata only (dates, accession
numbers, which document to fetch) via SEC EDGAR's per-company submissions API,
not the filing text itself yet:

```bash
python3 build_filings.py --limit 5     # test on a small batch first
python3 build_filings.py               # then the rest of Technology
python3 list_filings.py AAPL           # see what's been indexed for one ticker
```

- `filings.py` — fetches and filters one company's filing history to 10-K/10-Q
  within the last 5 years (`fetch_filings(cik)`).
- `build_filings.py` — drives that across every company in a sector
  (`--sector`, default Technology), same resumable pattern as
  `sector_classify.py`: stop (Ctrl+C) and re-run anytime, progress is saved per
  company as it happens.
- `sec_client.py` — the shared SEC-compliant session (`SEC_CONTACT_EMAIL`
  header) both `directory.py` and `filings.py` use.

## Summarizing filings with your local LLM (Phase 3, new, in progress)

Once a sector has a filing index (above), this fetches each filing's actual
document, extracts the most analysis-relevant prose (Management's Discussion
and Analysis, and Risk Factors where available), and summarizes it with your
local LLM:

```bash
python3 build_summaries.py --limit 5    # test on a small batch first - this calls your local model, so it's worth watching once
python3 build_summaries.py              # then the rest of Technology
python3 list_summaries.py AMD           # see what's been summarized for one ticker
```

- `filing_text.py` — fetches one filing's document and extracts MD&A/Risk
  Factors as plain text. Full 10-Ks are HTML files far bigger than any local
  model's context window, so this doesn't summarize the whole document - just
  these two sections, using the Item-number headers every 10-K/10-Q is
  required to have. The one real wrinkle: every filing's own table of
  contents repeats these same headings near the top as links to the real
  section - `extract_section()`'s docstring explains the heuristic used to
  tell those apart from the real thing.
- `llm_client.py::summarize_filing` — same local LLM integration `summarize()`
  already used for price/news, extended for filing text. `LLM_MAX_SECTION_CHARS`
  caps how much of a section gets sent per filing (auto-shrinks further and
  retries if the model reports a context-length error), in case a section is
  still too large for your model's context window even after extraction.
- `build_summaries.py` — drives both across every stored filing in a sector,
  same resumable pattern as the earlier steps. This one runs your local model
  once per filing, so expect it to be slower per-item than the SEC/Yahoo-only
  steps - how much slower depends entirely on your model and machine. If the
  local LLM server's backend crashes mid-run, it automatically waits and
  retries a few times (`MODEL_CRASH_RETRY_ATTEMPTS`/`MODEL_CRASH_COOLDOWN_SECONDS`)
  before stopping the batch for you to check on manually.

This is the newest, least-tested part of the build-out - the section-extraction
heuristic is validated against synthetic test documents, not real SEC filings
yet, so the first real run is worth checking by eye (`list_summaries.py`)
before trusting it at scale.

## Local development

```bash
pip install -r requirements-dev.txt
pytest
```

Every test mocks the network (Stooq/RSS/local LLM) - no live scraping, no local
LLM server, and no API keys needed to run the suite.

## Known limitations (v1, deliberately kept small)

- One ticker at a time, no watchlist, no saved history.
- No fundamentals (financial statements, ratios) - just price + news + a summary.
  This was a deliberate scope cut after an earlier, much larger version of this
  project (checklists, macro overview, moat analysis, filings digest, ...) spent a
  long time fighting free-data-source fragility. See `CLAUDE.md` for what was
  learned from that and is worth remembering if this grows again.
- Yahoo Finance's RSS feeds have reportedly been unreliable in places; the Google
  News fallback exists for exactly that reason, but if both ever come up empty for
  a real ticker, that's a real gap worth revisiting, not a sign something crashed.
