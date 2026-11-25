"""Learner-reported demonstration interaction, never assessment evidence."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.tutor.composition_catalog import Key
from leornian.modules.tutor.learning_artifact_contracts import LearningActionBase
from leornian.shared_kernel.contracts import Contract


class DemoBinding(Contract):
    component_id: Key
    profile_version: Literal["demo-report.v1"] = "demo-report.v1"
    event: Literal["timeline_end", "preview_snapshot"]


class DemoStartAction(LearningActionBase):
    action: Literal["start_demo"]
    component_id: Key
    inputs: dict[Key, str | float | int] = Field(default_factory=dict, max_length=2)


class DemoEventAction(LearningActionBase):
    action: Literal["acknowledge_demo_event"]
    component_id: Key
    generation: int = Field(ge=1)
    nonce: UUID
    sequence: Literal[1]
    event: Literal["timeline_end", "preview_snapshot"]
    step_index: int | None = Field(default=None, ge=0, le=10000)


class DemoCompleteAction(LearningActionBase):
    action: Literal["complete_demo"]
    component_id: Key
    generation: int = Field(ge=1)
    nonce: UUID
    sequence: Literal[2]


class DemoCompletion(Contract):
    id: UUID
    artifact_id: UUID
    component_id: Key
    generation: int
    presentation_id: UUID
    content_identity: str
    inputs: dict[Key, str | float | int]
    event: Literal["timeline_end", "preview_snapshot"]
    last_step: int | None
    evidence_kind: Literal["learner_demo_report.v1"] = "learner_demo_report.v1"
    completed_at: datetime


class DemoView(DemoBinding):
    state: Literal["ready", "started", "acknowledged", "completed"]
    generation: int
    nonce: UUID | None
    sequence: int
    inputs: dict[Key, str | float | int]
    last_step: int | None
    allowed_actions: list[Literal["start_demo", "acknowledge_demo_event", "complete_demo"]]
    completions: list[DemoCompletion] = Field(default_factory=list)
    completion_count: int = 0
    next_completion_before: int | None = None


class DemoHistory(Contract):
    items: list[DemoCompletion]
    next_before: int | None


class DemoActionReceipt(Contract):
    schema_version: Literal["learning_demo_action.v1"] = "learning_demo_action.v1"
    client_action_id: UUID
    artifact_id: UUID
    artifact_revision: int
    state: Literal["ready", "running", "completed", "cancelled", "superseded"]
    component_id: Key
    generation: int
    nonce: UUID
    sequence: int
    result_owner: Literal["tutor"] | None = None
    result_id: UUID | None = None
