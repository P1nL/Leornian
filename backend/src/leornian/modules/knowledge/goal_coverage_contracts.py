from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leornian.modules.knowledge.material_contracts import MaterialRef
from leornian.modules.knowledge.retrieval_contracts import MATERIAL_SYNOPSIS_LIMIT
from leornian.shared_kernel.contracts import Contract

MATERIAL_GOAL_SUMMARY_LIMIT = MATERIAL_SYNOPSIS_LIMIT
MaterialIssue = Literal[
    "incorrect", "version_mismatch", "irrelevant", "access_restricted", "incomplete",
]
SOURCE_DEFECTS = {"incorrect", "version_mismatch", "irrelevant", "access_restricted"}


class MaterialGoalFinding(Contract):
    issue: MaterialIssue
    scope: Literal["refs", "document"] = "refs"
    refs: list[MaterialRef] = Field(min_length=1)
    topics: list[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(min_length=1, max_length=1000)

    def affects(self, ref):
        return any(
            (item.document_id, item.document_revision)
            == (ref.document_id, ref.document_revision)
            and (self.scope == "document" or (
                item.block_id == ref.block_id
                and item.span.start < ref.span.end and ref.span.start < item.span.end
            ))
            for item in self.refs
        )


class MaterialGoalVerdict(Contract):
    status: Literal["supported", "partial", "missing", "uncertain"]
    summary: str = Field(min_length=1, max_length=MATERIAL_GOAL_SUMMARY_LIMIT)
    evidence_refs: list[MaterialRef] = Field(max_length=8)
    reviewed_refs: list[MaterialRef] = Field(default_factory=list)
    reviewed_parts: list[UUID] = Field(default_factory=list)
    issues: list[MaterialIssue] = Field(default_factory=list, max_length=5)
    findings: list[MaterialGoalFinding] = Field(
        default_factory=list, max_length=50, exclude_if=lambda value: not value,
    )
    supported_topics: list[str] = Field(
        default_factory=list, max_length=30, exclude_if=lambda value: not value,
    )
    topic_evidence: dict[str, list[MaterialRef]] = Field(
        default_factory=dict, exclude_if=lambda value: not value,
    )
    example_queries: dict[str, str] = Field(
        default_factory=dict, exclude_if=lambda value: not value,
    )
    missing_topics: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("supported_topics", "missing_topics")
    @classmethod
    def concise_topics(cls, values):
        if any(not value.strip() or len(value) > 300 for value in values):
            raise ValueError("Topics must be concise actionable descriptions")
        return list(dict.fromkeys(" ".join(value.split()) for value in values))

    @model_validator(mode="after")
    def usable_evidence(self):
        if any(finding.issue not in self.issues for finding in self.findings):
            raise ValueError("Scoped findings must retain their issue codes")
        defects = [finding for finding in self.findings if finding.issue in SOURCE_DEFECTS]
        if any(finding.affects(ref) for finding in defects for ref in self.evidence_refs):
            raise ValueError("Defective source ranges cannot be used as evidence")
        if self.status == "supported" and (
            set(self.issues) & SOURCE_DEFECTS
        ) - {finding.issue for finding in defects}:
            raise ValueError("Unscoped source defects cannot support a teaching goal")
        return self
