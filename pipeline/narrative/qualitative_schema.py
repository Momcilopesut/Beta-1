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
    criterion: str = Field(max_length=120)
    assessment: Literal["yes", "no", "unknown"]
    evidence: str = Field(max_length=220)


class QualitativeAssessment(BaseModel):
    moat_present: bool
    moat_type: MoatType
    moat_explanation: str = Field(max_length=700)
    management_assessment: str = Field(max_length=700)
    red_flags: list[str] = Field(max_length=6)
    fisher_checklist: list[FisherCriterion] = Field(max_length=12)
    extraction_confidence: Literal["section_match", "whole_document_fallback"]


class ThesisAndFalsification(BaseModel):
    thesis: str = Field(max_length=900)
    falsification_criteria: list[str] = Field(min_length=2, max_length=6)
