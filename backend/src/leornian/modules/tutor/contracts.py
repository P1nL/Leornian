from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator

from leornian.modules.identity.contracts import Actor
from leornian.shared_kernel.contracts import Contract


class ConversationInput(Contract):
    goal_id: UUID


class Conversation(Contract):
    id: UUID
    goal_id: UUID
    created_at: datetime


class TurnInput(Contract):
    text: str = Field(min_length=1, max_length=4000)

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
    purpose: Literal["teaching", "planning", "lesson"] = "teaching"
    plan_base_revision: int | None = None
    lesson_request_id: UUID | None = None


class TutorQueries(Protocol):
    def list_conversations(self, actor: Actor) -> list[Conversation]: ...
    def turns(self, conversation_id: UUID) -> list[Turn]: ...
