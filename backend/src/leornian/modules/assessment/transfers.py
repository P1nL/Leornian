from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.assessment.transfer_contracts import TransferSummary
from leornian.shared_kernel.errors import BusinessError


class Transfers:
    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, transfer_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM assessment.transfer_checks WHERE actor_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (actor.id, transfer_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Transfer check not found.")
        return row

    def for_run(self, run_id):
        row = self.connection.execute(
            "SELECT * FROM assessment.transfer_checks WHERE relation_run_id=%s", (run_id,)
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Transfer relation run not found.")
        return row

    @staticmethod
    def summary(row):
        return TransferSummary(**{key: row[key] for key in TransferSummary.model_fields})

    def list(self, actor):
        return [
            self.summary(row)
            for row in self.connection.execute(
                "SELECT * FROM assessment.transfer_checks WHERE actor_id=%s "
                "ORDER BY created_at DESC,id LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def previous(self, actor, key):
        return self.connection.execute(
            "SELECT * FROM assessment.transfer_checks WHERE actor_id=%s AND idempotency_key=%s",
            (actor.id, key),
        ).fetchone()

    def current_for_origin(self, actor, remediation_id, kind):
        origin = "python_remediation_id" if kind == "python_io" else "remediation_id"
        return self.connection.execute(
            "SELECT * FROM assessment.transfer_checks WHERE actor_id=%s "
            f"AND {origin}=%s AND status IN "
            "('preparing','ready','opened','submitted','passed','not_passed','error') "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (actor.id, remediation_id),
        ).fetchone()

    def require_available(self, actor, remediation_id, *, kind="choice"):
        origin = "python_remediation_id" if kind == "python_io" else "remediation_id"
        row = self.connection.execute(
            f"SELECT id FROM assessment.transfer_checks WHERE actor_id=%s AND {origin}=%s "
            "AND (status IN ('preparing','ready','opened','submitted',"
            "'passed','not_passed','error') "
            "OR opened_at IS NOT NULL)",
            (actor.id, remediation_id),
        ).fetchone()
        if row:
            raise BusinessError(
                "precondition_failed", "The exact transfer successor is already fixed."
            )

    def used_keys(self, actor):
        return [
            str(row["pack_id"]) + ":" + row["slot"]
            for row in self.connection.execute(
                "SELECT pack_id,slot FROM assessment.transfer_candidates WHERE actor_id=%s",
                (actor.id,),
            ).fetchall()
        ]

    def revision_feedback(self, actor, transfer_id, pack_id):
        row = self.row(actor, transfer_id)
        ids = sorted({item["pack_id"] for item in row["context_data"]["candidates"]})
        if (
            row["status"] != "blocked"
            or row["error_code"] != "no_independent_transfer"
            or not row["relation_report"]
            or str(pack_id) not in ids
        ):
            raise BusinessError(
                "precondition_failed", "Known transfer-quality feedback is required."
            )
        return {
            "transfer_id": str(row["id"]),
            "candidate_pack_ids": ids,
            "context": row["context_data"],
            "report": row["relation_report"],
        }

    def latest_pack_feedback(self, actor, pack_id):
        row = self.connection.execute(
            "SELECT t.id FROM assessment.transfer_checks t "
            "JOIN assessment.transfer_candidates c ON c.transfer_id=t.id "
            "WHERE t.actor_id=%s AND c.pack_id=%s AND t.status='blocked' "
            "AND t.error_code='no_independent_transfer' AND t.relation_report IS NOT NULL "
            "ORDER BY t.created_at DESC,t.id DESC LIMIT 1",
            (actor.id, pack_id),
        ).fetchone()
        return self.revision_feedback(actor, row["id"], pack_id) if row else None

    def require_regular_practice(self, actor, pack_id, slot=None):
        row = self.connection.execute(
            "SELECT 1 FROM assessment.transfer_candidates c "
            "JOIN assessment.transfer_checks t ON t.id=c.transfer_id "
            "WHERE c.actor_id=%s AND c.pack_id=%s AND (%s::text IS NULL OR c.slot=%s) "
            "AND (t.status='preparing' OR ((t.status IN ('ready','opened','submitted') "
            "OR (t.kind='python_io' AND t.opened_at IS NOT NULL)) "
            "AND t.candidate_pack_id=c.pack_id AND t.candidate_slot=c.slot)) LIMIT 1",
            (actor.id, pack_id, slot, slot),
        ).fetchone()
        if row:
            raise BusinessError(
                "precondition_failed",
                "Use the exact assigned transfer check, not regular practice.",
            )

    def create(self, actor, remediation_id, pack, key, revision, context, pairs):
        transfer_id = uuid4()
        self.connection.execute(
            "INSERT INTO assessment.transfer_checks(id,actor_id,remediation_id,"
            "python_remediation_id,kind,policy_version,source_pack_id,"
            "plan_id,plan_revision,node_key,idempotency_key,exposure_revision,context_data,comparisons)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                transfer_id,
                actor.id,
                remediation_id if pack["kind"] == "choice" else None,
                remediation_id if pack["kind"] == "python_io" else None,
                pack["kind"],
                "python-io-transfer.v1" if pack["kind"] == "python_io" else "concept-transfer.v2",
                pack["id"],
                pack["plan_id"],
                pack["plan_revision"],
                pack["node_key"],
                key,
                revision,
                Jsonb(context),
                Jsonb(pairs),
            ),
        )
        for candidate in context["candidates"]:
            self.connection.execute(
                "INSERT INTO assessment.transfer_candidates(actor_id,pack_id,slot,transfer_id) "
                "VALUES(%s,%s,%s,%s)",
                (actor.id, candidate["pack_id"], candidate["question"]["slot"], transfer_id),
            )
        return self.row(actor, transfer_id)

    def bind_run(self, transfer_id, run_id):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET relation_run_id=%s WHERE id=%s",
            (run_id, transfer_id),
        )

    def resume_relation(self, transfer_id):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status='preparing',error_code=NULL,"
            "completed_at=NULL WHERE id=%s AND status='blocked' AND relation_report IS NULL",
            (transfer_id,),
        )

    def invalidate_unopened(self, transfer_id, reason):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status='blocked',error_code=%s,"
            "completed_at=now() WHERE id=%s AND opened_at IS NULL "
            "AND status IN ('preparing','ready')",
            (reason, transfer_id),
        )

    def apply_relations(self, row, report):
        expected = {(pair["left"], pair["right"]) for pair in row["comparisons"]}
        actual = {(pair.left, pair.right) for pair in report.comparisons}
        if expected != actual:
            raise BusinessError("invalid_transfer_output", "Every actual pair must be covered.")
        verdicts = {(pair.left, pair.right): pair.verdict for pair in report.comparisons}
        selected = next(
            (
                candidate
                for candidate in row["context_data"]["candidates"]
                if all(
                    verdicts[(pair["left"], pair["right"])] == "distinct_decision"
                    for pair in row["comparisons"]
                    if pair["left"] == candidate["key"]
                )
            ),
            None,
        )
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET relation_report=%s,status=%s,error_code=%s,"
            "candidate_pack_id=%s,candidate_slot=%s,"
            "completed_at=CASE WHEN %s THEN NULL ELSE now() END "
            "WHERE id=%s",
            (
                Jsonb(report.model_dump(mode="json")),
                "ready" if selected else "blocked",
                None if selected else "no_independent_transfer",
                selected["pack_id"] if selected else None,
                selected["question"]["slot"] if selected else None,
                selected is not None,
                row["id"],
            ),
        )

    def open(self, transfer_id, revision):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status='opened',opened_at=now(),"
            "opened_exposure_revision=%s WHERE id=%s AND status='ready'",
            (revision, transfer_id),
        )

    def complete(self, transfer_id, key, result):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status=%s,result_id=%s,submit_key=%s,"
            "selected_key=%s,completed_at=now() WHERE id=%s AND status='opened'",
            (
                "passed" if result.correct else "not_passed",
                result.id,
                key,
                result.selected_key,
                transfer_id,
            ),
        )

    def queue_python(self, transfer_id, key, attempt_id):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status='submitted',submit_key=%s,"
            "python_result_id=%s WHERE id=%s AND status='opened'",
            (key, attempt_id, transfer_id),
        )

    def complete_python(self, transfer_id, attempt):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status=%s,error_code=%s,completed_at=now() "
            "WHERE id=%s AND status='submitted' AND python_result_id=%s",
            (
                attempt["status"],
                "execution_not_applicable" if attempt["status"] == "error" else None,
                transfer_id,
                attempt["id"],
            ),
        )

    def passed_for(self, actor, remediation_id, *, kind="choice"):
        origin = "python_remediation_id" if kind == "python_io" else "remediation_id"
        return (
            self.connection.execute(
                "SELECT 1 FROM assessment.transfer_checks WHERE actor_id=%s "
                f"AND {origin}=%s AND status='passed'",
                (actor.id, remediation_id),
            ).fetchone()
            is not None
        )

    def block_run(self, run_id, code, cancelled=False):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status=%s,error_code=%s,completed_at=now() "
            "WHERE relation_run_id=%s AND status='preparing'",
            ("cancelled" if cancelled else "blocked", code, run_id),
        )

    def cancel(self, actor, transfer_id):
        self.connection.execute(
            "UPDATE assessment.transfer_checks SET status='cancelled',completed_at=now() "
            "WHERE actor_id=%s AND id=%s AND status IN ('preparing','ready','opened','submitted')",
            (actor.id, transfer_id),
        )
