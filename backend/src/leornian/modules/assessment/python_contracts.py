from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from leornian.modules.assessment.contracts import Submission
from leornian.shared_kernel.contracts import Contract


class PythonTraining(Submission):
    slot: Literal["practice_1", "practice_2", "remediation_1"]


class GateProgram(Submission):
    slot: Literal["assessment_1", "assessment_2"]


class PythonGateSubmission(Contract):
    programs: list[GateProgram] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def both_slots(self):
        if {item.slot for item in self.programs} != {"assessment_1", "assessment_2"}:
            raise ValueError("Submit both programs together, exactly once.")
        return self


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


class PythonReceipt(Contract):
    attempt_id: UUID
    code: str
    correct: bool
    passed_cases: int
    explanation: str
