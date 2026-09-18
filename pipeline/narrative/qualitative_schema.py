"""Strict schemas for Layer 3 (qualitative filing-text reasoning) and Layer 5
(thesis + falsification). Separate from pipeline/narrative/schema.py's
CompanyNarrative deliberately: that schema's facts are grounded in a fixed
metrics dict, so grounding can be code-verified (a source_metric key either
exists or it doesn't - pipeline/narrative/grounding.py drops anything that
doesn't). These schemas are grounded in free-form filing prose instead,
which can't be checked the same mechanical way - there is no equivalent
"drop-if-not-real" pass here, only prompt discipline (see
qualitative_prompts.py). That's a real, lower guarantee than the rest of
this pipeline's narrative layer, and is documented as such rather than
implied to be equally verified.
"""

from typing import Literal

from pydantic import BaseModel, Field

MoatType = Literal[
    "network_effects", "cost_advantage", "intangible_assets", "switching_costs", "efficient_scale", "none"
]


class FisherCriterion(BaseModel):
    criterion: str = Field(max_length=150)
    assessment: Literal["yes", "no", "unknown"]
    evidence: str = Field(max_length=350)


class QualitativeAssessment(BaseModel):
    moat_present: bool
    moat_type: MoatType
    # A real production run showed this cap being hit constantly: Anthropic's
    # structured-output support does NOT enforce Field(max_length=...) on a
    # string during generation (only type/structure/enum constraints are
    # actually constrained at sampling time) - pydantic only checks it
    # AFTER the fact, so a too-tight cap doesn't truncate the model's
    # output, it just rejects an otherwise complete, valid response as an
    # error. A normal, non-runaway "1-3 sentences" or "2-4 sentences"
    # response citing specific filing details routinely runs past 700
    # characters. These limits are a loose backstop against pathological
    # output, not a token-budget control - max_tokens in
    # qualitative_client.py is what actually bounds generation length.
    moat_explanation: str = Field(max_length=1500)
    management_assessment: str = Field(max_length=1500)
    red_flags: list[str] = Field(max_length=6)
    fisher_checklist: list[FisherCriterion] = Field(max_length=12)
    extraction_confidence: Literal["section_match", "whole_document_fallback"]


class ThesisAndFalsification(BaseModel):
    thesis: str = Field(max_length=1800)  # see QualitativeAssessment's comment on why this is generous
    falsification_criteria: list[str] = Field(min_length=2, max_length=6)
