from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leornian.modules.knowledge.contracts import DocumentBlock, MaterialPurpose, MaterialRef
from leornian.shared_kernel.contracts import Contract


class MaterialCitation(Contract):
    binding_id: UUID
    binding_revision: int = Field(ge=1)
    purpose: MaterialPurpose
    ref: MaterialRef


def citation_key(citation: MaterialCitation):
    return citation.model_dump_json()


def material_content_key(ref: MaterialRef):
    return (
        ref.document_id, ref.document_revision, ref.block_id,
        ref.span.start, ref.span.end, ref.content_digest,
    )


class MaterialBindingInput(Contract):
    goal_id: UUID
    plan_id: UUID | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    node_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    purpose: MaterialPurpose
    expected_binding_revision: int = Field(ge=0)
    refs: list[MaterialRef] = Field(min_length=1, max_length=10000)
    expected_completion_at: datetime | None = None

    @field_validator("expected_completion_at")
    @classmethod
    def aware_date(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Expected completion needs a timezone")
        return value

    @model_validator(mode="after")
    def coherent_scope(self) -> Self:
        if (self.plan_id is None) != (self.plan_revision is None):
            raise ValueError("Bind the exact plan and revision together")
        if self.node_key and not self.plan_id:
            raise ValueError("A node binding requires a plan")
        identities = [material_content_key(r) for r in self.refs]
        if len(identities) != len(set(identities)):
            raise ValueError("Repeated material references")
        return self


class MaterialBinding(Contract):
    contract: Literal["material-binding.v1"] = "material-binding.v1"
    id: UUID
    goal_id: UUID
    revision: int
    plan_id: UUID | None
    plan_revision: int | None
    node_key: str | None
    purpose: MaterialPurpose
    refs: list[MaterialRef]
    expected_completion_at: datetime | None
    review_due_at: datetime
    created_at: datetime


class BoundMaterialPage(Contract):
    binding: MaterialBinding
    blocks: list[DocumentBlock]
    next_offset: int | None
