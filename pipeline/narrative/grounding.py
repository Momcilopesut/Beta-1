"""Post-hoc grounding enforcement.

The system prompt asks the model to cite only metrics present in the
payload; this module is the actual guarantee - it drops any fact whose
source_metric isn't a key that was really in the payload sent to the model,
rather than trusting the model to have followed the instruction.
"""

from pipeline.narrative.schema import CompanyNarrative, TieredFact


def enforce_grounding(narrative: CompanyNarrative, metrics: dict) -> tuple[CompanyNarrative, int]:
    """Returns (narrative_with_only_grounded_facts, dropped_count)."""
    valid_keys = set(metrics.keys())
    kept: list[TieredFact] = [f for f in narrative.facts if f.source_metric in valid_keys]
    dropped = len(narrative.facts) - len(kept)
    return narrative.model_copy(update={"facts": kept}), dropped
