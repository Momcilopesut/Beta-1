"""Regression coverage for a real production incident: a truncated Anthropic
response (output cut off mid-JSON, failing CompanyNarrative validation)
propagated all the way out of run_full() and killed the entire batch run
instead of degrading just that one company. generate_narrative() must turn
any client.messages.parse() failure into NarrativeError so pipeline.main's
existing "fall back to an empty narrative" path actually catches it."""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.narrative.anthropic_client import NarrativeError, generate_narrative


def _payload():
    return {"metrics": {"pe_ratio": 15.2}, "scores": {}, "macro": {}}


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("pipeline.narrative.anthropic_client.anthropic.Anthropic")
def test_generate_narrative_wraps_validation_failure_as_narrative_error(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.parse.side_effect = ValueError(
        "Invalid JSON: EOF while parsing a string at line 1 column 5439"
    )
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(NarrativeError):
        generate_narrative("AAPL", _payload())


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("pipeline.narrative.anthropic_client.anthropic.Anthropic")
def test_generate_narrative_wraps_any_api_failure(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.parse.side_effect = RuntimeError("connection reset")
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(NarrativeError):
        generate_narrative("AAPL", _payload())


def test_run_narrative_degrades_gracefully_instead_of_raising():
    from pipeline.main import _run_narrative

    with patch("pipeline.main.generate_narrative", side_effect=NarrativeError("boom")):
        narrative_out, dropped = _run_narrative("AAPL", _payload())

    assert narrative_out["one_line_summary"] is None
    assert narrative_out["facts"] == {k: [] for k in narrative_out["facts"]}
    assert dropped == 0
