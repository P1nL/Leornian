"""Closed local execution inputs. Expected answers and business authority stay outside."""

import math
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from leornian.shared_kernel.contracts import Contract
from pydantic import Field, StringConstraints, field_validator, model_validator

Identifier = Annotated[str, StringConstraints(
    min_length=1, max_length=63, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
)]
RelativeFile = Annotated[str, StringConstraints(
    min_length=1, max_length=160,
    pattern=r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_-]+$",
)]
SqlValue = Annotated[str, StringConstraints(max_length=500)] | Annotated[
    int, Field(strict=True, ge=-1_000_000_000, le=1_000_000_000)
] | Annotated[float, Field(strict=True, allow_inf_nan=False)] | Annotated[
    bool, Field(strict=True)
] | None
RuntimeVersion = Annotated[str, StringConstraints(
    min_length=1, max_length=60, pattern=r"^[0-9]+(?:\.[0-9]+){1,3}$",
)]


class SqlEnvironment(Contract):
    profile: Literal["sql-query.v1"] = "sql-query.v1"
    dialect: Literal["sqlite", "postgresql", "mysql"]
    runtime_version: RuntimeVersion
    environment_release_id: UUID | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class PythonProjectEnvironment(Contract):
    profile: Literal["python-project-io.v1"] = "python-project-io.v1"
    runtime_version: RuntimeVersion


ProjectLanguage = Literal["python", "javascript", "typescript", "java", "go", "csharp"]


class ProjectEnvironment(Contract):
    profile: Literal["project-stdio.v1"] = "project-stdio.v1"
    language: ProjectLanguage
    runtime_version: RuntimeVersion
    environment_release_id: UUID


class WebEnvironment(Contract):
    profile: Literal["web-check.v1"] = "web-check.v1"
    language: Literal["html-css", "javascript", "typescript"] = "html-css"
    runtime_version: RuntimeVersion
    environment_release_id: UUID


class HttpEnvironment(Contract):
    profile: Literal["project-http.v1"] = "project-http.v1"
    language: ProjectLanguage
    runtime_version: RuntimeVersion
    environment_release_id: UUID


ProgramEnvironment = Annotated[
    SqlEnvironment | PythonProjectEnvironment | ProjectEnvironment
    | WebEnvironment | HttpEnvironment,
    Field(discriminator="profile"),
]


class SqlTableResult(Contract):
    profile: Literal["sql-table.v1"] = "sql-table.v1"
    columns: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] = Field(
        min_length=1, max_length=12,
    )
    rows: list[list[Annotated[str, StringConstraints(max_length=500)] | None]] = Field(
        max_length=100,
    )
    types: list[list[Literal["integer", "number", "text", "boolean", "null"]]] = Field(
        max_length=100,
    )

    @model_validator(mode="after")
    def exact_cells(self):
        if len(self.rows) != len(self.types):
            raise ValueError("SQL values and their actual cell kinds must have equal shape.")
        for row, kinds in zip(self.rows, self.types, strict=True):
            if len(row) != len(self.columns) or len(kinds) != len(row):
                raise ValueError("Every SQL row must cover the exact result columns.")
            for value, kind in zip(row, kinds, strict=True):
                if (value is None) != (kind == "null"):
                    raise ValueError("NULL is distinct from every textual or numeric value.")
                if kind in {"integer", "number"}:
                    try:
                        number = Decimal(value)
                        normalized = format(number, "f")
                        if "." in normalized:
                            normalized = normalized.rstrip("0").rstrip(".")
                        if number == 0:
                            normalized = "0"
                        if (
                            not number.is_finite() or normalized != value
                            or kind == "integer" and number != number.to_integral_value()
                        ):
                            raise ValueError("SQL numeric cells must use canonical finite text.")
                    except (InvalidOperation, TypeError):
                        raise ValueError("SQL numeric cells need finite numeric text.") from None
                if kind == "boolean" and value not in {"true", "false"}:
                    raise ValueError("SQL booleans need their explicit kind and canonical value.")
        return self


