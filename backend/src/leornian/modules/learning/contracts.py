from datetime import datetime
from typing import Annotated, Protocol, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from leornian.modules.identity.contracts import Actor
from leornian.modules.knowledge.contracts import Material, SourceRef
from leornian.shared_kernel.contracts import Contract


class GoalInput(Contract):
    title: str = Field(min_length=3, max_length=120)
    motivation: str = Field(default="", max_length=1200)

    @field_validator("title", "motivation", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GoalRequest(Contract):
    id: UUID
    actor_id: UUID
    title: str
    motivation: str


class Goal(Contract):
    id: UUID
    title: str
    motivation: str
    created_at: datetime


class LearningFacade(Protocol):
    def request_goal(self, actor: Actor, key: str, data: GoalInput) -> GoalRequest: ...
    def create_goal(self, actor: Actor, request_id: UUID) -> Goal: ...
    def list_goals(self, actor: Actor) -> list[Goal]: ...
    def get_goal(self, actor: Actor, goal_id: UUID) -> Goal: ...


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
NodeKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]


class PlanNode(Contract):
    key: NodeKey
    title: ShortText
    objective: str = Field(min_length=1, max_length=600)
    estimated_minutes: int = Field(ge=5, le=240, strict=True)
    prerequisite_keys: list[NodeKey] = Field(max_length=7)
    source_refs: list[SourceRef] = Field(max_length=3)


class PlanDocument(Contract):
    title: ShortText
    summary: str = Field(min_length=1, max_length=1200)
    assumptions: list[ShortText] = Field(max_length=4)
    nodes: list[PlanNode] = Field(min_length=1, max_length=8)

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
            previous.add(node.key)
        if not self.summary.strip():
            raise ValueError("Plan summary cannot be empty")
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


class ConfirmDynamicPlan(Contract):
    expected_revision: int = Field(ge=1)


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
    explanation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1800)
    ]
    code_example: str = Field(max_length=1800)
    source_refs: list[SourceRef] = Field(min_length=1, max_length=3)


class LessonDocument(Contract):
    title: ShortText
    introduction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    sections: list[LessonSection] = Field(min_length=1, max_length=5)
    recall_prompts: list[ShortText] = Field(min_length=1, max_length=3)


class GeneratedLesson(Contract):
    id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: NodeKey
    document: LessonDocument
    sources: list[Material]
    created_at: datetime
