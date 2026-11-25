import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from pipeline.narrative.qualitative_client import QualitativeError, generate_qualitative_assessment
from pipeline.narrative.qualitative_schema import QualitativeAssessment


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("pipeline.narrative.qualitative_client.anthropic.Anthropic")
def test_generate_qualitative_assessment_overwrites_extraction_confidence(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = MagicMock(
        parsed_output=QualitativeAssessment(
            moat_present=True,
            moat_type="cost_advantage",
            moat_explanation="x",
            red_flags=[],
            extraction_confidence="section_match",  # model's own guess - must be overwritten
        )
    )
    mock_anthropic_cls.return_value = mock_client

    sections = {"business": "b", "risk_factors": None, "mdna": "m", "method": "whole_document_fallback"}
    result = generate_qualitative_assessment("AAPL", sections)
    assert result.extraction_confidence == "whole_document_fallback"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("pipeline.narrative.qualitative_client.anthropic.Anthropic")
def test_generate_qualitative_assessment_wraps_failures(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.parse.side_effect = ValueError("truncated JSON")
    mock_anthropic_cls.return_value = mock_client

    sections = {"business": None, "risk_factors": None, "mdna": None, "method": "whole_document_fallback"}
    with pytest.raises(QualitativeError):
        generate_qualitative_assessment("AAPL", sections)


def test_generate_qualitative_assessment_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(QualitativeError):
        generate_qualitative_assessment("AAPL", {"method": "section_match"})


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("pipeline.narrative.qualitative_client.anthropic.Anthropic")
def test_generate_qualitative_assessment_includes_10q_and_8k_text_in_prompt(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = MagicMock(
        parsed_output=QualitativeAssessment(
            moat_present=False,
            moat_type="none",
            moat_explanation="x",
            red_flags=[],
            extraction_confidence="section_match",
            filing_summary_10k="10-K summary.",
            filing_summary_10q="10-Q summary.",
            filing_summary_8k="8-K summary.",
        )
    )
    mock_anthropic_cls.return_value = mock_client

    sections = {"business": "b", "risk_factors": None, "mdna": "m", "method": "section_match"}
    filing_texts = {"10-Q": "Q3 revenue grew 8%.", "8-K": "Company announced a new CEO."}
    result = generate_qualitative_assessment("AAPL", sections, filing_texts)

    sent_prompt = mock_client.messages.parse.call_args.kwargs["messages"][0]["content"]
    assert "Q3 revenue grew 8%" in sent_prompt
    assert "Company announced a new CEO" in sent_prompt
    assert result.filing_summary_10q == "10-Q summary."
    assert result.filing_summary_8k == "8-K summary."


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("pipeline.narrative.qualitative_client.anthropic.Anthropic")
def test_generate_qualitative_assessment_omits_missing_filing_types_from_prompt(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = MagicMock(
        parsed_output=QualitativeAssessment(
            moat_present=False,
            moat_type="none",
            moat_explanation="x",
            red_flags=[],
            extraction_confidence="section_match",
        )
    )
    mock_anthropic_cls.return_value = mock_client

    sections = {"business": "b", "risk_factors": None, "mdna": "m", "method": "section_match"}
    result = generate_qualitative_assessment("AAPL", sections)  # no filing_texts at all - a company with no recent 10-Q/8-K

    sent_prompt = mock_client.messages.parse.call_args.kwargs["messages"][0]["content"]
    assert "10-Q" not in sent_prompt
    assert "8-K" not in sent_prompt
    assert result.filing_summary_10q is None
    assert result.filing_summary_8k is None


def _lmstudio_response(body: dict | str) -> MagicMock:
    content = body if isinstance(body, str) else json.dumps(body)
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return mock_response


_VALID_LMSTUDIO_BODY = {
    "moat_present": True,
    "moat_type": "cost_advantage",
    "moat_explanation": "x",
    "red_flags": [],
    "extraction_confidence": "section_match",  # must be overwritten, same as the Anthropic path
    "filing_summary_10k": "Summary.",
    "filing_summary_10q": None,
    "filing_summary_8k": None,
}


@patch.dict("os.environ", {"QUALITATIVE_PROVIDER": "lmstudio"})
@patch("pipeline.narrative.qualitative_client.requests.post")
def test_lmstudio_provider_parses_clean_json_response(mock_post):
    mock_post.return_value = _lmstudio_response(_VALID_LMSTUDIO_BODY)

    sections = {"business": "b", "risk_factors": None, "mdna": "m", "method": "whole_document_fallback"}
    result = generate_qualitative_assessment("GFS", sections)

    assert result.moat_type == "cost_advantage"
    assert result.filing_summary_10k == "Summary."
    assert result.extraction_confidence == "whole_document_fallback"  # overwritten, not the model's own "section_match"

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["response_format"] == {"type": "json_object"}
    assert "GFS" in sent_payload["messages"][1]["content"]


@patch.dict("os.environ", {"QUALITATIVE_PROVIDER": "lmstudio"})
@patch("pipeline.narrative.qualitative_client.requests.post")
def test_lmstudio_provider_strips_markdown_code_fences(mock_post):
    fenced = "```json\n" + json.dumps(_VALID_LMSTUDIO_BODY) + "\n```"
    mock_post.return_value = _lmstudio_response(fenced)

    sections = {"business": "b", "risk_factors": None, "mdna": None, "method": "section_match"}
    result = generate_qualitative_assessment("GFS", sections)
    assert result.moat_type == "cost_advantage"


@patch.dict("os.environ", {"QUALITATIVE_PROVIDER": "lmstudio"})
@patch("pipeline.narrative.qualitative_client.requests.post")
def test_lmstudio_provider_recovers_json_surrounded_by_stray_prose(mock_post):
    chatty = "Sure, here you go:\n" + json.dumps(_VALID_LMSTUDIO_BODY) + "\nHope that helps!"
    mock_post.return_value = _lmstudio_response(chatty)

    sections = {"business": "b", "risk_factors": None, "mdna": None, "method": "section_match"}
    result = generate_qualitative_assessment("GFS", sections)
    assert result.moat_type == "cost_advantage"


@patch.dict("os.environ", {"QUALITATIVE_PROVIDER": "lmstudio"})
@patch("pipeline.narrative.qualitative_client.requests.post")
def test_lmstudio_provider_wraps_malformed_json_as_qualitative_error(mock_post):
    mock_post.return_value = _lmstudio_response("not json at all")

    sections = {"business": "b", "risk_factors": None, "mdna": None, "method": "section_match"}
    with pytest.raises(QualitativeError):
        generate_qualitative_assessment("GFS", sections)


@patch.dict("os.environ", {"QUALITATIVE_PROVIDER": "lmstudio"})
@patch("pipeline.narrative.qualitative_client.requests.post")
def test_lmstudio_provider_wraps_connection_errors(mock_post):
    mock_post.side_effect = requests.ConnectionError("no server on localhost:1234")

    sections = {"business": "b", "risk_factors": None, "mdna": None, "method": "section_match"}
    with pytest.raises(QualitativeError):
        generate_qualitative_assessment("GFS", sections)


@patch.dict("os.environ", {"QUALITATIVE_PROVIDER": "lmstudio", "LMSTUDIO_JSON_MODE": "0"})
@patch("pipeline.narrative.qualitative_client.requests.post")
def test_lmstudio_json_mode_can_be_disabled(mock_post):
    mock_post.return_value = _lmstudio_response(_VALID_LMSTUDIO_BODY)

    sections = {"business": "b", "risk_factors": None, "mdna": None, "method": "section_match"}
    generate_qualitative_assessment("GFS", sections)

    sent_payload = mock_post.call_args.kwargs["json"]
    assert "response_format" not in sent_payload


def test_unknown_provider_raises_qualitative_error(monkeypatch):
    monkeypatch.setenv("QUALITATIVE_PROVIDER", "carrier-pigeon")
    with pytest.raises(QualitativeError):
        generate_qualitative_assessment("AAPL", {"method": "section_match"})