class SqlColumn(Contract):
    name: Identifier
    type: Literal["integer", "text", "real", "boolean"]
    nullable: bool = True
    primary_key: bool = False


class SqlForeignKey(Contract):
    column: Identifier
    references_table: Identifier
    references_column: Identifier


class SqlTable(Contract):
    name: Identifier
    columns: list[SqlColumn] = Field(min_length=1, max_length=12)
    foreign_keys: list[SqlForeignKey] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def distinct_columns(self):
        names = [c.name for c in self.columns]
        if (
            len(names) != len({name.lower() for name in names})
            or sum(c.primary_key for c in self.columns) > 1
        ):
            raise ValueError("Columns must be distinct with at most one primary key.")
        if any(f.column not in names for f in self.foreign_keys):
            raise ValueError("A foreign key must identify a declared source column.")
        return self


class SqlSchema(Contract):
    tables: list[SqlTable] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def exact_references(self):
        tables = {table.name: table for table in self.tables}
        if len({name.lower() for name in tables}) != len(self.tables):
            raise ValueError("SQL table identities must be distinct.")
        for table in self.tables:
            for key in table.foreign_keys:
                target = tables.get(key.references_table)
                target_column = next(
                    (c for c in target.columns if c.name == key.references_column), None,
                ) if target else None
                source_column = next(c for c in table.columns if c.name == key.column)
                if (
                    target_column is None or not target_column.primary_key
                    or source_column.type != target_column.type
                ):
                    raise ValueError("A foreign key must identify an exact declared target.")
        return self


class SqlDataset(Contract):
    rows: dict[Identifier, list[list[SqlValue]]] = Field(max_length=8)


class SqlProgram(Contract):
    profile: Literal["sql-query.v1"] = "sql-query.v1"
    dialect: Literal["sqlite", "postgresql", "mysql"]
    runtime_version: RuntimeVersion | None = None
    environment_release_id: UUID | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    query: str = Field(min_length=1, max_length=12000)
    schema_definition: SqlSchema
    datasets: list[SqlDataset] = Field(min_length=1, max_length=3)

    @field_validator("query")
    @classmethod
    def query_bytes(cls, value):
        if "\x00" in value or len(value.encode("utf-8")) > 12000:
            raise ValueError("Query must contain no NUL and fit 12000 UTF-8 bytes.")
        return value

    @model_validator(mode="after")
    def typed_datasets(self):
        tables = {t.name: t for t in self.schema_definition.tables}
        for dataset in self.datasets:
            if set(dataset.rows) != set(tables):
                raise ValueError("Every dataset must exactly cover its declared SQL tables.")
            if sum(len(rows) for rows in dataset.rows.values()) > 100:
                raise ValueError("An SQL dataset permits at most 100 rows.")
            for name, rows in dataset.rows.items():
                columns = tables[name].columns
                for row in rows:
                    if len(row) != len(columns):
                        raise ValueError("A dataset row must cover its declared columns.")
                    for cell, column in zip(row, columns, strict=True):
                        if cell is None:
                            if not column.nullable or column.primary_key:
                                raise ValueError("A required SQL cell cannot be NULL.")
                            continue
                        kind = column.type
                        valid = (
                            kind == "integer" and type(cell) is int
                            or kind == "real" and type(cell) in (int, float)
                            or kind == "text" and isinstance(cell, str) and "\x00" not in cell
                            or kind == "boolean" and type(cell) is bool
                        )
                        if not valid or isinstance(cell, float) and not math.isfinite(cell):
                            raise ValueError("A dataset cell must match its declared SQL type.")
            for table in tables.values():
                for index, column in enumerate(table.columns):
                    if column.primary_key:
                        values = [row[index] for row in dataset.rows[table.name]]
                        if len(values) != len(set(values)):
                            raise ValueError("Primary key values must be distinct.")
                for key in table.foreign_keys:
                    source_index = next(
                        i for i, c in enumerate(table.columns) if c.name == key.column
                    )
                    target_index = next(
                        i for i, c in enumerate(tables[key.references_table].columns)
                        if c.name == key.references_column
                    )
                    targets = {
                        row[target_index] for row in dataset.rows[key.references_table]
                    }
                    if any(
                        row[source_index] is not None and row[source_index] not in targets
                        for row in dataset.rows[table.name]
                    ):
                        raise ValueError("A dataset foreign key must refer to an existing row.")
        return self


