"""Anthropic calls for Layer 3 (qualitative filing-text reasoning) and
Layer 5 (thesis + falsification). Kept separate from
pipeline/narrative/anthropic_client.py deliberately - see
qualitative_schema.py for why these carry a different grounding guarantee
than the metrics-only narrative layer.
"""

import json
import os

import anthropic

from pipeline.narrative.qualitative_prompts import QUALITATIVE_SYSTEM_PROMPT, THESIS_SYSTEM_PROMPT
from pipeline.narrative.qualitative_schema import QualitativeAssessment, ThesisAndFalsification

DEFAULT_MODEL = "claude-sonnet-5"


class QualitativeError(Exception):
    pass


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise QualitativeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic()


def generate_qualitative_assessment(ticker: str, sections: dict, quant_scorecard: dict) -> QualitativeAssessment:
    """sections: pipeline.fetch.filing_text.extract_sections()'s return value
    for this company's most recent 10-K. quant_scorecard:
    pipeline.scoring.quant_score.build_quant_scorecard()'s return value."""
    client = _client()
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    excerpt_parts = []
    if sections.get("business"):
        excerpt_parts.append(f"--- Business (Item 1) ---\n{sections['business']}")
    if sections.get("risk_factors"):
        excerpt_parts.append(f"--- Risk Factors (Item 1A) ---\n{sections['risk_factors']}")
    if sections.get("mdna"):
        excerpt_parts.append(f"--- Management's Discussion and Analysis (Item 7) ---\n{sections['mdna']}")
    excerpts = "\n\n".join(excerpt_parts) or "(no filing text could be extracted)"

    try:
        response = client.messages.parse(
            model=model,
            # 8192: a real production run showed 4096 still truncating output
            # mid-JSON-string (the fisher_checklist field, up to 12 items
            # with evidence text each, pushes a real response well past
            # 4096 tokens) - the exact same failure mode as the crash this
            # pipeline hit earlier from an underestimated output budget
            # (see pipeline/narrative/anthropic_client.py's max_tokens
            # history). Generous headroom here, not a tight fit.
            max_tokens=8192,
            system=[{"type": "text", "text": QUALITATIVE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Ticker: {ticker}\n\n"
                        f"Quantitative scorecard (JSON):\n{json.dumps(quant_scorecard, default=str)}\n\n"
                        f"10-K filing excerpts (extraction method: {sections.get('method')}):\n{excerpts}"
                    ),
                }
            ],
            output_format=QualitativeAssessment,
        )
    except Exception as exc:  # noqa: BLE001 - degrades this one ticker's qualitative layer, not the batch
        raise QualitativeError(f"Qualitative assessment failed for {ticker}: {exc}") from exc

    parsed = response.parsed_output
    # extraction_confidence must reflect the actual extraction method, not
    # whatever the model decided to say - overwrite rather than trust it.
    return parsed.model_copy(update={"extraction_confidence": sections.get("method", "whole_document_fallback")})


def generate_thesis(
    ticker: str, quant_scorecard: dict, qualitative: QualitativeAssessment, valuation: dict
) -> ThesisAndFalsification:
    client = _client()
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    payload = {
        "quant": quant_scorecard,
        "qualitative": qualitative.model_dump(),
        "valuation": valuation,
    }

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=2048,
            system=[{"type": "text", "text": THESIS_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": f"Ticker: {ticker}\n\nLayers 2-4 (JSON):\n{json.dumps(payload, default=str)}",
                }
            ],
            output_format=ThesisAndFalsification,
        )
    except Exception as exc:  # noqa: BLE001
        raise QualitativeError(f"Thesis generation failed for {ticker}: {exc}") from exc
    return response.parsed_output
