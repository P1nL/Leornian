from datetime import datetime
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from leornian.modules.execution.contracts import EnvironmentRequirement, RecipeId
from leornian.modules.execution.environment_contracts import CourseEnvironment
from leornian.modules.identity.contracts import Actor
from leornian.modules.knowledge.contracts import Material, SourceRef
from leornian.modules.learning.material_contracts import MaterialCitation, citation_key
from leornian.modules.learning.material_contracts import (
    material_content_key as material_content_key,
)
from leornian.modules.learning.review_contracts import (
    ActivityResponse as ActivityResponse,
)
from leornian.modules.learning.review_contracts import (
    PresentReview as PresentReview,
)
from leornian.modules.learning.review_contracts import (
    ReviewActivity as ReviewActivity,
)
from leornian.modules.learning.review_contracts import (
    ReviewLog as ReviewLog,
)
from leornian.shared_kernel.contracts import Contract


class GoalMaterialScope(Contract):
    contract: Literal["goal-material-scope.v1"] = "goal-material-scope.v1"
    language: str | None = Field(default=None, min_length=1, max_length=80)
    language_version: str | None = Field(default=None, min_length=1, max_length=80)
    framework: str | None = Field(default=None, min_length=1, max_length=100)
    framework_version: str | None = Field(default=None, min_length=1, max_length=80)
    authorized_official_sources: bool = Field(strict=True)
    authorized_public_sources: bool = Field(
        default=False, strict=True, exclude_if=lambda value: not value,
    )

    @field_validator("language", "language_version", "framework", "framework_version")
    @classmethod
    def explicit_subject(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Course subject labels cannot be blank")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def confirmed(self) -> Self:
        if not self.authorized_official_sources:
            raise ValueError("Official-source discovery requires explicit authorization")
        if self.language_version and not self.language:
            raise ValueError("A language version requires its language")
        if self.framework and not self.language:
            raise ValueError("A framework requires its language")
        if self.framework_version and not self.framework:
            raise ValueError("A framework version requires its framework")
        return self


class GoalInput(Contract):
    title: str = Field(min_length=3, max_length=120)
    motivation: str = Field(default="", max_length=1200)
    material_scope: GoalMaterialScope | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )

    @field_validator("title", "motivation", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GoalRename(Contract):
    title: str = Field(min_length=1, max_length=120)
    motivation: str | None = Field(default=None, max_length=1200)

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class GoalRequest(Contract):
    id: UUID
    actor_id: UUID
    title: str
    motivation: str
    material_scope: GoalMaterialScope | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class Goal(Contract):
    id: UUID
    title: str
    motivation: str
    created_at: datetime
    material_scope: GoalMaterialScope | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class LearningFacade(Protocol):
    def request_goal(self, actor: Actor, key: str, data: GoalInput) -> GoalRequest: ...
    def create_goal(self, actor: Actor, request_id: UUID) -> Goal: ...
    def list_goals(self, actor: Actor) -> list[Goal]: ...
    def get_goal(self, actor: Actor, goal_id: UUID) -> Goal: ...


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
NodeKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]


class CurriculumTechnology(Contract):
    name: ShortText
    version: ShortText | None = None


class CurriculumText(Contract):
    key: NodeKey
    title: ShortText
    role: Literal["primary", "reference"]
    source_url: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
    ] | None = None
    edition: ShortText | None = None
    material_citations: list[MaterialCitation] = Field(min_length=1)


class CurriculumChapter(Contract):
    text_key: NodeKey
    title: ShortText
    source_url: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
    ] | None = None
    document_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def source_locator(self) -> Self:
        if self.source_url is None and self.document_id is None:
            raise ValueError("A chapter needs its observed URL or exact supplied document")
        return self


class CurriculumProject(Contract):
    title: ShortText
    outcome: str = Field(min_length=1, max_length=1200)
    conventions: list[ShortText] = Field(default_factory=list)


class PlannedReading(Contract):
    title: ShortText
    source_url: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
    ] | None = None
    document_id: UUID | None = None
    document_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def located(self) -> Self:
        if self.source_url is None and self.document_id is None:
            raise ValueError("A planned reading needs an observed URL or supplied document")
        if (self.document_id is None) != (self.document_revision is None):
            raise ValueError("A planned document needs its exact revision")
        return self


class NodeMaterialPlan(Contract):
    stage_key: NodeKey | None = Field(default=None, exclude_if=lambda value: value is None)
    topics: list[ShortText] = Field(default_factory=list, max_length=12)
    technologies: list[ShortText] = Field(default_factory=list, max_length=16)
    readings: list[PlannedReading] = Field(default_factory=list, max_length=12)


class RouteCurriculum(Contract):
    contract: Literal["route-curriculum.v1"] = "route-curriculum.v1"
    basis: Literal["selected_materials", "model_knowledge"] = Field(
        default="selected_materials", exclude_if=lambda value: value == "selected_materials",
    )
    technologies: list[CurriculumTechnology] = Field(min_length=1)
    texts: list[CurriculumText]
    project: CurriculumProject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len({text.key for text in self.texts}) != len(self.texts):
            raise ValueError("Selected curriculum texts need unique keys")
        if self.basis == "selected_materials" and not any(
            text.role == "primary" for text in self.texts
        ):
            raise ValueError("A curriculum needs a primary textbook or guide")
        if len({item.name.casefold() for item in self.technologies}) != len(self.technologies):
            raise ValueError("Choose one version for each curriculum technology")
        if any(
            citation.purpose != "planning"
            for text in self.texts for citation in text.material_citations
        ):
            raise ValueError("Curriculum selection needs planning-purpose evidence")
        return self


