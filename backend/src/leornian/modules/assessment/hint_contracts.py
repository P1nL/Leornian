from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from leornian.shared_kernel.contracts import Contract


class GraduatedHint(Contract):
    level: Literal[1, 2, 3]
    purpose: Literal["concept", "strategy", "next_step"]
    text: str = Field(min_length=12, max_length=2000)

    @model_validator(mode="after")
    def fixed_purpose(self):
        if not self.text.strip() or self.purpose != {
            1: "concept", 2: "strategy", 3: "next_step",
        }[self.level]:
            raise ValueError("Each hint level has its own teaching purpose.")
        return self


class PracticeHintReceipt(Contract):
    id: UUID
    profile_version: Literal["practice-hints.v1"] = "practice-hints.v1"
    pack_id: UUID
    pack_revision: int = Field(ge=1)
    slot: Literal["practice_1", "practice_2"]
    public_identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    hint_identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    assistance_kind: Literal["hint"] = "hint"
    level: Literal[1, 2, 3]
    content: GraduatedHint
    created_at: datetime
