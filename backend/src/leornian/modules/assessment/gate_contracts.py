from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from leornian.modules.execution.contracts import CaseOutput
from leornian.modules.item_bank.contracts import (
    PublicProgramQuestion,
    PublicQuestion,
    PythonQuestion,
)
from leornian.shared_kernel.contracts import Contract


class RelationCheck(Contract):
    left: str = Field(min_length=1, max_length=100)
    right: str = Field(min_length=1, max_length=100)
    verdict: Literal["distinct_decision", "answer_leakage", "uncertain"]
    reason: str = Field(min_length=1, max_length=180)


class GateRelations(Contract):
    comparisons: list[RelationCheck] = Field(min_length=1)
    exposure_summary: str = ""

    @model_validator(mode="after")
    def unique_pairs(self):
        keys = [(entry.left, entry.right) for entry in self.comparisons]
        if len(keys) != len(set(keys)):
            raise ValueError("Every required pair must be compared exactly once.")
        return self


class GateRevisionFeedback(Contract):
    """Stored quality facts for a new author version, never a permission or public solution."""

    gate_id: UUID
    pack_id: UUID
    policy_version: Literal["concept-gate.v1", "python-io-gate.v1", "program-execution-gate.v1"]
    relation_report: GateRelations
    reviewed_context: dict
    actual_exposures: list[dict]


class GateRequest(Contract):
    expected_plan_revision: int = Field(ge=1)


class GateSelection(Contract):
    slot: Literal["assessment_1", "assessment_2"]
    selected_key: Literal["A", "B", "C", "D"]


class GateSubmission(Contract):
    answers: list[GateSelection] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def both_slots_once(self):
        if {answer.slot for answer in self.answers} != {"assessment_1", "assessment_2"}:
            raise ValueError("Submit both assessment answers together, exactly once.")
        return self


class GateItemResult(GateSelection):
    correct: bool
    explanation: str


class GateSummary(Contract):
    id: UUID
    pack_id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: str
    lesson_id: UUID
    policy_version: Literal[
        "concept-gate.v1", "python-io-gate.v1", "program-execution-gate.v1",
    ] = "concept-gate.v1"
    relation_run_id: UUID | None
    status: Literal[
        "preparing",
        "ready",
        "in_progress",
        "submitted",
        "passed",
        "not_passed",
        "blocked",
        "cancelled",
    ]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class GateProgramResult(Contract):
    slot: Literal["assessment_1", "assessment_2"]
    attempt_id: UUID
    status: Literal["passed", "not_passed", "error"]
    passed_cases: int = Field(ge=0, le=3)
    feedback: str | None
    error_code: str | None
    compilation: CaseOutput | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class GateView(Contract):
    gate: GateSummary
    questions: list[PublicQuestion | PythonQuestion | PublicProgramQuestion] = []
    results: list[GateItemResult] = []
    allowed_actions: list[Literal["start", "submit", "cancel"]] = []
    blocked_reason: str | None = None
    program_results: list[GateProgramResult] = Field(
        default_factory=list, exclude_if=lambda values: not values,
    )


class Remediation(Contract):
    id: UUID
    pack_id: UUID
    parent_result_id: UUID
    status: Literal["available", "passed", "not_passed"]
    transfer_required: bool
    created_at: datetime


class ConceptCompletion(Contract):
    gate_id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: str
    policy_version: Literal["concept-gate.v1"] = "concept-gate.v1"
    passed_items: Literal[2] = 2
    total_items: Literal[2] = 2
