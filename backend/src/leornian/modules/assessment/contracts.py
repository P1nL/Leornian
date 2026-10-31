from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from leornian.shared_kernel.contracts import Contract


class Submission(Contract):
    code: str = Field(min_length=1, max_length=12000)

    @field_validator("code")
    @classmethod
    def byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 12000:
            raise ValueError("Code exceeds 12000 bytes")
        return value


class Attempt(Contract):
    id: UUID
    track_id: UUID
    item_version: str
    status: Literal["queued", "passed", "not_passed", "error"]
    feedback: str | None
    passed_cases: int | None
    total_cases: int
    created_at: datetime
    completed_at: datetime | None


class AssessmentResult(Contract):
    passed: bool
    passed_cases: int
    feedback: str
