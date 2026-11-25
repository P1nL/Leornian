from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.shared_kernel.contracts import Contract


class MaterialUpdateNotificationContent(Contract):
    offer_id: UUID
    goal_id: UUID
    plan_id: UUID | None
    plan_revision: int | None
    node_key: str | None
    binding_id: UUID
    binding_revision: int
    document_id: UUID
    baseline_revision: int
    candidate_revision: int
    affected_plan_count: int
    affected_lesson_count: int
    recommendation: Literal["consider_update"] = "consider_update"
    reason: Literal["reviewed_semantic_change"] = "reviewed_semantic_change"
    migration_cost: Literal["binding_only", "dependent_content_requires_reprepare"]


class Notification(Contract):
    id: UUID
    offer_id: UUID
    kind: Literal["material_update"]
    payload: MaterialUpdateNotificationContent
    state: Literal["unread", "read", "deferred", "kept_current", "accepted"]
    read_at: datetime | None
    deferred_at: datetime | None
    created_at: datetime
