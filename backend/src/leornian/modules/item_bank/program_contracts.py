import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from leornian.modules.execution.contracts import (
    HttpDatabase,
    HttpEnvironment,
    HttpProgram,
    HttpResponse,
    HttpScenario,
    HttpScenarioResult,
    ProgramFile,
    ProjectEnvironment,
    ProjectProgram,
    PythonProjectEnvironment,
    PythonProjectProgram,
    SqlDataset,
    SqlEnvironment,
    SqlProgram,
    SqlSchema,
    SqlTableResult,
    WebCheck,
    WebCheckResult,
    WebEnvironment,
    WebProgram,
)
from leornian.modules.item_bank.generation_contracts import SupplyStageOutput
from leornian.modules.item_bank.python_contracts import PythonCase
from leornian.modules.item_bank.supply_contracts import SLOTS, Slot
from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.learning.contracts import MaterialCitation
from leornian.shared_kernel.contracts import Contract


class SqlAnswer(Contract):
    type: Literal["sql"] = "sql"
    query: str = Field(min_length=1, max_length=12000)

    @model_validator(mode="after")
    def bounded_query(self):
        if "\x00" in self.query or len(self.query.encode("utf-8")) > 12000:
            raise ValueError("SQL query must fit 12000 UTF-8 bytes without NUL.")
        return self


class ProjectAnswer(Contract):
    type: Literal["project"] = "project"
    files: list[ProgramFile] = Field(min_length=2, max_length=20)


class StdioAnswer(Contract):
    type: Literal["stdio"] = "stdio"
    files: list[ProgramFile] = Field(min_length=1, max_length=32)


class WebAnswer(Contract):
    type: Literal["web"] = "web"
    files: list[ProgramFile] = Field(min_length=1, max_length=32)


class HttpAnswer(Contract):
    type: Literal["http"] = "http"
    files: list[ProgramFile] = Field(min_length=1, max_length=32)


ProgramAnswer = Annotated[
    SqlAnswer | ProjectAnswer | StdioAnswer | WebAnswer | HttpAnswer, Field(discriminator="type"),
]


class ProgramQuestion(Contract):
    slot: Slot
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=1800)
    difficulty: int = Field(ge=1, le=5)
    source_refs: list[SourceRef] = Field(max_length=3)
    material_citations: list[MaterialCitation] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def cited(self):
        if not self.source_refs and not self.material_citations:
            raise ValueError("A program question needs an exact supplied citation.")
        return self


