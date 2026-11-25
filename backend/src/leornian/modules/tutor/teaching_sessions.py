"""Tutor-owned session controls and one-level artifact question branches."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.tutor.teaching_session_contracts import (
    ReturnToMain,
    TeachingBranch,
    TeachingSession,
)
from leornian.shared_kernel.errors import BusinessError

SESSION_VIEW = """
    SELECT s.*, CASE WHEN s.focus->>'kind'='node' THEN jsonb_build_object(
        'after_turn_id', latest.id, 'next_step', CASE
            WHEN latest.id IS NULL THEN 'opening'
            WHEN latest.completed_at IS NULL THEN 'hold'
            ELSE coalesce(latest.pacing->>'next_step','hold') END) END AS node_window
    FROM tutor.teaching_sessions s LEFT JOIN LATERAL (
        SELECT t.id,t.completed_at,t.pacing FROM tutor.turns t
        WHERE s.focus->>'kind'='node' AND t.conversation_id=s.conversation_id
        AND t.context_focus->>'node_key'=s.focus->>'node_key' AND t.context_focus=s.focus
        AND t.purpose='teaching' AND (t.teaching_branch_id IS NULL OR (
            s.active_branch_id IS NULL AND t.completed_at IS NOT NULL
            AND t.pacing->>'next_step'='wrap_up'
            AND EXISTS(SELECT 1 FROM tutor.teaching_branches b
                WHERE b.id=t.teaching_branch_id AND b.state='closed')
            AND NOT EXISTS(SELECT 1 FROM tutor.turns newer
                WHERE newer.conversation_id=t.conversation_id
                AND newer.context_focus=t.context_focus
                AND newer.purpose='teaching' AND (newer.created_at,newer.id)>(t.created_at,t.id))
        ))
        ORDER BY t.created_at DESC,t.id DESC LIMIT 1
    ) latest ON true
