from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.knowledge.material_contracts import MaterialPurpose, MaterialRef
from leornian.shared_kernel.contracts import Contract


class MaterialUpdatePrepareInput(Contract):
    expected_binding_revision: int = Field(ge=1)
    candidate_selection_id: UUID


class MaterialUpdatePreparation(Contract):
    id: UUID
    check_id: UUID
    status: Literal[
        "queued", "processing", "waiting_config", "waiting_dependency",
        "blocked_unknown", "ready", "cancelled",
    ]
    error_code: str | None
    demand_id: UUID | None
    job_id: UUID | None
    search_id: UUID | None
    offer_id: UUID | None
    created_at: datetime


class MaterialUpdateDependency(Contract):
    kind: Literal["plan", "lesson"]
    id: UUID
    revision: int | None = None
    plan_id: UUID | None = None
    plan_revision: int | None = None
    node_key: str | None = None


class MaterialUpdateImpact(Contract):
    dependencies: list[MaterialUpdateDependency]
    existing_content: Literal["keeps_exact_references"] = "keeps_exact_references"
    successor_application: Literal["new_consumption_only"] = "new_consumption_only"
    route_confirmation: Literal["required_before_route_change"] = "required_before_route_change"


class MaterialUpdateOffer(Contract):
    contract: Literal["material-update-offer.v1"] = "material-update-offer.v1"
    id: UUID
    revision: int
    check_id: UUID
    preparation_id: UUID
    goal_id: UUID
    plan_id: UUID | None
    plan_revision: int | None
    node_key: str | None
    purpose: MaterialPurpose
    binding_id: UUID
    binding_revision: int
    document_id: UUID
    baseline_revision: int
    candidate_revision: int
    candidate_selection_id: UUID
    candidate_refs: list[MaterialRef]
    summary: str
    recommendation: Literal["consider_update"] = "consider_update"
    preparation_cost: Literal["completed"] = "completed"
    migration_cost: Literal["binding_only", "dependent_content_requires_reprepare"]
    impact: MaterialUpdateImpact
    options: list[Literal["accept_update", "decide_later", "keep_current_for_track"]] = [
        "accept_update", "decide_later", "keep_current_for_track",
    ]
    created_at: datetime
