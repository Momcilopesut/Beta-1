"""Vercel Python serverless function: GET /api/lookup?ticker=XYZ

On-demand equivalent of the batch pipeline's per-company analysis, for any
ticker - not just ones tracked in config/watchlist.yaml. Reuses
pipeline/main.py's own fetch_and_score_company()/finalize_company()
directly, so a live lookup is computed identically to a scheduled batch
run; this file is purely HTTP handling, access control, and macro-fetch
resilience.

Deployed separately from the GitHub-Pages-hosted static site (Pages can't
run server code) - the frontend calls this cross-origin. See README.md's
"On-demand lookup" section for Vercel setup, required environment
variables, and why SEARCH_API_KEY matters (this endpoint spends your FMP/
Anthropic API budget on every call; left unprotected, anyone who finds the
URL can run it up).
"""

import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, request  # noqa: E402

from pipeline.main import fetch_and_score_company, fetch_benchmark, fetch_macro, finalize_company  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Search-Key"
    return response


def _error(message: str, status: int):
    return _cors(jsonify({"error": message})), status


def _access_allowed() -> bool:
    required = os.environ.get("SEARCH_API_KEY")
    if not required:
        return True  # explicit opt-out; see README - not recommended for a public deployment
    provided = request.headers.get("X-Search-Key") or request.args.get("key")
    return provided == required


def _valid_ticker(ticker: str) -> bool:
    if not ticker or len(ticker) > 10:
        return False
    return ticker.replace(".", "").replace("-", "").isalnum()


def _regime() -> dict:
    try:
        _macro_data, regime_info = fetch_macro()
        return regime_info
    except Exception:  # noqa: BLE001
        logger.exception("Macro fetch failed; using a neutral regime")
        return {"regime": "Neutral/Expansion", "signals": {}}


@app.route("/api/lookup", methods=["GET", "OPTIONS"])
def lookup():
    if request.method == "OPTIONS":
        return _cors(app.make_default_options_response())

    if not _access_allowed():
        return _error("Invalid or missing search key.", 401)

    ticker = (request.args.get("ticker") or "").strip().upper()
    if not _valid_ticker(ticker):
        return _error("Provide a valid ?ticker= (letters/numbers/./-, max 10 chars).", 400)

    skip_ai = request.args.get("ai") == "0"

    try:
        regime_info = _regime()
        benchmark_prices = fetch_benchmark()
        state = fetch_and_score_company({"ticker": ticker}, regime_info, benchmark_prices)
        # Full parity with the batch pipeline - narrative and qualitative
        # run concurrently (see finalize_company's docstring) to fit this
        # function's timeout (vercel.json's maxDuration - see README's
        # "On-demand lookup deployment" section for raising it if you have
        # Vercel headroom for it, e.g. Fluid Compute or a Pro plan).
        company_doc, _summary, _warnings, _qual_failed, _narrative_failed = finalize_company(
            state, regime_info, skip_ai, Path(tempfile.gettempdir())
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Lookup failed for %s", ticker)
        return _error(f"Analysis failed for {ticker}: {exc}", 502)

    company_doc["on_demand"] = True
    return _cors(jsonify(company_doc))


# Local dev: `python api/lookup.py`, then e.g.
#   curl "http://localhost:5328/api/lookup?ticker=AAPL"
if __name__ == "__main__":
    app.run(port=5328, debug=True)
