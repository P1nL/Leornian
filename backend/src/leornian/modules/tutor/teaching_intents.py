"""Tutor's committed result intents; external work stays in the original Runtime."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.shared_kernel.errors import BusinessError


class TeachingIntents:
    def __init__(self, connection):
        self.connection = connection

    def create_window(self, actor, session, reference):
        return self.connection.execute(
            "INSERT INTO tutor.teaching_intents(id,actor_id,conversation_id,generation,focus,"
            "content_identity,trigger_kind,trigger_ref,priority) "
            "VALUES(%s,%s,%s,%s,%s,%s,'node_window',%s,30) RETURNING *",
            (uuid4(), actor.id, session.conversation_id, session.continuation_generation,
             Jsonb(session.focus.model_dump(mode="json")), reference, reference),
        ).fetchone()

    def create_review(self, actor, session, activity, session_digest):
        return self.connection.execute(
            "INSERT INTO tutor.teaching_intents(id,actor_id,conversation_id,generation,focus,"
            "content_identity,trigger_kind,trigger_ref,priority,review_activity_id,session_digest) "
            "VALUES(%s,%s,%s,%s,%s,%s,'review_due',%s,40,%s,%s) "
            "ON CONFLICT(review_activity_id) DO NOTHING RETURNING *",
            (uuid4(), actor.id, session.conversation_id, session.continuation_generation,
             Jsonb(session.focus.model_dump(mode="json")),
             f"review:{activity['id']}:{activity['card_revision']}", str(activity["id"]),
             activity["id"], session_digest),
        ).fetchone()

    def create(self, actor, session, artifact, source_run_id, kind, reference):
        row = self.connection.execute(
            "INSERT INTO tutor.teaching_intents"
            "(id,actor_id,conversation_id,generation,focus,artifact_id,content_identity,"
            "source_run_id,trigger_kind,trigger_ref,priority) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (artifact_id,trigger_kind,trigger_ref) DO NOTHING RETURNING *",
            (uuid4(), actor.id, session.conversation_id, session.continuation_generation,
             Jsonb(session.focus.model_dump(mode="json")), artifact["id"],
             artifact["public_identity"], source_run_id, kind, reference,
             {"artifact_action": 10, "expected_result": 20, "interaction_event": 30}[kind]),
        ).fetchone()
        return row

    def row(self, actor, conversation_id, intent_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM tutor.teaching_intents WHERE id=%s AND actor_id=%s "
            "AND conversation_id=%s" + (" FOR UPDATE" if lock else ""),
            (intent_id, actor.id, conversation_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Teaching intent not found.")
        return row

    def for_turn(self, turn_id):
        return self.connection.execute(
            "SELECT i.* FROM tutor.teaching_intents i JOIN tutor.turns t "
            "ON t.teaching_intent_id=i.id WHERE t.id=%s", (turn_id,),
        ).fetchone()

    def page(self, actor, conversation_id, before=None, limit=20):
        anchor = self.row(actor, conversation_id, before) if before else None
        return self.connection.execute(
            "SELECT * FROM tutor.teaching_intents WHERE actor_id=%s AND conversation_id=%s "
            + ("AND (created_at,id)<(%s,%s) " if anchor else "")
            + "ORDER BY created_at DESC,id DESC LIMIT %s",
            (actor.id, conversation_id,
             *((anchor["created_at"], anchor["id"]) if anchor else ()), limit),
        ).fetchall()

    def pending(self, limit=20):
        return self.connection.execute(
            "SELECT * FROM tutor.teaching_intents WHERE state='pending' AND next_check_at<=now() "
            "ORDER BY next_check_at,priority,created_at,id LIMIT %s", (limit,),
        ).fetchall()

    def first(self, conversation_id):
        return self.connection.execute(
            "SELECT id FROM tutor.teaching_intents WHERE conversation_id=%s AND state='pending' "
            "ORDER BY priority,created_at,id LIMIT 1", (conversation_id,),
        ).fetchone()

    def state(self, intent_id, state, reason=None, run_id=None):
        self.connection.execute(
            "UPDATE tutor.teaching_intents SET state=%s,wait_reason=%s,"
            "run_id=coalesce(%s,run_id),updated_at=now() WHERE id=%s",
            (state, reason, run_id, intent_id),
        )

    def wait(self, intent_id, reason):
        self.connection.execute(
            "UPDATE tutor.teaching_intents SET "
            "updated_at=CASE WHEN wait_reason IS DISTINCT FROM %s THEN now() ELSE updated_at END,"
            "wait_reason=%s,next_check_at=now()+interval '5 seconds' WHERE id=%s",
            (reason, reason, intent_id),
        )

    def latest_mainline(self, actor, conversation_id, focus):
        row = self.connection.execute(
            "SELECT a.id FROM tutor.learning_artifacts a JOIN tutor.turns t "
            "ON t.id=a.source_turn_id WHERE a.actor_id=%s AND a.conversation_id=%s "
            "AND a.state NOT IN ('cancelled','superseded') AND t.teaching_branch_id IS NULL "
            "AND t.context_focus=%s ORDER BY a.created_at DESC,a.id DESC LIMIT 1",
            (actor.id, conversation_id, Jsonb(focus.model_dump(mode="json"))),
        ).fetchone()
        return row["id"] if row else None

    def invalidate(self, conversation_id, generation):
        return self.connection.execute(
            "UPDATE tutor.teaching_intents SET state='superseded',wait_reason='session_changed',"
            "updated_at=now() WHERE conversation_id=%s AND state='pending' AND generation<>%s "
            "RETURNING id", (conversation_id, generation),
        ).fetchall()

    def wake(self, conversation_id):
        self.connection.execute(
            "UPDATE tutor.teaching_intents SET next_check_at=now() "
            "WHERE conversation_id=%s AND state='pending'", (conversation_id,),
        )

    def cancellation(self, intent_id, action_id):
        row = self.connection.execute(
            "SELECT result FROM tutor.teaching_intent_cancellations "
            "WHERE intent_id=%s AND client_action_id=%s", (intent_id, action_id),
        ).fetchone()
        return row["result"] if row else None

    def remember_cancel(self, intent_id, action_id, result):
        self.connection.execute(
            "INSERT INTO tutor.teaching_intent_cancellations"
            "(intent_id,client_action_id,result) VALUES(%s,%s,%s)",
            (intent_id, action_id, Jsonb(result.model_dump(mode="json"))),
        )
