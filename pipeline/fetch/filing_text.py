"""Fetches plain text from a company's most recent 10-K for the qualitative
(Layer 3) analysis - the only place in this pipeline that feeds an AI call
raw filing prose rather than only already-computed metrics. Every other
narrative call (pipeline/narrative/anthropic_client.py) stays grounded
strictly in the metrics payload by design; this is a deliberate, separate
exception scoped to moat/management reasoning, kept visibly distinct in the
output (see pipeline/narrative/qualitative_schema.py and company_doc's
"qualitative" key) rather than blurring the two grounding models together.
"""

import re

from bs4 import BeautifulSoup

from pipeline.fetch.sec_edgar import edgar_headers
from pipeline.utils.http import get_text

_MAX_CHARS = 60_000  # ~15k tokens - keeps the qualitative-layer prompt a bounded, predictable size
_RATE = {"host_key": "sec_edgar", "min_interval_seconds": 0.15}

# Item headers as they appear (case-insensitively) at the start of a 10-K's
# structured sections. Real filings vary in formatting (all-caps, "Item 7.",
# "ITEM 7 —", a table-of-contents entry vs. the actual section, etc.), so
# this is a best-effort heuristic, not a guarantee - see extract_sections()'s
# "method" field, which downstream code/output should treat as a confidence
# signal rather than assuming a clean section match every time.
_ITEM_1_BUSINESS = re.compile(r"item\s+1\.\s*business", re.IGNORECASE)
_ITEM_1A_RISK = re.compile(r"item\s+1a\.\s*risk\s+factors", re.IGNORECASE)
_ITEM_7_MDNA = re.compile(
    r"item\s+7\.\s*management.?s\s+discussion\s+and\s+analysis", re.IGNORECASE
)
_ITEM_7A = re.compile(r"item\s+7a\.\s*quantitative", re.IGNORECASE)
_ITEM_8 = re.compile(r"item\s+8\.\s*financial\s+statements", re.IGNORECASE)


class FilingTextError(Exception):
    pass


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    # SEC filing HTML is table-heavy; get_text() leaves long runs of blank
    # lines that would otherwise waste a meaningful chunk of the char budget.
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _section_between(text: str, start_pattern: re.Pattern, end_pattern: re.Pattern) -> str | None:
    """Real 10-Ks usually list every item in a table of contents before the
    actual sections - take the LAST match of start_pattern (the real
    section header, not the ToC entry) and the first end_pattern match
    after it."""
    start_matches = list(start_pattern.finditer(text))
    if not start_matches:
        return None
    start = start_matches[-1].start()
    end_match = end_pattern.search(text, pos=start + 1)
    end = end_match.start() if end_match else min(len(text), start + _MAX_CHARS)
    section = text[start:end].strip()
    return section or None


def extract_sections(html: str) -> dict:
    """Returns {"business": str|None, "risk_factors": str|None, "mdna": str|None,
    "method": "section_match" | "whole_document_fallback"}.

    mdna (Item 7) is what the qualitative layer weights most heavily for
    moat/management reasoning; business (Item 1) and risk_factors (Item 1A)
    are included as supporting context, each capped independently so one
    very long section can't crowd out the others."""
    text = _html_to_text(html)

    business = _section_between(text, _ITEM_1_BUSINESS, _ITEM_1A_RISK)
    risk_factors = _section_between(text, _ITEM_1A_RISK, re.compile(r"item\s+1b\.|item\s+2\.", re.IGNORECASE))
    mdna = _section_between(text, _ITEM_7_MDNA, re.compile(rf"({_ITEM_7A.pattern})|({_ITEM_8.pattern})", re.IGNORECASE))

    if mdna or business:
        return {
            "business": (business or "")[:20_000] or None,
            "risk_factors": (risk_factors or "")[:15_000] or None,
            "mdna": (mdna or "")[:30_000] or None,
            "method": "section_match",
        }

    # Heuristic section matching failed (unusual filing structure/format) -
    # fall back to a bounded prefix of the whole document rather than
    # sending nothing. Flagged distinctly so the qualitative layer's prompt
    # (and anyone reading company_doc later) knows this wasn't a clean
    # Item-7 extraction.
    return {
        "business": None,
        "risk_factors": None,
        "mdna": text[:_MAX_CHARS] or None,
        "method": "whole_document_fallback",
    }


def fetch_filing_sections(url: str) -> dict:
    """Fetches one filing document and returns extract_sections()'s dict.
    Raises FilingTextError (caller decides how to degrade) rather than a
    raw exception, matching the rest of pipeline/fetch/'s error convention."""
    try:
        html = get_text(url, headers=edgar_headers(), **_RATE)
    except Exception as exc:  # noqa: BLE001
        raise FilingTextError(f"Failed to fetch filing text from {url}: {exc}") from exc
    return extract_sections(html)
