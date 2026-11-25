from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.shared_kernel.contracts import Contract


class ThinkingStep(Contract):
    id: UUID
    kind: Literal["thinking", "tool", "review"]
    title: str
    summary: str = ""
    detail: str = ""
    status: Literal["running", "completed", "waiting", "failed", "cancelled", "unknown"]
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    tool_name: str | None = None
