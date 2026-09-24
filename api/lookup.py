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

from pipeline.main import (  # noqa: E402
    _risk_free_rate_pct,
    fetch_and_score_company,
    fetch_benchmark,
    fetch_macro,
    finalize_company,
)
from pipeline.scoring import capital_efficiency  # noqa: E402
from pipeline.utils.config import capital_efficiency_config  # noqa: E402

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


def _macro() -> tuple[dict, dict]:
    try:
        return fetch_macro()
    except Exception:  # noqa: BLE001
        logger.exception("Macro fetch failed; using a neutral regime")
        return {}, {"regime": "Neutral/Expansion", "signals": {}}


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
        macro_data, regime_info = _macro()
        benchmark_prices = fetch_benchmark()
        state = fetch_and_score_company({"ticker": ticker}, regime_info, benchmark_prices)
        # Full parity with the batch pipeline - identical scoring, the same
        # 10-K filing summaries (subject to this function's timeout -
        # vercel.json's maxDuration, see README's "On-demand lookup
        # deployment" section for raising it, or pass ?ai=0 to skip it), and
        # the same quantitative Moat Signal (value_creation_pct - needs no
        # AI call, so it's unaffected by ?ai=0 either way). ce_inputs/
        # risk_free_rate_pct/ce_cfg feed just that last one; a fetch_macro
        # failure above still gets a company_doc back, just without a moat
        # read for this ticker (None propagates gracefully, same "null not
        # zero" convention as everywhere else).
        ce_inputs = capital_efficiency.company_capital_efficiency_inputs(state["raw"], state["profile"])
        ce_cfg = capital_efficiency_config()
        risk_free_rate_pct = _risk_free_rate_pct(macro_data, ce_cfg["risk_free_rate_series"])
        company_doc, _summary, _qual_failed = finalize_company(
            state, regime_info, skip_ai, Path(tempfile.gettempdir()), ce_inputs, risk_free_rate_pct, ce_cfg
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
