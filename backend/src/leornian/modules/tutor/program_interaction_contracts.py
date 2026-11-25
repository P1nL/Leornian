from typing import Literal
from uuid import UUID

from leornian.modules.item_bank.contracts import ProgramAnswer, PublicProgramQuestion
from leornian.modules.tutor.composition_catalog import Key
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.modules.tutor.learning_artifact_contracts import (
    LearningActionBase,
    LearningContentRef,
)
from leornian.shared_kernel.contracts import Contract


class ProgramCandidatePresentation(Contract):
    type: Literal["program_practice"] = "program_practice"
    task: PublicProgramQuestion


class ProgramCandidateOption(Contract):
    id: UUID
    conversation_id: UUID
    kind: Literal["sql_workspace", "project_workspace"]
    focus: TeachingFocus
    content_ref: LearningContentRef
    title: str
    presentation: ProgramCandidatePresentation


class ProgramCandidateList(Contract):
    status: Literal["completed"]
    items: list[ProgramCandidateOption]
    next_before: UUID | None


class CompositionProgramPayload(Contract):
    answer: ProgramAnswer
    previous_attempt_id: UUID | None = None
    retry: bool = False


class CompositionProgramRunAction(LearningActionBase):
    action: Literal["run_program_component"]
    component_id: Key
    payload: CompositionProgramPayload
