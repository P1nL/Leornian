from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.knowledge.contracts import MaterialUpdateDependency
from leornian.shared_kernel.contracts import Contract

MaterialUpdateChoice = Literal["accept_update", "decide_later", "keep_current_for_track"]


class MaterialUpdateDecisionInput(Contract):
    decision: MaterialUpdateChoice
    expected_offer_revision: int = Field(ge=1)
    expected_binding_revision: int = Field(ge=1)


class MaterialUpdateDecision(Contract):
    id: UUID
    offer_id: UUID
    decision: MaterialUpdateChoice
    binding_id: UUID
    binding_revision: int
    successor_binding_id: UUID | None
    successor_binding_revision: int | None
    requires_reprepare: list[MaterialUpdateDependency]
    created_at: datetime


class MaterialRepreparation(Contract):
    id: UUID
    decision_id: UUID
    kind: Literal["plan", "lesson"]
    source_id: UUID
    source_revision: int
    plan_id: UUID
    node_key: str | None
    state: Literal[
        "queued", "waiting_priority", "waiting_confirmation", "running",
        "waiting_receipt", "ready", "superseded", "cancelled", "waiting_dependency",
    ]
    reason: str | None
    run_id: UUID | None
    delivery_task_id: UUID | None
    output_plan_revision: int | None
    output_lesson_id: UUID | None
    created_at: datetime
    updated_at: datetime
