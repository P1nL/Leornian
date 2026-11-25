from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from pydantic import Field, field_validator, model_serializer, model_validator

from leornian.modules.execution.contracts import ProgramEnvironment
from leornian.modules.item_bank.generation_contracts import (
    IndependenceVerdict,
    PackKind,
    PackStatus,
    ReviewRole,
    ReviewVerdict,
    Slot,
    SupplyStageOutput,
)
from leornian.modules.item_bank.response_contracts import ResponsePracticeFormats
from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.learning.contracts import MaterialCitation, citation_key, material_content_key
from leornian.shared_kernel.contracts import Contract

OptionKey = Literal["A", "B", "C", "D"]
REVIEW_ROLES = get_args(ReviewRole)
SLOTS = ("practice_1", "practice_2", "assessment_1", "assessment_2", "remediation_1")


class PackMaterialContext(Contract):
    contract: Literal["item-materials.v1"] = "item-materials.v1"
    preparation: Literal["exact_origin", "curriculum_node"] = Field(
        default="exact_origin", exclude_if=lambda value: value == "exact_origin",
    )
    origin_citations: list[MaterialCitation] = Field(default_factory=list, max_length=2000)
    author_citations: list[MaterialCitation] = Field(default_factory=list, max_length=2000)
    review_citations: list[MaterialCitation] = Field(default_factory=list, max_length=2000)

    @property
    def requires_material_selection(self):
        return self.preparation == "curriculum_node" or bool(self.origin_citations)

    @model_validator(mode="after")
    def exact_role_content(self):
        origins = {material_content_key(c.ref) for c in self.origin_citations}
        for purpose, citations in (
            ("item_author", self.author_citations), ("item_review", self.review_citations)
        ):
            keys = [citation_key(c) for c in citations]
            if (
                any(c.purpose != purpose for c in citations)
                or len(keys) != len(set(keys))
                or self.preparation == "exact_origin" and (
                    {material_content_key(c.ref) for c in citations} != origins
                )
            ):
                raise ValueError("Each item role needs its own exact node material binding.")
        return self


class PackRequest(Contract):
    expected_plan_revision: int = Field(ge=1)
    node_key: str = Field(min_length=1, max_length=60)
    instruction: str = Field(min_length=1, max_length=2000)
    predecessor_id: UUID | None = None
    gate_feedback_id: UUID | None = None
    transfer_feedback_id: UUID | None = None
    kind: PackKind = "choice"
    automatic: bool = True
    response_formats: ResponsePracticeFormats | None = None
    program_environment: ProgramEnvironment | None = None

    @field_validator("instruction", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def gate_needs_predecessor(self):
        if (self.gate_feedback_id or self.transfer_feedback_id) and not self.predecessor_id:
            raise ValueError("Feedback must identify the exact revision predecessor.")
        if self.gate_feedback_id and self.transfer_feedback_id:
            raise ValueError("Only one exact quality feedback origin is allowed.")
        if self.response_formats is not None and self.kind != "response":
            raise ValueError("Response formats require a response pack.")
        if self.kind in {
            "sql_query", "python_project", "project_stdio", "web_project", "http_project",
        }:
            expected = {
                "sql_query": "sql-query.v1", "python_project": "python-project-io.v1",
                "project_stdio": "project-stdio.v1", "web_project": "web-check.v1",
                "http_project": "project-http.v1",
            }[self.kind]
            if self.program_environment is None or self.program_environment.profile != expected:
                raise ValueError(
                    "Program supply requires an explicit matching environment version.",
                )
        elif self.program_environment is not None:
            raise ValueError("Only program supply can bind a program environment.")
        return self


class ChoiceOption(Contract):
    key: OptionKey
    text: str = Field(min_length=1, max_length=500)


class PublicQuestion(Contract):
    slot: Slot
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=1800)
    options: list[ChoiceOption] = Field(min_length=4, max_length=4)
    difficulty: int = Field(ge=1, le=5)
    source_refs: list[SourceRef] = Field(max_length=3)
    material_citations: list[MaterialCitation] = Field(default_factory=list, max_length=2000)

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler):
        data = handler(self)
        # Old candidate identities and saved exposure snapshots must not change.
        if not self.material_citations:
            data.pop("material_citations", None)
        return data

    @model_validator(mode="after")
    def distinct_options(self):
        if not self.source_refs and not self.material_citations:
            raise ValueError("A question needs an exact supplied citation.")
        if {option.key for option in self.options} != {"A", "B", "C", "D"}:
            raise ValueError("Exactly four distinct option keys are required.")
        if len({option.text.strip().casefold() for option in self.options}) != 4:
            raise ValueError("Option texts must be distinct.")
        return self


