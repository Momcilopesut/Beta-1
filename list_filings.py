"""Prints the stored 10-K/10-Q filing index for one ticker - a quick way
to check build_filings.py's results without writing SQL by hand.

Usage:
    python3 list_filings.py AAPL
"""

import argparse

import db


def list_filings(ticker: str) -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT f.form, f.filing_date, f.report_date, f.accession_number, f.primary_document
            FROM filings f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = ?
            ORDER BY f.filing_date DESC
            """,
            (ticker.upper(),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List stored 10-K/10-Q filings for one ticker.")
    parser.add_argument("ticker")
    args = parser.parse_args()

    rows = list_filings(args.ticker)
    ticker = args.ticker.upper()
    print(f"{len(rows)} filings for {ticker}:")
    for r in rows:
        print(f"  {r['form']:<6} filed {r['filing_date']}  (report period {r['report_date']})  {r['accession_number']}  {r['primary_document']}")
