from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.assessment.gate_contracts import (
    ConceptCompletion,
    GateItemResult,
    GateRelations,
    GateRevisionFeedback,
    GateSummary,
)
from leornian.modules.assessment.transfers import Transfers
from leornian.shared_kernel.errors import BusinessError


class Gates:
    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, gate_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE actor_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (actor.id, gate_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Concept Gate not found.")
        return row

    def for_run(self, run_id):
        row = self.connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE relation_run_id=%s",
            (run_id,),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Gate relation run not found.")
        return row

    @staticmethod
    def summary(row):
        return GateSummary(**{key: row[key] for key in GateSummary.model_fields})

    def list(self, actor):
        return [
            self.summary(row)
            for row in self.connection.execute(
                "SELECT * FROM assessment.concept_gates WHERE actor_id=%s "
                "ORDER BY created_at DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def previous(self, actor, key):
        return self.connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE actor_id=%s AND idempotency_key=%s",
            (actor.id, key),
        ).fetchone()

    def active(self, actor):
        return self.connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE actor_id=%s "
            "AND status IN ('preparing','ready','in_progress','submitted')",
            (actor.id,),
        ).fetchone()

    def require_no_exam(self, actor):
        row = self.active(actor)
        if row and row["status"] in {"in_progress", "submitted"}:
            raise BusinessError("precondition_failed", "Finish or cancel the active concept Gate.")

    def require_training(self, actor, pack_id, results, remediation):
        completed = {item.slot for item in results if item.slot.startswith("practice_")}
        if completed != {"practice_1", "practice_2"}:
            raise BusinessError("precondition_failed", "Submit both practices before the Gate.")
        if any(not item.correct for item in results if item.slot.startswith("practice_")):
            if not remediation or (
                remediation.status != "passed"
                and not Transfers(self.connection).passed_for(actor, remediation.id)
            ):
                raise BusinessError(
                    "precondition_failed", "Complete the assigned remediation first."
                )

    def require_unseen_pack(self, actor, pack_id):
        started = self.connection.execute(
            "SELECT id FROM assessment.concept_gates WHERE actor_id=%s AND pack_id=%s "
            "AND started_at IS NOT NULL",
            (actor.id, pack_id),
        ).fetchone()
        if started:
            raise BusinessError("precondition_failed", "These assessment items were already used.")

    def require_new_review(self, actor, pack_id, revision, context):
        rejected = self.connection.execute(
            "SELECT id FROM assessment.concept_gates WHERE actor_id=%s AND pack_id=%s "
            "AND exposure_revision=%s AND context_data=%s "
            "AND relation_report IS NOT NULL AND error_code='assessment_not_independent' LIMIT 1",
            (actor.id, pack_id, revision, Jsonb(context)),
        ).fetchone()
        if rejected:
            raise BusinessError(
                "assessment_not_independent",
                "These unchanged materials already failed independence review; revise the pack.",
            )

    def revision_feedback(self, actor, gate_id, pack_id) -> GateRevisionFeedback:
        row = self.row(actor, gate_id)
        if (
            row["pack_id"] != pack_id
            or row["status"] != "blocked"
            or row["error_code"] != "assessment_not_independent"
            or not row["relation_report"]
        ):
            raise BusinessError(
                "precondition_failed",
                "A failed independence report for this exact pack is required.",
            )
        return GateRevisionFeedback(
            gate_id=row["id"],
            pack_id=row["pack_id"],
            policy_version=row["policy_version"],
            relation_report=row["relation_report"],
            reviewed_context=row["context_data"],
            actual_exposures=row["exposures"],
        )

    def latest_pack_feedback(self, actor, pack_id):
        row = self.connection.execute(
            "SELECT id FROM assessment.concept_gates WHERE actor_id=%s AND pack_id=%s "
            "AND status='blocked' AND error_code='assessment_not_independent' "
            "AND relation_report IS NOT NULL ORDER BY created_at DESC,id DESC LIMIT 1",
            (actor.id, pack_id),
        ).fetchone()
        return self.revision_feedback(actor, row["id"], pack_id) if row else None

    def create(self, actor, pack, lesson_id, key, revision, exposures, context, pairs):
        gate_id = uuid4()
        self.connection.execute(
            "INSERT INTO assessment.concept_gates(id,actor_id,pack_id,plan_id,plan_revision,"
            "node_key,lesson_id,idempotency_key,exposure_revision,exposures,"
            "context_data,comparisons,policy_version) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                gate_id,
                actor.id,
                pack["id"],
                pack["plan_id"],
                pack["plan_revision"],
                pack["node_key"],
                lesson_id,
                key,
                revision,
                Jsonb(exposures),
                Jsonb(context),
                Jsonb(pairs),
                "python-io-gate.v1" if pack["kind"] == "python_io" else "concept-gate.v1",
            ),
        )
        return self.row(actor, gate_id)

    def bind_run(self, gate_id, run_id):
        self.connection.execute(
            "UPDATE assessment.concept_gates SET relation_run_id=%s WHERE id=%s",
            (run_id, gate_id),
        )

    def block_run(self, run_id, code, cancelled=False):
        self.connection.execute(
            "UPDATE assessment.concept_gates SET status=%s,error_code=%s,completed_at=now() "
            "WHERE relation_run_id=%s AND status='preparing'",
            ("cancelled" if cancelled else "blocked", code, run_id),
        )

    def resume_recorded_batch(self, actor, row):
        if (
            row["status"] != "blocked"
            or row["error_code"] != "invalid_relation_batch"
            or row["relation_report"] is not None
            or row["started_at"] is not None
        ):
            raise BusinessError("resume_not_allowed", "Only a known unapplied batch can resume.")
        active = self.active(actor)
        if active and active["id"] != row["id"]:
            raise BusinessError("precondition_failed", "Finish the other active Gate first.")
        self.connection.execute(
            "UPDATE assessment.concept_gates SET status='preparing',error_code=NULL,"
            "completed_at=NULL WHERE id=%s",
            (row["id"],),
        )

    def record_relations(self, row, report: GateRelations):
        expected = {(pair["left"], pair["right"]) for pair in row["comparisons"]}
        actual = {(pair.left, pair.right) for pair in report.comparisons}
        if expected != actual:
            raise BusinessError("invalid_gate_output", "Every actual relationship must be covered.")
        supported = all(pair.verdict == "distinct_decision" for pair in report.comparisons)
        self.connection.execute(
            "UPDATE assessment.concept_gates SET relation_report=%s,status=%s,error_code=%s,"
            "completed_at=CASE WHEN %s THEN NULL ELSE now() END "
            "WHERE id=%s",
            (
                Jsonb(report.model_dump(mode="json")),
                "ready" if supported else "blocked",
                None if supported else "assessment_not_independent",
                supported,
                row["id"],
            ),
        )
        return supported

    def start(self, actor, gate_id, exposure_revision):
        row = self.row(actor, gate_id, lock=True)
        if row["status"] == "in_progress":
            return row
        if row["status"] != "ready":
            raise BusinessError("precondition_failed", "Gate is not ready to start.")
        self.connection.execute(
            "UPDATE assessment.concept_gates SET status='in_progress',started_at=now(),"
            "started_exposure_revision=%s WHERE id=%s",
            (exposure_revision, gate_id),
        )
        return self.row(actor, gate_id)

    def submitted(self, actor, gate_id, key, answers):
        row = self.row(actor, gate_id)
        if row["status"] not in {"passed", "not_passed"}:
            return None
        if row["submit_key"] != key or row["answers"] != answers:
            raise BusinessError("idempotency_conflict", "Gate submission is already locked.")
        return row

    def submit(self, actor, gate_id, key, answers, materials):
        row = self.row(actor, gate_id, lock=True)
        if row["status"] != "in_progress":
            raise BusinessError("precondition_failed", "Start the Gate before submitting.")
        selected = {answer["slot"]: answer["selected_key"] for answer in answers}
        results = [
            GateItemResult(
                slot=item.slot,
                selected_key=selected[item.slot],
                correct=selected[item.slot] == item.correct_key,
                explanation=item.explanation,
            )
            for item in materials
        ]
        passed = len(results) == 2 and all(result.correct for result in results)
        self.connection.execute(
            "UPDATE assessment.concept_gates SET status=%s,submit_key=%s,answers=%s,result=%s,"
            "completed_at=now() WHERE id=%s",
            (
                "passed" if passed else "not_passed",
                key,
                Jsonb(answers),
                Jsonb([result.model_dump(mode="json") for result in results]),
                gate_id,
            ),
        )
        return self.row(actor, gate_id), passed

    @staticmethod
    def completion(row):
        if row["status"] != "passed":
            raise BusinessError("precondition_failed", "A passed Gate is required.")
        return ConceptCompletion(
            gate_id=row["id"],
            plan_id=row["plan_id"],
            plan_revision=row["plan_revision"],
            node_key=row["node_key"],
        )

    def cancel(self, actor, gate_id):
        row = self.row(actor, gate_id, lock=True)
        if row["status"] in {"preparing", "ready", "in_progress", "submitted"}:
            self.connection.execute(
                "UPDATE assessment.concept_gates SET status='cancelled',completed_at=now() "
                "WHERE id=%s",
                (gate_id,),
            )
        return self.row(actor, gate_id)

    def queue_python(self, actor, row, key):
        if row["status"] != "in_progress" or row["policy_version"] != "python-io-gate.v1":
            raise BusinessError("precondition_failed", "Start an execution Gate first.")
        self.connection.execute(
            "UPDATE assessment.concept_gates SET status='submitted',submission_key=%s WHERE id=%s",
            (key, row["id"]),
        )

    def complete_python(self, actor, row, passed):
        self.connection.execute(
            "UPDATE assessment.concept_gates SET status=%s,completed_at=now() "
            "WHERE id=%s AND status='submitted'",
            ("passed" if passed else "not_passed", row["id"]),
        )
        return self.row(actor, row["id"])
