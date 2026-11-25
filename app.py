"""Desktop entry point: run this project entirely from your own computer.

    python app.py                  # start the local server, open it in your browser
    python app.py --refresh-now    # run the full screen first (prints progress here), then serve
    python app.py --no-browser     # don't auto-open a browser tab
    python app.py --port 8080

One process does everything that used to be split across GitHub Actions
(the scheduled weekly screen + commit + GitHub Pages deploy) and a
separately-deployed Vercel function (api/lookup.py, now removed): it
serves the static frontend (site/) and the data it reads (data/) exactly
like scripts/dev_server.sh did, PLUS a same-origin /api/lookup for
on-demand tickers and /api/refresh to re-run the full screen - so
everything in README's "Data source limits and free backup chain" and
"Local generation with LM Studio" sections now applies to every run, not
just manual ones. See README's "Running the app" section for setup.

Binds to 127.0.0.1 (not your network) by default - this is a personal
tool, not something meant to be reachable from another machine. Pass
--host 0.0.0.0 only if you specifically want that and understand the
exposure (no auth of any kind is implemented, deliberately - see README).
"""

import argparse
import logging
import threading
import time
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from pipeline.main import (  # noqa: E402
    _risk_free_rate_pct,
    fetch_and_score_company,
    fetch_benchmark,
    fetch_macro,
    finalize_company,
    parse_args,
    run_full,
)
from pipeline.scoring import capital_efficiency  # noqa: E402
from pipeline.build import writer  # noqa: E402
from pipeline.utils.config import capital_efficiency_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 5050

app = Flask(__name__, static_folder=str(REPO_ROOT), static_url_path="")

# --- On-demand lookup (same job api/lookup.py used to do on Vercel, minus
# the CORS/search-key handling a publicly-reachable cloud function needed -
# this only ever talks to itself, same-origin, on localhost). Always
# use_fmp=False: see README, this is the fully-local/free path. ---

_MACRO_CACHE_SECONDS = 6 * 3600
_macro_cache: dict = {"ts": 0.0, "macro_data": {}, "regime_info": None, "benchmark_prices": []}
_macro_lock = threading.Lock()


def _macro_context() -> tuple[dict, dict, list[dict]]:
    """Macro/benchmark data changes slowly (daily at most) and costs a FRED
    round trip, so it's cached in-process for a few hours rather than
    re-fetched on every single ticker lookup."""
    with _macro_lock:
        stale = time.time() - _macro_cache["ts"] > _MACRO_CACHE_SECONDS
        if _macro_cache["regime_info"] is None or stale:
            try:
                macro_data, regime_info = fetch_macro()
            except Exception:  # noqa: BLE001
                logger.exception("Macro fetch failed; using a neutral regime")
                macro_data, regime_info = {}, {"regime": "Neutral/Expansion", "signals": {}}
            benchmark_prices = fetch_benchmark(use_fmp=False)
            _macro_cache.update(
                ts=time.time(), macro_data=macro_data, regime_info=regime_info, benchmark_prices=benchmark_prices
            )
        return _macro_cache["macro_data"], _macro_cache["regime_info"], _macro_cache["benchmark_prices"]


def _valid_ticker(ticker: str) -> bool:
    if not ticker or len(ticker) > 10:
        return False
    return ticker.replace(".", "").replace("-", "").isalnum()


