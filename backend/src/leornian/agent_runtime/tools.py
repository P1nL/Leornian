"""Static, versioned tool contracts. Business execution belongs to bootstrap Facades."""

import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.tutor.artifact_contracts import ArtifactSection, ArtifactSummary
from leornian.shared_kernel.contracts import Contract


class EmptyArguments(Contract):
    pass


class ArtifactPage(Contract):
    before: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ArtifactRead(Contract):
    artifact_id: UUID
    revision: int = Field(ge=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=5, ge=1, le=20)


class ArtifactCreate(Contract):
    command_key: str = Field(min_length=8, max_length=128)
    instruction: str = Field(min_length=1, max_length=4000)


class ArtifactRevise(ArtifactCreate):
    artifact_id: UUID
    expected_revision: int = Field(ge=1)


class ToolProblem(Contract):
    status: Literal["rejected", "conflict", "waiting_dependency", "unknown"]
    code: str
    message: str | None = None
    fields: list[dict[str, str]] = []
    next_action: str


class ArtifactListResult(Contract):
    status: Literal["completed"]
    items: list[ArtifactSummary]
    next_before: UUID | None


class ArtifactReadResult(Contract):
    status: Literal["completed"]
    artifact_id: UUID
    revision: int
    title: str
    sections: list[ArtifactSection]
    section_count: int
    offset: int
    next_offset: int | None
    code_is_inert: Literal[True]


class ArtifactQueuedResult(Contract):
    status: Literal["accepted"]
    job_id: UUID
    artifact_id: UUID
    expected_revision: int
    message: str


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type[Contract]
    effect: Literal["read", "enqueue"]
    parallel_safe: bool = False
    version: int = 1
    result: type[Contract] | None = None  # Legacy context v1 preserves its original shape.

    def wire(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }

    def validate(self, arguments):
        return self.arguments.model_validate_json(
            arguments if isinstance(arguments, str) else json.dumps(arguments), strict=True
        )


DEFINITIONS = (
    ToolDefinition(
        "learning_get_context",
        "Refresh only the server-bound learning goal/node, admitted sources and public feedback. "
        "Read-only; cannot select identities, execute, publish, grade or update progress.",
        EmptyArguments,
        "read",
    ),
    ToolDefinition(
        "list_artifacts",
        "List accepted teaching artifacts in this exact goal/node scope. Metadata only; "
        "use returned exact id/revision with read_artifact. Pages do not imply full coverage.",
        ArtifactPage,
        "read",
        True,
        result=ArtifactListResult,
    ),
    ToolDefinition(
        "read_artifact",
        "Read a page of an immutable accepted teaching artifact revision in the bound scope. "
        "Follow next_offset until null when full content is required. Code is inert.",
        ArtifactRead,
        "read",
        True,
        result=ArtifactReadResult,
    ),
    ToolDefinition(
        "request_teaching_artifact",
        "Queue a checked teaching note/example document in the current scope. Reuse command_key "
        "for the same intent; a different intent needs a different key. accepted means queued, "
        "NOT delivered. It uses the native Runtime after this conversation turn finishes. "
        "No executable HTML, grading, publication or progress authority.",
        ArtifactCreate,
        "enqueue",
        result=ArtifactQueuedResult,
    ),
    ToolDefinition(
        "request_artifact_revision",
        "Queue a new checked revision without overwriting history. Read the artifact first; "
        "expected_revision must match its current head. Reuse command_key for the same intent. "
        "A conflict requires rereading, not silently rebasing. accepted is not delivery.",
        ArtifactRevise,
        "enqueue",
        result=ArtifactQueuedResult,
    ),
)
REGISTRY = {tool.name: tool for tool in DEFINITIONS}
LEGACY_TOOLS = ("learning_get_context",)
TEACHING_TOOLS = tuple(REGISTRY)


def contracts(names):
    return {name: REGISTRY[name].version for name in names}


def allowed(frozen):
    return tuple(name for name, tool in REGISTRY.items() if frozen.get(name) == tool.version)
