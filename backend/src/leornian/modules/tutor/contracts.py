from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from leornian.modules.identity.contracts import Actor
from leornian.shared_kernel.contracts import Contract


class ConversationInput(Contract):
    goal_id: UUID


class Conversation(Contract):
    id: UUID
    goal_id: UUID
    created_at: datetime


class TeachingFocus(Contract):
    kind: Literal["goal", "node", "attempt"] = "goal"
    plan_id: UUID | None = None
    expected_plan_revision: int | None = Field(default=None, ge=1)
    node_key: str | None = None
    lesson_id: UUID | None = None
    assessment_receipt_id: UUID | None = None

    @model_validator(mode="after")
    def complete_binding(self):
        if self.kind in {"node", "attempt"} and not (
            self.plan_id and self.expected_plan_revision and self.node_key
        ):
            raise ValueError("A node/attempt focus needs an exact plan, revision and node.")
        if self.kind == "attempt" and not self.assessment_receipt_id:
            raise ValueError("An attempt focus needs an already public receipt.")
        if self.kind == "node" and self.assessment_receipt_id:
            raise ValueError("Use attempt focus to attach feedback.")
        if self.kind == "goal" and any(
            (
                self.plan_id,
                self.expected_plan_revision,
                self.node_key,
                self.lesson_id,
                self.assessment_receipt_id,
            )
        ):
            raise ValueError("Goal focus cannot carry hidden node bindings.")
        return self


class TurnInput(Contract):
    text: str = Field(min_length=1, max_length=4000)
    focus: TeachingFocus = TeachingFocus()

    @field_validator("text", mode="before")
    @classmethod
    def trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PlanningInput(TurnInput):
    expected_revision: int = Field(ge=0)


class Turn(Contract):
    id: UUID
    user_text: str
    assistant_text: str | None
    created_at: datetime
    completed_at: datetime | None
    purpose: Literal["teaching", "planning", "lesson", "item_supply", "evaluation"] = "teaching"
    plan_base_revision: int | None = None
    lesson_request_id: UUID | None = None
    context_focus: TeachingFocus = TeachingFocus()


class TutorQueries(Protocol):
    def list_conversations(self, actor: Actor) -> list[Conversation]: ...
    def turns(self, conversation_id: UUID) -> list[Turn]: ...
