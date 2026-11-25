"""Phase 2 of the market-wide build-out: for one company already in the
local directory (directory.py), pulls its filing history from SEC EDGAR
and returns the 10-K/10-Q filings from the past 5 years - metadata only
(accession number, dates, and the primary document's filename), not the
filing text itself. Fetching and summarizing the actual documents is a
later step; this just builds the index of what to fetch.

SEC EDGAR's data.sec.gov JSON API is exactly the endpoint CLAUDE.md's
TLS-fingerprinting incident was about (an earlier version of this project
got 403 "Request Rate Threshold Exceeded" from here on a real machine,
well under the documented rate limit, with fully compliant headers - the
real cause turned out to be TLS/HTTP2 fingerprinting, not rate limiting).
If this hits the same wall, run that lesson's diagnostic (does a real
browser load the exact same URL fine on this same machine/connection?)
before assuming this needs the same curl_cffi workaround - directory.py's
bulk-file fetch against www.sec.gov did NOT hit this, so there's no
guarantee data.sec.gov will either; test first.
"""

import logging
from datetime import date, timedelta

import requests

import sec_client

logger = logging.getLogger(__name__)

_LOOKBACK_YEARS = 5
_TARGET_FORMS = {"10-K", "10-Q"}


class FilingsFetchError(Exception):
    pass


def _fetch_filing_page(session: requests.Session, url: str) -> dict:
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _extract_matching(block: dict, cutoff: str) -> list[dict]:
    forms = block.get("form", [])
    accession_numbers = block.get("accessionNumber", [])
    filing_dates = block.get("filingDate", [])
    report_dates = block.get("reportDate", [])
    primary_docs = block.get("primaryDocument", [])

    out = []
    for i, form in enumerate(forms):
        if form not in _TARGET_FORMS:
            continue
        filing_date = filing_dates[i] if i < len(filing_dates) else None
        if filing_date and filing_date < cutoff:
            continue
        out.append(
            {
                "accession_number": accession_numbers[i] if i < len(accession_numbers) else None,
                "form": form,
                "filing_date": filing_date,
                "report_date": report_dates[i] if i < len(report_dates) else None,
                "primary_document": primary_docs[i] if i < len(primary_docs) else None,
            }
        )
    return out


def fetch_filings(cik: int) -> list[dict]:
    """Returns 10-K/10-Q filings from the past 5 years for one company, as
    [{"accession_number", "form", "filing_date", "report_date",
    "primary_document"}, ...], newest first."""
    session = sec_client.get_session()
    cik_padded = f"{cik:010d}"
    try:
        payload = _fetch_filing_page(session, f"https://data.sec.gov/submissions/CIK{cik_padded}.json")
    except (requests.RequestException, ValueError) as exc:
        raise FilingsFetchError(f"Failed to fetch filings for CIK {cik}: {exc}") from exc

    try:
        filings_section = payload["filings"]
        blocks = [filings_section["recent"]]
    except (KeyError, TypeError) as exc:
        raise FilingsFetchError(f"Unexpected response shape for CIK {cik}: {exc}") from exc

    # A company with a long filing history keeps older filings in
    # separate paginated files instead of "recent" - these are few even
    # for decades-old filers (each covers roughly 1000 filings), so
    # fetching all of them and filtering by date afterward is simpler and
    # more robust than guessing from metadata which ones might still fall
    # inside our 5-year window.
    try:
        for file_ref in filings_section.get("files", []):
            blocks.append(_fetch_filing_page(session, f"https://data.sec.gov/submissions/{file_ref['name']}"))
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise FilingsFetchError(f"Failed to fetch an older filing page for CIK {cik}: {exc}") from exc

    cutoff = (date.today() - timedelta(days=365 * _LOOKBACK_YEARS)).isoformat()
    out = []
    for block in blocks:
        out.extend(_extract_matching(block, cutoff))

    out.sort(key=lambda f: f["filing_date"] or "", reverse=True)
    return out
