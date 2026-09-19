"""Strict schema for the AI narrative layer's output, enforced via the
Anthropic SDK's structured-output support (client.messages.parse)."""

from typing import Literal

from pydantic import BaseModel, Field


class TieredFact(BaseModel):
    text: str
    tier: Literal["critical", "important", "minor", "noise"]
    source_metric: str
    source_value: str


class CompanyNarrative(BaseModel):
    # The prompt asks for <=140 characters as the actual target; this cap is
    # deliberately looser (see pipeline/scoring/aggregation.py's and
    # qualitative_schema.py's comments on the same pattern) - Anthropic's
    # structured-output support doesn't enforce Field(max_length=...) during
    # generation, so a tight cap just rejects an otherwise-valid response
    # that slightly overshot the target instead of catching a real problem.
    one_line_summary: str = Field(max_length=200)
    short_term_narrative: str
    long_term_narrative: str
    facts: list[TieredFact]
