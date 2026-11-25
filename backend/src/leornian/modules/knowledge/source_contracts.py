from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leornian.modules.knowledge.file_contracts import FileFormat
from leornian.modules.knowledge.material_contracts import MaterialPurpose, TextMaterialImport
from leornian.modules.knowledge.source_network import approved_source_url, canonical_source_url
from leornian.shared_kernel.contracts import Contract
from leornian.shared_kernel.errors import BusinessError


class MaterialSourceInput(Contract):
    goal_id: UUID
    title: str = Field(min_length=1, max_length=160)
    entry_url: str = Field(min_length=1, max_length=2048)
    allowed_prefixes: list[str] = Field(min_length=1, max_length=20)
    authorized_use: Literal[True]
    purposes: list[MaterialPurpose] = Field(min_length=1)
    language: str | None = Field(default=None, min_length=1, max_length=80)
    language_version: str | None = Field(default=None, min_length=1, max_length=80)
    framework: str | None = Field(default=None, min_length=1, max_length=100)
    framework_version: str | None = Field(default=None, min_length=1, max_length=80)
    topics: list[str] = Field(default_factory=list, max_length=100)
    format: FileFormat | None = None
    discover_links: bool = True
    use_until: datetime | None = None
    retain_until: datetime | None = None

    @field_validator("entry_url")
    @classmethod
    def safe_entry(cls, value):
        try:
            return canonical_source_url(value)
        except BusinessError as error:
            raise ValueError(error.message) from None

    @field_validator("allowed_prefixes")
    @classmethod
    def safe_prefixes(cls, values):
        try:
            return list(dict.fromkeys(canonical_source_url(v) for v in values))
        except BusinessError as error:
            raise ValueError(error.message) from None

    @field_validator("use_until", "retain_until")
    @classmethod
    def real_date(cls, value):
        return TextMaterialImport.aware_date(value)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        try:
            approved_source_url(self.entry_url, self.allowed_prefixes)
        except BusinessError as error:
            raise ValueError(error.message) from None
        if "indexing" not in self.purposes or len(set(self.purposes)) != len(self.purposes):
            raise ValueError("Sources need indexing permission and distinct purposes")
        if self.language_version and not self.language:
            raise ValueError("A language version needs a language")
        if self.framework_version and not self.framework:
            raise ValueError("A framework version needs a framework")
        if not self.title.strip() or any(not t.strip() or len(t) > 300 for t in self.topics):
            raise ValueError("Source title and topics cannot be blank")
        return self


class MaterialSource(MaterialSourceInput):
    id: UUID
    revision: int
    admission: Literal["allowed", "revoked"]
    basis: Literal[
        "explicit_approval", "official_catalog", "learning_catalog", "public_discovery",
    ]
    catalog_id: str | None
    created_at: datetime


class MaterialSourceAction(Contract):
    expected_revision: int = Field(ge=1)


class MaterialSourceObservation(Contract):
    id: UUID
    source_id: UUID
    resource_id: UUID
    status: Literal[
        "queued", "fetching", "processing", "unchanged", "noise_only", "changed",
        "waiting_config", "waiting_dependency", "blocked_unknown", "cancelled",
    ]
    response_status: int | None
    raw_digest: str | None
    teaching_digest: str | None
    upload_id: UUID | None
    job_id: UUID | None
    document_id: UUID | None
    document_revision: int | None
    error_code: str | None
    created_at: datetime


class MaterialDiscovery(Contract):
    id: UUID
    demand_id: UUID
    demand_revision: int
    status: Literal[
        "queued", "processing", "waiting_config", "waiting_dependency", "blocked_unknown",
        "ready", "cancelled",
    ]
    selection_id: UUID | None
    missing_facets: list[str]
    error_code: str | None
    created_at: datetime