class AuthoredQuestion(PublicQuestion):
    correct_key: OptionKey
    explanation: str = Field(min_length=1, max_length=1200)

    def public(self) -> PublicQuestion:
        return PublicQuestion(**self.model_dump(exclude={"correct_key", "explanation"}))


class PackDocument(SupplyStageOutput):
    items: list[AuthoredQuestion] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def complete_distinct_slots(self):
        if {item.slot for item in self.items} != set(SLOTS):
            raise ValueError(
                "Each of the 2 practice / 2 assessment / 1 remediation slots is required."
            )
        prompts = ["".join(item.prompt.split()).casefold() for item in self.items]
        if len(set(prompts)) != 5:
            raise ValueError("A renamed duplicate prompt is not a distinct assessment.")
        decisions = [
            tuple(sorted(option.text.strip().casefold() for option in item.options))
            for item in self.items
        ]
        if len(set(decisions)) != 5:
            raise ValueError("Identical answer choices are not independent task decisions.")
        return self


class BlindAnswer(Contract):
    slot: Slot
    selected_key: OptionKey


class BlindSolution(SupplyStageOutput):
    answers: list[BlindAnswer] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def full_coverage(self):
        if {answer.slot for answer in self.answers} != set(SLOTS):
            raise ValueError("Blind solution must cover each slot once.")
        return self


class ItemReview(Contract):
    slot: Slot
    verdict: ReviewVerdict
    reason: str = Field(min_length=1, max_length=600)
    material_citations: list[MaterialCitation] = Field(default_factory=list, max_length=2000)

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler):
        data = handler(self)
        if not self.material_citations:
            data.pop("material_citations", None)
        return data


class ReviewDocument(SupplyStageOutput):
    items: list[ItemReview] = Field(min_length=5, max_length=5)
    assessment_independence: IndependenceVerdict
    relationship_reason: str = Field(min_length=1, max_length=900)

    @model_validator(mode="after")
    def full_coverage(self):
        if {item.slot for item in self.items} != set(SLOTS):
            raise ValueError("Review must cover every actual item.")
        return self

    @property
    def passed(self) -> bool:
        return self.assessment_independence == "supported" and all(
            item.verdict == "pass" for item in self.items
        )


class PackSummary(Contract):
    id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: str
    revision: int
    predecessor_id: UUID | None
    gate_feedback_id: UUID | None = None
    transfer_feedback_id: UUID | None = None
    supply_demand_id: UUID | None = None
    kind: PackKind = "choice"
    status: PackStatus
    reviewed_roles: list[str]
    passed_roles: list[str]
    blind_passed: bool | None
    item_count: int
    pending_run_id: UUID | None = None
    pending_role: str | None = None
    created_at: datetime
    published_at: datetime | None
    automatic: bool = False
    automation_error: str | None = None
    supply_task_id: UUID | None = None
    automation_status: Literal["running", "waiting", "completed", "cancelled"] | None = None
    automation_action: str | None = None
    automation_reason: str | None = None
    response_formats: ResponsePracticeFormats | None = None
    program_environment: ProgramEnvironment | None = None


class PackAccepted(Contract):
    pack_id: UUID
    run_id: UUID
    status: Literal["accepted"] = "accepted"


class PracticeSet(Contract):
    pack_id: UUID
    questions: list[PublicQuestion]


class ChoiceInput(Contract):
    slot: Literal["practice_1", "practice_2", "remediation_1"]
    selected_key: OptionKey


class ChoiceResult(Contract):
    id: UUID
    pack_id: UUID
    slot: str
    selected_key: OptionKey
    correct: bool
    explanation: str
    created_at: datetime
