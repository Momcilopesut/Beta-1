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


def edgar_headers() -> dict:
    """Public so pipeline/fetch/filing_text.py (which fetches raw filing
    documents from the same Archives host, not the XBRL API) can reuse the
    same User-Agent instead of duplicating the env var lookup."""
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "Beta1-Watchlist/1.0 (unset-contact)")
    return {"User-Agent": ua}


def _load_ticker_map() -> dict[str, dict]:
    global _ticker_cik_map
    if _ticker_cik_map is None:
        raw = get_json(f"{SEC_BASE}/files/company_tickers.json", headers=edgar_headers(), **_RATE)
        _ticker_cik_map = {row["ticker"].upper(): row for row in raw.values()}
    return _ticker_cik_map


def cik_for_ticker(ticker: str) -> str | None:
    row = _load_ticker_map().get(ticker.upper())
    if row is None:
        return None
    return str(row["cik_str"]).zfill(10)


def fetch_submissions(cik: str) -> dict:
    return get_json(f"{SEC_DATA_BASE}/submissions/CIK{cik}.json", headers=edgar_headers(), **_RATE)


def fetch_company_facts(cik: str) -> dict:
    return get_json(
        f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json", headers=edgar_headers(), **_RATE
    )


def _filing_url(cik: str, accession: str, primary_doc: str) -> str:
    accession_nodash = accession.replace("-", "")
    return f"{SEC_BASE}/Archives/edgar/data/{cik}/{accession_nodash}/{primary_doc}"


def latest_filings_by_form(
    submissions: dict, forms: tuple[str, ...] = ("10-K", "10-Q", "8-K")
) -> dict[str, dict]:
    """Most recent filing of each requested form type, found independently -
    a burst of recent 8-Ks (a company can file 10-20+/year, vs. 1 10-K and
    ~3 10-Qs) can't crowd out the latest 10-Q/10-K the way a single
    combined-and-capped list would. submissions["filings"]["recent"] is
    already newest-first, so the first match per form is its latest filing.

    Returns {form: {"form", "filed", "url"}}, omitting any form with no
    match in the submissions payload."""
    recent = submissions.get("filings", {}).get("recent", {})
    cik = str(int(submissions.get("cik", "0")))
    forms_list = recent.get("form", [])

    out: dict[str, dict] = {}
    for i, form in enumerate(forms_list):
        if form not in forms or form in out:
            continue
        out[form] = {
            "form": form,
            "filed": recent["filingDate"][i],
            "url": _filing_url(cik, recent["accessionNumber"][i], recent["primaryDocument"][i]),
        }
        if len(out) == len(forms):
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


# XBRL concept candidates per FMP-shaped field, tried in order until one has
# annual (10-K, fp=="FY") data. Field names deliberately match what
# pipeline.scoring.fundamentals already reads from FMP's own statement
# responses, so a synthesized row is a drop-in substitute for a real one.
_INCOME_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "grossProfit": ("GrossProfit",),
    "netIncome": ("NetIncomeLoss",),
    "epsdiluted": ("EarningsPerShareDiluted",),
    "operatingIncome": ("OperatingIncomeLoss",),
    "incomeBeforeTax": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "incomeTaxExpense": ("IncomeTaxExpenseBenefit",),
    "weightedAverageShsOutDil": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "interestExpense": ("InterestExpense", "InterestExpenseDebt"),
    "researchAndDevelopmentExpenses": ("ResearchAndDevelopmentExpense",),
}
# Per-share and share-count concepts are reported under different XBRL
# units ("USD/shares", "shares") than the dollar-amount concepts above
# ("USD"); anything not listed here defaults to USD in _annual_facts_by_end.
_INCOME_UNIT_OVERRIDES: dict[str, str] = {
    "epsdiluted": "USD/shares",
    "weightedAverageShsOutDil": "shares",
}
_BALANCE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "totalAssets": ("Assets",),
    "totalCurrentAssets": ("AssetsCurrent",),
    "totalCurrentLiabilities": ("LiabilitiesCurrent",),
    "totalLiabilities": ("Liabilities",),
    "totalStockholdersEquity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cashAndCashEquivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashAndCashEquivalentsAtCarryingValueIncludingDiscontinuedOperations",
    ),
}
_LONG_TERM_DEBT_CONCEPTS = ("LongTermDebtNoncurrent",)
_CURRENT_DEBT_CONCEPTS = ("DebtCurrent", "LongTermDebtCurrent")
_CASHFLOW_CONCEPTS: dict[str, tuple[str, ...]] = {
    "operatingCashFlow": ("NetCashProvidedByUsedInOperatingActivities",),
    "depreciationAndAmortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ),
    "capitalExpenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "dividendsPaid": ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
}


