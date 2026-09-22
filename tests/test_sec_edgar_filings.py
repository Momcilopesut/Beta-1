"""Tests for sec_edgar.latest_filings_by_form() - finding the single most
recent filing of each requested type independently, so a burst of 8-Ks
(a company can file 10-20+/year) can't crowd out the latest 10-Q/10-K."""

from pipeline.fetch.sec_edgar import latest_filings_by_form


def _submissions(forms: list[str], accessions: list[str], docs: list[str], dates: list[str]) -> dict:
    return {
        "cik": "320193",
        "filings": {
            "recent": {
                "form": forms,
                "accessionNumber": accessions,
                "primaryDocument": docs,
                "filingDate": dates,
            }
        },
    }


def test_finds_latest_of_each_form_independently():
    # Newest-first, as the real SEC API returns it: three recent 8-Ks
    # (the kind of burst that would crowd out a combined-and-capped list),
    # then the latest 10-Q, then the latest 10-K.
    submissions = _submissions(
        forms=["8-K", "8-K", "8-K", "10-Q", "10-K", "10-Q"],
        accessions=[
            "0000320193-26-000006",
            "0000320193-26-000005",
            "0000320193-26-000004",
            "0000320193-26-000003",
            "0000320193-26-000002",
            "0000320193-26-000001",
        ],
        docs=["e3.htm", "e2.htm", "e1.htm", "q2.htm", "k.htm", "q1.htm"],
        dates=["2026-08-01", "2026-07-15", "2026-06-01", "2026-05-01", "2026-02-01", "2026-01-01"],
    )

    result = latest_filings_by_form(submissions)

    assert set(result) == {"10-K", "10-Q", "8-K"}
    assert result["8-K"]["filed"] == "2026-08-01"
    assert result["8-K"]["url"].endswith("e3.htm")
    assert result["10-Q"]["filed"] == "2026-05-01"  # the newer of the two 10-Qs, not the older
    assert result["10-K"]["filed"] == "2026-02-01"


def test_omits_forms_with_no_match():
    submissions = _submissions(
        forms=["10-Q"],
        accessions=["0000320193-26-000001"],
        docs=["q.htm"],
        dates=["2026-05-01"],
    )
    result = latest_filings_by_form(submissions)
    assert set(result) == {"10-Q"}
    assert "10-K" not in result
    assert "8-K" not in result


def test_respects_custom_forms_tuple():
    submissions = _submissions(
        forms=["10-K", "DEF 14A"],
        accessions=["0000320193-26-000001", "0000320193-26-000002"],
        docs=["k.htm", "proxy.htm"],
        dates=["2026-02-01", "2026-03-01"],
    )
    result = latest_filings_by_form(submissions, forms=("DEF 14A",))
    assert set(result) == {"DEF 14A"}


def test_url_is_built_from_cik_and_accession_number():
    submissions = _submissions(
        forms=["10-K"],
        accessions=["0000320193-26-000001"],
        docs=["aapl-20251231.htm"],
        dates=["2026-02-01"],
    )
    result = latest_filings_by_form(submissions)
    assert (
        result["10-K"]["url"]
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/aapl-20251231.htm"
    )
