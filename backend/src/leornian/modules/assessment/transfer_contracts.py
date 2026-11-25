from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.modules.assessment.gate_contracts import RelationCheck
from leornian.modules.assessment.program_contracts import ProgramTransferAttempt
from leornian.modules.assessment.python_contracts import PythonAttempt
from leornian.modules.item_bank.contracts import (
    PublicProgramQuestion,
    PublicQuestion,
    PythonQuestion,
)
from leornian.shared_kernel.contracts import Contract
from pydantic import Field, model_validator


class TransferRelations(Contract):
    comparisons: list[RelationCheck] = Field(min_length=1)
    exposure_summary: str = ""

    @model_validator(mode="after")
    def unique_pairs(self):
        pairs = [(pair.left, pair.right) for pair in self.comparisons]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Every actual pair must appear exactly once.")
        return self


class TransferSummary(Contract):
    id: UUID
    remediation_id: UUID | None
    python_remediation_id: UUID | None
    program_remediation_id: UUID | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    kind: Literal[
        "choice", "python_io", "sql_query", "python_project",
        "project_stdio", "web_project", "http_project",
    ]
    source_pack_id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: str
    relation_run_id: UUID | None
    candidate_pack_id: UUID | None
    candidate_slot: Literal["practice_1", "practice_2"] | None
    status: Literal[
        "preparing",
        "ready",
        "opened",
        "submitted",
        "passed",
        "not_passed",
        "error",
        "blocked",
        "cancelled",
    ]
    error_code: str | None
    created_at: datetime
    opened_at: datetime | None
    completed_at: datetime | None


class TransferAnswer(Contract):
    selected_key: Literal["A", "B", "C", "D"]


class TransferRequest(Contract):
    expected_plan_revision: int = Field(ge=1)


class TransferFeedback(TransferAnswer):
    correct: bool
    explanation: str


class TransferView(Contract):
    transfer: TransferSummary
    question: PublicQuestion | PythonQuestion | PublicProgramQuestion | None = None
    result: TransferFeedback | None = None
    python_attempt: PythonAttempt | None = None
    program_attempt: ProgramTransferAttempt | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    allowed_actions: list[Literal["open", "submit", "cancel"]] = []
    blocked_reason: str | None = None
