from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from pydantic import Field, field_validator

from leornian.agent_runtime.contracts import RunStatus
from leornian.shared_kernel.contracts import Contract

PackKind = Literal[
    "choice", "python_io", "response", "sql_query", "python_project",
    "project_stdio", "web_project", "http_project",
]
PackStatus = Literal[
    "authoring", "blind_solving", "qualifying", "reviewing", "changes_required",
    "ready", "published", "failed", "cancelled",
]
Slot = Literal["practice_1", "practice_2", "assessment_1", "assessment_2", "remediation_1"]
ReviewRole = Literal[
    "curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial",
]
ReviewVerdict = Literal["pass", "revise", "reject"]
IndependenceVerdict = Literal["supported", "revise", "reject"]
PublicNote = Literal[
    "从本节目标选取考点。", "让补救题集中检查一个基础步骤。", "为同一概念设计不同的应用情境。",
    "按公开题面独立作答。", "用公开样例核对作答。", "另行检查边界情况。",
    "核对题目是否用到尚未学习的知识。", "比较练习、考核和补救题的难度。",
    "核对题面与判定规则是否一致。", "检查题目条件是否有多种解释。",
    "检查公开内容是否泄露答案。", "检查能否照搬练习解法通过考核。",
    "本版使用了超出节点目标的知识。", "补救题还需要降低难度。",
    "题面描述与判定规则需要对齐。", "需要补充条件才能唯一作答。",
    "练习给出了过多的考核线索。", "需要换一种情境检验独立应用。",
]
_PUBLIC_NOTES = frozenset(get_args(PublicNote))


class SupplyStageOutput(Contract):
    public_notes: list[PublicNote] = Field(
        default_factory=list, max_length=2, exclude_if=lambda value: not value,
    )

    @field_validator("public_notes", mode="before")
    @classmethod
    def accepted_notes(cls, value):
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(note for note in value
                                  if isinstance(note, str) and note in _PUBLIC_NOTES))[:2]


class BankPack(Contract):
    id: UUID
    plan_revision: int
    node_key: str
    revision: int
    kind: PackKind
    status: PackStatus
    created_at: datetime
    predecessor_id: UUID | None
    supply_task_id: UUID | None


class BankNode(Contract):
    plan_revision: int
    node_key: str
    title: str
    position: int
    packs: list[BankPack]


class GenerationStage(Contract):
    role: Literal["author", "blind"] | ReviewRole
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None
    public_notes: list[PublicNote]
    item_count: int | None = None
    blind_passed: bool | None = None
    decisions: dict[Slot, ReviewVerdict] = Field(default_factory=dict)
    independence: IndependenceVerdict | None = None


class GenerationReport(Contract):
    pack_id: UUID
    status: PackStatus
    stages: list[GenerationStage]
    qualifications: dict[str, int]
    published_at: datetime | None
