"""Strict schema for Layer 3 (qualitative filing-text reasoning: is there a
durable moat?). Grounded in free-form filing prose, which can't be checked
mechanically the way a fixed metrics dict can (a required key either exists
or it doesn't) - there is no code-verified "drop-if-not-real" pass here,
only prompt discipline (see qualitative_prompts.py). That's a real, lower
guarantee than the rest of this pipeline's output, and is documented as
such rather than implied to be equally verified.
"""

from typing import Literal

from pydantic import BaseModel, Field

MoatType = Literal[
    "network_effects", "cost_advantage", "intangible_assets", "switching_costs", "efficient_scale", "none"
]


class QualitativeAssessment(BaseModel):
    moat_present: bool
    moat_type: MoatType
    # A real production run showed a tighter cap being hit constantly:
    # Anthropic's structured-output support does NOT enforce
    # Field(max_length=...) on a string during generation (only
    # type/structure/enum constraints are actually constrained at sampling
    # time) - pydantic only checks it AFTER the fact, so a too-tight cap
    # doesn't truncate the model's output, it just rejects an otherwise
    # complete, valid response as an error. A normal, non-runaway "1-3
    # sentences" response citing specific filing details routinely runs past
    # 700 characters. This limit is a loose backstop against pathological
    # output, not a token-budget control - max_tokens in qualitative_client.py
    # is what actually bounds generation length.
    moat_explanation: str = Field(max_length=1000)
    red_flags: list[str] = Field(max_length=6)
    extraction_confidence: Literal["section_match", "whole_document_fallback"]