def _annual_facts_by_end(company_facts: dict, tags: tuple[str, ...], unit: str = "USD") -> dict[str, float]:
    """First candidate tag with any 10-K/FY data wins. Returns {fiscal_year_end: value},
    keeping the most-recently-filed value if a figure was restated."""
    for tag in tags:
        facts = xbrl_concept(company_facts, "us-gaap", tag, unit)
        annual = [f for f in facts if f.get("form") == "10-K" and f.get("fp") == "FY" and f.get("end")]
        if annual:
            annual.sort(key=lambda f: f.get("filed", ""))
            return {f["end"]: f["val"] for f in annual}
    return {}


def _rows_from_fields(by_field: dict[str, dict[str, float]], years: int) -> list[dict]:
    all_ends = sorted({end for values in by_field.values() for end in values}, reverse=True)
    rows = []
    for end in all_ends[:years]:
        row: dict[str, Any] = {"date": end}
        for field, values in by_field.items():
            if end in values:
                row[field] = values[end]
        rows.append(row)
    return rows


def xbrl_fundamentals(company_facts: dict | None, years: int = 6) -> dict:
    """Synthesizes FMP-shaped annual statement rows (most-recent-first) from
    XBRL company facts - a free fallback for when FMP's own statement
    endpoints are unavailable (plan-gated or erroring). Every downstream
    metric computation in pipeline.scoring.fundamentals reads these same
    field names regardless of which source populated them."""
    if not company_facts:
        return {"income_stmts": [], "balance_stmts": [], "cashflow_stmts": []}

    income_by_field = {
        field: _annual_facts_by_end(company_facts, tags, unit=_INCOME_UNIT_OVERRIDES.get(field, "USD"))
        for field, tags in _INCOME_CONCEPTS.items()
    }
    balance_by_field = {field: _annual_facts_by_end(company_facts, tags) for field, tags in _BALANCE_CONCEPTS.items()}
    cashflow_by_field = {
        field: _annual_facts_by_end(company_facts, tags) for field, tags in _CASHFLOW_CONCEPTS.items()
    }

    long_term_debt = _annual_facts_by_end(company_facts, _LONG_TERM_DEBT_CONCEPTS)
    current_debt = _annual_facts_by_end(company_facts, _CURRENT_DEBT_CONCEPTS)
    debt_ends = set(long_term_debt) | set(current_debt)
    if debt_ends:
        balance_by_field["totalDebt"] = {
            end: long_term_debt.get(end, 0) + current_debt.get(end, 0) for end in debt_ends
        }

    return {
        "income_stmts": _rows_from_fields(income_by_field, years),
        "balance_stmts": _rows_from_fields(balance_by_field, years),
        "cashflow_stmts": _rows_from_fields(cashflow_by_field, years),
    }


def latest_shares_outstanding(company_facts: dict | None) -> float | None:
    """Most recent EntityCommonStockSharesOutstanding cover-page fact (from
    the dei taxonomy) - appears on every 10-K/10-Q, so it's more current
    than an annual-only concept."""
    if not company_facts:
        return None
    facts = []
    try:
        facts = company_facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    except KeyError:
        return None
    dated = [f for f in facts if f.get("end")]
    if not dated:
        return None
    dated.sort(key=lambda f: f["end"])
    return dated[-1]["val"]


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
        "xbrl_fundamentals": xbrl_fundamentals(company_facts),
        "shares_outstanding": latest_shares_outstanding(company_facts),
        "sic_description": (submissions or {}).get("sicDescription"),
        "_errors": errors,
    }
