import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from leornian.modules.execution.program_contracts import ProgramEnvironment, RuntimeVersion
from leornian.shared_kernel.contracts import Contract
from pydantic import Field, StringConstraints, model_validator

RecipeId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9.-]+$",
    ),
]
EnvironmentLanguage = Literal[
    "python",
    "javascript",
    "typescript",
    "java",
    "go",
    "csharp",
    "html-css",
    "sql",
]
EnvironmentProfile = Literal[
    "project-stdio.v1", "web-check.v1", "sql-query.v1", "project-http.v1",
]
EnvironmentStatus = Literal[
    "waiting_authorization",
    "waiting_engine",
    "queued",
    "preparing",
    "verifying",
    "ready",
    "deferred",
    "declined",
    "revoked",
    "failed",
    "blocked_unknown",
]


class CourseDependency(Contract):
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(
        min_length=3, max_length=80,
        pattern=r"^v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+._][A-Za-z0-9][A-Za-z0-9._-]*)?$",
    )


class CourseEnvironment(Contract):
    """Course packages and a maintained build mode; never shell commands or registries."""

    language: Literal["python", "javascript", "typescript", "java", "go", "csharp"]
    title: str = Field(min_length=1, max_length=160)
    dependencies: list[CourseDependency] = Field(max_length=64)
    build: Literal["stdio", "vite", "http"] = "stdio"
    database: Literal["sqlite", "postgresql", "mysql"] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def package_coordinates(self):
        patterns = {
            "python": r"[A-Za-z0-9][A-Za-z0-9._-]*",
            "javascript": r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*",
            "typescript": r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*",
            "java": r"[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.-]*",
            "go": r"[a-z0-9][a-z0-9.-]+(?:/[A-Za-z0-9_~.-]+)+",
            "csharp": r"[A-Za-z0-9][A-Za-z0-9._-]*",
        }
        names = [item.name for item in self.dependencies]
        if not names and self.build != "http":
            raise ValueError("A package environment needs dependencies or an HTTP service.")
        if self.database is not None and self.build != "http":
            raise ValueError("Project databases belong to HTTP service environments.")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Declare each course package once.")
        if any(
            re.fullmatch(patterns[self.language], name) is None
            or any(part in {".", ".."} for part in name.split("/"))
            for name in names
        ):
            raise ValueError("Use package coordinates from this language's public registry.")
        if self.language == "go" and any("." not in name.split("/")[0] for name in names):
            raise ValueError("Go modules need their public module path.")
        if any(
            item.version.startswith("v") != (self.language == "go")
            for item in self.dependencies
        ):
            raise ValueError("Use canonical exact package versions; only Go versions start with v.")
        if self.build == "vite" and (
            self.language not in {"javascript", "typescript"} or "vite" not in names
        ):
            raise ValueError("A Vite course needs JavaScript/TypeScript and a pinned vite package.")
        if self.build == "vite" and "vue" in names and "@vitejs/plugin-vue" not in names:
            raise ValueError("A Vue Vite course also needs a pinned @vitejs/plugin-vue package.")
        object.__setattr__(
            self, "dependencies", sorted(self.dependencies, key=lambda item: item.name),
        )
        return self


class EnvironmentRequirement(Contract):
    recipe_id: RecipeId
    recipe_revision: int = Field(ge=1)
    profile: EnvironmentProfile
    language: EnvironmentLanguage
    dialect: Literal["sqlite", "postgresql", "mysql"] | None = None
    title: str
    toolchains: list[str]
    dependency_lock: list[str]
    course_environment: CourseEnvironment | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    version_policy: str
    sources: list[str]
    install_location: Literal["application-owned Docker images and volumes"] = (
        "application-owned Docker images and volumes"
    )
    preparation_network: Literal["trusted dependency download only"] = (
        "trusted dependency download only"
    )
    learner_network: Literal["none"] = "none"
    services: list[str] = Field(default_factory=list)
    estimated_download_bytes: int | None = Field(default=None, ge=0)
    estimated_disk_bytes: int | None = Field(default=None, ge=0)
    cost: Literal["public dependencies; no paid service activation"] = (
        "public dependencies; no paid service activation"
    )

    def installation_scope(self):
        value = self.model_dump(mode="json")
        if self.course_environment is not None:
            value.pop("title")
            value["course_environment"].pop("title")
        return value


class EnvironmentDemandInput(Contract):
    recipe_id: RecipeId
    course_environment: CourseEnvironment | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    plan_id: UUID | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    expected_requirement_revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def plan_identity(self):
        if (self.plan_id is None) != (self.plan_revision is None):
            raise ValueError("Plan identity and revision must be supplied together.")
        return self


class EnvironmentRebuildInput(Contract):
    expected_requirement_revision: int = Field(ge=1)
    expected_decision_revision: int = Field(ge=0)


class EnvironmentDecisionInput(EnvironmentRebuildInput):
    decision: Literal["allow", "defer", "decline", "revoke"]


