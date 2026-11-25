from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.assessment.contracts import PythonAttempt, Submission
from leornian.modules.item_bank.contracts import (
    ChoiceResult,
    ProgramAnswer,
    PublicQuestion,
    PythonQuestion,
)
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.shared_kernel.contracts import Contract


class LearningCandidateInput(Contract):
    pack_id: UUID
    slot: Literal["practice_1", "practice_2"]


class LearningContentRef(Contract):
    owner: Literal["item_bank"] = "item_bank"
    id: UUID
    revision: int
    slot: Literal["practice_1", "practice_2"]
    public_identity: str


class LearningCandidate(Contract):
    id: UUID
    conversation_id: UUID
    kind: Literal["knowledge_check", "code_workspace"]
    focus: TeachingFocus
    content_ref: LearningContentRef
    title: str


class KnowledgeCheckPresentation(Contract):
    type: Literal["knowledge_check"] = "knowledge_check"
    question: PublicQuestion


class CodeWorkspacePresentation(Contract):
    type: Literal["code_workspace"] = "code_workspace"
    task: PythonQuestion


class LearningCandidateOption(LearningCandidate):
    presentation: Annotated[
        KnowledgeCheckPresentation | CodeWorkspacePresentation, Field(discriminator="type")
    ]


class LearningCandidateList(Contract):
    status: Literal["completed"]
    items: list[LearningCandidateOption]
    next_before: UUID | None


class LearningArtifactSummary(Contract):
    schema_version: Literal["learning_artifact.v1"] = "learning_artifact.v1"
    id: UUID
    conversation_id: UUID
    source_turn_id: UUID
    timeline_item_id: UUID
    revision: int
    kind: Literal["knowledge_check", "code_workspace"]
    state: Literal["ready", "running", "completed", "cancelled", "superseded"]
    created_at: datetime


class LearningArtifactView(LearningArtifactSummary):
    title: str
    practice_only: bool = False
    focus: TeachingFocus
    content_ref: LearningContentRef
    presentation: Annotated[
        KnowledgeCheckPresentation | CodeWorkspacePresentation, Field(discriminator="type")
    ]
    allowed_actions: list[Literal["respond", "run", "cancel"]]
    result: ChoiceResult | PythonAttempt | None = None
    commentary_status: Literal["not_requested", "pending_or_available"] = "not_requested"


class LearningActionBase(Contract):
    client_action_id: UUID
    expected_artifact_revision: int = Field(ge=1)


class PracticeSampleRunInput(Contract):
    command_id: UUID
    expected_artifact_revision: int = Field(ge=1)
    component_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    answer: Submission | ProgramAnswer


class RespondPayload(Contract):
    selected_key: Literal["A", "B", "C", "D"]


class RespondAction(LearningActionBase):
    action: Literal["respond"]
    payload: RespondPayload


class RunAction(LearningActionBase):
    action: Literal["run"]
    payload: Submission


class CancelAction(LearningActionBase):
    action: Literal["cancel"]


LearningArtifactAction = Annotated[
    RespondAction | RunAction | CancelAction, Field(discriminator="action")
]


class LearningActionReceipt(Contract):
    client_action_id: UUID
    artifact_id: UUID
    artifact_revision: int
    state: Literal["ready", "running", "completed", "cancelled", "superseded"]
    result_owner: Literal["assessment"] | None = None
    result_id: UUID | None = None
