"""Tutor owns delivery coordination, not plans, lessons, grading or mastery."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from leornian.shared_kernel.contracts import Contract
from leornian.shared_kernel.errors import BusinessError


class DeliveryTask(Contract):
    id: UUID
    run_id: UUID
    kind: Literal["teaching", "planning", "lesson", "artifact"]
    status: str
    revision: int
    repair_strategy: str
    created_at: datetime
    updated_at: datetime
    cancel_requested: bool
    can_resume: bool = False
    required_input: list[str] = []


class DeliveryResume(Contract):
    additional_instruction: str = Field(default="", max_length=4000)


class DeliveryIssue(Contract):
    code: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    repair_instruction: str = Field(min_length=1)


class QualityCheck(Contract):
    code: str
    verdict: Literal["accepted", "changes_required", "needs_input"]
    issues: list[DeliveryIssue] = []


class QualityReport(Contract):
    candidate_call_id: UUID
    verdict: Literal["accepted", "changes_required", "needs_input"]
    checks: list[QualityCheck] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self):
        if len({item.code for item in self.checks}) != len(self.checks):
            raise ValueError("Duplicate quality checks.")
        for item in self.checks:
            if (item.verdict == "accepted") != (not item.issues):
                raise ValueError("A failed check needs actionable evidence; pass has no issues.")
        expected = (
            "needs_input"
            if any(c.verdict == "needs_input" for c in self.checks)
            else "changes_required"
            if any(c.verdict == "changes_required" for c in self.checks)
            else "accepted"
        )
        if expected != self.verdict:
            raise ValueError("Overall verdict contradicts the checks.")
        return self


RUBRICS = {
    "teaching": ["request_alignment", "factual_grounding", "teaching_intent", "claim_boundaries"],
    "planning": ["goal_coverage", "prerequisites", "learner_feasibility", "source_grounding"],
    "lesson": ["objective_coverage", "source_grounding", "example_consistency", "recall_quality"],
    "artifact": ["request_alignment", "source_grounding", "revision_fidelity", "claim_boundaries"],
}
TERMINAL = {"accepted", "cancelled", "superseded"}


class Deliveries:
    def __init__(self, connection):
        self.connection = connection

    def create(self, actor, run_id, kind, focus):
        row = self.connection.execute(
            "INSERT INTO tutor.delivery_tasks(id,actor_id,run_id,kind,focus) "
            "VALUES(%s,%s,%s,%s,%s) RETURNING *",
            (uuid4(), actor.id, run_id, kind, Jsonb(focus)),
        ).fetchone()
        return self.summary(row)

    def for_run(self, run_id):
        return self.connection.execute(
            "SELECT * FROM tutor.delivery_tasks WHERE run_id=%s", (run_id,)
        ).fetchone()

    def row(self, actor, task_id):
        row = self.connection.execute(
            "SELECT * FROM tutor.delivery_tasks WHERE actor_id=%s AND id=%s",
            (actor.id, task_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Delivery task not found.")
        return row

    @staticmethod
    def summary(row):
        return DeliveryTask(
            **{key: row[key] for key in DeliveryTask.model_fields if key in row},
            can_resume=row["status"] in {"waiting_input", "waiting_dependency", "waiting_config"}
            and not row["cancel_requested"],
            required_input=[item.get("repair_instruction", "") for item in row["issues"]]
            if row["status"] == "waiting_input"
            else [],
        )

    def page(self, actor, before=None, limit=50):
        anchor = self.row(actor, before) if before else None
        rows = self.connection.execute(
            "SELECT * FROM tutor.delivery_tasks WHERE actor_id=%s "
            + ("AND (created_at,id)<(%s,%s) " if anchor else "")
            + "ORDER BY created_at DESC,id DESC LIMIT %s",
            (actor.id, *((anchor["created_at"], anchor["id"]) if anchor else ()), limit),
        ).fetchall()
        return [self.summary(row) for row in rows]

    def context(self, task_id, messages, manifest):
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET author_messages=%s,context_manifest=%s WHERE id=%s",
            (Jsonb(messages), Jsonb(manifest), task_id),
        )

    def state(self, task_id, status, *, issues=None):
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET status=%s,updated_at=now(),"
            "issues=COALESCE(%s,issues),next_action_at=CASE WHEN %s='waiting_dependency' "
            "THEN now()+interval '30 seconds' ELSE now() END WHERE id=%s",
            (status, Jsonb(issues) if issues is not None else None, status, task_id),
        )

    def candidate(self, row, call_id, text, messages):
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET candidate_call_id=%s,candidate=%s,status='checking',"
            "revision=revision+1,candidate_input=%s,phase='review',updated_at=now() WHERE id=%s",
            (call_id, text, Jsonb(messages), row["id"]),
        )

    def check(self, row, call_id, verdict, issues):
        self.connection.execute(
            "INSERT INTO tutor.delivery_checks"
            "(id,task_id,candidate_call_id,review_call_id,verdict,issues) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                row["id"],
                row["candidate_call_id"],
                call_id,
                verdict,
                Jsonb(
                    {
                        "issues": issues,
                        "candidate": row["candidate"],
                        "input": row["author_messages"],
                    }
                ),
            ),
        )

    def rejected_unchanged(self, row, candidate):
        return (
            self.connection.execute(
                "SELECT id FROM tutor.delivery_checks WHERE task_id=%s "
                "AND verdict='changes_required' AND issues->>'candidate'=%s "
                "AND issues->'input'=%s LIMIT 1",
                (row["id"], candidate, Jsonb(row["author_messages"])),
            ).fetchone()
            is not None
        )

    def repair(self, row, issues, *, truncated=False):
        previous = {item.get("code") for item in row["issues"]}
        recurring = bool(previous & {item.get("code") for item in issues})
        recurring = (
            recurring
            or self.connection.execute(
                "SELECT id FROM tutor.delivery_checks WHERE task_id=%s "
                "AND candidate_call_id IS DISTINCT FROM %s AND EXISTS("
                "SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(issues)='object' "
                "THEN issues->'issues' ELSE issues END) issue "
                "WHERE issue->>'code'=ANY(%s)) LIMIT 1",
                (row["id"], row["candidate_call_id"], [item.get("code") for item in issues]),
            ).fetchone()
            is not None
        )
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET status='repairing',phase='author',issues=%s,"
            "repair_strategy=%s,output_multiplier=output_multiplier*%s,"
            "updated_at=now() WHERE id=%s",
            (
                Jsonb(issues),
                "redesign" if recurring else "diagnostic",
                2 if truncated else 1,
                row["id"],
            ),
        )

    def fragments(self, task_id, fragments):
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET fragments=%s WHERE id=%s",
            (Jsonb(fragments), task_id),
        )
