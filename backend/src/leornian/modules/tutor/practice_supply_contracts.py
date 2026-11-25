"""Requests for the existing ItemBank supply task, never model-authored questions."""

from typing import Literal
from uuid import UUID

from leornian.modules.execution.contracts import ProgramEnvironment
from leornian.modules.item_bank.contracts import ResponsePracticeFormats
from leornian.shared_kernel.contracts import Contract
from pydantic import Field, model_validator


class RequestPracticeSupply(Contract):
    command_key: str = Field(min_length=8, max_length=128)
    kind: Literal["choice", "python_io", "response"]
    instruction: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    response_formats: ResponsePracticeFormats | None = None

    @model_validator(mode="after")
    def exact_format_request(self):
        if (self.kind == "response") != (self.response_formats is not None):
            raise ValueError("Response supply needs exact formats for both ordinary slots.")
        return self


class ReadPracticeSupply(Contract):
    task_id: UUID


class RequestProgramSupply(Contract):
    command_key: str = Field(min_length=8, max_length=128)
    kind: Literal["sql_query", "python_project", "project_stdio", "web_project", "http_project"]
    instruction: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    program_environment: ProgramEnvironment

    @model_validator(mode="after")
    def matching_environment(self):
        expected = {
            "sql_query": "sql-query.v1", "python_project": "python-project-io.v1",
            "project_stdio": "project-stdio.v1", "web_project": "web-check.v1",
            "http_project": "project-http.v1",
        }[self.kind]
        if self.program_environment.profile != expected:
            raise ValueError("Program kind must match the exact local execution environment.")
        return self


class QueuedPracticeSupply(Contract):
    status: Literal["accepted"] = "accepted"
    task_id: UUID
    pack_id: UUID
    message: str


class PracticeSupplyStatus(Contract):
    status: Literal["completed"] = "completed"
    task_id: UUID
    pack_id: UUID
    kind: Literal["choice", "python_io", "response"]
    supply_status: Literal["running", "waiting", "completed", "cancelled"]
    action: str
    reason: str | None = None
    pack_status: str
    revision: int = Field(ge=1)
    response_formats: ResponsePracticeFormats | None = None
    next_action: str


class ProgramSupplyStatus(PracticeSupplyStatus):
    kind: Literal["sql_query", "python_project", "project_stdio", "web_project", "http_project"]
    program_environment: ProgramEnvironment
