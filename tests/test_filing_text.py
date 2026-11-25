"""Tests for filing_text.py - the TOC-vs-real-section heuristic is the
part most worth testing carefully here; network calls are mocked."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from filing_text import FilingTextError, extract_section, extract_sections_for_form, fetch_filing_text, filing_url


@pytest.fixture(autouse=True)
def sec_contact(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "Test User test@example.com")


def test_filing_url_strips_dashes_from_accession_number():
    url = filing_url(320193, "0000320193-26-000012", "aapl-20260101.htm")
    assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000012/aapl-20260101.htm"


# --- extract_section: the TOC-avoidance heuristic ---


def _ten_k_with_toc_and_real_sections(mdna_body: str, risk_body: str) -> str:
    # A table of contents entry for an Item is immediately followed by the
    # next Item's TOC entry - a short gap. The real section is followed by
    # substantial prose before the next Item heading - a long gap. This is
    # exactly the ambiguity extract_section has to resolve.
    return (
        "TABLE OF CONTENTS\n"
        "PART I\n"
        "Item 1. Business ... 4\n"
        "Item 1A. Risk Factors ... 12\n"
        "PART II\n"
        "Item 7. Management's Discussion and Analysis ... 45\n"
        "Item 7A. Quantitative and Qualitative Disclosures About Market Risk ... 67\n"
        "\n\nPART I\n\n"
        "Item 1A. Risk Factors\n\n"
        f"{risk_body}\n\n"
        "Item 1B. Unresolved Staff Comments\n\nNone.\n\n"
        "\n\nPART II\n\n"
        "Item 7. Management's Discussion and Analysis\n\n"
        f"{mdna_body}\n\n"
        "Item 7A. Quantitative and Qualitative Disclosures About Market Risk\n\n"
        "Not applicable.\n"
    )


def test_extract_section_finds_real_mdna_not_the_toc_entry():
    mdna_body = "Revenue increased due to strong demand. " * 20
    risk_body = "Our business depends on several key customers. " * 20
    text = _ten_k_with_toc_and_real_sections(mdna_body, risk_body)

    result = extract_section(text, "7")

    assert result is not None
    assert mdna_body.strip() in result
    assert "67" not in result.split("\n")[0]  # didn't grab the TOC line itself


def test_extract_section_finds_real_risk_factors_not_the_toc_entry():
    mdna_body = "Revenue increased due to strong demand. " * 20
    risk_body = "Our business depends on several key customers. " * 20
    text = _ten_k_with_toc_and_real_sections(mdna_body, risk_body)

    result = extract_section(text, "1A")

    assert result is not None
    assert risk_body.strip() in result


def test_extract_section_returns_none_when_item_not_present():
    text = "This document has no item headings of the kind we're looking for at all."
    assert extract_section(text, "7") is None


def test_extract_section_rejects_short_toc_only_match():
    # Only a TOC-style mention, no real section body anywhere - should not
    # be mistaken for genuine content just because it technically matched.
    text = "Item 7. Management's Discussion and Analysis ... 45\nItem 7A. Market Risk ... 67\n"
    assert extract_section(text, "7") is None


def test_extract_section_resolves_10q_item_2_ambiguity():
    # 10-Q's one real collision: Item 2 is MD&A in Part I, but
    # "Unregistered Sales of Equity Securities" in Part II - the real
    # MD&A is always far longer, which is what the heuristic relies on.
    mdna_body = "Revenue for the quarter increased year over year. " * 30
    text = (
        "PART I\n\n"
        "Item 2. Management's Discussion and Analysis\n\n"
        f"{mdna_body}\n\n"
        "Item 3. Quantitative and Qualitative Disclosures About Market Risk\n\nNot applicable.\n\n"
        "PART II\n\n"
        "Item 1A. Risk Factors\n\nNo material changes.\n\n"
        "Item 2. Unregistered Sales of Equity Securities and Use of Proceeds\n\nNone.\n\n"
        "Item 6. Exhibits\n\nSee exhibit index.\n"
    )

    result = extract_section(text, "2")

    assert result is not None
    assert mdna_body.strip() in result
    assert "Unregistered Sales" not in result


# --- extract_sections_for_form ---


def test_extract_sections_for_form_10k_includes_both_sections():
    mdna_body = "Revenue increased due to strong demand. " * 20
    risk_body = "Our business depends on several key customers. " * 20
    text = _ten_k_with_toc_and_real_sections(mdna_body, risk_body)

    sections = extract_sections_for_form(text, "10-K")

    assert set(sections) == {"Management's Discussion and Analysis", "Risk Factors"}
    assert mdna_body.strip() in sections["Management's Discussion and Analysis"]
    assert risk_body.strip() in sections["Risk Factors"]


def test_extract_sections_for_form_unknown_form_returns_empty():
    assert extract_sections_for_form("Item 7. Management's Discussion...", "8-K") == {}


def test_extract_sections_for_form_omits_sections_it_cant_find():
    text = "Item 7. Management's Discussion and Analysis\n\n" + ("Revenue increased. " * 20)
    sections = extract_sections_for_form(text, "10-K")
    assert set(sections) == {"Management's Discussion and Analysis"}


# --- fetch_filing_text ---


def _mock_html_response(html: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.content = html.encode("utf-8")
    return response


def test_fetch_filing_text_strips_tags_scripts_and_styles():
    html = """
    <html><head><style>body { color: red; }</style></head>
    <body>
    <script>alert('x')</script>
    <p>Item 7. Management's Discussion and Analysis</p>
    <p>Revenue grew.</p>
    </body></html>
    """
    with patch("filing_text.sec_client.get_session") as mock_get_session:
        mock_get_session.return_value.get.return_value = _mock_html_response(html)
        text = fetch_filing_text(320193, "0000320193-26-000012", "aapl-20260101.htm")

    assert "alert" not in text
    assert "color: red" not in text
    assert "Revenue grew." in text


def test_fetch_filing_text_wraps_network_errors():
    with patch("filing_text.sec_client.get_session") as mock_get_session:
        mock_get_session.return_value.get.side_effect = requests.ConnectionError("no route")
        with pytest.raises(FilingTextError):
            fetch_filing_text(320193, "0000320193-26-000012", "aapl-20260101.htm")
