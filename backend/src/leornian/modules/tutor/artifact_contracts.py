from datetime import datetime
from uuid import UUID

from pydantic import Field

from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.shared_kernel.contracts import Contract


class ArtifactSection(Contract):
    heading: str = Field(min_length=1)
    text: str = Field(min_length=1)
    code: str | None = None
    language: str | None = None
    source_refs: list[SourceRef] = []


class ArtifactDocument(Contract):
    title: str = Field(min_length=1)
    sections: list[ArtifactSection] = Field(min_length=1)


class ArtifactSummary(Contract):
    id: UUID
    goal_id: UUID
    focus: TeachingFocus
    revision: int
    title: str
    created_at: datetime


class ArtifactView(ArtifactSummary):
    document: ArtifactDocument


class ArtifactJob(Contract):
    id: UUID
    conversation_id: UUID
    artifact_id: UUID
    expected_revision: int
    instruction: str
    status: str
    run_id: UUID | None
    created_at: datetime


class ArtifactRequestInput(Contract):
    instruction: str = Field(min_length=1, max_length=4000)
    focus: TeachingFocus = TeachingFocus()
    artifact_id: UUID | None = None
    expected_revision: int = Field(default=0, ge=0)
