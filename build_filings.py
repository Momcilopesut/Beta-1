"""Driver for filings.py: builds the 10-K/10-Q filing index for every
company in a given sector, resumable the same way sector_classify.py is -
each company's result is committed to the database as soon as it's
fetched, and progress is tracked via companies.filings_status ('pending'
-> 'done' or 'error') rather than redoing the whole batch on every run.

Usage:
    python3 build_filings.py                   # Technology (default)
    python3 build_filings.py --sector Healthcare
    python3 build_filings.py --limit 10         # quick test run
"""

import argparse
import logging
import os
import time

import db
import filings

logger = logging.getLogger(__name__)

_DELAY_SECONDS = float(os.environ.get("FILINGS_FETCH_DELAY_SECONDS", "0.3"))

_UPSERT_FILING = """
INSERT INTO filings (cik, accession_number, form, filing_date, report_date, primary_document)
VALUES (:cik, :accession_number, :form, :filing_date, :report_date, :primary_document)
ON CONFLICT(cik, accession_number) DO UPDATE SET
    form = excluded.form,
    filing_date = excluded.filing_date,
    report_date = excluded.report_date,
    primary_document = excluded.primary_document
"""


def build_for_sector(sector: str, limit: int | None = None) -> dict:
    conn = db.get_connection()
    counts = {"done": 0, "errored": 0}
    try:
        query = "SELECT cik, ticker FROM companies WHERE sector = ? AND filings_status IN ('pending', 'error') ORDER BY cik"
        params: tuple = (sector,)
        if limit:
            query += " LIMIT ?"
            params = (sector, limit)
        rows = conn.execute(query, params).fetchall()

        total = len(rows)
        logger.info("Building filing index for %d companies in sector '%s'...", total, sector)
        for i, row in enumerate(rows, start=1):
            try:
                company_filings = filings.fetch_filings(row["cik"])
                conn.executemany(_UPSERT_FILING, [{**f, "cik": row["cik"]} for f in company_filings])
                conn.execute("UPDATE companies SET filings_status = 'done' WHERE cik = ?", (row["cik"],))
                counts["done"] += 1
                logger.info("  %s: %d filings", row["ticker"], len(company_filings))
            except filings.FilingsFetchError as exc:
                logger.warning("Marking %s as error (will retry next run): %s", row["ticker"], exc)
                conn.execute("UPDATE companies SET filings_status = 'error' WHERE cik = ?", (row["cik"],))
                counts["errored"] += 1
            conn.commit()

            if i % 25 == 0 or i == total:
                logger.info("Progress: %d/%d (%d done, %d errored)", i, total, counts["done"], counts["errored"])

            time.sleep(_DELAY_SECONDS)
    finally:
        conn.close()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the 10-K/10-Q filing index for every company in a sector (resumable).")
    parser.add_argument("--sector", default="Technology")
    parser.add_argument("--limit", type=int, default=None, help="Only process this many companies (useful for a quick test run).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = build_for_sector(args.sector, limit=args.limit)
    logger.info("Done: %s", result)
