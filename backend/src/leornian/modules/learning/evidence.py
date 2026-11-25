from leornian.modules.learning.evidence_contracts import (
    AbilityDimension,
    LearningEvidenceProjection,
)


def project_evidence(evidence):
    """Projection keeps all owner outcomes; only independent Gate passes demonstrate ability."""
    dimensions = []
    for dimension in ("concept", "execution", "transfer"):
        facts = sorted(
            (fact for fact in evidence if fact.dimension == dimension),
            key=lambda fact: (fact.occurred_at, str(fact.source_receipt)),
        )
        independent = sum(
            fact.outcome == "passed" and fact.independence == "independent_gate" for fact in facts
        )
        dimensions.append(AbilityDimension(
            dimension=dimension, status="demonstrated" if independent else (
                "practicing" if facts else "unobserved"
            ), evidence_count=len(facts), passed_count=sum(
                fact.outcome == "passed" for fact in facts
            ), failed_count=sum(fact.outcome == "not_passed" for fact in facts),
            error_count=sum(fact.outcome == "error" for fact in facts),
            assisted_count=sum(fact.independence == "assisted" for fact in facts),
            independent_pass_count=independent,
            latest_receipt=facts[-1].source_receipt if facts else None,
            latest_at=facts[-1].occurred_at if facts else None,
        ))
    return LearningEvidenceProjection(dimensions=dimensions, evidence=evidence)
