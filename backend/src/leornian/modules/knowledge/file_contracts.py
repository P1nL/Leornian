from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leornian.modules.knowledge.material_contracts import MaterialPurpose, TextMaterialImport
from leornian.shared_kernel.contracts import Contract

MAX_FILE_BYTES = 20_000_000
FileFormat = Literal["text", "markdown", "html", "pdf", "png", "jpeg", "docx"]


class FileMaterialInput(Contract):
    goal_id: UUID
    document_id: UUID | None = None
    expected_revision: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=160)
    source_url: str | None = Field(default=None, min_length=1, max_length=2048)
    format: FileFormat
    authorized_use: Literal[True]
    purposes: list[MaterialPurpose] = Field(min_length=1)
    use_until: datetime | None = None
    retain_until: datetime | None = None

    @field_validator("source_url")
    @classmethod
    def safe_link(cls, value):
        return TextMaterialImport.safe_link(value) if value is not None else None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value):
        return TextMaterialImport.trim_title(value)

    @field_validator("use_until", "retain_until")
    @classmethod
    def aware_date(cls, value):
        return TextMaterialImport.aware_date(value)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.document_id is None) != (self.expected_revision == 0):
            raise ValueError("New documents use revision zero; revisions need an existing document")
        if len(self.purposes) != len(set(self.purposes)):
            raise ValueError("Duplicate purposes")
        return self


class MaterialUploadInput(Contract):
    expected_demand_revision: int = Field(ge=1)
    material: FileMaterialInput
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0, le=MAX_FILE_BYTES)


class MaterialUpload(Contract):
    id: UUID
    demand_id: UUID
    demand_revision: int
    format: FileFormat
    content_digest: str
    byte_size: int
    state: Literal["pending", "stored", "purged"]
    created_at: datetime
    expires_at: datetime


class MaterialFileJobInput(Contract):
    expected_demand_revision: int = Field(ge=1)
    upload_id: UUID
