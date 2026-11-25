from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leornian.shared_kernel.contracts import Contract

MaterialPurpose = Literal[
    "reference", "planning", "lesson", "teaching", "item_author", "item_review", "indexing"
]


class TextMaterialImport(Contract):
    goal_id: UUID
    document_id: UUID | None = None
    expected_revision: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=160)
    source_url: str = Field(min_length=1, max_length=2048)
    format: Literal["text", "markdown"] = "text"
    text: str = Field(min_length=1, max_length=1_000_000)
    authorized_use: Literal[True]
    purposes: list[MaterialPurpose] = Field(min_length=1)
    use_until: datetime | None = None
    retain_until: datetime | None = None

    @field_validator("source_url")
    @classmethod
    def safe_link(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Provide an HTTPS source locator without credentials")
        return value

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be empty")
        return value.strip()

    @field_validator("text")
    @classmethod
    def bounded_original(cls, value: str) -> str:
        if not value.strip() or "\x00" in value or len(value.encode("utf-8")) > 2_000_000:
            raise ValueError("Material needs nonempty text within 2 MB; split larger imports")
        # Original offsets and code indentation must survive ingestion.
        return value

    @field_validator("use_until", "retain_until")
    @classmethod
    def aware_date(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("A real deadline needs an explicit timezone")
        return value

    @model_validator(mode="after")
    def coherent_request(self) -> Self:
        if (self.document_id is None) != (self.expected_revision == 0):
            raise ValueError("New documents use revision zero; revisions need an existing document")
        if len(self.purposes) != len(set(self.purposes)):
            raise ValueError("Duplicate purposes")
        return self


class MaterialSpan(Contract):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Span must be nonempty")
        return self


class MaterialRef(Contract):
    document_id: UUID
    document_revision: int = Field(ge=1)
    block_id: UUID
    span: MaterialSpan
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Retrieval adds a selection identity in WP03; direct exact reads do not invent one.
    selection_id: UUID | None = None


class DocumentPermission(Contract):
    revision: int
    status: Literal["allowed", "revoked"]
    purposes: list[MaterialPurpose]
    use_until: datetime | None
    retain_until: datetime | None
    basis: Literal["learner_authorized", "legacy_admission"]


class DocumentPage(Contract):
    number: int = Field(ge=1)
    method: Literal["embedded_text", "none", "ocr"]
    requires_ocr: bool
    reason_code: str | None
    region: list[int] | None = Field(default=None, min_length=4, max_length=4)
    original_part: str | None = None
    location_basis: Literal["document_page", "image_region", "document_part"] = "document_page"


class UnresolvedRegion(Contract):
    ordinal: int = Field(ge=0)
    kind: str
    label: str = ""
    source_url: str | None = None
    section_path: list[str] = Field(default_factory=list)
    after_block: int = Field(ge=0)


class DocumentVersion(Contract):
    document_id: UUID
    goal_id: UUID
    revision: int
    title: str
    source_url: str
    format: Literal["text", "markdown", "html", "pdf", "png", "jpeg", "docx"]
    content_digest: str
    parser_version: str
    provenance: Literal["learner_supplied", "legacy_excerpt"]
    legacy_source_id: UUID | None = None
    legacy_source_revision: int | None = None
    permission: DocumentPermission
    next_check_at: datetime
    created_at: datetime
    upload_id: UUID | None = None
    text_basis: Literal["source_text", "extracted_text"] = "source_text"
    pages: list[DocumentPage] = Field(default_factory=list)
    content_state: Literal["retained", "purged"] = "retained"
    purged_at: datetime | None = None
    # Parsing is not material quality, retrieval validation or corpus release.
    processing_state: Literal["parsed", "partial"] = "parsed"
    unresolved_regions: list[UnresolvedRegion] = Field(default_factory=list)


class DocumentBlock(Contract):
    id: UUID
    ordinal: int
    kind: Literal["heading", "paragraph", "code", "table"]
    section_path: list[str]
    text: str
    ref: MaterialRef
    source_page: int | None = None
    span_basis: Literal["source_text", "extracted_text"] = "source_text"


class DocumentBlockPage(Contract):
    document: DocumentVersion
    blocks: list[DocumentBlock]
    next_after: int | None


class DocumentPermissionAction(Contract):
    expected_revision: int = Field(ge=1)
    action: Literal["revoke"]


class LegacyMaterialImport(Contract):
    expected_revision: int = Field(ge=1)
