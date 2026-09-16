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
    one_line_summary: str = Field(max_length=140)
    short_term_narrative: str
    long_term_narrative: str
    facts: list[TieredFact]
