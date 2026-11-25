"""Local SQLite database for the market-wide company directory this app is
building up over time (sector by sector, starting with Technology) - see
directory.py and sector_classify.py.

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
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn
