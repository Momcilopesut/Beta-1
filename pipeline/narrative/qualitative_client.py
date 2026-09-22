"""Anthropic call for Layer 3 (qualitative filing-text reasoning). Kept
separate from pipeline/narrative/anthropic_client.py deliberately - see
qualitative_schema.py for why this carries a different grounding guarantee
than the metrics-only narrative layer.
"""

import os

import anthropic

from pipeline.narrative.qualitative_prompts import QUALITATIVE_SYSTEM_PROMPT
from pipeline.narrative.qualitative_schema import QualitativeAssessment

DEFAULT_MODEL = "claude-sonnet-5"


class QualitativeError(Exception):
    pass


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise QualitativeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic()


def generate_qualitative_assessment(ticker: str, sections: dict) -> QualitativeAssessment:
    """sections: pipeline.fetch.filing_text.extract_sections()'s return value
    for this company's most recent 10-K."""
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
            # This schema no longer carries the Fisher checklist or
            # management_assessment (moat_present/moat_type/moat_explanation/
            # red_flags only) - a much smaller response than the 8192 this
            # call needed before, but kept generous rather than re-tuned to
            # the exact minimum (see qualitative_schema.py's comment on why
            # max_length isn't the real truncation control - max_tokens is).
            max_tokens=3072,
            system=[{"type": "text", "text": QUALITATIVE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Ticker: {ticker}\n\n"
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
