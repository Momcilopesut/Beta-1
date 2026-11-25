# Stock Lookup

A small personal tool that runs entirely on your own computer: search a ticker, and
it scrapes free price and news data for it, hands that to a local LLM (via
[LM Studio](https://lmstudio.ai)) to summarize, and shows you the result. No cloud
APIs, no API keys, no subscriptions - everything happens on your machine.

**This is not financial advice.** Price/news data comes from free public sources
and may be delayed, incomplete, or wrong; the summary is written by a local model
from whatever it's given and can be wrong too.

## How it works

```
your ticker  →  scraper.py (Stooq price + RSS news)  →  llm_client.py (your local LM Studio model)  →  app.py (Flask)  →  your browser
```

- **Price** (`scraper.py::fetch_price`) — Stooq's free daily CSV endpoint, no API key.
- **News** (`scraper.py::fetch_news`) — Yahoo Finance's per-ticker RSS feed, falling
  back to a Google News RSS search if that one's empty. RSS feeds are built for
  automated readers, which matters: this project's earlier attempt to fetch SEC
  filing data ran straight into SEC's anti-bot system blocking non-browser traffic
  at the TLS level (see `CLAUDE.md` for the full story) - RSS sidesteps that
  entirely rather than needing a workaround for it.
- **Summary** (`llm_client.py::summarize`) — sends the scraped price + headlines to
  your local LM Studio server and asks for a short, grounded summary. Never invents
  facts beyond what it was given; if LM Studio isn't running or returns something
  unusable, the lookup still succeeds, just without a summary (never a crash).
- **App** (`app.py`) — one Flask process serves the page and the `/api/lookup`
  endpoint that ties the above together.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust if your LM Studio setup differs from the defaults
```

Start LM Studio, load a model, and start its local server (the "Developer" tab ->
**Start Server**; default `http://localhost:1234`). Then:

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

## Local development

```bash
pip install -r requirements-dev.txt
pytest
```

Every test mocks the network (Stooq/RSS/LM Studio) - no live scraping, no LM Studio
server, and no API keys needed to run the suite.

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
