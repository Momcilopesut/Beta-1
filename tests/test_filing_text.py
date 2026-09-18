from pipeline.fetch.filing_text import extract_sections


_SYNTHETIC_10K = """
<html><body>
<div>Table of Contents</div>
<div>Item 1. Business ......... 3</div>
<div>Item 1A. Risk Factors ......... 10</div>
<div>Item 7. Management's Discussion and Analysis ......... 25</div>

<h3>Item 1. Business</h3>
<p>We design, manufacture and market widgets globally. Our moat comes from switching
costs and a large installed base of enterprise customers.</p>

<h3>Item 1A. Risk Factors</h3>
<p>Our business is subject to competition and supply chain risk.</p>

<h3>Item 1B. Unresolved Staff Comments</h3>
<p>None.</p>

<h3>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</h3>
<p>Revenue grew 12% year over year. Management returned $2B to shareholders via buybacks.</p>

<h3>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</h3>
<p>Interest rate risk disclosures.</p>

<h3>Item 8. Financial Statements and Supplementary Data</h3>
<p>See financial statements below.</p>
</body></html>
"""


def test_extracts_business_risk_and_mdna_sections():
    result = extract_sections(_SYNTHETIC_10K)
    assert result["method"] == "section_match"
    assert "switching" in result["business"]
    assert "supply chain" in result["risk_factors"]
    assert "12%" in result["mdna"]
    # The MD&A section must stop before Item 7A, not bleed into it.
    assert "Interest rate risk" not in result["mdna"]


def test_skips_table_of_contents_entries_uses_real_section():
    # The ToC line "Item 7. Management's Discussion and Analysis ......." at
    # the top must not be mistaken for the real section.
    result = extract_sections(_SYNTHETIC_10K)
    assert "Revenue grew 12%" in result["mdna"]


def test_falls_back_to_whole_document_when_no_item_headers_found():
    html = "<html><body><p>Some random filing text with no item headers.</p></body></html>"
    result = extract_sections(html)
    assert result["method"] == "whole_document_fallback"
    assert result["business"] is None
    assert "random filing text" in result["mdna"]


def test_strips_script_and_style_tags():
    html = "<html><body><script>evil()</script><style>.x{}</style><p>Item 1. Business text here.</p></body></html>"
    result = extract_sections(html)
    assert "evil()" not in (result["mdna"] or "") + (result["business"] or "")
