from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from leornian.modules.execution.contracts import (
    CaseOutput,
    HttpScenarioResult,
    ProgramEnvironment,
    SqlTableResult,
    WebCheckResult,
)
from leornian.modules.item_bank.contracts import ProgramAnswer
from leornian.shared_kernel.contracts import Contract
from pydantic import Field, model_serializer, model_validator


class ProgramPracticeSubmission(Contract):
    slot: Literal["practice_1", "practice_2", "remediation_1"]
    answer: ProgramAnswer
    previous_attempt_id: UUID | None = None
    retry: bool = False


class ProgramGateAnswer(Contract):
    slot: Literal["assessment_1", "assessment_2"]
    answer: ProgramAnswer


class ProgramGateSubmission(Contract):
    programs: list[ProgramGateAnswer] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def both_slots(self):
        if {value.slot for value in self.programs} != {"assessment_1", "assessment_2"}:
            raise ValueError("Submit both reserved program answers together, exactly once.")
        return self


class ProgramTransferSubmission(Contract):
    answer: ProgramAnswer


class ProgramSampleResult(Contract):
    profile: Literal["program-public-sample.v1"] = "program-public-sample.v1"
    outcome: Literal["completed", "timeout", "output_limit", "infrastructure_error"]
    exit_code: int | None
    output: (
        SqlTableResult | WebCheckResult | HttpScenarioResult
        | Annotated[int, Field(strict=True)] | None
    )
    integer_text: str | None = Field(default=None, max_length=4096, pattern=r"^-?(0|[1-9][0-9]*)$")
    text_output: str | None = Field(
        default=None, max_length=4096, exclude_if=lambda value: value is None,
    )

    @model_serializer(mode="wrap")
    def exact_integer(self, handler):
        data = handler(self)
        if self.integer_text is None:
            if type(self.output) is int:
                data["integer_text"] = str(self.output)
            else:
                data.pop("integer_text", None)
        return data


class ProgramPracticeAttempt(Contract):
    id: UUID
    pack_id: UUID
    slot: Literal["practice_1", "practice_2", "remediation_1"]
    environment: ProgramEnvironment
    comparison_profile: Literal[
        "sql-result-typed.v1", "python-project-io-result.v1", "stdio-text.v1", "web-check.v1",
        "http-response.v1",
    ]
    comparison_order: Literal["ordered", "multiset"] | None
    answer: ProgramAnswer
    status: Literal["queued", "passed", "not_passed", "error"]
    passed_cases: int = Field(ge=0, le=3)
    feedback: str | None
    error_code: str | None
    attempt_number: int = Field(ge=1)
    previous_attempt_id: UUID | None
    retry_requested: bool
    created_at: datetime
    completed_at: datetime | None
    sample_result: ProgramSampleResult | None = None
    compilation: CaseOutput | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class ProgramPracticeHistory(Contract):
    latest_attempt_id: UUID | None
    attempts: list[ProgramPracticeAttempt]
    next_before: UUID | None = None


class ProgramTransferAttempt(ProgramPracticeAttempt):
    slot: Literal["practice_1", "practice_2"]


class ProgramReceipt(Contract):
    attempt_id: UUID
    answer: ProgramAnswer
    correct: bool | None
    passed_cases: int = Field(ge=0, le=3)
    explanation: str
