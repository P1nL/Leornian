from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.shared_kernel.contracts import Contract

Dimension = Literal["concept", "execution", "transfer"]


class OwnedEvidence(Contract):
    source_owner: Literal["assessment"] = "assessment"
    source_receipt: UUID
    evidence_kind: str
    dimension: Dimension
    outcome: Literal["passed", "not_passed", "error", "observed"]
    occurred_at: datetime
    plan_id: UUID | None = None
    plan_revision: int | None = None
    node_key: str | None = None
    track_id: UUID | None = None
    pack_id: UUID | None = None
    slot: str | None = None
    item_version: str
    policy_version: str
    assistance: list[dict] = []
    exposure: list[dict] = []
    material_versions: list[dict] = []
    independence: Literal["independent_gate", "assisted", "practice", "unknown"]