class EnvironmentDecision(Contract):
    id: UUID
    demand_id: UUID
    requirement_revision: int
    revision: int
    decision: Literal["allow", "defer", "decline", "revoke"]
    requirement: EnvironmentRequirement
    created_at: datetime
    authorization_basis: Literal["user", "managed_base", "reused_consent"] = "user"


class EnvironmentRelease(Contract):
    id: UUID
    demand_id: UUID
    requirement_revision: int
    recipe_id: str
    recipe_revision: int
    profile: EnvironmentProfile
    language: EnvironmentLanguage
    dialect: str
    runtime_version: RuntimeVersion
    image_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    image_ids: dict[str, str]
    toolchains: dict[str, str]
    verification: dict
    created_at: datetime

    def environment(self):
        result = {
            "profile": self.profile,
            "runtime_version": self.runtime_version,
            "environment_release_id": str(self.id),
        }
        if self.profile == "sql-query.v1":
            result["dialect"] = self.dialect
        else:
            result["language"] = self.language
        return result


class EnvironmentDemand(Contract):
    id: UUID
    local_scope: Literal["this-device.v1"]
    plan_id: UUID | None
    plan_revision: int | None
    requirement_revision: int
    requirement: EnvironmentRequirement
    decision_revision: int
    decision: Literal["allow", "defer", "decline", "revoke"] | None
    status: EnvironmentStatus
    release: EnvironmentRelease | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class EngineObservationInput(Contract):
    runner_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    status: Literal["ready", "missing", "stopped", "unsupported"]
    version: str | None = Field(default=None, max_length=80)
    operating_system: str | None = Field(default=None, max_length=80)
    detail: str = Field(max_length=400)


class EngineState(Contract):
    status: Literal["ready", "missing", "stopped", "unsupported", "not_connected"]
    version: str | None = None
    operating_system: str | None = None
    detail: str
    observed_at: datetime | None = None
    installation_requires_explicit_system_permission: bool = True


class ExecutionEnvironments(Contract):
    application_status: Literal["ready"] = "ready"
    engine: EngineState
    recipes: list[EnvironmentRequirement]
    demands: list[EnvironmentDemand]
    evaluation_only: list[str] = Field(default_factory=lambda: ["rust", "cpp"])
    automatic_recipe_ids: list[str] = Field(default_factory=list)


class ExecutionEnvironmentSnapshot(Contract):
    local_scope: Literal["this-device.v1"] = "this-device.v1"
    plan_id: UUID | None
    plan_revision: int | None
    engine: EngineState
    recipes: list[EnvironmentRequirement]
    demands: list[EnvironmentDemand]
    usable_environments: list[ProgramEnvironment]
    automatic_recipe_ids: list[str] = Field(default_factory=list)


class RouteEnvironmentManifest(Contract):
    plan_id: UUID
    plan_revision: int
    requirements: list[EnvironmentRequirement]
    automatic_recipe_ids: list[str]
    consent_required: list[EnvironmentRequirement]
    demands: list[EnvironmentDemand]
    engine: EngineState
    gaps: list[str] = Field(default_factory=list)


class GetExecutionEnvironments(Contract):
    pass


class RequestExecutionEnvironment(EnvironmentDemandInput):
    command_key: str = Field(min_length=8, max_length=128)


class EnvironmentDemandToolReceipt(Contract):
    status: Literal["accepted"] = "accepted"
    demand: EnvironmentDemand
    requires_user_decision: bool
    command_receipt_key: str


class EnvironmentPreparationClaimInput(Contract):
    runner_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")


class EnvironmentPreparationClaim(Contract):
    job_id: UUID
    claim_token: UUID
    demand_id: UUID
    requirement_revision: int
    requirement: EnvironmentRequirement


class EnvironmentPreparationProgress(Contract):
    claim_token: UUID
    phase: Literal["downloading", "building", "verifying"]


class EnvironmentPreparationReport(Contract):
    claim_token: UUID
    outcome: Literal["ready", "failed"]
    runtime_version: RuntimeVersion | None = None
    image_id: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    image_ids: dict[
        str,
        Annotated[
            str,
            StringConstraints(
                pattern=r"^sha256:[a-f0-9]{64}$",
            ),
        ],
    ] = Field(default_factory=dict, max_length=8)
    toolchains: dict[str, str] = Field(default_factory=dict, max_length=12)
    verification: dict = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def complete_release(self):
        if self.outcome == "ready" and (
            self.runtime_version is None
            or self.image_id is None
            or not self.image_ids
            or not self.toolchains
            or self.verification.get("isolated") is not True
            or self.verification.get("smoke") is not True
        ):
            raise ValueError(
                "Ready requires an exact image, toolchains and isolated smoke evidence."
            )
        if self.outcome == "failed" and not self.error_code:
            raise ValueError("A failed preparation needs its concrete error code.")
        return self


class EnvironmentReleaseUnavailable(Contract):
    reason: Literal["image_missing", "verification_failed"]


class EnvironmentReleaseVerificationInput(Contract):
    profile: EnvironmentProfile
    language: EnvironmentLanguage | None = None
    dialect: Literal["sqlite", "postgresql", "mysql"] | None = None
    runtime_version: RuntimeVersion
