from unittest.mock import MagicMock, patch

import pytest

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
    result = generate_qualitative_assessment("AAPL", sections, {"gate_pass": True})
    assert result.extraction_confidence == "whole_document_fallback"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("pipeline.narrative.qualitative_client.anthropic.Anthropic")
def test_generate_qualitative_assessment_wraps_failures(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.parse.side_effect = ValueError("truncated JSON")
    mock_anthropic_cls.return_value = mock_client

    sections = {"business": None, "risk_factors": None, "mdna": None, "method": "whole_document_fallback"}
    with pytest.raises(QualitativeError):
        generate_qualitative_assessment("AAPL", sections, {"gate_pass": True})


def test_generate_qualitative_assessment_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(QualitativeError):
        generate_qualitative_assessment("AAPL", {"method": "section_match"}, {"gate_pass": True})
