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

# Unlike scraper.py's v8/finance/chart (no auth needed), Yahoo's
# quoteSummary endpoint requires a "crumb" token tied to a session cookie -
# a real requirement for every caller (Yahoo's own site does the same
# handshake), not anti-bot blocking, confirmed by the 401 on a plain
# request. Seed cookies from fc.yahoo.com, then exchange them for a crumb;
# cached module-wide since it stays valid across many calls, refreshed on
# demand if a request ever 401s with it.
_crumb: str | None = None


class SectorFetchError(Exception):
    pass


def _refresh_crumb() -> str:
    global _crumb
    _session.get("https://fc.yahoo.com", timeout=10)
    resp = _session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
    resp.raise_for_status()
    crumb = resp.text.strip()
    if not crumb:
        raise SectorFetchError("Yahoo returned an empty crumb")
    _crumb = crumb
    return crumb


def _request_quote_summary(ticker: str, crumb: str) -> requests.Response:
    return _session.get(
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
        params={"modules": "assetProfile", "crumb": crumb},
        timeout=10,
    )


def fetch_sector(ticker: str) -> dict:
    """Returns {"sector": str|None, "industry": str|None} from Yahoo
    Finance's quoteSummary endpoint for one ticker. A ticker Yahoo has no
    profile for (delisted, wrong symbol, etc.) comes back as both None,
    same degrade-gracefully pattern as scraper.py's fetch_price."""
    global _crumb
    try:
        crumb = _crumb or _refresh_crumb()
        resp = _request_quote_summary(ticker, crumb)
        if resp.status_code == 401:
            # Crumb/cookie expired mid-run - refresh once and retry this
            # one ticker before giving up on it.
            crumb = _refresh_crumb()
            resp = _request_quote_summary(ticker, crumb)
        if resp.status_code == 404:
            # SEC's bulk file includes preferred shares, rights, and other
            # non-common-stock tickers under the same CIK as a real
            # company (e.g. "BA-PA", "CELG-RI") - Yahoo has no profile for
            # most of these under that exact symbol. That's a real,
            # permanent answer ("no data"), not a failure worth retrying
            # forever.
            logger.debug("No Yahoo profile for %s (404) - treating as no data", ticker)
            return {"sector": None, "industry": None}
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
