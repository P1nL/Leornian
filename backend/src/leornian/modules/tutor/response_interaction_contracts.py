"""Explicit new-client response capability; existing candidate tools stay frozen."""

from typing import Literal
from uuid import UUID

from leornian.modules.item_bank.contracts import ResponseQuestion
from leornian.modules.tutor.learning_artifact_contracts import LearningCandidate
from leornian.shared_kernel.contracts import Contract


class ResponsePresentation(Contract):
    type: Literal["knowledge_response"] = "knowledge_response"
    question: ResponseQuestion


class ResponseCandidateOption(LearningCandidate):
    kind: Literal["knowledge_response"] = "knowledge_response"
    presentation: ResponsePresentation


class ResponseCandidateList(Contract):
    status: Literal["completed"] = "completed"
    items: list[ResponseCandidateOption]
    next_before: UUID | None
