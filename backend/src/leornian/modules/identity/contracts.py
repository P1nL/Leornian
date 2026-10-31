from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from leornian.shared_kernel.contracts import Contract


class Actor(Contract):
    id: UUID
    display_name: str


class LocalSessionRequest(Contract):
    display_name: str = Field(min_length=1, max_length=60)

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class Session(Contract):
    token: str
    actor: Actor
    expires_at: datetime
