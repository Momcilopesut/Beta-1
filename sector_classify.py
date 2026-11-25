"""Phase 1b of the market-wide build-out: tags every company already in
the local directory (directory.py) with its sector/industry, one Yahoo
Finance lookup at a time.

This is the slow part - thousands of individual HTTP requests - so it's
built to be interrupted and resumed freely: each company's result is
committed to the database as soon as it's fetched, and progress is
tracked via sector_status ('pending' -> 'done' or 'error') rather than
redoing the whole batch on every run.

Every company gets classified here, not just Technology - the request has
to be made per company either way to find out what sector it's in, so
later sectors (financials, healthcare, ...) end up as a plain database
query instead of a new batch job.
"""

import argparse
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".stocklookup.env")
load_dotenv()

import db

logger = logging.getLogger(__name__)

_DELAY_SECONDS = float(os.environ.get("SECTOR_FETCH_DELAY_SECONDS", "0.4"))
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_session = requests.Session()
_session.headers.update(_BROWSER_HEADERS)


class SectorFetchError(Exception):
    pass


def fetch_sector(ticker: str) -> dict:
    """Returns {"sector": str|None, "industry": str|None} from Yahoo
    Finance's quoteSummary endpoint for one ticker. A ticker Yahoo has no
    profile for (delisted, wrong symbol, etc.) comes back as both None,
    same degrade-gracefully pattern as scraper.py's fetch_price."""
    try:
        resp = _session.get(
            f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
            params={"modules": "assetProfile"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise SectorFetchError(f"Sector fetch failed for {ticker}: {exc}") from exc

    try:
        profile = payload["quoteSummary"]["result"][0]["assetProfile"]
    except (KeyError, IndexError, TypeError):
        return {"sector": None, "industry": None}

    return {"sector": profile.get("sector"), "industry": profile.get("industry")}


def classify_pending(limit: int | None = None) -> dict:
    """Looks up and stores sector/industry for every company not yet
    classified ('pending' or 'error'), lowest CIK first. Safe to stop
    (Ctrl+C) and re-run - each row is committed right after its own
    lookup. Returns {"done": n, "errored": n}."""
    conn = db.get_connection()
    counts = {"done": 0, "errored": 0}
    try:
        # 'error' rows are retried too, not just 'pending' - a transient
        # network blip shouldn't permanently strand a company unclassified.
        query = "SELECT cik, ticker FROM companies WHERE sector_status IN ('pending', 'error') ORDER BY cik"
        params: tuple = ()
        if limit:
            query += " LIMIT ?"
            params = (limit,)
        rows = conn.execute(query, params).fetchall()

        total = len(rows)
        logger.info("Classifying %d pending companies...", total)
        for i, row in enumerate(rows, start=1):
            try:
                result = fetch_sector(row["ticker"])
                conn.execute(
                    "UPDATE companies SET sector = ?, industry = ?, sector_status = 'done' WHERE cik = ?",
                    (result["sector"], result["industry"], row["cik"]),
                )
                counts["done"] += 1
            except SectorFetchError as exc:
                logger.warning("Marking %s as error (will retry next run): %s", row["ticker"], exc)
                conn.execute("UPDATE companies SET sector_status = 'error' WHERE cik = ?", (row["cik"],))
                counts["errored"] += 1
            conn.commit()

            if i % 50 == 0 or i == total:
                logger.info("Progress: %d/%d (%d done, %d errored)", i, total, counts["done"], counts["errored"])

            time.sleep(_DELAY_SECONDS)
    finally:
        conn.close()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify companies in the local directory by sector (resumable).")
    parser.add_argument("--limit", type=int, default=None, help="Only process this many companies (useful for a quick test run).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = classify_pending(limit=args.limit)
    logger.info("Done: %s", result)
