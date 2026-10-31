from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from leornian.shared_kernel.contracts import Contract

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "blocked_unknown"]


class RoleSpec(Contract):
    policy_version: Literal["tutor.v1", "planner.v1", "lesson.v1"] = "tutor.v1"
    allowed_tools: tuple[str, ...] = ("learning_get_context",)
    messages: list[dict[str, Any]]


class Run(Contract):
    id: UUID
    conversation_id: UUID
    turn_id: UUID
    status: RunStatus
    cancel_requested: bool
    error_code: str | None
    tool_count: int = 0
    can_resume: bool = False
    created_at: datetime
    completed_at: datetime | None
    purpose: Literal["teaching", "planning", "lesson"] = "teaching"


class TurnAccepted(Contract):
    status: Literal["accepted"] = "accepted"
    run_id: UUID
    turn_id: UUID


class ModelAvailability(Contract):
    ready: bool
    reason: Literal["ready", "not_configured"]
    protocol: Literal["chat_completions"] = "chat_completions"


class Lease(Contract):
    run_id: UUID
    token: UUID


class ToolCall(Contract):
    id: str
    name: str
    arguments: dict[str, Any]


class Decision(Contract):
    content: str | None = None
    tools: list[ToolCall] = []


class StoredCall(Contract):
    id: UUID
    step: int
    status: str
    endpoint: str
    request: dict[str, Any]
    response_body: str | None
    http_status: int | None
    applied: bool


class Receipt(Contract):
    body: str
    http_status: int
    provider_request_id: str | None = None


class EmptyToolArguments(Contract):
    pass
