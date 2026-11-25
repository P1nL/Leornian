from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from leornian.modules.assessment.contracts import PythonAttempt as PythonAttempt
from leornian.modules.assessment.contracts import PythonPracticeAttempt as PythonPracticeAttempt
from leornian.modules.assessment.contracts import PythonPracticeHistory as PythonPracticeHistory
from leornian.modules.assessment.contracts import Submission
from leornian.shared_kernel.contracts import Contract


class PythonTraining(Submission):
    slot: Literal["practice_1", "practice_2", "remediation_1"]


class PythonPracticeSubmission(PythonTraining):
    previous_attempt_id: UUID | None = None
    retry: bool = False


class GateProgram(Submission):
    slot: Literal["assessment_1", "assessment_2"]


class PythonGateSubmission(Contract):
    programs: list[GateProgram] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def both_slots(self):
        if {item.slot for item in self.programs} != {"assessment_1", "assessment_2"}:
            raise ValueError("Submit both programs together, exactly once.")
        return self


class PythonReceipt(Contract):
    attempt_id: UUID
    code: str
    correct: bool
    passed_cases: int
    explanation: str
