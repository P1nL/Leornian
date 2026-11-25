from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from leornian.modules.execution.environment_contracts import (
    EnvironmentRequirement as EnvironmentRequirement,
)
from leornian.modules.execution.environment_contracts import (
    RecipeId as RecipeId,
)
from leornian.modules.execution.program_contracts import (
    ExecutionProgram as ExecutionProgram,
)
from leornian.modules.execution.program_contracts import (
    HttpDatabase as HttpDatabase,
)
from leornian.modules.execution.program_contracts import (
    HttpEnvironment as HttpEnvironment,
)
from leornian.modules.execution.program_contracts import (
    HttpProgram as HttpProgram,
)
from leornian.modules.execution.program_contracts import (
    HttpRequest as HttpRequest,
)
from leornian.modules.execution.program_contracts import (
    HttpResponse as HttpResponse,
)
from leornian.modules.execution.program_contracts import (
    HttpScenario as HttpScenario,
)
from leornian.modules.execution.program_contracts import (
    HttpScenarioResult as HttpScenarioResult,
)
from leornian.modules.execution.program_contracts import (
    ProgramEnvironment as ProgramEnvironment,
)
from leornian.modules.execution.program_contracts import (
    ProgramFile as ProgramFile,
)
from leornian.modules.execution.program_contracts import (
    ProjectEnvironment as ProjectEnvironment,
)
from leornian.modules.execution.program_contracts import (
    ProjectLanguage as ProjectLanguage,
)
from leornian.modules.execution.program_contracts import (
    ProjectProgram as ProjectProgram,
)
from leornian.modules.execution.program_contracts import (
    PythonProjectEnvironment as PythonProjectEnvironment,
)
from leornian.modules.execution.program_contracts import (
    PythonProjectProgram as PythonProjectProgram,
)
from leornian.modules.execution.program_contracts import (
    SqlColumn as SqlColumn,
)
from leornian.modules.execution.program_contracts import (
    SqlDataset as SqlDataset,
)
from leornian.modules.execution.program_contracts import (
    SqlEnvironment as SqlEnvironment,
)
from leornian.modules.execution.program_contracts import (
    SqlForeignKey as SqlForeignKey,
)
from leornian.modules.execution.program_contracts import (
    SqlProgram as SqlProgram,
)
from leornian.modules.execution.program_contracts import (
    SqlSchema as SqlSchema,
)
from leornian.modules.execution.program_contracts import (
    SqlTable as SqlTable,
)
from leornian.modules.execution.program_contracts import (
    SqlTableResult as SqlTableResult,
)
from leornian.modules.execution.program_contracts import (
    WebCheck as WebCheck,
)
from leornian.modules.execution.program_contracts import (
    WebCheckResult as WebCheckResult,
)
from leornian.modules.execution.program_contracts import (
    WebEnvironment as WebEnvironment,
)
from leornian.modules.execution.program_contracts import (
    WebProgram as WebProgram,
)
from leornian.shared_kernel.contracts import Contract


class RunnerClaim(Contract):
    runner_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    program_environments: list[ProgramEnvironment] = Field(default_factory=list, max_length=64)
    example_terminal: bool = Field(default=False, strict=True)


class ExecutionClaim(Contract):
    job_id: UUID
    claim_token: UUID
    code: str
    inputs: list[list[int]]


class ProgramExecutionClaim(Contract):
    job_id: UUID
    claim_token: UUID
    program: ExecutionProgram
    interactive: Literal[True] | None = Field(default=None, exclude_if=lambda value: value is None)


class ExecutionVerificationInput(Contract):
    claim_token: UUID


class CaseOutput(Contract):
    exit_code: int | None
    stdout: str = Field(max_length=4096)
    stderr: str = Field(max_length=4096)
    outcome: Literal["completed", "timeout", "output_limit", "infrastructure_error"]


class RunnerReport(Contract):
    claim_token: UUID
    cases: list[CaseOutput] = Field(min_length=0, max_length=3)
    compilation: CaseOutput | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def completed_work(self):
        if not self.cases and (
            self.compilation is None
            or self.compilation.outcome == "completed" and self.compilation.exit_code == 0
        ):
            raise ValueError("An empty run requires its distinct failed compilation receipt.")
        return self
