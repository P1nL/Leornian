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
    track_id: UUID
    revision: int
    status: Literal["scheduled", "paused"]
    next_due_at: datetime
    due: bool
    last_rating: Rating | None
    reviewed_at: datetime | None
    prompt: str = "不看课文，回忆如何遍历整数数组、筛选偶数并累加；空数组应输出什么？"
