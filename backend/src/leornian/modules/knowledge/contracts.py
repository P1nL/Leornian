from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator

from leornian.shared_kernel.contracts import Contract


class SourceInput(Contract):
    title: str = Field(min_length=1, max_length=160)
    source_url: str = Field(min_length=1, max_length=2048)
    excerpt: str = Field(min_length=1, max_length=8000)

    @field_validator("title", "source_url", "excerpt", mode="before")
    @classmethod
    def trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("source_url")
    @classmethod
    def safe_link(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Provide an HTTPS source link without credentials")
        return value

    @field_validator("excerpt")
    @classmethod
    def byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 8000:
            raise ValueError("Excerpt exceeds 8000 UTF-8 bytes")
        return value


class SourceRevision(SourceInput):
    expected_revision: int = Field(ge=1)


class SourceAction(Contract):
    expected_revision: int = Field(ge=1)


class AdmitSource(SourceAction):
    valid_until: datetime


class SourceRef(Contract):
    source_id: UUID
    revision: int


class Source(Contract):
    id: UUID
    goal_id: UUID
    revision: int
    title: str
    source_url: str
    excerpt: str
    origin: Literal["learner_supplied"]
    admission: Literal["pending", "admitted", "revoked"]
    valid_until: datetime | None
    usable: bool
    created_at: datetime


class Material(Contract):
    source_id: UUID
    revision: int
    title: str
    source_url: str
    excerpt: str
    origin: Literal["learner_supplied"]
    valid_until: datetime
