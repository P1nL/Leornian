"""Tutor owns delivery coordination, not plans, lessons, grading or mastery."""

import json
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
    last_progress_at: datetime | None = None
    reason_code: str | None = None


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
        blockage = row.get("context_manifest", {}).get("material_blockage") if row["status"] in {
            "waiting_input", "waiting_config", "waiting_dependency",
        } else None
        required_input = (
            [item.get("repair_instruction", "") for item in row["issues"]]
            if row["status"] == "waiting_input" else []
        )
        if required_input and row.get("context_manifest", {}).get("learning_hint_contract") == 1:
            # Private review findings may quote levels the learner has not requested.
            required_input = [
                "The hint review needs more input. "
                "Add clarification in the original task to resume."
            ]
        return DeliveryTask(
            **{key: row[key] for key in DeliveryTask.model_fields if key in row},
            can_resume=row["status"] in {
                "waiting_input", "waiting_dependency", "waiting_config", "blocked_protocol",
            }
            and not row["cancel_requested"]
            and blockage not in {"material_discovery_exhausted", "material_quality_pending"},
            required_input=required_input,
            reason_code="delivery_protocol_stalled"
            if row["status"] == "blocked_protocol" else blockage,
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

    def accepted_plan_review(self, conversation_id, turn_id, turn_run_ids):
        rows = self.connection.execute(
            "SELECT c.id,c.review_call_id,c.issues,d.context_manifest "
            "FROM tutor.delivery_checks c JOIN tutor.delivery_tasks d ON d.id=c.task_id "
            "JOIN unnest(%s::uuid[],%s::uuid[]) AS r(run_id,turn_id) ON r.run_id=d.run_id "
            "JOIN tutor.turns t ON t.id=r.turn_id "
            "WHERE t.conversation_id=%s AND t.id<>%s AND t.completed_at IS NOT NULL "
            "AND d.kind='planning' AND c.verdict='accepted' AND c.review_call_id IS NOT NULL "
            "AND (t.created_at,t.id)<(SELECT created_at,id FROM tutor.turns WHERE id=%s) "
            "ORDER BY t.created_at DESC,c.created_at DESC",
            (list(turn_run_ids.values()), list(turn_run_ids), conversation_id, turn_id, turn_id),
        ).fetchall()
        for row in rows:
            try:
                candidate = json.loads(row["issues"]["candidate"])
            except (ValueError, TypeError, KeyError):
                continue
            route = candidate.get("route") if isinstance(candidate, dict) else None
            if route:
                return {
                    "check_id": str(row["id"]), "review_call_id": str(row["review_call_id"]),
                    "route": route,
                    "requirements": row["context_manifest"].get("route_requirements", {}).get(
                        "learner_stated", {},
                    ),
                }
        return None

    def await_route_materials(
        self, task_id, material_demand=None, *, turn_id=None, blockage=None, route_draft=None,
    ):
        manifest = self.connection.execute(
            "SELECT context_manifest FROM tutor.delivery_tasks WHERE id=%s", (task_id,),
        ).fetchone()["context_manifest"]
        retained = manifest.get("retained_planning_refs", [])
        for ref in manifest.get("material_context_refs", []):
            if ref not in retained:
                retained.append(ref)
        updates = {"retained_planning_refs": retained, "material_blockage": blockage}
        if route_draft is not None:
            updates["planning_route_draft"] = route_draft.model_dump(mode="json")
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET author_messages='[]',candidate=NULL,"
            "candidate_call_id=NULL,fragments='[]',phase='author',"
            "context_manifest=(context_manifest-'material_preparation') || "
            "'{\"route_discussion\":1,\"planning_requested\":true,"
            "\"awaiting_route_materials\":true}'::jsonb || %s "
            "WHERE id=%s",
            (Jsonb(updates), task_id),
        )
        if material_demand:
            self.connection.execute(
                "UPDATE tutor.delivery_tasks SET context_manifest=context_manifest||%s::jsonb "
                "WHERE id=%s",
                (Jsonb({"material_demand": {
                    "id": str(material_demand.id), "revision": material_demand.revision,
                }}), task_id),
            )
        if turn_id:
            self.connection.execute(
                "UPDATE tutor.delivery_tasks SET context_manifest=context_manifest||%s::jsonb "
                "WHERE id=%s",
                (Jsonb({"material_wait_turn_id": str(turn_id)}), task_id),
            )

    def node_material_available(self, demand_id):
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET next_action_at=now() WHERE kind='teaching' "
            "AND NOT cancel_requested AND status='waiting_dependency' AND author_messages='[]' "
            "AND focus->>'kind'='node' AND context_manifest->'material_demand'->>'id'=%s",
            (str(demand_id),),
        )

    def material_ready(self, demand_id):
        self.connection.execute(
            "UPDATE tutor.delivery_tasks d SET next_action_at=now(),status='waiting_dependency' "
            "WHERE NOT cancel_requested AND "
            "(status='waiting_dependency' OR (status='waiting_input' AND EXISTS("
            "SELECT 1 FROM tutor.turns t "
            "WHERE t.id::text=d.context_manifest->>'material_wait_turn_id' "
            "AND t.planning_state->>'material_blocked'='true' "
            "AND NOT EXISTS(SELECT 1 FROM tutor.turns newer "
            "WHERE newer.conversation_id=t.conversation_id AND newer.purpose='planning' "
            "AND (newer.created_at,newer.id)>(t.created_at,t.id))))) "
            "AND context_manifest->>'awaiting_route_materials'='true' "
            "AND context_manifest->>'planning_requested'='true' "
            "AND context_manifest->'material_demand'->>'id'=%s", (str(demand_id),),
        )

    def continue_route_discussion(self, task_id):
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET next_action_at=now(),"
            "context_manifest=context_manifest-'awaiting_route_materials' "
            "WHERE id=%s AND status='waiting_dependency'", (task_id,),
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
            "revision=revision+1,candidate_input=%s,phase='review',updated_at=now(),"
            "last_progress_at=now(),protocol_repair='{}' WHERE id=%s",
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
        self.connection.execute(
            "UPDATE tutor.delivery_tasks SET last_progress_at=now(),protocol_repair='{}' "
            "WHERE id=%s", (row["id"],),
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
            "UPDATE tutor.delivery_tasks SET last_progress_at=CASE "
            "WHEN jsonb_array_length(%s::jsonb)>jsonb_array_length(fragments) THEN now() "
            "ELSE last_progress_at END,protocol_repair=CASE "
            "WHEN jsonb_array_length(%s::jsonb)>jsonb_array_length(fragments) THEN '{}'::jsonb "
            "ELSE protocol_repair END,fragments=%s WHERE id=%s",
            (Jsonb(fragments), Jsonb(fragments), Jsonb(fragments), task_id),
        )
