"""Phase 1a of the market-wide build-out: pulls the full list of actively
NYSE/Nasdaq-listed US companies from SEC EDGAR's bulk ticker/exchange file
into the local database (db.py).

Sector tagging is a separate, much slower step (sector_classify.py) since
it needs one request per company instead of one bulk file - this module
only gets the company/ticker/CIK universe in place.

SEC's fair-access policy requires a real, reachable contact in the
User-Agent on every request to their servers - set SEC_CONTACT_EMAIL in
~/.stocklookup.env (see .env.example). Unlike the data.sec.gov JSON API
that CLAUDE.md's TLS-fingerprinting incident was about, this is a static
file under www.sec.gov/files/ - if it 403s even with a compliant header,
run that lesson's diagnostic (does a real browser load the exact URL fine
on this same machine/connection?) before assuming this needs the same
curl_cffi workaround.
"""

import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".stocklookup.env")
load_dotenv()

import db

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_ALLOWED_EXCHANGES = {"NYSE", "NASDAQ"}


class DirectoryError(Exception):
    pass


def _sec_session() -> requests.Session:
    contact = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not contact:
        raise DirectoryError(
            "SEC_CONTACT_EMAIL is not set. SEC requires a real, reachable "
            "contact in the User-Agent for every request to their servers - "
            'set it in ~/.stocklookup.env, e.g.:\n  SEC_CONTACT_EMAIL="Your Name your@email.com"'
        )
    session = requests.Session()
    session.headers.update({"User-Agent": f"stock-hub-personal-project ({contact})"})
    return session


def fetch_sec_companies() -> list[dict]:
    """Downloads SEC's bulk ticker/exchange file and returns every row
    listed on NYSE or Nasdaq, as {"cik", "ticker", "name", "exchange"}."""
    try:
        resp = _sec_session().get(_TICKERS_URL, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise DirectoryError(f"Failed to fetch SEC company list: {exc}") from exc

    try:
        fields = payload["fields"]
        rows = payload["data"]
    except (KeyError, TypeError) as exc:
        raise DirectoryError(f"Unexpected response shape from SEC: {exc}") from exc

    idx = {name: i for i, name in enumerate(fields)}
    for required in ("cik", "ticker", "name", "exchange"):
        if required not in idx:
            raise DirectoryError(f"SEC response is missing expected field '{required}' - fields were {fields}")

    seen_exchanges = set()
    out = []
    for row in rows:
        exchange_raw = (row[idx["exchange"]] or "").strip()
        seen_exchanges.add(exchange_raw)
        if exchange_raw.upper() not in _ALLOWED_EXCHANGES:
            continue
        out.append(
            {
                "cik": int(row[idx["cik"]]),
                "ticker": row[idx["ticker"]],
                "name": row[idx["name"]],
                "exchange": exchange_raw,
            }
        )

    if not out:
        # Same reasoning as scraper.py's empty-feed logging: a silent empty
        # result here looks identical whether SEC changed their field names
        # or just doesn't use the exchange strings this was written against.
        logger.warning(
            "No NYSE/Nasdaq rows matched - every distinct 'exchange' value SEC actually sent: %s",
            sorted(seen_exchanges),
        )
    return out


def build_directory() -> int:
    """Fetches the SEC company list and (re)populates the local companies
    table. Existing sector/sector_status for a company already stored is
    left untouched - re-running this doesn't throw away classification
    work sector_classify.py already did."""
    companies = fetch_sec_companies()
    conn = db.get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO companies (cik, ticker, name, exchange)
            VALUES (:cik, :ticker, :name, :exchange)
            ON CONFLICT(cik) DO UPDATE SET
                ticker = excluded.ticker,
                name = excluded.name,
                exchange = excluded.exchange
            """,
            companies,
        )
        conn.commit()
    finally:
        conn.close()
    return len(companies)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    count = build_directory()
    logger.info("Stored %d NYSE/Nasdaq companies in %s", count, db.DB_PATH)
