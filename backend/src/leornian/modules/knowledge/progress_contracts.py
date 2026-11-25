from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from leornian.shared_kernel.contracts import Contract

PreparationState = Literal[
    "idle", "processing", "waiting_dependency", "waiting_config", "blocked_unknown", "ready",
    "cancelled",
]
StepState = Literal["pending", "running", "completed", "waiting", "unknown", "cancelled"]


class MaterialPreparationStep(Contract):
    key: Literal[
        "sources", "acquisition", "parsing", "ocr", "quality", "chunking", "embedding",
        "indexing", "retrieval",
    ]
    status: StepState
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    unit: Literal["documents", "chunks", "checks"] = "documents"
    level: int | None = Field(default=None, ge=0)


class MaterialPreparationDocument(Contract):
    title: str
    state: str
    phase: str
    reason_code: str | None = None


class MaterialPreparationProgress(Contract):
    demand_id: UUID | None = None
    preparation: Literal["complete", "initial", "incremental"] = "complete"
    goal: str | None = None
    status: PreparationState = "idle"
    reason_code: str | None = None
    steps: list[MaterialPreparationStep] = Field(default_factory=list)
    documents: list[MaterialPreparationDocument] = Field(default_factory=list)
    current_documents: int = Field(default=0, ge=0)
    ready_documents: int = Field(default=0, ge=0)
    background_documents: int = Field(default=0, ge=0)
    background_ready_documents: int = Field(default=0, ge=0)
    last_progress_at: datetime | None = None
