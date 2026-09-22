"""Anthropic call for Layer 3 (qualitative filing-text reasoning) - the only
AI call in this pipeline. See qualitative_schema.py for why this carries a
prompt-only grounding guarantee rather than a code-verified one.
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


def generate_qualitative_assessment(
    ticker: str, sections: dict, filing_texts: dict[str, str] | None = None
) -> QualitativeAssessment:
    """sections: pipeline.fetch.filing_text.extract_sections()'s return value
    for this company's most recent 10-K (drives the moat read and
    filing_summary_10k).

    filing_texts: optional {"10-Q": text, "8-K": text} bounded plain text
    (pipeline.fetch.filing_text.fetch_plain_text()) for filing_summary_10q/
    8k - either or both keys may be absent when that filing type wasn't
    found for this company."""
    client = _client()
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    filing_texts = filing_texts or {}

    excerpt_parts = []
    if sections.get("business"):
        excerpt_parts.append(f"--- 10-K Business (Item 1) ---\n{sections['business']}")
    if sections.get("risk_factors"):
        excerpt_parts.append(f"--- 10-K Risk Factors (Item 1A) ---\n{sections['risk_factors']}")
    if sections.get("mdna"):
        excerpt_parts.append(f"--- 10-K Management's Discussion and Analysis (Item 7) ---\n{sections['mdna']}")
    if filing_texts.get("10-Q"):
        excerpt_parts.append(f"--- Most recent 10-Q (whole document, bounded) ---\n{filing_texts['10-Q']}")
    if filing_texts.get("8-K"):
        excerpt_parts.append(f"--- Most recent 8-K (whole document, bounded) ---\n{filing_texts['8-K']}")
    excerpts = "\n\n".join(excerpt_parts) or "(no filing text could be extracted)"

    try:
        response = client.messages.parse(
            model=model,
            # Grew from 3072 to fit the 3 new filing_summary_* fields
            # alongside the existing moat read - still kept generous rather
            # than re-tuned to the exact minimum (see qualitative_schema.py's
            # comment on why max_length isn't the real truncation control -
            # max_tokens is).
            max_tokens=4096,
            system=[{"type": "text", "text": QUALITATIVE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Ticker: {ticker}\n\n"
                        f"10-K extraction method: {sections.get('method')}\n\n"
                        f"Filing excerpts:\n{excerpts}"
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
