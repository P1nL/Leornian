from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from leornian.modules.assessment.assistance_contracts import PracticeAssistanceReceipt
from leornian.modules.assessment.evidence_contracts import OwnedEvidence
from leornian.modules.assessment.gate_contracts import ConceptCompletion
from leornian.modules.assessment.hint_contracts import GraduatedHint, PracticeHintReceipt
from leornian.modules.assessment.program_contracts import (
    ProgramPracticeAttempt,
    ProgramPracticeHistory,
)
from leornian.modules.item_bank.contracts import ReferenceFinding, ResponseValue
from leornian.shared_kernel.contracts import Contract

__all__ = [
    "Attempt", "Submission", "AssessmentResult", "ConceptCompletion", "PythonAttempt",
    "PythonPracticeAttempt", "PythonPracticeHistory", "ResponseResult",
    "ProgramPracticeAttempt", "ProgramPracticeHistory", "PracticeAssistanceReceipt",
    "GraduatedHint", "PracticeHintReceipt", "OwnedEvidence",
]


class Submission(Contract):
    code: str = Field(min_length=1, max_length=12000)

    @field_validator("code")
    @classmethod
    def byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 12000:
            raise ValueError("Code exceeds 12000 bytes")
        return value


class Attempt(Contract):
    id: UUID
    track_id: UUID
    item_version: str
    status: Literal["queued", "passed", "not_passed", "error"]
    feedback: str | None
    passed_cases: int | None
    total_cases: int
    created_at: datetime
    completed_at: datetime | None


class AssessmentResult(Contract):
    passed: bool
    passed_cases: int
    feedback: str


class PythonCompletion(Contract):
    gate_id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: str
    policy_version: Literal["python-io-gate.v1"] = "python-io-gate.v1"


class ProgramCompletion(Contract):
    gate_id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: str
    policy_version: Literal["program-execution-gate.v1"] = "program-execution-gate.v1"


class PythonAttempt(Contract):
    id: UUID
    pack_id: UUID
    slot: str
    gate_id: UUID | None
    transfer_id: UUID | None
    code: str
    status: Literal["queued", "passed", "not_passed", "error"]
    passed_cases: int
    total_cases: Literal[3] = 3
    feedback: str | None
    created_at: datetime
    completed_at: datetime | None


class PythonPracticeAttempt(PythonAttempt):
    policy_version: Literal["python-io-attempt.v1", "python-practice.v2"]
    attempt_number: int = Field(ge=1)
    previous_attempt_id: UUID | None
    retry_requested: bool


class PythonPracticeHistory(Contract):
    items: list[PythonPracticeAttempt]
    latest_attempt_id: UUID | None
    next_before: UUID | None = None


class ResponseResult(Contract):
    id: UUID
    pack_id: UUID
    slot: str
    response: ResponseValue
    correct: bool | None
    profile_version: Literal[
        "knowledge-multiple.v1", "knowledge-prediction.v1", "knowledge-order.v1",
        "knowledge-line-location.v1", "knowledge-reference.v1",
    ]
    explanation: str
    reference: ResponseValue
    findings: list[ReferenceFinding]
    created_at: datetime
