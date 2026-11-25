"""Layer 3 (qualitative filing-text reasoning) - the only AI call in this
pipeline. Defaults to Anthropic's Claude; QUALITATIVE_PROVIDER=lmstudio
swaps in a local LM Studio model instead, run entirely on your own
machine for zero API spend (see README's "Local generation with LM
Studio"). Local-only: the automated weekly screen and the Vercel
on-demand lookup both run in the cloud and can't reach a server on your
machine, so they always use the Anthropic provider regardless of what's
set in your own shell.

See qualitative_schema.py for why this carries a prompt-only grounding
guarantee rather than a code-verified one - true for either provider.
"""

import json
import os

import anthropic
import requests

from pipeline.narrative.qualitative_prompts import LOCAL_JSON_RESPONSE_INSTRUCTIONS, QUALITATIVE_SYSTEM_PROMPT
from pipeline.narrative.qualitative_schema import QualitativeAssessment

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_LMSTUDIO_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LMSTUDIO_MODEL = "local-model"
DEFAULT_LMSTUDIO_TIMEOUT_SECONDS = 300


class QualitativeError(Exception):
    pass


def _anthropic_client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise QualitativeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic()


def _build_excerpts(sections: dict, filing_texts: dict[str, str]) -> str:
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
    return "\n\n".join(excerpt_parts) or "(no filing text could be extracted)"


def _user_content(ticker: str, sections: dict, excerpts: str) -> str:
    return (
        f"Ticker: {ticker}\n\n"
        f"10-K extraction method: {sections.get('method')}\n\n"
        f"Filing excerpts:\n{excerpts}"
    )


def _generate_via_anthropic(ticker: str, sections: dict, filing_texts: dict[str, str]) -> QualitativeAssessment:
    client = _anthropic_client()
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    excerpts = _build_excerpts(sections, filing_texts)

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
            messages=[{"role": "user", "content": _user_content(ticker, sections, excerpts)}],
            output_format=QualitativeAssessment,
        )
    except Exception as exc:  # noqa: BLE001 - degrades this one ticker's qualitative layer, not the batch
        raise QualitativeError(f"Qualitative assessment failed for {ticker}: {exc}") from exc

    return response.parsed_output


def _extract_json_object(text: str) -> dict:
    """Local models routinely wrap JSON in markdown fences, or add a
    stray sentence before/after it despite being told not to - a direct
    json.loads() on the raw content is the common case, but falls back to
    slicing out the outermost {...} span before giving up."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise
        return json.loads(text[start : end + 1])


def _generate_via_lmstudio(ticker: str, sections: dict, filing_texts: dict[str, str]) -> QualitativeAssessment:
    """Same prompt and schema as the Anthropic path, sent to a local LM
    Studio server's OpenAI-compatible /chat/completions endpoint instead.
    Local models don't get Anthropic's structured-output enforcement, so
    the schema is spelled out in the prompt (LOCAL_JSON_RESPONSE_INSTRUCTIONS)
    and the response is parsed/validated by hand; a model that ignores the
    instructions, times out, or isn't running at all surfaces as a
    QualitativeError, degrading just this one ticker's qualitative layer -
    exactly like an Anthropic failure would."""
    base_url = os.environ.get("LMSTUDIO_BASE_URL", DEFAULT_LMSTUDIO_BASE_URL).rstrip("/")
    model = os.environ.get("LMSTUDIO_MODEL", DEFAULT_LMSTUDIO_MODEL)
    timeout = float(os.environ.get("LMSTUDIO_TIMEOUT_SECONDS", DEFAULT_LMSTUDIO_TIMEOUT_SECONDS))
    # Most LM Studio/llama.cpp server builds honor response_format, which
    # makes a schema-following model far more likely to return clean JSON -
    # but older builds can reject the field outright, so it's an escape
    # hatch rather than hardcoded on.
    json_mode = os.environ.get("LMSTUDIO_JSON_MODE", "1") != "0"
    excerpts = _build_excerpts(sections, filing_texts)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": QUALITATIVE_SYSTEM_PROMPT + "\n\n" + LOCAL_JSON_RESPONSE_INSTRUCTIONS},
            {"role": "user", "content": _user_content(ticker, sections, excerpts)},
        ],
        "temperature": 0.2,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=timeout)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)
        return QualitativeAssessment.model_validate(parsed)
    except Exception as exc:  # noqa: BLE001 - connection error, bad JSON, schema mismatch, ...
        raise QualitativeError(f"Local LM Studio qualitative assessment failed for {ticker}: {exc}") from exc


def generate_qualitative_assessment(
    ticker: str, sections: dict, filing_texts: dict[str, str] | None = None
) -> QualitativeAssessment:
    """sections: pipeline.fetch.filing_text.extract_sections()'s return value
    for this company's most recent 10-K (drives the moat read and
    filing_summary_10k).

    filing_texts: optional {"10-Q": text, "8-K": text} bounded plain text
    (pipeline.fetch.filing_text.fetch_plain_text()) for filing_summary_10q/
    8k - either or both keys may be absent when that filing type wasn't
    found for this company.

    Provider is picked by QUALITATIVE_PROVIDER ("anthropic", the default,
    or "lmstudio" for a local model - see this module's own docstring)."""
    filing_texts = filing_texts or {}
    provider = os.environ.get("QUALITATIVE_PROVIDER", "anthropic").strip().lower()
    if provider == "anthropic":
        parsed = _generate_via_anthropic(ticker, sections, filing_texts)
    elif provider == "lmstudio":
        parsed = _generate_via_lmstudio(ticker, sections, filing_texts)
    else:
        raise QualitativeError(f"Unknown QUALITATIVE_PROVIDER {provider!r} (expected 'anthropic' or 'lmstudio')")

    # extraction_confidence must reflect the actual extraction method, not
    # whatever the model decided to say - overwrite rather than trust it.
    return parsed.model_copy(update={"extraction_confidence": sections.get("method", "whole_document_fallback")})
