from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.item_bank.contracts import DirectAnswerContent
from leornian.shared_kernel.contracts import Contract


class PracticeAssistanceReceipt(Contract):
    id: UUID
    profile_version: Literal["practice-direct-answer.v1"] = "practice-direct-answer.v1"
    pack_id: UUID
    pack_revision: int = Field(ge=1)
    slot: Literal["practice_1", "practice_2"]
    public_identity: str = Field(pattern=r"^[a-f0-9]{64}$")
    assistance_kind: Literal["direct_answer"] = "direct_answer"
    content: DirectAnswerContent
    created_at: datetime