class PlanNode(Contract):
    key: NodeKey
    title: ShortText
    objective: str = Field(min_length=1, max_length=600)
    estimated_minutes: int = Field(ge=5, le=240, strict=True)
    prerequisite_keys: list[NodeKey] = []
    source_refs: list[SourceRef] = []
    material_citations: list[MaterialCitation] = Field(default_factory=list)
    curriculum_chapters: list[CurriculumChapter] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    project_milestone: ShortText | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    material_plan: NodeMaterialPlan | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class PlanDocument(Contract):
    title: ShortText
    summary: str = Field(min_length=1, max_length=1200)
    assumptions: list[ShortText] = Field(max_length=4)
    nodes: list[PlanNode] = Field(min_length=1)
    environment_recipes: list[RecipeId] = Field(
        default_factory=list, max_length=16, exclude_if=lambda value: not value,
    )
    environment_dependencies: list[CourseEnvironment] = Field(
        default_factory=list, max_length=16, exclude_if=lambda value: not value,
    )
    environment_gaps: list[ShortText] = Field(
        default_factory=list, max_length=16, exclude_if=lambda value: not value,
    )
    curriculum: RouteCurriculum | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def ordered_dependencies(self) -> Self:
        previous = set()
        for node in self.nodes:
            if node.key in previous or not set(node.prerequisite_keys) <= previous:
                raise ValueError("Node keys must be unique; prerequisites must precede the node")
            if len(set(node.prerequisite_keys)) != len(node.prerequisite_keys):
                raise ValueError("Repeated prerequisites are not allowed")
            if not node.objective.strip():
                raise ValueError("A node needs a concrete learning objective")
            refs = [(ref.source_id, ref.revision) for ref in node.source_refs]
            if len(set(refs)) != len(refs):
                raise ValueError("Repeated source references are not allowed")
            citations = [citation_key(c) for c in node.material_citations]
            if len(set(citations)) != len(citations):
                raise ValueError("Repeated material citations are not allowed")
            if self.curriculum:
                if (
                    self.curriculum.basis == "selected_materials"
                    and not node.curriculum_chapters
                ):
                    raise ValueError("Every curriculum node needs selected chapters")
                if node.curriculum_chapters and not node.material_citations:
                    raise ValueError(
                        "A curriculum node needs its selected text's planning citation"
                    )
                if any(chapter.text_key not in {text.key for text in self.curriculum.texts}
                       for chapter in node.curriculum_chapters):
                    raise ValueError("Node chapters must belong to the selected curriculum")
            elif node.curriculum_chapters or node.project_milestone:
                raise ValueError("Node curriculum details need the route curriculum")
            if node.material_plan and node.material_plan.technologies:
                names = {item.name for item in self.curriculum.technologies} if (
                    self.curriculum
                ) else set()
                if not set(node.material_plan.technologies) <= names:
                    raise ValueError(
                        "Node material technologies must belong to the route curriculum"
                    )
            previous.add(node.key)
        if not self.summary.strip():
            raise ValueError("Plan summary cannot be empty")
        if len(set(self.environment_recipes)) != len(self.environment_recipes):
            raise ValueError("Route environment recipes must be unique")
        scopes = [(item.language, item.build) for item in self.environment_dependencies]
        if len(set(scopes)) != len(scopes):
            raise ValueError("Combine course dependencies for the same language and build mode.")
        return self


class PlanRevision(Contract):
    id: UUID
    revision: int
    predecessor_revision: int
    document: PlanDocument
    sources: list[Material]
    created_at: datetime


class LearningPlan(Contract):
    id: UUID
    goal_id: UUID
    latest: PlanRevision
    active: PlanRevision | None


class PlanConfirmation(Contract):
    plan_id: UUID
    revision: int
    confirmed_at: datetime


class ConfirmDynamicPlan(Contract):
    expected_revision: int = Field(ge=1)
    environment_requirements: list[EnvironmentRequirement] | None = Field(
        default=None, max_length=16, exclude_if=lambda value: value is None,
    )


class LessonRequestInput(Contract):
    expected_plan_revision: int = Field(ge=1)
    node_key: NodeKey
    instruction: str = Field(min_length=1, max_length=4000)

    @field_validator("instruction", mode="before")
    @classmethod
    def trim_instruction(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class LessonRequest(Contract):
    id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: NodeKey
    instruction: str


class LessonSection(Contract):
    heading: ShortText
    explanation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    code_example: str
    source_refs: list[SourceRef]
    material_citations: list[MaterialCitation] = Field(default_factory=list)

    @model_validator(mode="after")
    def supported_section(self) -> Self:
        if not self.source_refs and not self.material_citations:
            raise ValueError("A lesson section needs an exact source or material citation")
        citations = [citation_key(c) for c in self.material_citations]
        if len(set(citations)) != len(citations):
            raise ValueError("Repeated material citations are not allowed")
        return self


class LessonDocument(Contract):
    title: ShortText
    introduction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    sections: list[LessonSection] = Field(min_length=1)
    recall_prompts: list[ShortText] = Field(min_length=1)


class GeneratedLesson(Contract):
    id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: NodeKey
    document: LessonDocument
    sources: list[Material]
    created_at: datetime


class NodeProgress(Contract):
    plan_id: UUID
    plan_revision: int
    node_key: NodeKey
    evidence_gate_id: UUID
    completed_at: datetime
    capability: str = "concept_choice"
