from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionActionReceipt,
    CompositionArtifactSummary,
    parse_action_receipt,
)
from leornian.modules.tutor.learning_artifact_contracts import (
    LearningActionReceipt,
    LearningArtifactSummary,
)
from leornian.shared_kernel.errors import BusinessError


class LearningArtifacts:
    """Only interaction shells and action receipts; content and grades keep their owners."""

    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, conversation_id, artifact_id, *, lock=False):
        row = self.connection.execute(
            "SELECT a.*,c.pack_id,c.slot,c.public_identity,c.focus,c.presentation_id "
            "FROM tutor.learning_artifacts a "
            "JOIN tutor.learning_candidates c ON c.id=a.candidate_id "
            "WHERE a.id=%s AND a.actor_id=%s AND a.conversation_id=%s"
            + (" FOR UPDATE OF a" if lock else ""),
            (artifact_id, actor.id, conversation_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Learning artifact not found.")
        return row

    def candidate(self, actor, conversation_id, candidate_id):
        row = self.connection.execute(
            "SELECT * FROM tutor.learning_candidates WHERE id=%s AND actor_id=%s "
            "AND conversation_id=%s",
            (candidate_id, actor.id, conversation_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Learning candidate not found.")
        return row

    def node_ended(self, artifact):
        focus = artifact["focus"]
        if not focus.get("node_key"):
            return False
        return self.connection.execute(
            "SELECT 1 FROM tutor.teaching_session_commands WHERE conversation_id=%s "
            "AND command->>'action'='finish_node' AND command->'focus' @> %s LIMIT 1",
            (artifact["conversation_id"], Jsonb({
                key: focus[key] for key in ("plan_id", "expected_plan_revision", "node_key")
            })),
        ).fetchone() is not None

    def for_turn(self, actor, conversation_id, turn_id):
        row = self.connection.execute(
            "SELECT l.candidate_id,l.selection_origin FROM tutor.learning_turn_candidates l "
            "JOIN tutor.turns t ON t.id=l.turn_id JOIN tutor.conversations c "
            "ON c.id=t.conversation_id WHERE t.id=%s AND c.id=%s AND c.actor_id=%s",
            (turn_id, conversation_id, actor.id),
        ).fetchone()
        return {
            **self.candidate(actor, conversation_id, row["candidate_id"]),
            "selection_origin": row["selection_origin"],
        } if row else None

    def teaching_example_refs(self, actor, conversation_id, focus, node_keys, before, anchor_id):
        return self.connection.execute(
            "SELECT a.id,a.revision,a.source_turn_id,c.focus->>'node_key' AS node_key "
            "FROM tutor.learning_artifacts a "
            "JOIN tutor.learning_candidates c ON c.id=a.candidate_id "
            "JOIN tutor.turns t ON t.id=a.source_turn_id "
            "JOIN tutor.learning_presentations p ON p.id=c.presentation_id "
            "WHERE a.actor_id=%s AND a.conversation_id=%s AND a.state='ready' "
            "AND a.kind='learning_composition' AND t.completed_at<=%s "
            "AND c.focus->>'kind'='node' AND c.focus->>'plan_id'=%s "
            "AND c.focus->>'expected_plan_revision'=%s AND c.focus->>'node_key'=ANY(%s) "
            "AND ((%s::uuid IS NULL AND t.teaching_branch_id IS NULL) OR a.id=%s) "
            "AND (p.definition->'components' @> '[{\"component\":\"CodeEditor\"}]' OR "
            "p.definition->'components' @> '[{\"component\":\"CodeDiff\"}]') "
            "ORDER BY t.completed_at DESC,a.id DESC",
            (actor.id, conversation_id, before, str(focus.plan_id),
             str(focus.expected_plan_revision), list(node_keys), anchor_id, anchor_id),
        ).fetchall()

    def delivered(self, actor, candidate_id):
        return self.connection.execute(
            "SELECT 1 FROM tutor.learning_artifacts WHERE actor_id=%s AND candidate_id=%s "
            "UNION ALL SELECT 1 FROM tutor.learning_component_bindings b "
            "JOIN tutor.learning_artifacts a ON a.id=b.artifact_id "
            "WHERE a.actor_id=%s AND b.source_candidate_id=%s LIMIT 1",
            (actor.id, candidate_id, actor.id, candidate_id),
        ).fetchone() is not None

    def choose(self, actor, conversation_id, turn_id, candidate_id, expected_revision):
        self.candidate(actor, conversation_id, candidate_id)
        self.connection.execute(
            "INSERT INTO tutor.learning_turn_candidates"
            "(turn_id,candidate_id,expected_teaching_revision,selection_origin) "
            "VALUES (%s,%s,%s,'model')",
            (turn_id, candidate_id, expected_revision),
        )

    def advance(self, actor, conversation_id, expected_revision):
        updated = self.connection.execute(
            "UPDATE tutor.conversations SET teaching_revision=teaching_revision+1 "
            "WHERE id=%s AND actor_id=%s AND teaching_revision=%s RETURNING id",
            (conversation_id, actor.id, expected_revision),
        ).fetchone()
        if not updated:
            raise BusinessError("stale_version", "Teaching version changed before publication.")

    def list(
        self, actor, conversation_id=None, *, before=None, limit=20,
        include_compositions=False,
    ):
        rows = self.connection.execute(
            "SELECT * FROM tutor.learning_artifacts WHERE actor_id=%s "
            "AND (%s OR kind<>'learning_composition') "
            "AND (%s::uuid IS NULL OR conversation_id=%s) "
            "AND (%s::uuid IS NULL OR (created_at,id)<"
            "(SELECT created_at,id FROM tutor.learning_artifacts WHERE id=%s AND actor_id=%s)) "
            "ORDER BY created_at DESC,id DESC LIMIT %s",
            (
                actor.id, include_compositions, conversation_id, conversation_id,
                before, before, actor.id, limit,
            ),
        ).fetchall()
        return [
            (CompositionArtifactSummary if row["kind"] == "learning_composition"
             else LearningArtifactSummary)(
                **{k: row[k] for k in LearningArtifactSummary.model_fields if k in row}
            )
            for row in rows
        ]

    def replay(self, actor, artifact_id, data):
        row = self.connection.execute(
            "SELECT * FROM tutor.learning_artifact_actions "
            "WHERE actor_id=%s AND client_action_id=%s",
            (actor.id, data.client_action_id),
        ).fetchone()
        if row:
            if row["artifact_id"] != artifact_id or row["request"] != data.model_dump(mode="json"):
                raise BusinessError("idempotency_conflict", "Learning action input changed.")
            return parse_action_receipt(row["result"])
        return None

    def action_receipt(self, actor, conversation_id, artifact_id, action_id):
        self.row(actor, conversation_id, artifact_id)
        row = self.connection.execute(
            "SELECT result FROM tutor.learning_artifact_actions "
            "WHERE actor_id=%s AND artifact_id=%s AND client_action_id=%s",
            (actor.id, artifact_id, action_id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "No committed action receipt.")
        return parse_action_receipt(row["result"])

    def remember_component(self, actor, artifact, data, *, assistance_receipt_id=None):
        current = self.row(actor, artifact["conversation_id"], artifact["id"])
        component = self.connection.execute(
            "SELECT * FROM tutor.learning_component_bindings "
            "WHERE artifact_id=%s AND component_id=%s",
            (artifact["id"], data.component_id),
        ).fetchone()
        result_id = assistance_receipt_id or (
            component["choice_result_id"] or component["python_attempt_id"]
            or component["response_result_id"] or component["program_attempt_id"]
        )
        receipt = CompositionActionReceipt(
            client_action_id=data.client_action_id, artifact_id=artifact["id"],
            artifact_revision=current["revision"], state=current["state"],
            component_id=data.component_id, component_state=component["state"],
            result_owner="assessment" if result_id else None, result_id=result_id,
        )
        self.connection.execute(
            "INSERT INTO tutor.learning_artifact_actions"
            "(actor_id,client_action_id,artifact_id,request,result) VALUES(%s,%s,%s,%s,%s)",
            (
                actor.id, data.client_action_id, artifact["id"],
                Jsonb(data.model_dump(mode="json")), Jsonb(receipt.model_dump(mode="json")),
            ),
        )
        return receipt

    def remember(self, actor, row, data):
        result_id = row["choice_result_id"] or row["python_attempt_id"]
        receipt = LearningActionReceipt(
            client_action_id=data.client_action_id,
            artifact_id=row["id"],
            artifact_revision=row["revision"],
            state=row["state"],
            result_owner="assessment" if result_id else None,
            result_id=result_id,
        )
        self.connection.execute(
            "INSERT INTO tutor.learning_artifact_actions"
            "(actor_id,client_action_id,artifact_id,request,result) VALUES (%s,%s,%s,%s,%s)",
            (
                actor.id,
                data.client_action_id,
                row["id"],
                Jsonb(data.model_dump(mode="json")),
                Jsonb(receipt.model_dump(mode="json")),
            ),
        )
        return receipt

    def publish(self, actor, conversation_id, turn_id, candidate):
        link = self.connection.execute(
            "SELECT expected_teaching_revision FROM tutor.learning_turn_candidates "
            "WHERE turn_id=%s",
            (turn_id,),
        ).fetchone()
        self.advance(actor, conversation_id, link["expected_teaching_revision"])
        artifact_id = uuid4()
        self.connection.execute(
            "INSERT INTO tutor.learning_artifacts"
            "(id,actor_id,conversation_id,source_turn_id,timeline_item_id,candidate_id,kind) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                artifact_id,
                actor.id,
                conversation_id,
                turn_id,
                uuid4(),
                candidate["id"],
                candidate["kind"],
            ),
        )
        return self.row(actor, conversation_id, artifact_id)

    def owner_result(self, actor, pack_id, slot, kind, result_id, state):
        field = "choice_result_id" if kind == "choice" else "python_attempt_id"
        return self.connection.execute(
            "UPDATE tutor.learning_artifacts a SET state=%s," + field + "=%s,revision=revision+1 "
            "FROM tutor.learning_candidates c WHERE c.id=a.candidate_id AND c.actor_id=%s "
            "AND c.pack_id=%s AND c.slot=%s AND a.state NOT IN ('cancelled','superseded') "
            "AND (a." + field + " IS NULL OR a." + field + "=%s) "
            "AND (a.state<>%s OR a." + field + " IS DISTINCT FROM %s) "
            "RETURNING a.id,a.conversation_id",
            (state, result_id, actor.id, pack_id, slot, result_id, state, result_id),
        ).fetchall()
