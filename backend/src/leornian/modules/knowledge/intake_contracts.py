from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leornian.modules.knowledge.material_contracts import MaterialPurpose, TextMaterialImport
from leornian.shared_kernel.contracts import Contract

MaterialJobState = Literal[
    "queued", "parsing", "processing", "waiting_dependency", "waiting_config",
    "blocked_unknown", "ready", "cancelled"
]
MaterialJobPhase = Literal["parsing", "ocr", "checking", "indexing", "validating"]


class MaterialDemandInput(Contract):
    goal_id: UUID
    plan_id: UUID | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    node_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    purpose: MaterialPurpose
    language: str | None = Field(default=None, min_length=1, max_length=80)
    language_version: str | None = Field(default=None, min_length=1, max_length=80)
    framework: str | None = Field(default=None, min_length=1, max_length=100)
    framework_version: str | None = Field(default=None, min_length=1, max_length=80)
    scope_mode: Literal["facets", "whole_source", "teaching_goal"] = "facets"
    preparation: Literal["complete", "initial", "incremental"] = "complete"
    index_mode: Literal["hybrid", "lexical"] = Field(
        default="hybrid", exclude_if=lambda value: value == "hybrid",
    )
    goal_text: str | None = Field(default=None, min_length=1, max_length=10000)
    required_facets: list[str] = Field(default_factory=list, max_length=100)
    optional_facets: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("language", "language_version", "framework", "framework_version")
    @classmethod
    def nonempty_subject(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Subject and version labels cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("required_facets", "optional_facets")
    @classmethod
    def exact_facets(cls, values):
        if any(not value.strip() or len(value) > 300 for value in values):
            raise ValueError("Facets need nonempty descriptions within 300 characters")
        values = [value.strip() for value in values]
        if len(set(values)) != len(values):
            raise ValueError("Repeated facets")
        return values

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.preparation != "complete" and (
            self.scope_mode != "teaching_goal" or self.purpose != "planning" or self.plan_id
        ):
            raise ValueError("Planning batches need a goal-scoped semantic planning demand")
        if self.scope_mode == "facets" and not self.required_facets and (
            getattr(self, "status", None) != "cancelled"
        ):
            raise ValueError("A teaching demand needs its explicit required facets")
        if self.scope_mode == "whole_source" and (self.required_facets or self.optional_facets):
            raise ValueError("Whole-source intake freezes original scope after extraction")
        if self.scope_mode == "teaching_goal":
            if not self.goal_text or not self.goal_text.strip():
                if getattr(self, "status", None) != "cancelled":
                    raise ValueError("Semantic teaching coverage needs the complete goal")
            if self.required_facets or self.optional_facets:
                raise ValueError("Teaching goals are reviewed semantically, not as literal facets")
        elif self.goal_text is not None:
            raise ValueError("Goal text belongs to semantic teaching demands")
        if (self.plan_id is None) != (self.plan_revision is None):
            raise ValueError("Demand needs the exact plan and revision together")
        if self.node_key and self.plan_id is None:
            raise ValueError("A node requires an exact plan")
        if self.framework_version and not self.framework:
            raise ValueError("A framework version requires a framework")
        if self.language_version and not self.language:
            raise ValueError("A language version requires a language")
        if set(self.required_facets) & set(self.optional_facets):
            raise ValueError("Required and optional facets cannot overlap")
        return self


class MaterialDemand(MaterialDemandInput):
    required_facets: list[str] = Field(min_length=0, max_length=100)
    id: UUID
    revision: int
    consumer_ref: str
    scope: Literal["private"] = "private"
    status: Literal["open", "ready", "cancelled"]
    created_at: datetime

    @model_validator(mode="after")
    def retained_facets(self) -> Self:
        if self.status != "cancelled" and self.scope_mode == "facets" and not self.required_facets:
            raise ValueError("An active material demand needs its required facets")
        return self


class MaterialTextJobInput(Contract):
    expected_demand_revision: int = Field(ge=1)
    material: TextMaterialImport


class MaterialJobStep(Contract):
    revision: int
    state: MaterialJobState
    phase: MaterialJobPhase
    reason_code: str | None
    issues: list[str]
    created_at: datetime


class MaterialPreparedScope(Contract):
    basis: Literal["whole-source-index.v1", "selected-source-text.v1"] = "whole-source-index.v1"
    document_id: UUID
    document_revision: int = Field(ge=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    block_count: int = Field(gt=0)
    indexed_characters: int = Field(gt=0)


class MaterialJob(Contract):
    id: UUID
    root_id: UUID
    demand_id: UUID
    demand_revision: int
    revision: int
    state: MaterialJobState
    background_deferred: bool = False
    phase: MaterialJobPhase
    reason_code: str | None
    issues: list[str]
    document_id: UUID | None
    document_revision: int | None
    upload_id: UUID | None = None
    title: str = "Material"
    format: Literal["text", "markdown", "html", "pdf", "png", "jpeg", "docx"] | None = None
    prepared_scope: MaterialPreparedScope | None = None
    steps: list[MaterialJobStep]
    created_at: datetime
    updated_at: datetime
