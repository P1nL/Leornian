from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.shared_kernel.contracts import Contract

Rating = Literal["again", "good", "easy"]


class ReviewInput(Contract):
    expected_revision: int = Field(ge=1)
    rating: Rating


class ReviewStatus(Contract):
    expected_revision: int = Field(ge=1)
    status: Literal["scheduled", "paused"]


class ReviewCard(Contract):
    id: UUID
    track_id: UUID | None
    goal_id: UUID
    plan_id: UUID | None = None
    plan_revision: int | None = None
    node_key: str | None = None
    source_receipt: UUID | None = None
    revision: int
    status: Literal["scheduled", "paused"]
    next_due_at: datetime
    due: bool
    last_rating: Rating | None
    reviewed_at: datetime | None
    algorithm_version: str = "legacy-fixed.v1"
    parameter_version: str = "legacy-fixed.v1"
    scheduling_state: dict | None = None
    prompt: str = "不看课文，回忆如何遍历整数数组、筛选偶数并累加；空数组应输出什么？"


class ReviewLog(Contract):
    id: UUID
    card_id: UUID
    response_id: UUID
    evidence_kind: Literal["self_rating"] = "self_rating"
    source_receipt: UUID
    rating: Rating
    rating_contract: Literal["self-rating-three.v1"]
    algorithm_version: str
    parameter_version: str
    scheduler: dict
    previous_state: dict
    next_state: dict
    algorithm_log: dict
    reviewed_at: datetime
    due_at: datetime


class ReviewActivity(Contract):
    kind: Literal["memory_review"] = "memory_review"
    id: UUID
    card_id: UUID
    goal_id: UUID
    card_revision: int
    due_at: datetime
    state: Literal["due", "presented", "completed", "cancelled"]
    conversation_id: UUID | None
    presented_at: datetime | None
    source_receipt: UUID | None
    created_at: datetime
    updated_at: datetime
    card: ReviewCard
    evidence_kind: Literal["self_rating"] = "self_rating"


class PresentReview(Contract):
    expected_card_revision: int = Field(ge=1)
    conversation_id: UUID


class ActivityResponse(ReviewInput):
    pass
