from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.shared_kernel.contracts import Contract


class RunnerClaim(Contract):
    runner_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")


class ExecutionClaim(Contract):
    job_id: UUID
    claim_token: UUID
    code: str
    inputs: list[list[int]]


class CaseOutput(Contract):
    exit_code: int | None
    stdout: str = Field(max_length=4096)
    stderr: str = Field(max_length=4096)
    outcome: Literal["completed", "timeout", "output_limit", "infrastructure_error"]


class RunnerReport(Contract):
    claim_token: UUID
    cases: list[CaseOutput] = Field(min_length=1, max_length=3)