class ProgramFile(Contract):
    path: RelativeFile
    content: str = Field(max_length=100000)
    read_only: bool = False

    @field_validator("path")
    @classmethod
    def safe_path(cls, value):
        if any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("Program files need canonical paths without dot segments.")
        return value


class PythonProjectProgram(Contract):
    profile: Literal["python-project-io.v1"] = "python-project-io.v1"
    runtime_version: RuntimeVersion | None = None
    files: list[ProgramFile] = Field(min_length=2, max_length=20)
    entrypoint: RelativeFile
    inputs: list[list[Annotated[
        int, Field(strict=True, ge=-1_000_000, le=1_000_000)
    ]]] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def declared_files(self):
        paths = [f.path for f in self.files]
        if (
            len(paths) != len(set(paths)) or self.entrypoint not in paths
            or not self.entrypoint.endswith(".py")
            or any(p.startswith(other + "/") for p in paths for other in paths if p != other)
            or any(len(values) > 20 for values in self.inputs)
            or sum(len(f.content.encode("utf-8")) for f in self.files) > 100000
        ):
            raise ValueError("Project identity, entrypoint or input size is invalid.")
        return self


def validate_project_files(files, entrypoint):
    paths = [item.path for item in files]
    if (
        len(paths) != len(set(paths)) or entrypoint not in paths
        or any(path.startswith(other + "/") for path in paths for other in paths if path != other)
        or sum(len(item.content.encode("utf-8")) for item in files) > 256000
    ):
        raise ValueError("Project manifest, entrypoint or total UTF-8 size is invalid.")


class ProjectProgram(Contract):
    profile: Literal["project-stdio.v1"] = "project-stdio.v1"
    language: ProjectLanguage
    runtime_version: RuntimeVersion
    environment_release_id: UUID
    files: list[ProgramFile] = Field(min_length=1, max_length=32)
    entrypoint: RelativeFile
    inputs: list[Annotated[str, StringConstraints(max_length=8192)]] = Field(
        min_length=1, max_length=3,
    )

    @model_validator(mode="after")
    def closed_project(self):
        validate_project_files(self.files, self.entrypoint)
        suffix = {
            "python": ".py", "javascript": ".js", "typescript": ".ts",
            "java": ".java", "go": ".go", "csharp": ".cs",
        }[self.language]
        if (
            not self.entrypoint.endswith(suffix)
            or self.language == "java" and self.entrypoint != "Main.java"
            or self.language == "csharp" and self.entrypoint != "Program.cs"
        ):
            raise ValueError("Entrypoint does not match the trusted language profile.")
        forbidden = {"Dockerfile", "Makefile", "package.json", "tsconfig.json",
                     "go.mod", "go.sum", "NuGet.Config"}
        if any(
            item.path.rsplit("/", 1)[-1] in forbidden
            or item.path.endswith((".csproj", ".props", ".targets"))
            for item in self.files
        ):
            raise ValueError("Build configuration is owned by the trusted profile.")
        return self


class WebCheck(Contract):
    key: Annotated[str, StringConstraints(
        min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$",
    )]
    kind: Literal["exists", "text", "style", "click_text"]
    selector: str = Field(min_length=1, max_length=240)
    property: Annotated[str, StringConstraints(
        min_length=1, max_length=80, pattern=r"^[a-z][a-z-]*$",
    )] | None = None
    action_selector: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def fields_match_kind(self):
        if (
            (self.kind == "style") != (self.property is not None)
            or (self.kind == "click_text") != (self.action_selector is not None)
        ):
            raise ValueError("Web check fields must match their declared operation.")
        return self


