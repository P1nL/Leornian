from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.modules.assessment.contracts import OwnedEvidence
from leornian.shared_kernel.contracts import Contract


class AbilityDimension(Contract):
    dimension: Literal["concept", "execution", "transfer"]
    status: Literal["unobserved", "practicing", "demonstrated"]
    evidence_count: int
    passed_count: int
    failed_count: int
    error_count: int
    assisted_count: int
    independent_pass_count: int
    latest_receipt: UUID | None
    latest_at: datetime | None


class LearningEvidenceProjection(Contract):
    projector_version: Literal["ability-dimensions.v1"] = "ability-dimensions.v1"
    dimensions: list[AbilityDimension]
    evidence: list[OwnedEvidence]
