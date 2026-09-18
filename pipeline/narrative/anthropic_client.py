"""Calls the Anthropic API to produce a grounded narrative for one company.

Uses the SDK's structured-output helper (client.messages.parse), which
validates the response against CompanyNarrative before returning it. The
system prompt is passed with cache_control: ephemeral since it's
byte-identical across every sequential call in a pipeline run - only the
per-company payload in the user turn varies.
"""

import json
import os

import anthropic

from pipeline.narrative.prompts import SYSTEM_PROMPT
from pipeline.narrative.schema import CompanyNarrative

DEFAULT_MODEL = "claude-sonnet-5"


class NarrativeError(Exception):
    pass


def generate_narrative(ticker: str, payload: dict) -> CompanyNarrative:
    """payload: the grounding dict (metrics + scores + macro context) for one
    company. Only payload["metrics"] keys may be cited as source_metric."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise NarrativeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=8192,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Ticker: {ticker}\n\nData payload (JSON):\n"
                        f"{json.dumps(payload, default=str)}"
                    ),
                }
            ],
            output_format=CompanyNarrative,
        )
    except Exception as exc:  # noqa: BLE001 - any API/parse failure degrades this one ticker, not the batch
        raise NarrativeError(f"Anthropic call failed for {ticker}: {exc}") from exc
    return response.parsed_output