class WebProgram(Contract):
    profile: Literal["web-check.v1"] = "web-check.v1"
    language: Literal["html-css", "javascript", "typescript"] = "html-css"
    runtime_version: RuntimeVersion
    environment_release_id: UUID
    files: list[ProgramFile] = Field(min_length=1, max_length=32)
    entrypoint: RelativeFile
    checks: list[WebCheck] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def closed_web(self):
        validate_project_files(self.files, self.entrypoint)
        if not self.entrypoint.endswith(".html"):
            raise ValueError("The browser profile needs a declared HTML entrypoint.")
        if len({check.key for check in self.checks}) != len(self.checks):
            raise ValueError("Web check keys must be unique.")
        if self.language != "html-css" and any(
            item.path.rsplit("/", 1)[-1] in {
                "Dockerfile", "package.json", "package-lock.json", "tsconfig.json",
                "vite.config.js", "vite.config.ts", "vite.config.mjs", "vite.config.mts",
            }
            for item in self.files
        ):
            raise ValueError("The course environment owns its dependency and build configuration.")
        return self


class WebCheckValue(Contract):
    key: str = Field(min_length=1, max_length=40)
    actual: (
        Annotated[str, StringConstraints(max_length=500)]
        | Annotated[bool, Field(strict=True)] | None
    )


class WebCheckResult(Contract):
    protocol: Literal["web-check-result.v1"] = "web-check-result.v1"
    results: list[WebCheckValue] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_keys(self):
        if len({result.key for result in self.results}) != len(self.results):
            raise ValueError("Web observation keys must be unique.")
        return self


class HttpRequest(Contract):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    path: str = Field(min_length=1, max_length=500, pattern=r"^/[^\\\r\n\x00]*$")
    body: str | None = Field(default=None, max_length=4000)
    content_type: Literal["application/json", "text/plain"] = "application/json"

    @model_validator(mode="after")
    def local_request(self):
        if self.path.startswith("//") or "#" in self.path:
            raise ValueError("HTTP checks use paths on this task's local service.")
        return self


class HttpScenario(Contract):
    requests: list[HttpRequest] = Field(min_length=1, max_length=6)
    dataset: SqlDataset | None = None


class HttpDatabase(Contract):
    dialect: Literal["sqlite", "postgresql", "mysql"]
    schema_definition: SqlSchema | None = None


class HttpProgram(Contract):
    profile: Literal["project-http.v1"] = "project-http.v1"
    language: ProjectLanguage
    runtime_version: RuntimeVersion
    environment_release_id: UUID
    files: list[ProgramFile] = Field(min_length=1, max_length=32)
    entrypoint: RelativeFile
    database: HttpDatabase | None = None
    scenarios: list[HttpScenario] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def closed_service(self):
        ProjectProgram(
            language=self.language, runtime_version=self.runtime_version,
            environment_release_id=self.environment_release_id,
            files=self.files, entrypoint=self.entrypoint, inputs=[""],
        )
        for scenario in self.scenarios:
            if scenario.dataset is not None:
                if self.database is None or self.database.schema_definition is None:
                    raise ValueError("Seed data requires the task's declared database schema.")
                SqlProgram(
                    dialect=self.database.dialect, query="SELECT 1",
                    schema_definition=self.database.schema_definition,
                    datasets=[scenario.dataset],
                )
        return self


class HttpResponse(Contract):
    status: int = Field(ge=100, le=599)
    body: str = Field(max_length=3000)


class HttpScenarioResult(Contract):
    protocol: Literal["http-scenario-result.v1"] = "http-scenario-result.v1"
    responses: list[HttpResponse] = Field(min_length=1, max_length=6)


ExecutionProgram = Annotated[
    SqlProgram | PythonProjectProgram | ProjectProgram | WebProgram | HttpProgram,
    Field(discriminator="profile"),
]
