"""SEC EDGAR client: no API key, but requires a descriptive User-Agent and
respect for the ~10 req/sec fair-access limit (enforced via host_key rate
limiting in pipeline.utils.http).

Used both for filing source links (submissions) and as an authoritative
fallback for structured fundamentals (XBRL company facts) when an FMP
endpoint is unavailable or gated on the free tier.
"""

import os
from typing import Any

from pipeline.utils.http import get_json

SEC_BASE = "https://www.sec.gov"
SEC_DATA_BASE = "https://data.sec.gov"
_RATE = {"host_key": "sec_edgar", "min_interval_seconds": 0.15}

_ticker_cik_map: dict[str, dict] | None = None


def _headers() -> dict:
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "Beta1-Watchlist/1.0 (unset-contact)")
    return {"User-Agent": ua}


def _load_ticker_map() -> dict[str, dict]:
    global _ticker_cik_map
    if _ticker_cik_map is None:
        raw = get_json(f"{SEC_BASE}/files/company_tickers.json", headers=_headers(), **_RATE)
        _ticker_cik_map = {row["ticker"].upper(): row for row in raw.values()}
    return _ticker_cik_map


def cik_for_ticker(ticker: str) -> str | None:
    row = _load_ticker_map().get(ticker.upper())
    if row is None:
        return None
    return str(row["cik_str"]).zfill(10)


def fetch_submissions(cik: str) -> dict:
    return get_json(f"{SEC_DATA_BASE}/submissions/CIK{cik}.json", headers=_headers(), **_RATE)


def fetch_company_facts(cik: str) -> dict:
    return get_json(
        f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json", headers=_headers(), **_RATE
    )


def recent_filings(submissions: dict, forms: tuple[str, ...] = ("10-K", "10-Q"), limit: int = 5) -> list[dict]:
    """Extract recent filing metadata (form, filed date, direct document URL)."""
    recent = submissions.get("filings", {}).get("recent", {})
    cik = str(int(submissions.get("cik", "0")))
    forms_list = recent.get("form", [])

    out: list[dict] = []
    for i, form in enumerate(forms_list):
        if form not in forms:
            continue
        accession = recent["accessionNumber"][i]
        primary_doc = recent["primaryDocument"][i]
        filed = recent["filingDate"][i]
        accession_nodash = accession.replace("-", "")
        url = f"{SEC_BASE}/Archives/edgar/data/{cik}/{accession_nodash}/{primary_doc}"
        out.append({"form": form, "filed": filed, "url": url})
        if len(out) >= limit:
            break
    return out


def xbrl_concept(company_facts: dict, taxonomy: str, tag: str, unit: str = "USD") -> list[dict]:
    """Raw list of {val, end, fy, fp, form, ...} facts for one XBRL concept."""
    try:
        return company_facts["facts"][taxonomy][tag]["units"][unit]
    except KeyError:
        return []


def latest_annual_value(
    company_facts: dict, taxonomy: str, tag: str, unit: str = "USD"
) -> float | None:
    """Latest full-year (10-K, fp=='FY') value for a concept, or None."""
    facts = xbrl_concept(company_facts, taxonomy, tag, unit)
    annual = [f for f in facts if f.get("form") == "10-K" and f.get("fp") == "FY"]
    if not annual:
        return None
    annual.sort(key=lambda f: f.get("end", ""))
    return annual[-1]["val"]


def fetch_company(ticker: str) -> dict[str, Any]:
    """Fetch submissions + company facts for one ticker.

    Returns {"cik": str|None, "submissions": dict|None, "company_facts": dict|None,
    "_errors": {...}}.
    """
    errors: dict[str, str] = {}
    cik = None
    submissions = None
    company_facts = None

    try:
        cik = cik_for_ticker(ticker)
        if cik is None:
            errors["cik"] = f"No CIK found for ticker {ticker}"
    except Exception as exc:  # noqa: BLE001
        errors["cik"] = str(exc)

    if cik:
        try:
            submissions = fetch_submissions(cik)
        except Exception as exc:  # noqa: BLE001
            errors["submissions"] = str(exc)
        try:
            company_facts = fetch_company_facts(cik)
        except Exception as exc:  # noqa: BLE001
            errors["company_facts"] = str(exc)

    return {
        "cik": cik,
        "submissions": submissions,
        "company_facts": company_facts,
        "_errors": errors,
    }
