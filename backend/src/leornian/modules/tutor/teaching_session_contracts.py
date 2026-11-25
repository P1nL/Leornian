from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.tutor.composition_v2_contracts import PresentationCapabilities
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.modules.tutor.interaction_contracts import NextSpeaker
from leornian.shared_kernel.contracts import Contract


class NodeWindow(Contract):
    after_turn_id: UUID | None
    next_step: NextSpeaker | Literal["opening", "hold"]


class ContinueNode(Contract):
    expected_session_revision: int = Field(ge=1)
    focus: TeachingFocus
    after_turn_id: UUID | None
    presentation_capabilities: PresentationCapabilities = Field(
        default_factory=PresentationCapabilities,
    )


class TeachingSession(Contract):
    conversation_id: UUID
    revision: int
    generation: int
    mode: Literal["guided", "free_reading"]
    paused: bool
    focus: TeachingFocus
    active_branch_id: UUID | None
    updated_at: datetime
    continuation_policy: Literal["manual", "after_result.v1"] = "manual"
    continuation_generation: int = 1
    node_window: NodeWindow | None = None


class TeachingBranch(Contract):
    id: UUID
    conversation_id: UUID
    generation: int
    anchor_artifact_id: UUID
    anchor_revision: int
    content_identity: str
    focus: TeachingFocus
    state: Literal["active", "closed", "superseded"]
    opened_at: datetime
    closed_at: datetime | None
    turn_count: int


class ArtifactQuestionFeedback(Contract):
    kind: Literal["artifact_question.v1"] = "artifact_question.v1"
    turn_id: UUID
    artifact_id: UUID
    text: str


class SessionCommand(Contract):
    client_action_id: UUID
    expected_session_revision: int = Field(ge=0)


class OpenTeachingSession(SessionCommand):
    action: Literal["open"]
    mode: Literal["guided", "free_reading"] = "guided"
    focus: TeachingFocus = Field(default_factory=TeachingFocus)


class SetTeachingMode(SessionCommand):
    action: Literal["set_mode"]
    mode: Literal["guided", "free_reading"]


class PauseTeaching(SessionCommand):
    action: Literal["pause"]


class ResumeTeaching(SessionCommand):
    action: Literal["resume"]


class ReturnToMain(SessionCommand):
    action: Literal["return_to_main"]
    branch_id: UUID


class SetTeachingTopic(SessionCommand):
    action: Literal["set_topic"]
    focus: TeachingFocus


class FinishTeachingNode(SessionCommand):
    action: Literal["finish_node"]
    focus: TeachingFocus
    after_turn_id: UUID


class SetContinuationPolicy(SessionCommand):
    action: Literal["set_continuation_policy"]
    policy: Literal["manual", "after_result.v1"]


TeachingSessionCommand = Annotated[
    OpenTeachingSession | SetTeachingMode | PauseTeaching | ResumeTeaching | ReturnToMain
    | SetTeachingTopic | SetContinuationPolicy | FinishTeachingNode,
    Field(discriminator="action"),
]
