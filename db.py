"""Local SQLite database for the market-wide company directory this app is
building up over time (sector by sector, starting with Technology) - see
directory.py, sector_classify.py, and filings.py/build_filings.py.

Kept under the user's home directory rather than inside the repo, for the
same reason app.py loads config from ~/.stocklookup.env: a double-clicked
.app's working directory isn't predictable, and this will grow into a real
amount of data over time, which doesn't belong checked into git either.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".stocklookup" / "market.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    sector TEXT,
    industry TEXT,
    sector_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_sector_status ON companies(sector_status);
CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector);

CREATE TABLE IF NOT EXISTS filings (
    cik INTEGER NOT NULL,
    accession_number TEXT NOT NULL,
    form TEXT NOT NULL,
    filing_date TEXT,
    report_date TEXT,
    primary_document TEXT,
    PRIMARY KEY (cik, accession_number)
);
CREATE INDEX IF NOT EXISTS idx_filings_cik_form ON filings(cik, form);

CREATE TABLE IF NOT EXISTS filing_summaries (
    cik INTEGER NOT NULL,
    accession_number TEXT NOT NULL,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (cik, accession_number)
);
"""

# Columns added after the first release of this table - CREATE TABLE IF NOT
# EXISTS above won't add these to a companies table that already exists
# from before this column was introduced, so anyone with an existing
# market.db needs them added explicitly, once, here.
_MIGRATED_COLUMNS = [
    ("companies", "filings_status", "TEXT NOT NULL DEFAULT 'pending'"),
]


def _ensure_columns(conn: sqlite3.Connection) -> None:
    for table, column, coltype in _MIGRATED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _ensure_columns(conn)
    conn.commit()
    return conn
