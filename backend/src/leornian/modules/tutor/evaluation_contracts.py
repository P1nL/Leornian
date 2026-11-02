from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.shared_kernel.contracts import Contract


class EvaluationDocument(Contract):
    recorded_correct: bool
    explanation: str = Field(min_length=1, max_length=1800)
    reflection: str = Field(min_length=1, max_length=600)


class Evaluation(Contract):
    id: UUID
    pack_id: UUID
    source_kind: Literal["choice", "transfer", "python"]
    source_id: UUID
    correct: bool
    run_id: UUID | None
    document: EvaluationDocument | None
    created_at: datetime
