from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from leornian.modules.knowledge.material_contracts import MaterialRef
from leornian.shared_kernel.contracts import Contract

MATERIAL_SYNOPSIS_LIMIT = 4000


class MaterialSearchSource(Contract):
    document_id: UUID
    document_revision: int = Field(ge=1)


class MaterialSearchInput(Contract):
    demand_id: UUID
    expected_demand_revision: int = Field(ge=1)
    query: str = Field(min_length=1, max_length=4000)
    mode: Literal["lexical", "hybrid"] = "hybrid"
    binding_id: UUID | None = None
    expected_binding_revision: int | None = Field(default=None, ge=1)
    document_id: UUID | None = None
    document_revision: int | None = Field(default=None, ge=1)
    required_refs: list[MaterialRef] | None = Field(default=None, min_length=1, max_length=10000)
    source_versions: list[MaterialSearchSource] | None = Field(
        default=None, min_length=1, max_length=10000
    )

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if not self.query.strip():
            raise ValueError("A material query cannot be blank")
        if (self.binding_id is None) != (self.expected_binding_revision is None):
            raise ValueError("Use an exact binding revision")
        if (self.document_id is None) != (self.document_revision is None):
            raise ValueError("Use an exact document revision")
        if self.document_id and self.source_versions:
            raise ValueError("Choose one document filter or an exact source version set")
        if self.source_versions and len({
            (source.document_id, source.document_revision) for source in self.source_versions
        }) != len(self.source_versions):
            raise ValueError("Source versions cannot repeat")
        if self.required_refs is not None:
            if self.mode != "lexical":
                raise ValueError("Complete exact ranges use lexical mode")
            if self.document_id and any(
                (ref.document_id, ref.document_revision)
                != (self.document_id, self.document_revision) for ref in self.required_refs
            ):
                raise ValueError("Required ranges belong to the exact candidate document")
            if self.source_versions:
                versions = {
                    (item.document_id, item.document_revision) for item in self.source_versions
                }
                if any((ref.document_id, ref.document_revision) not in versions
                       for ref in self.required_refs):
                    raise ValueError("Required ranges fall outside the frozen source versions")
        return self


class FacetCoverage(Contract):
    facet: str
    status: Literal["text_supported", "supported", "partial", "missing", "uncertain"]
    evidence: list[MaterialRef]


class MaterialCoverage(Contract):
    status: Literal["sufficient", "partial", "insufficient", "unavailable"]
    basis: Literal[
        "lexical-evidence.v1", "semantic-goal-evidence.v1", "planning-batch-evidence.v1",
        "route-planning-evidence.v1",
    ] = "lexical-evidence.v1"
    required: list[FacetCoverage]
    missing_facets: list[str]
    # Textual support is not an independent factual or teaching-quality certification.
    semantic_quality: Literal["not_certified"] = "not_certified"
    excluded_for_capacity: int = 0
    lexical_coverage: list[FacetCoverage] | None = None
    reviewed_parts: int | None = None
    synopsis: str | None = Field(default=None, max_length=MATERIAL_SYNOPSIS_LIMIT)
    usable_for_planning: bool = Field(default=False, exclude_if=lambda value: not value)


class MaterialEvidence(Contract):
    ref: MaterialRef
    text: str
    title: str
    source_url: str
    source_page: int | None
    section_path: list[str]


class MaterialSelection(Contract):
    id: UUID
    demand_id: UUID
    mode: Literal["lexical", "hybrid"]
    evidence: list[MaterialEvidence]
    coverage: MaterialCoverage
    created_at: datetime


class MaterialSearch(Contract):
    id: UUID
    status: Literal[
        "queued",
        "processing",
        "waiting_config",
        "waiting_dependency",
        "blocked_unknown",
        "ready",
        "cancelled",
    ]
    selection_id: UUID | None
    error_code: str | None
    created_at: datetime
