"""Tests for llm_client.py's LM Studio integration - network mocked."""

import json
from unittest.mock import MagicMock, patch

import pytest

from llm_client import LlmError, summarize, summarize_filing

_PRICE = {"close": 150.0, "as_of": "2026-01-02", "change_pct": 2.5}
_NEWS = [{"title": "Company beats earnings expectations", "link": "https://example.com", "published": "today"}]


def _lmstudio_response(body) -> MagicMock:
    content = body if isinstance(body, str) else json.dumps(body)
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


def test_summarize_parses_clean_json_response():
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"summary": "Shares rose on strong earnings."})):
        result = summarize("AAPL", _PRICE, _NEWS)

    assert result == "Shares rose on strong earnings."


def test_summarize_strips_markdown_code_fences():
    fenced = '```json\n{"summary": "Fenced summary."}\n```'
    with patch("llm_client.requests.post", return_value=_lmstudio_response(fenced)):
        result = summarize("AAPL", _PRICE, _NEWS)

    assert result == "Fenced summary."


def test_summarize_recovers_json_surrounded_by_stray_prose():
    chatty = 'Sure thing:\n{"summary": "Chatty summary."}\nHope that helps!'
    with patch("llm_client.requests.post", return_value=_lmstudio_response(chatty)):
        result = summarize("AAPL", _PRICE, _NEWS)

    assert result == "Chatty summary."


def test_summarize_raises_llm_error_on_malformed_json():
    with patch("llm_client.requests.post", return_value=_lmstudio_response("not json at all")):
        with pytest.raises(LlmError):
            summarize("AAPL", _PRICE, _NEWS)


def test_summarize_raises_llm_error_when_summary_field_missing():
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"not_summary": "x"})):
        with pytest.raises(LlmError):
            summarize("AAPL", _PRICE, _NEWS)


def test_summarize_includes_response_body_in_error_on_400():
    response = MagicMock()
    response.status_code = 400
    response.text = '{"error": "This model\'s maximum context length is 4096 tokens"}'
    import requests

    response.raise_for_status.side_effect = requests.HTTPError("400 Client Error: Bad Request for url: x", response=response)
    with patch("llm_client.requests.post", return_value=response):
        with pytest.raises(LlmError, match="maximum context length"):
            summarize("AAPL", _PRICE, _NEWS)


def test_summarize_raises_llm_error_on_connection_failure():
    with patch("llm_client.requests.post", side_effect=ConnectionError("no server on localhost:1234")):
        with pytest.raises(LlmError):
            summarize("AAPL", _PRICE, _NEWS)


def test_summarize_includes_ticker_and_headlines_in_prompt():
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"summary": "x"})) as mock_post:
        summarize("AAPL", _PRICE, _NEWS)

    sent_messages = mock_post.call_args.kwargs["json"]["messages"]
    user_content = sent_messages[1]["content"]
    assert "AAPL" in user_content
    assert "Company beats earnings expectations" in user_content


def test_summarize_handles_missing_price_data_gracefully():
    no_price = {"close": None, "as_of": None, "change_pct": None}
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"summary": "No price data."})) as mock_post:
        result = summarize("ZZZZ", no_price, [])

    assert result == "No price data."
    user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "no price data available" in user_content


# --- Filing summaries ---

_SECTIONS = {"Management's Discussion and Analysis": "Revenue grew 10% year over year."}


def test_summarize_filing_parses_clean_json_response():
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"summary": "Revenue grew."})):
        result = summarize_filing("AMD", "10-K", _SECTIONS)

    assert result == "Revenue grew."


def test_summarize_filing_raises_when_no_sections_extracted():
    with pytest.raises(LlmError):
        summarize_filing("AMD", "10-K", {})


def test_summarize_filing_raises_llm_error_when_summary_field_missing():
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"not_summary": "x"})):
        with pytest.raises(LlmError):
            summarize_filing("AMD", "10-K", _SECTIONS)


def test_summarize_filing_raises_llm_error_on_connection_failure():
    with patch("llm_client.requests.post", side_effect=ConnectionError("no server on localhost:1234")):
        with pytest.raises(LlmError):
            summarize_filing("AMD", "10-K", _SECTIONS)


def test_summarize_filing_includes_ticker_form_and_section_titles_in_prompt():
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"summary": "x"})) as mock_post:
        summarize_filing("AMD", "10-K", _SECTIONS)

    user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "AMD" in user_content
    assert "10-K" in user_content
    assert "Management's Discussion and Analysis" in user_content
    assert "Revenue grew 10% year over year." in user_content


def test_summarize_filing_truncates_oversized_sections(monkeypatch):
    monkeypatch.setattr("llm_client.MAX_SECTION_CHARS", 50)
    long_section = {"Risk Factors": "x" * 500}
    with patch("llm_client.requests.post", return_value=_lmstudio_response({"summary": "x"})) as mock_post:
        summarize_filing("AMD", "10-K", long_section)

    user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "x" * 500 not in user_content
    assert "[truncated for length]" in user_content
