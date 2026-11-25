"""Prints every company currently tagged with a given sector (default:
Technology). A quick way to check progress or results from
sector_classify.py without writing SQL by hand.

Usage:
    python3 list_sector.py              # Technology
    python3 list_sector.py "Healthcare"
"""

import argparse

import db


def list_sector(sector: str) -> list[dict]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT ticker, name, industry FROM companies WHERE sector = ? ORDER BY ticker",
            (sector,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List companies currently tagged with a given sector.")
    parser.add_argument("sector", nargs="?", default="Technology")
    args = parser.parse_args()

    companies = list_sector(args.sector)
    print(f"{len(companies)} companies in sector '{args.sector}':")
    for c in companies:
        print(f"  {c['ticker']:<8} {c['name']} ({c['industry']})")
