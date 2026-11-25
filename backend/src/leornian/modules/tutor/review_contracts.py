"""Explicit learner acknowledgement of an immutable submitted-code review."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.modules.tutor.composition_catalog import Key
from leornian.modules.tutor.learning_artifact_contracts import LearningActionBase
from leornian.shared_kernel.contracts import Contract


class CompleteReviewAction(LearningActionBase):
    action: Literal["complete_review"]
    component_id: Key


class ReviewCompletion(Contract):
    id: UUID
    artifact_id: UUID
    component_id: Key
    presentation_id: UUID
    content_identity: str
    attempt_id: UUID
    evaluation_id: UUID
    evidence_kind: Literal["learner_review_report.v1"] = "learner_review_report.v1"
    completed_at: datetime


class ReviewReportView(Contract):
    component_id: Key
    state: Literal["ready", "completed", "cancelled"]
    allowed_actions: list[Literal["complete_review"]]
    completion: ReviewCompletion | None


class ReviewActionReceipt(Contract):
    schema_version: Literal["learning_review_action.v1"] = "learning_review_action.v1"
    client_action_id: UUID
    artifact_id: UUID
    artifact_revision: int
    state: Literal["ready", "running", "completed", "cancelled", "superseded"]
    component_id: Key
    result_owner: Literal["tutor"] = "tutor"
    result_id: UUID
