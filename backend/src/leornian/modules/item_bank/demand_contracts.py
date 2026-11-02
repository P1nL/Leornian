from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.modules.item_bank.supply_contracts import PackSummary
from leornian.shared_kernel.contracts import Contract


class SupplyRequest(Contract):
    expected_plan_revision: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=1600)
    automatic: bool = True


class SupplyRevision(Contract):
    expected_pack_revision: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=1600)
    transfer_feedback_id: UUID | None = None


class SupplyDemand(Contract):
    id: UUID
    remediation_id: UUID | None
    python_remediation_id: UUID | None
    kind: Literal["choice", "python_io"]
    source_pack_id: UUID
    plan_revision: int
    allowed_difficulties: list[int]
    created_at: datetime
    pack: PackSummary
