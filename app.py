"""Desktop entry point: run this project entirely from your own computer.

    python app.py              # start the local server, open it in your browser
    python app.py --no-browser
    python app.py --port 8080

Search a ticker; it scrapes free price (Stooq) and news (RSS) data for
it, asks your local LM Studio model to summarize it, and shows the
result - no cloud APIs, no API keys, nothing but your own machine.
"""

import argparse
import logging
import threading
import time
import webbrowser

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

import scraper  # noqa: E402
from llm_client import LlmError, summarize  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_PORT = 5050

app = Flask(__name__)


def _valid_ticker(ticker: str) -> bool:
    if not ticker or len(ticker) > 10:
        return False
    return ticker.replace(".", "").replace("-", "").isalnum()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/lookup")
def api_lookup():
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not _valid_ticker(ticker):
        return jsonify({"error": "Provide a valid ?ticker= (letters/numbers/./-, max 10 chars)."}), 400

    try:
        price = scraper.fetch_price(ticker)
    except scraper.ScraperError as exc:
        logger.warning("Price fetch failed for %s: %s", ticker, exc)
        price = {"close": None, "as_of": None, "change_pct": None}

    news = scraper.fetch_news(ticker)

    try:
        summary = summarize(ticker, price, news)
    except LlmError as exc:
        logger.warning("LLM summary failed for %s: %s", ticker, exc)
        summary = None

    return jsonify({"ticker": ticker, "price": price, "news": news, "summary": summary})


def _open_browser(url: str, delay_seconds: float = 1.0) -> None:
    time.sleep(delay_seconds)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - no browser available (e.g. headless) is fine, just log and move on
        logger.info("Couldn't auto-open a browser; open %s yourself.", url)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1, local-only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab on startup")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    url = f"http://{args.host}:{args.port}/"
    logger.info("Serving at %s", url)
    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    main()
