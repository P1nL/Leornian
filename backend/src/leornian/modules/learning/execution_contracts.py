from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.shared_kernel.contracts import Contract


class ExecutionProgress(Contract):
    gate_id: UUID
    plan_id: UUID
    plan_revision: int
    node_key: str
    policy_version: Literal["python-io-gate.v1", "program-execution-gate.v1"]
    completed_at: datetime
