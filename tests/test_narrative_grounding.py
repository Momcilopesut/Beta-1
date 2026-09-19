from pipeline.narrative.grounding import enforce_grounding
from pipeline.narrative.schema import CompanyNarrative, TieredFact


def _narrative(facts: list[TieredFact]) -> CompanyNarrative:
    return CompanyNarrative(
        one_line_summary="Test summary.",
        narrative="Plain-language narrative.",
        facts=facts,
    )


def test_enforce_grounding_keeps_facts_backed_by_a_real_metric():
    facts = [
        TieredFact(text="ROE is strong.", tier="important", source_metric="roe_pct", source_value="18.4%"),
    ]
    grounded, dropped = enforce_grounding(_narrative(facts), {"roe_pct": 18.4})
    assert dropped == 0
    assert len(grounded.facts) == 1


def test_enforce_grounding_drops_fact_with_fabricated_source_metric():
    facts = [
        TieredFact(text="ROE is strong.", tier="important", source_metric="roe_pct", source_value="18.4%"),
        TieredFact(
            text="Insider buying is heavy this quarter.",
            tier="critical",
            source_metric="insider_buying_score",  # not a real key in the payload
            source_value="high",
        ),
    ]
    grounded, dropped = enforce_grounding(_narrative(facts), {"roe_pct": 18.4})
    assert dropped == 1
    assert len(grounded.facts) == 1
    assert grounded.facts[0].source_metric == "roe_pct"


def test_enforce_grounding_drops_everything_when_metrics_empty():
    facts = [TieredFact(text="Some claim.", tier="minor", source_metric="anything", source_value="x")]
    grounded, dropped = enforce_grounding(_narrative(facts), {})
    assert dropped == 1
    assert grounded.facts == []
