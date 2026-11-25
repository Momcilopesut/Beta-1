"""Prints the stored filing summaries for one ticker - a quick way to
check build_summaries.py's results without writing SQL by hand.

Usage:
    python3 list_summaries.py AMD
"""

import argparse

import db


def list_summaries(ticker: str) -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT f.form, f.filing_date, f.report_date, fs.status, fs.summary
            FROM filings f
            JOIN companies c ON c.cik = f.cik
            LEFT JOIN filing_summaries fs ON fs.cik = f.cik AND fs.accession_number = f.accession_number
            WHERE c.ticker = ?
            ORDER BY f.filing_date DESC
            """,
            (ticker.upper(),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List stored filing summaries for one ticker.")
    parser.add_argument("ticker")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    rows = list_summaries(ticker)
    print(f"{len(rows)} filings for {ticker}:")
    for r in rows:
        status = r["status"] or "not started"
        print(f"\n{r['form']} filed {r['filing_date']} (report period {r['report_date']}) - {status}")
        if r["summary"]:
            print(f"  {r['summary']}")
