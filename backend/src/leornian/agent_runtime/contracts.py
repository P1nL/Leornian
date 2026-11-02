from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from leornian.shared_kernel.contracts import Contract

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "blocked_unknown"]


class RoleSpec(Contract):
    policy_version: Literal[
        "tutor.v1",
        "planner.v1",
        "lesson.v1",
        "item_author.v1",
        "item_blind.v1",
        "item_review.v1",
        "gate_relation.v1",
        "transfer_relation.v1",
        "evaluation.v1",
        "delivery_review.v1",
        "artifact.v1",
    ] = "tutor.v1"
    allowed_tools: tuple[str, ...] = ()
    recover_tool_errors: bool = False
    require_initial_tool: bool = True
    messages: list[dict[str, Any]]
    completion_driven: bool = False
    output_multiplier: int = 1
    optional_history: list[list[dict[str, Any]]] = []
    context_manifest: dict[str, Any] = {}


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
    purpose: Literal[
        "teaching",
        "planning",
        "lesson",
        "item_supply",
        "gate",
        "transfer",
        "evaluation",
        "artifact",
    ] = "teaching"


class TurnAccepted(Contract):
    status: Literal["accepted"] = "accepted"
    run_id: UUID
    turn_id: UUID
    delivery_task_id: UUID | None = None


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
    arguments: dict[str, Any] | str


class Decision(Contract):
    content: str | None = None
    tools: list[ToolCall] = []
    # Private protocol continuation, never a public reply or a serialized DTO.
    assistant_message: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)


class StoredCall(Contract):
    id: UUID
    step: int
    status: str
    endpoint: str
    request: dict[str, Any]
    response_body: str | None
    http_status: int | None
    applied: bool
    policy_snapshot: dict[str, Any] = {}
    context_manifest: dict[str, Any] = {}


class Receipt(Contract):
    body: str
    http_status: int
    provider_request_id: str | None = None


class EmptyToolArguments(Contract):
    pass


class ToolActivity(Contract):
    id: UUID
    run_id: UUID
    name: str
    contract_version: int
    outcome: str
    duration_ms: int
    created_at: datetime
