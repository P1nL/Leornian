from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.knowledge.material_contracts import MaterialPurpose, MaterialRef
from leornian.shared_kernel.contracts import Contract


class MaterialChangeInput(Contract):
    binding_id: UUID
    expected_binding_revision: int = Field(ge=1)
    document_id: UUID
    candidate_revision: int = Field(ge=1)


class MaterialBlockMapping(Contract):
    baseline: MaterialRef
    candidate: MaterialRef


class MaterialChangeReport(Contract):
    contract: Literal["material-change.v1"] = "material-change.v1"
    id: UUID
    binding_id: UUID
    binding_revision: int
    goal_id: UUID
    purpose: MaterialPurpose
    document_id: UUID
    baseline_revision: int
    candidate_revision: int
    classification: Literal["unchanged", "uncertain"]
    semantic_quality: Literal["not_certified"] = "not_certified"
    state: Literal["no_content_change", "waiting_dependency"]
    reason_code: Literal["change_review_required"] | None
    unchanged_blocks: list[MaterialBlockMapping]
    removed_or_changed_blocks: list[MaterialRef]
    added_or_changed_blocks: list[MaterialRef]
    affected_refs: list[MaterialRef]
    affected_context_refs: list[MaterialRef]
    relocated_refs: list[MaterialBlockMapping]
    created_at: datetime


class MaterialChangeVerdict(Contract):
    classification: Literal["editorial_equivalent", "semantic_change", "uncertain"]
    summary: str = Field(min_length=1, max_length=1200)
    reviewed_refs: list[MaterialRef] = Field(min_length=1, max_length=40_000)


class MaterialChangeReview(Contract):
    contract: Literal["material-change-review.v1"] = "material-change-review.v1"
    id: UUID
    check_id: UUID
    status: Literal[
        "queued",
        "processing",
        "waiting_config",
        "waiting_dependency",
        "blocked_unknown",
        "reviewed",
        "cancelled",
    ]
    result: MaterialChangeVerdict | None
    error_code: str | None
    created_at: datetime
