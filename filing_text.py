"""Phase 3, step 1: fetches one filing document from SEC EDGAR and pulls
out its most analytically useful prose sections as plain text - ready to
hand to the local LLM (see llm_client.py::summarize_filing).

Modern 10-K/10-Q primary documents are large Inline XBRL HTML files, far
bigger than any local LLM's context window - this doesn't try to
summarize the whole thing. Instead it extracts just Management's
Discussion and Analysis (MD&A) and, where present, Risk Factors - the
densest, most analysis-relevant prose in the filing - using the Item
number headers SEC's own form structure requires every filer to use
(10-K: MD&A is Item 7, Risk Factors is Item 1A; 10-Q: MD&A is Item 2,
Risk Factors is Item 1A).

The one real wrinkle: a filing's own table of contents repeats these same
"Item 7."/"Item 1A." headings near the top, as links down to the real
section - a naive first-match search finds the TOC entry, not the actual
section, and returns almost nothing useful. extract_section() below picks
whichever candidate match has the most text before the next Item heading
of any kind, since a TOC entry is immediately followed by another TOC
line while the real section body is followed by substantial prose. This
also happens to resolve 10-Q's one genuine ambiguity (Item 2 means MD&A
in Part I, but "Unregistered Sales of Equity Securities" in Part II) -
the real MD&A is always far longer than that Part II boilerplate, so the
same "longest span" heuristic picks the right one without needing to
track Part I/II boundaries separately.
"""

import re

import requests
from bs4 import BeautifulSoup

import sec_client

_ITEM_HEADING_RE = re.compile(r"item\s+\d{1,2}[a-z]?\b", re.IGNORECASE)

# (display title, Item number to search for) per form type.
_SECTIONS_BY_FORM = {
    "10-K": [("Management's Discussion and Analysis", "7"), ("Risk Factors", "1A")],
    "10-Q": [("Management's Discussion and Analysis", "2"), ("Risk Factors", "1A")],
}

_MIN_SECTION_CHARS = 200  # shorter than this is almost certainly a TOC-only match, not real content.


class FilingTextError(Exception):
    pass


def filing_url(cik: int, accession_number: str, primary_document: str) -> str:
    accession_nodash = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{primary_document}"


def fetch_filing_text(cik: int, accession_number: str, primary_document: str) -> str:
    """Downloads one filing document and returns its visible text, with
    tags/scripts/styles stripped and paragraph breaks collapsed."""
    url = filing_url(cik, accession_number, primary_document)
    try:
        resp = sec_client.get_session().get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FilingTextError(f"Failed to fetch filing document {url}: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _find_item_positions(text: str, item_number: str) -> list[int]:
    pattern = re.compile(rf"item\s+{re.escape(item_number)}\b", re.IGNORECASE)
    return [m.start() for m in pattern.finditer(text)]


def extract_section(text: str, item_number: str) -> str | None:
    """Returns the text of one Item section (e.g. "7" for 10-K MD&A, "1A"
    for Risk Factors), or None if it can't be confidently located."""
    starts = _find_item_positions(text, item_number)
    if not starts:
        return None

    all_item_positions = sorted(m.start() for m in _ITEM_HEADING_RE.finditer(text))

    best_span = None
    best_length = -1
    for start in starts:
        later = [p for p in all_item_positions if p > start + 10]
        end = later[0] if later else len(text)
        length = end - start
        if length > best_length:
            best_length = length
            best_span = (start, end)

    if best_span is None or best_length < _MIN_SECTION_CHARS:
        return None
    return text[best_span[0] : best_span[1]].strip()


def extract_sections_for_form(text: str, form: str) -> dict[str, str]:
    """Returns {"Management's Discussion and Analysis": "...", "Risk
    Factors": "...", ...} for whichever of the wanted sections could be
    confidently located - a form type with no mapping, or a filing where
    neither section was found, returns an empty dict (callers should
    treat that as "nothing to summarize," not crash)."""
    wanted = _SECTIONS_BY_FORM.get(form, [])
    sections = {}
    for title, item_number in wanted:
        section_text = extract_section(text, item_number)
        if section_text:
            sections[title] = section_text
    return sections