@app.route("/api/lookup", methods=["GET"])
def api_lookup():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not _valid_ticker(ticker):
        return jsonify({"error": "Provide a valid ?ticker= (letters/numbers/./-, max 10 chars)."}), 400

    skip_ai = request.args.get("ai") == "0"

    try:
        macro_data, regime_info, benchmark_prices = _macro_context()
        state = fetch_and_score_company({"ticker": ticker}, regime_info, benchmark_prices, use_fmp=False)
        ce_inputs = capital_efficiency.company_capital_efficiency_inputs(state["raw"], state["profile"])
        ce_cfg = capital_efficiency_config()
        risk_free_rate_pct = _risk_free_rate_pct(macro_data, ce_cfg["risk_free_rate_series"])
        # Writing into the real data/qualitative_cache/ (not a temp dir, as
        # api/lookup.py used on Vercel's ephemeral filesystem) so a repeat
        # local search for the same ad-hoc ticker reuses the cached
        # qualitative read instead of re-running the AI call (Anthropic
        # spend, or your own LM Studio's compute) every time.
        company_doc, _summary, _qual_failed = finalize_company(
            state, regime_info, skip_ai, writer.output_dir(dry_run=False), ce_inputs, risk_free_rate_pct, ce_cfg
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Lookup failed for %s", ticker)
        return jsonify({"error": f"Analysis failed for {ticker}: {exc}"}), 502

    company_doc["on_demand"] = True
    return jsonify(company_doc)


# --- Full-screen refresh (what the retired weekly-screen.yml used to do on
# a schedule, in the cloud). Runs in a background thread so the HTTP
# request returns immediately; poll /api/refresh/status for progress.
# Only one run at a time - a second request while one is running is
# rejected rather than queued or stomping on the first. ---

_refresh_lock = threading.Lock()
_refresh_state: dict = {"status": "idle", "started_at": None, "finished_at": None, "message": None}


def _pipeline_args(tickers: str | None, skip_ai: bool) -> argparse.Namespace:
    """Always dry_run=False, use_fmp=False: a refresh triggered from this
    app writes real data/ (there's no separate CI commit step anymore) and
    stays on the free-sources-only path (see README)."""
    args = parse_args([])
    args.tickers = tickers
    args.dry_run = False
    args.skip_ai = skip_ai
    args.use_fmp = False
    return args


def _run_refresh(tickers: str | None, skip_ai: bool) -> None:
    try:
        logger.info("Refresh starting (tickers=%s, skip_ai=%s)", tickers or "<all>", skip_ai)
        exit_code = run_full(_pipeline_args(tickers, skip_ai))
        _refresh_state.update(
            status="done" if exit_code == 0 else "error",
            finished_at=writer.now_iso(),
            message=None if exit_code == 0 else "run_full() reported a failure - see this terminal's log above.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Refresh failed")
        _refresh_state.update(status="error", finished_at=writer.now_iso(), message=str(exc))
    finally:
        _refresh_lock.release()


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if not _refresh_lock.acquire(blocking=False):
        # **_refresh_state last would clobber this literal "status" with
        # whatever _refresh_state's own "status" already is ("running") -
        # spread first, literal second, so the response always correctly
        # says why this particular request was rejected.
        return jsonify({**_refresh_state, "status": "already_running"}), 409

    body = request.get_json(silent=True) or {}
    tickers = body.get("tickers") or None
    skip_ai = bool(body.get("skip_ai", False))
    _refresh_state.update(status="running", started_at=writer.now_iso(), finished_at=None, message=None)
    thread = threading.Thread(target=_run_refresh, args=(tickers, skip_ai), daemon=True)
    thread.start()
    return jsonify({**_refresh_state, "status": "started"})


@app.route("/api/refresh/status", methods=["GET"])
def api_refresh_status():
    return jsonify(_refresh_state)


# --- Static site (site/ + data/, same relative layout scripts/dev_server.sh
# already serves for local preview - app.py replaces that script, it isn't
# meant to run alongside it). ---


@app.route("/")
def index():
    return send_from_directory(REPO_ROOT / "site", "index.html")


def _open_browser(url: str, delay_seconds: float = 1.0) -> None:
    time.sleep(delay_seconds)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - no browser available (e.g. headless) is fine, just log and move on
        logger.info("Couldn't auto-open a browser; open %s yourself.", url)


def parse_app_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1, local-only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab on startup")
    parser.add_argument(
        "--refresh-now",
        action="store_true",
        help="Run the full screen synchronously (progress prints to this terminal) before starting the server",
    )
    parser.add_argument("--tickers", help="With --refresh-now: comma-separated tickers (default: full watchlist)")
    parser.add_argument("--skip-ai", action="store_true", help="With --refresh-now: skip the AI moat-read/filing-summary call")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_app_args(argv)

    if args.refresh_now:
        run_full(_pipeline_args(args.tickers, args.skip_ai))

    url = f"http://{args.host}:{args.port}/"
    logger.info("Serving %s at %s", REPO_ROOT, url)
    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    main()