class SqlCase(Contract):
    dataset: SqlDataset
    expected: SqlTableResult

    @model_validator(mode="after")
    def returnable_result(self):
        encoded = json.dumps(self.expected.model_dump(mode="json"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) >= 4095:
            raise ValueError("A private SQL result must fit the actual Runner output limit.")
        return self


class SqlQuestion(ProgramQuestion):
    language: Literal["sql_query"] = "sql_query"
    environment: SqlEnvironment
    schema_definition: SqlSchema
    starter_query: str = Field(min_length=1, max_length=2000)
    comparison: Literal["ordered", "multiset"]
    comparison_profile: Literal["sql-result-typed.v1"] = "sql-result-typed.v1"
    sample: SqlCase

    @model_validator(mode="after")
    def valid_sample(self):
        SqlProgram(
            **self.environment.model_dump(),
            query=self.starter_query, schema_definition=self.schema_definition,
            datasets=[self.sample.dataset],
        )
        return self

    def normalize_answer(self, answer):
        if not isinstance(answer, SqlAnswer):
            raise ValueError("This exact question requires an SQL answer.")
        return answer


class SqlItem(SqlQuestion):
    tests: list[SqlCase] = Field(min_length=3, max_length=3)
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def bound_tests(self):
        identities = [case.dataset.model_dump() for case in self.tests]
        if self.sample not in self.tests or any(
            a == b for i, a in enumerate(identities) for b in identities[i + 1:]
        ):
            raise ValueError("Three distinct datasets must include the exact public sample.")
        self.execution(SqlAnswer(query=self.starter_query))
        return self

    def public(self):
        return SqlQuestion(**self.model_dump(exclude={"tests", "explanation"}))

    def execution(self, answer, *, sample_only=False):
        answer = self.normalize_answer(answer)
        return SqlProgram(
            **self.environment.model_dump(),
            query=answer.query, schema_definition=self.schema_definition,
            datasets=[case.dataset for case in ([self.sample] if sample_only else self.tests)],
        )


class ProjectQuestion(ProgramQuestion):
    language: Literal["python_project"] = "python_project"
    environment: PythonProjectEnvironment
    files: list[ProgramFile] = Field(min_length=2, max_length=20)
    entrypoint: str = Field(min_length=1, max_length=160)
    sample: PythonCase
    comparison_profile: Literal["python-project-io-result.v1"] = "python-project-io-result.v1"

    @model_validator(mode="after")
    def valid_project(self):
        if not any(not item.read_only for item in self.files):
            raise ValueError("A project exercise needs an editable declared file.")
        PythonProjectProgram(
            **self.environment.model_dump(), files=self.files,
            entrypoint=self.entrypoint, inputs=[self.sample.input],
        )
        return self

    def normalize_answer(self, answer):
        if not isinstance(answer, ProjectAnswer):
            raise ValueError("This exact question requires a project answer.")
        edits = {file.path: file for file in answer.files}
        if len(edits) != len(answer.files) or set(edits) != {file.path for file in self.files}:
            raise ValueError("A submission must preserve the exact declared file manifest.")
        for file in self.files:
            value = edits[file.path]
            if (
                file.read_only != value.read_only
                or file.read_only and file.content != value.content
            ):
                raise ValueError("Read-only file identity and contents cannot change.")
        normalized = ProjectAnswer(files=[edits[file.path] for file in self.files])
        PythonProjectProgram(
            **self.environment.model_dump(), files=normalized.files,
            entrypoint=self.entrypoint, inputs=[self.sample.input],
        )
        return normalized


class ProjectItem(ProjectQuestion):
    tests: list[PythonCase] = Field(min_length=3, max_length=3)
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def bound_tests(self):
        if len({tuple(case.input) for case in self.tests}) != 3 or self.sample not in self.tests:
            raise ValueError("Three distinct inputs must include the exact public sample.")
        return self

    def public(self):
        return ProjectQuestion(**self.model_dump(exclude={"tests", "explanation"}))

    def execution(self, answer, *, sample_only=False):
        answer = self.normalize_answer(answer)
        return PythonProjectProgram(
            **self.environment.model_dump(), files=answer.files, entrypoint=self.entrypoint,
            inputs=[self.sample.input] if sample_only else [case.input for case in self.tests],
        )


def normalize_manifest(declared, submitted):
    edits = {file.path: file for file in submitted}
    if len(edits) != len(submitted) or set(edits) != {file.path for file in declared}:
        raise ValueError("A submission must preserve the exact declared file manifest.")
    for file in declared:
        value = edits[file.path]
        if (
            file.read_only != value.read_only
            or file.read_only and file.content != value.content
        ):
            raise ValueError("Read-only file identity and contents cannot change.")
    return [edits[file.path] for file in declared]


class StdioCase(Contract):
    input: str = Field(max_length=8192)
    expected: str = Field(max_length=4000)

    @model_validator(mode="after")
    def returnable_output(self):
        if "\x00" in self.expected or len(self.expected.encode("utf-8")) >= 4095:
            raise ValueError("Expected output must fit the actual Runner UTF-8 output limit.")
        return self


class StdioQuestion(ProgramQuestion):
    language: Literal["project_stdio"] = "project_stdio"
    environment: ProjectEnvironment
    files: list[ProgramFile] = Field(min_length=1, max_length=32)
    entrypoint: str = Field(min_length=1, max_length=160)
    sample: StdioCase
    comparison_profile: Literal["stdio-text.v1"] = "stdio-text.v1"

    @model_validator(mode="after")
    def valid_project(self):
        if not any(not item.read_only for item in self.files):
            raise ValueError("A project exercise needs an editable declared file.")
        ProjectProgram(
            **self.environment.model_dump(), files=self.files,
            entrypoint=self.entrypoint, inputs=[self.sample.input],
        )
        return self

    def normalize_answer(self, answer):
        if not isinstance(answer, StdioAnswer):
            raise ValueError("This exact question requires a stdio project answer.")
        normalized = StdioAnswer(files=normalize_manifest(self.files, answer.files))
        ProjectProgram(
            **self.environment.model_dump(), files=normalized.files,
            entrypoint=self.entrypoint, inputs=[self.sample.input],
        )
        return normalized


class StdioItem(StdioQuestion):
    tests: list[StdioCase] = Field(min_length=3, max_length=3)
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def bound_tests(self):
        if len({case.input for case in self.tests}) != 3 or self.sample not in self.tests:
            raise ValueError("Three distinct stdin cases must include the exact public sample.")
        return self

    def public(self):
        return StdioQuestion(**self.model_dump(exclude={"tests", "explanation"}))

    def execution(self, answer, *, sample_only=False):
        answer = self.normalize_answer(answer)
        return ProjectProgram(
            **self.environment.model_dump(), files=answer.files,
            entrypoint=self.entrypoint,
            inputs=[self.sample.input] if sample_only else [case.input for case in self.tests],
        )


class WebCase(Contract):
    check: WebCheck
    expected: str | Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def typed_expectation(self):
        if (
            self.check.kind == "exists" and type(self.expected) is not bool
            or self.check.kind != "exists" and not isinstance(self.expected, str)
            or isinstance(self.expected, str) and len(self.expected) > 500
        ):
            raise ValueError("Web expectations must match the exact check operation and bound.")
        return self


class WebQuestion(ProgramQuestion):
    language: Literal["web_project"] = "web_project"
    environment: WebEnvironment
    files: list[ProgramFile] = Field(min_length=1, max_length=32)
    entrypoint: str = Field(min_length=1, max_length=160)
    sample: WebCase
    comparison_profile: Literal["web-check.v1"] = "web-check.v1"

    @model_validator(mode="after")
    def valid_project(self):
        if not any(not item.read_only for item in self.files):
            raise ValueError("A web exercise needs an editable declared file.")
        WebProgram(
            **self.environment.model_dump(), files=self.files,
            entrypoint=self.entrypoint, checks=[self.sample.check],
        )
        return self

    def normalize_answer(self, answer):
        if not isinstance(answer, WebAnswer):
            raise ValueError("This exact question requires a web project answer.")
        normalized = WebAnswer(files=normalize_manifest(self.files, answer.files))
        WebProgram(
            **self.environment.model_dump(), files=normalized.files,
            entrypoint=self.entrypoint, checks=[self.sample.check],
        )
        return normalized


class WebItem(WebQuestion):
    tests: list[WebCase] = Field(min_length=3, max_length=3)
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def bound_tests(self):
        if len({case.check.key for case in self.tests}) != 3 or self.sample not in self.tests:
            raise ValueError("Three distinct web checks must include the exact public sample.")
        # The trusted browser returns one bounded document covering the complete check set.
        result = WebCheckResult(
            results=[{"key": case.check.key, "actual": case.expected} for case in self.tests],
        )
        if len(result.model_dump_json().encode("utf-8")) >= 4095:
            raise ValueError("Expected web observations must fit the Runner output limit.")
        return self

    def public(self):
        return WebQuestion(**self.model_dump(exclude={"tests", "explanation"}))

    def execution(self, answer, *, sample_only=False):
        answer = self.normalize_answer(answer)
        return WebProgram(
            **self.environment.model_dump(), files=answer.files,
            entrypoint=self.entrypoint,
            checks=[self.sample.check] if sample_only else [case.check for case in self.tests],
        )


class HttpCase(Contract):
    scenario: HttpScenario
    expected: list[HttpResponse] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def bounded_responses(self):
        result = HttpScenarioResult(responses=self.expected)
        if len(self.expected) != len(self.scenario.requests) or len(
            result.model_dump_json().encode("utf-8")
        ) >= 4095:
            raise ValueError("Expected HTTP responses must cover each request and fit 4094 bytes.")
        return self


class HttpQuestion(ProgramQuestion):
    language: Literal["http_project"] = "http_project"
    environment: HttpEnvironment
    files: list[ProgramFile] = Field(min_length=1, max_length=32)
    entrypoint: str = Field(min_length=1, max_length=160)
    database: HttpDatabase | None = None
    sample: HttpCase
    comparison_profile: Literal["http-response.v1"] = "http-response.v1"

    @model_validator(mode="after")
    def valid_project(self):
        if not any(not item.read_only for item in self.files):
            raise ValueError("An HTTP project needs an editable declared source file.")
        HttpProgram(
            **self.environment.model_dump(), files=self.files, entrypoint=self.entrypoint,
            database=self.database, scenarios=[self.sample.scenario],
        )
        return self

    def normalize_answer(self, answer):
        if not isinstance(answer, HttpAnswer):
            raise ValueError("This question requires an HTTP project answer.")
        normalized = HttpAnswer(files=normalize_manifest(self.files, answer.files))
        HttpProgram(
            **self.environment.model_dump(), files=normalized.files, entrypoint=self.entrypoint,
            database=self.database, scenarios=[self.sample.scenario],
        )
        return normalized


class HttpItem(HttpQuestion):
    tests: list[HttpCase] = Field(min_length=3, max_length=3)
    explanation: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def bound_tests(self):
        identities = [case.scenario.model_dump_json() for case in self.tests]
        if len(set(identities)) != 3 or self.sample not in self.tests:
            raise ValueError("Three distinct HTTP scenarios must include the exact public sample.")
        self.execution(HttpAnswer(files=self.files))
        return self

    def public(self):
        return HttpQuestion(**self.model_dump(exclude={"tests", "explanation"}))

    def execution(self, answer, *, sample_only=False):
        answer = self.normalize_answer(answer)
        return HttpProgram(
            **self.environment.model_dump(), files=answer.files, entrypoint=self.entrypoint,
            database=self.database,
            scenarios=[case.scenario for case in ([self.sample] if sample_only else self.tests)],
        )


def complete_slots(items):
    if len(items) != 5 or {item.slot for item in items} != set(SLOTS):
        raise ValueError("Every original five-slot supply stage is required.")
    if len({"".join(item.prompt.split()).casefold() for item in items}) != 5:
        raise ValueError("Five independent contextual decisions are required.")


class SqlPack(SupplyStageOutput):
    items: list[SqlItem] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        complete_slots(self.items)
        return self


class ProjectPack(SupplyStageOutput):
    items: list[ProjectItem] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        complete_slots(self.items)
        return self


class StdioPack(SupplyStageOutput):
    items: list[StdioItem] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        complete_slots(self.items)
        return self


class WebPack(SupplyStageOutput):
    items: list[WebItem] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        complete_slots(self.items)
        return self


class HttpPack(SupplyStageOutput):
    items: list[HttpItem] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        complete_slots(self.items)
        return self


class BlindSqlProgram(Contract):
    slot: Slot
    answer: SqlAnswer


class BlindProjectProgram(Contract):
    slot: Slot
    answer: ProjectAnswer


class BlindStdioProgram(Contract):
    slot: Slot
    answer: StdioAnswer


class BlindWebProgram(Contract):
    slot: Slot
    answer: WebAnswer


class BlindHttpProgram(Contract):
    slot: Slot
    answer: HttpAnswer


class BlindSqlPrograms(SupplyStageOutput):
    programs: list[BlindSqlProgram] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        if {value.slot for value in self.programs} != set(SLOTS):
            raise ValueError("Independently solve all five public SQL tasks exactly once.")
        return self


class BlindProjectPrograms(SupplyStageOutput):
    programs: list[BlindProjectProgram] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        if {value.slot for value in self.programs} != set(SLOTS):
            raise ValueError("Independently solve all five public projects exactly once.")
        return self


class BlindStdioPrograms(SupplyStageOutput):
    programs: list[BlindStdioProgram] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        if {value.slot for value in self.programs} != set(SLOTS):
            raise ValueError("Independently solve all five public stdio tasks exactly once.")
        return self


class BlindWebPrograms(SupplyStageOutput):
    programs: list[BlindWebProgram] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        if {value.slot for value in self.programs} != set(SLOTS):
            raise ValueError("Independently solve all five public web tasks exactly once.")
        return self


class BlindHttpPrograms(SupplyStageOutput):
    programs: list[BlindHttpProgram] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete(self):
        if {value.slot for value in self.programs} != set(SLOTS):
            raise ValueError("Independently solve all five public HTTP projects exactly once.")
        return self


PublicProgramQuestion = Annotated[
    SqlQuestion | ProjectQuestion | StdioQuestion | WebQuestion | HttpQuestion,
    Field(discriminator="language"),
]
