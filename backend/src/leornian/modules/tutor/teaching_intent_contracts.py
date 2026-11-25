from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.modules.tutor.contracts import TeachingFocus
from leornian.shared_kernel.contracts import Contract


class TeachingIntent(Contract):
    id: UUID
    conversation_id: UUID
    generation: int
    focus: TeachingFocus
    artifact_id: UUID | None
    trigger_kind: Literal[
        "artifact_action", "expected_result", "interaction_event", "review_due", "node_window",
    ]
    trigger_ref: str
    priority: int
    state: Literal["pending", "dispatched", "cancelled", "superseded"]
    wait_reason: str | None
    run_id: UUID | None
    run_status: str | None = None
    created_at: datetime
    updated_at: datetime
    review_activity_id: UUID | None = None


class CancelTeachingIntent(Contract):
    client_action_id: UUID
