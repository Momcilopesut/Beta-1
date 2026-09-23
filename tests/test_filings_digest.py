from pipeline.main import build_filings_digest, digest_entry_from_doc


def _company_doc(ticker, **qualitative_overrides):
    qualitative = {"filing_summary_10k": None, "filing_summary_10q": None, "filing_summary_8k": None}
    qualitative.update(qualitative_overrides)
    return {
        "ticker": ticker,
        "name": f"{ticker} Inc.",
        "sector": "Technology",
        "qualitative": qualitative,
        "sources": {"sec_filings": [{"form": "10-K", "filed": "2026-01-01", "url": "https://example.com/10k"}]},
    }


def test_digest_entry_from_doc_with_summaries():
    doc = _company_doc("AAPL", filing_summary_10k="Revenue grew.")
    entry = digest_entry_from_doc(doc)
    assert entry["ticker"] == "AAPL"
    assert entry["name"] == "AAPL Inc."
    assert entry["sector"] == "Technology"
    assert entry["qualitative"]["filing_summary_10k"] == "Revenue grew."
    assert entry["sec_filings"][0]["form"] == "10-K"


def test_digest_entry_from_doc_returns_none_without_any_summary():
    doc = _company_doc("XYZ")  # all three filing_summary_* are None
    assert digest_entry_from_doc(doc) is None


def test_digest_entry_from_doc_returns_none_without_qualitative():
    doc = _company_doc("XYZ")
    doc["qualitative"] = None
    assert digest_entry_from_doc(doc) is None


def test_digest_entry_from_doc_missing_sec_filings_defaults_empty():
    doc = _company_doc("AAPL", filing_summary_8k="New CEO announced.")
    del doc["sources"]
    entry = digest_entry_from_doc(doc)
    assert entry["sec_filings"] == []


def test_build_filings_digest_sorts_by_ticker_and_counts():
    entries = [digest_entry_from_doc(_company_doc(t, filing_summary_10k="x")) for t in ["MSFT", "AAPL", "GOOGL"]]
    digest = build_filings_digest(entries, "2026-01-01T00:00:00Z")
    assert digest["generated_at"] == "2026-01-01T00:00:00Z"
    assert digest["tickers_covered"] == 3
    assert [e["ticker"] for e in digest["entries"]] == ["AAPL", "GOOGL", "MSFT"]


def test_build_filings_digest_empty_entries():
    digest = build_filings_digest([], "2026-01-01T00:00:00Z")
    assert digest["tickers_covered"] == 0
    assert digest["entries"] == []
