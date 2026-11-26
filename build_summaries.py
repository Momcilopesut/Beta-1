"""Phase 3, step 2: for every stored filing (filings.py/build_filings.py)
in a given sector that doesn't have a summary yet, fetches the actual
document, extracts MD&A/Risk Factors (filing_text.py), and summarizes it
with the local LLM (llm_client.py::summarize_filing) - resumable the same
way sector_classify.py/build_filings.py are: each filing's result is
committed as soon as it's done, progress tracked via
filing_summaries.status ('pending'/implicit -> 'done' or 'error').

This step runs your local model once per filing, so it'll likely be
slower per-item than the earlier SEC/Yahoo-only steps - how much slower
depends entirely on your model and machine. No rush; stop (Ctrl+C) and
re-run anytime.

Usage:
    python3 build_summaries.py                   # Technology (default)
    python3 build_summaries.py --sector Healthcare
    python3 build_summaries.py --limit 5          # quick test run
"""

import argparse
import logging
import os
import time

import db
import filing_text
import llm_client

logger = logging.getLogger(__name__)

_FETCH_DELAY_SECONDS = float(os.environ.get("FILINGS_FETCH_DELAY_SECONDS", "0.3"))

# Local LLM servers (observed directly with LM Studio) can auto-reload a
# crashed model on their next request - so a crash is often
# recoverable on its own within a short wait, not something that needs a
# human to manually reload it every time. Retry a few times with a
# cooldown before giving up and stopping the whole batch.
_CRASH_RETRY_ATTEMPTS = int(os.environ.get("MODEL_CRASH_RETRY_ATTEMPTS", "3"))
_CRASH_COOLDOWN_SECONDS = float(os.environ.get("MODEL_CRASH_COOLDOWN_SECONDS", "60"))

_SELECT_PENDING = """
SELECT f.cik, f.accession_number, f.form, f.primary_document, c.ticker
FROM filings f
JOIN companies c ON c.cik = f.cik
LEFT JOIN filing_summaries fs ON fs.cik = f.cik AND fs.accession_number = f.accession_number
WHERE c.sector = ?
  AND (fs.status IS NULL OR fs.status IN ('pending', 'error'))
ORDER BY f.cik, f.filing_date DESC
"""

_UPSERT_SUMMARY = """
INSERT INTO filing_summaries (cik, accession_number, summary, status)
VALUES (:cik, :accession_number, :summary, :status)
ON CONFLICT(cik, accession_number) DO UPDATE SET
    summary = excluded.summary,
    status = excluded.status
"""


def summarize_one(row) -> str:
    """Fetches, extracts, and summarizes one filing. Raises on any
    failure - callers mark the row 'error' and move on, same
    degrade-one-item-at-a-time pattern as the rest of this build-out.

    A crashed backend gets a few cooldown-and-retry attempts here first,
    since a local LLM server often auto-reloads the model on its next
    request once it notices the old one died - only once those are
    exhausted does llm_client.ModelCrashedError propagate up to stop the
    whole batch."""
    text = filing_text.fetch_filing_text(row["cik"], row["accession_number"], row["primary_document"])
    sections = filing_text.extract_sections_for_form(text, row["form"])

    for attempt in range(1, _CRASH_RETRY_ATTEMPTS + 1):
        try:
            return llm_client.summarize_filing(row["ticker"], row["form"], sections)
        except llm_client.ModelCrashedError as exc:
            if attempt >= _CRASH_RETRY_ATTEMPTS:
                raise
            logger.warning(
                "Local LLM backend crash for %s (attempt %d/%d) - waiting %ds for it to recover: %s",
                row["ticker"],
                attempt,
                _CRASH_RETRY_ATTEMPTS,
                _CRASH_COOLDOWN_SECONDS,
                exc,
            )
            time.sleep(_CRASH_COOLDOWN_SECONDS)


def build_for_sector(sector: str, limit: int | None = None) -> dict:
    conn = db.get_connection()
    counts = {"done": 0, "errored": 0}
    try:
        query = _SELECT_PENDING
        params: tuple = (sector,)
        if limit:
            query += " LIMIT ?"
            params = (sector, limit)
        rows = conn.execute(query, params).fetchall()

        total = len(rows)
        logger.info("Summarizing %d filings for sector '%s'...", total, sector)
        for i, row in enumerate(rows, start=1):
            try:
                summary = summarize_one(row)
                conn.execute(
                    _UPSERT_SUMMARY,
                    {"cik": row["cik"], "accession_number": row["accession_number"], "summary": summary, "status": "done"},
                )
                counts["done"] += 1
                logger.info("  %s %s (%s): done", row["ticker"], row["form"], row["accession_number"])
            except llm_client.ModelCrashedError as exc:
                # The model process itself has died - every remaining
                # filing would fail identically, so stopping now (rather
                # than marking thousands of filings as individually
                # "errored" for no real reason) and leaving them pending
                # is the right move. Reload the model in your local LLM
                # server, then just re-run this script to pick back up.
                logger.error(
                    "Stopping this run: %s. Reload the model in your local LLM server, then re-run this script - it'll pick up where it left off.",
                    exc,
                )
                return counts
            except (filing_text.FilingTextError, llm_client.LlmError) as exc:
                logger.warning("Marking %s %s as error (will retry next run): %s", row["ticker"], row["accession_number"], exc)
                conn.execute(
                    _UPSERT_SUMMARY,
                    {"cik": row["cik"], "accession_number": row["accession_number"], "summary": None, "status": "error"},
                )
                counts["errored"] += 1
            conn.commit()

            if i % 10 == 0 or i == total:
                logger.info("Progress: %d/%d (%d done, %d errored)", i, total, counts["done"], counts["errored"])

            time.sleep(_FETCH_DELAY_SECONDS)
    finally:
        conn.close()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarize stored filings for every company in a sector (resumable).")
    parser.add_argument("--sector", default="Technology")
    parser.add_argument("--limit", type=int, default=None, help="Only process this many filings (useful for a quick test run).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = build_for_sector(args.sector, limit=args.limit)
    logger.info("Done: %s", result)