"""


class TeachingSessions:
    def __init__(self, connection):
        self.connection = connection

    def get(self, conversation_id):
        row = self.connection.execute(
            SESSION_VIEW + " WHERE s.conversation_id=%s",
            (conversation_id,),
        ).fetchone()
        return TeachingSession(**row) if row else None

    def list(self, actor):
        rows = self.connection.execute(
            SESSION_VIEW +
            "JOIN tutor.conversations c ON c.id=s.conversation_id WHERE c.actor_id=%s "
            "ORDER BY s.updated_at DESC,s.conversation_id LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [TeachingSession(**row) for row in rows]

    def branches(self, actor, conversation_id=None, before=None, limit=20):
        cursor = None
        if before:
            cursor = self.connection.execute(
                "SELECT b.opened_at,b.id FROM tutor.teaching_branches b "
                "JOIN tutor.conversations c ON c.id=b.conversation_id "
                "WHERE b.id=%s AND c.actor_id=%s AND b.conversation_id=%s",
                (before, actor.id, conversation_id),
            ).fetchone()
            if not cursor:
                raise BusinessError("not_found", "Branch cursor is outside this conversation.")
        rows = self.connection.execute(
            "SELECT b.*,(SELECT count(*) FROM tutor.turns t "
            "WHERE t.teaching_branch_id=b.id) AS turn_count FROM tutor.teaching_branches b "
            "JOIN tutor.conversations c ON c.id=b.conversation_id WHERE c.actor_id=%s "
            + ("AND b.conversation_id=%s " if conversation_id else "")
            + ("AND (b.opened_at,b.id)<(%s,%s) " if cursor else "")
            + "ORDER BY b.opened_at DESC,b.id DESC LIMIT %s",
            (actor.id, *((conversation_id,) if conversation_id else ()),
             *((cursor["opened_at"], cursor["id"]) if cursor else ()), limit),
        ).fetchall()
        return [TeachingBranch(**row) for row in rows]

    def branch(self, conversation_id, branch_id):
        row = self.connection.execute(
            "SELECT * FROM tutor.teaching_branches WHERE id=%s AND conversation_id=%s",
            (branch_id, conversation_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Question branch not found.")
        return row

    def binding(self, turn_id):
        return self.connection.execute(
            "SELECT b.*,t.teaching_branch_id,t.conversation_id,t.created_at AS turn_started_at "
            "FROM tutor.teaching_turn_bindings b "
            "JOIN tutor.turns t ON t.id=b.turn_id WHERE b.turn_id=%s",
            (turn_id,),
        ).fetchone()

    def receipt(self, conversation_id, command):
        row = self.connection.execute(
            "SELECT command,result FROM tutor.teaching_session_commands "
            "WHERE conversation_id=%s AND client_action_id=%s",
            (conversation_id, command.client_action_id),
        ).fetchone()
        if row:
            if row["command"] != command.model_dump(mode="json"):
                raise BusinessError("idempotency_conflict", "Session command changed.")
            return TeachingSession(**row["result"])
        return None

    def command_receipt(self, conversation_id, action_id):
        row = self.connection.execute(
            "SELECT result FROM tutor.teaching_session_commands "
            "WHERE conversation_id=%s AND client_action_id=%s",
            (conversation_id, action_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "No committed teaching session command.")
        return TeachingSession(**row["result"])

    def record(self, command, session):
        self.connection.execute(
            "INSERT INTO tutor.teaching_session_commands"
            "(conversation_id,client_action_id,command,result) VALUES (%s,%s,%s,%s)",
            (session.conversation_id, command.client_action_id,
             Jsonb(command.model_dump(mode="json")), Jsonb(session.model_dump(mode="json"))),
        )

    def continuity(self, conversation_id, focus):
        rows = self.connection.execute(
            "SELECT pacing FROM tutor.turns WHERE conversation_id=%s AND context_focus=%s "
            "AND completed_at IS NOT NULL AND pacing IS NOT NULL ORDER BY created_at,id",
            (conversation_id, Jsonb(focus.model_dump(mode="json"))),
        ).fetchall()
        choice = next((row["pacing"]["practice_choice"] for row in reversed(rows)
                       if row["pacing"].get("practice_choice")), None)
        return {
            "resume_at": rows[-1]["pacing"]["resume_at"] if rows else "",
            **({"practice_choice": choice} if choice else {}),
            "checked_topics": list(dict.fromkeys(
                row["pacing"]["check_topic"] for row in rows if row["pacing"].get("check_topic")
            )),
        }

    def control(self, conversation_id, command, *, advance_to=None):
        session = self.get(conversation_id)
        if command.expected_session_revision != (session.revision if session else 0):
            raise BusinessError("stale_version", "Teaching session changed; read current state.")
        if command.action == "open":
            if session:
                raise BusinessError("precondition_failed", "Teaching session is already open.")
            self.connection.execute(
                "INSERT INTO tutor.teaching_sessions"
                "(conversation_id,revision,generation,mode,focus) VALUES (%s,1,1,%s,%s)",
                (conversation_id, command.mode, Jsonb(command.focus.model_dump(mode="json"))),
            )
        else:
            if not session:
                raise BusinessError("precondition_failed", "Open the teaching session explicitly.")
            mode, paused, focus, branch_id = (
                session.mode, session.paused, session.focus, session.active_branch_id,
            )
            policy = session.continuation_policy
            continuation_generation = session.continuation_generation
            if command.action == "set_mode":
                mode = command.mode
            elif command.action == "set_continuation_policy":
                policy = command.policy
            elif command.action in {"pause", "resume"}:
                paused = command.action == "pause"
            elif command.action in {"return_to_main", "set_topic", "finish_node"}:
                if command.action == "finish_node" and (
                    branch_id or session.focus.kind != "node" or command.focus != session.focus
                    or not session.node_window or session.node_window.next_step != "wrap_up"
                    or session.node_window.after_turn_id != command.after_turn_id
                ):
                    raise BusinessError("stale_version", "请在当前节点的收尾讲解后结束本节。")
                if command.action == "return_to_main" and command.branch_id != branch_id:
                    raise BusinessError("stale_version", "The active question branch changed.")
                if branch_id:
                    self.connection.execute(
                        "UPDATE tutor.teaching_branches SET state=%s,closed_at=now() WHERE id=%s",
                        (
                            "closed" if command.action == "return_to_main" else "superseded",
                            branch_id,
                        ),
                    )
                branch_id = None
                if command.action == "set_topic":
                    focus = command.focus
                elif advance_to is not None:
                    focus = advance_to
                if focus != session.focus and focus.kind == "node":
                    prior = self.connection.execute(
                        "SELECT result FROM tutor.teaching_session_commands "
                        "WHERE conversation_id=%s AND result->'focus'=%s "
                        "ORDER BY (result->>'revision')::int DESC LIMIT 1",
                        (conversation_id, Jsonb(focus.model_dump(mode="json"))),
                    ).fetchone()
                    if prior:
                        paused, mode = prior["result"]["paused"], prior["result"]["mode"]
            if command.action in {
                "set_mode", "set_topic", "set_continuation_policy", "finish_node",
            }:
                continuation_generation += 1
            self.connection.execute(
                "UPDATE tutor.teaching_sessions SET revision=revision+1,generation=generation+1,"
                "mode=%s,paused=%s,focus=%s,active_branch_id=%s,continuation_policy=%s,"
                "continuation_generation=%s,updated_at=now() "
                "WHERE conversation_id=%s",
                (mode, paused, Jsonb(focus.model_dump(mode="json")), branch_id, policy,
                 continuation_generation, conversation_id),
            )
        return self.get(conversation_id)

    def replay(self, turn_id, data):
        binding = self.binding(turn_id)
        if binding:
            if binding["request_payload"] != data.model_dump(mode="json"):
                raise BusinessError("idempotency_conflict", "Session-bound teaching input changed.")
        elif data.teaching_session_revision is not None:
            raise BusinessError("idempotency_conflict", "Legacy Turn has no session binding.")
        return binding

    def admit(self, actor, conversation_id, turn_id, data, *, mainline=False):
        session = self.get(conversation_id)
        if not session:
            if data.teaching_session_revision is not None:
                raise BusinessError("precondition_failed", "Open the teaching session explicitly.")
            return None
        if data.teaching_session_revision != session.revision:
            raise BusinessError("stale_version", "Teaching session changed; read current state.")
        if data.focus != session.focus:
            raise BusinessError("stale_version", "Change teaching topic with an explicit control.")
        branch_id = session.active_branch_id
        if data.node_pacing and data.text.rstrip("。！.! ").casefold() in {
            "继续", "请继续", "继续讲", "先跳过", "跳过", "跳过这道题", "返回主线",
            "continue", "skip", "skip this exercise", "back to the lesson",
        }:
            mainline = True
            if branch_id:
                command = ReturnToMain(
                    action="return_to_main", branch_id=branch_id, client_action_id=turn_id,
                    expected_session_revision=session.revision,
                )
                session = self.control(conversation_id, command)
                self.record(command, session)
                branch_id = None
        if data.node_pacing and session.node_window and session.node_window.next_step not in {
            "wait_for_action", "hold",
        }:
            mainline = True
        if not branch_id and not mainline:
            # A new topic retires old anchors without cancelling their saved artifacts.
            anchor = self.connection.execute(
                "SELECT a.id,a.revision,c.public_identity,(%s AND EXISTS("
                "SELECT 1 FROM tutor.learning_presentations p "
                "JOIN tutor.teaching_branches prior ON prior.anchor_artifact_id=a.id "
                "AND prior.conversation_id=a.conversation_id AND prior.state='closed' "
                "WHERE p.id=c.presentation_id AND p.owner_bindings='[]' AND p.review_bindings='[]' "
                "AND p.demo_bindings='[]' AND p.hint_bindings='[]')) AS returned_example "
                "FROM tutor.learning_artifacts a "
                "JOIN tutor.learning_candidates c ON c.id=a.candidate_id "
                "JOIN tutor.turns t ON t.id=a.source_turn_id "
                "LEFT JOIN tutor.teaching_turn_bindings b ON b.turn_id=t.id WHERE a.actor_id=%s "
                "AND a.conversation_id=%s AND a.state IN ('ready','active','running') "
                "AND t.teaching_branch_id IS NULL AND t.context_focus=%s "
                "AND coalesce(b.generation,0)>=coalesce(("
                "SELECT max((control.result->>'generation')::bigint) "
                "FROM tutor.teaching_session_commands control "
                "WHERE control.conversation_id=a.conversation_id "
                "AND control.command->>'action'='set_topic'),0) "
                "ORDER BY a.created_at DESC,a.id DESC LIMIT 1",
                (data.node_pacing, actor.id, conversation_id, Jsonb(session.focus.model_dump(
                    mode="json",
                ))),
            ).fetchone()
            if anchor and not anchor["returned_example"]:
                branch_id = uuid4()
                self.connection.execute(
                    "INSERT INTO tutor.teaching_branches"
                    "(id,conversation_id,generation,anchor_artifact_id,anchor_revision,"
                    "content_identity,focus,state) VALUES (%s,%s,%s,%s,%s,%s,%s,'active')",
                    (branch_id, conversation_id, session.generation, anchor["id"],
                     anchor["revision"], anchor["public_identity"],
                     Jsonb(session.focus.model_dump(mode="json"))),
                )
                self.connection.execute(
                    "UPDATE tutor.teaching_sessions SET active_branch_id=%s,"
                    "revision=revision+1,updated_at=now() WHERE conversation_id=%s",
                    (branch_id, conversation_id),
                )
        if branch_id and data.learning_candidate_id:
            raise BusinessError(
                "precondition_failed", "A question branch cannot replace its anchor."
            )
        self.connection.execute(
            "UPDATE tutor.turns SET teaching_branch_id=%s WHERE id=%s", (branch_id, turn_id),
        )
        self.connection.execute(
            "INSERT INTO tutor.teaching_turn_bindings(turn_id,generation,request_payload) "
            "VALUES (%s,%s,%s)",
            (turn_id, session.generation, Jsonb(data.model_dump(mode="json"))),
        )
        return self.binding(turn_id)

    def require_current(self, turn_id):
        binding = self.binding(turn_id)
        if not binding:
            return None
        session = self.get(binding["conversation_id"])
        if session.generation != binding["generation"] or (
            session.active_branch_id != binding["teaching_branch_id"]
        ):
            raise BusinessError("stale_version", "Teaching session or question branch changed.")
        if binding["teaching_branch_id"]:
            branch = self.branch(session.conversation_id, binding["teaching_branch_id"])
            if branch["state"] != "active":
                raise BusinessError("stale_version", "This question branch is retired.")
        return binding
