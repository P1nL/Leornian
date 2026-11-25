from datetime import UTC, datetime
from uuid import UUID, uuid4

from psycopg import Connection

from leornian.modules.identity.contracts import Actor
from leornian.modules.tutor.contracts import Conversation, Turn
from leornian.shared_kernel.errors import BusinessError

CONVERSATION_COLUMNS = "id, goal_id, created_at, hidden_from_recents"
TURN_COLUMNS = (
    "id, user_text, assistant_text, created_at, completed_at, purpose, "
    "plan_base_revision, lesson_request_id, context_focus, learning_interaction, "
    "teaching_branch_id, teaching_intent_id, material_demand_id, stage_replies, "
    "planning_requested, planning_state, pacing"
)


class PgTutorStore:
    def __init__(self, connection: Connection):
        self.connection = connection

    def studied_nodes(self, conversation_id):
        return self.connection.execute(
            "SELECT DISTINCT context_focus->>'plan_id' AS plan_id,"
            "(context_focus->>'expected_plan_revision')::int AS plan_revision,"
            "context_focus->>'node_key' AS node_key FROM tutor.turns "
            "WHERE conversation_id=%s AND purpose='teaching' AND completed_at IS NOT NULL "
            "AND assistant_text IS NOT NULL AND teaching_intent_id IS NULL "
            "AND context_focus->>'kind'='node'",
            (conversation_id,),
        ).fetchall()

    def view(self, row):
        ended = self.connection.execute(
            "SELECT DISTINCT command->'focus'->>'plan_id' AS plan_id,"
            "(command->'focus'->>'expected_plan_revision')::int AS plan_revision,"
            "command->'focus'->>'node_key' AS node_key FROM tutor.teaching_session_commands "
            "WHERE conversation_id=%s AND command->>'action'='finish_node'", (row["id"],),
        ).fetchall()
        return Conversation(**row, studied_nodes=self.studied_nodes(row["id"]), ended_nodes=ended)

    def conversation(self, actor: Actor, goal_id: UUID) -> Conversation:
        self.connection.execute(
            "INSERT INTO tutor.conversations(id, actor_id, goal_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (actor_id, goal_id) DO NOTHING",
            (uuid4(), actor.id, goal_id),
        )
        return Conversation(
            **self.connection.execute(
                f"SELECT {CONVERSATION_COLUMNS} FROM tutor.conversations "
                "WHERE actor_id = %s AND goal_id = %s",
                (actor.id, goal_id),
            ).fetchone()
        )

    def get(
        self, actor: Actor, conversation_id: UUID, *, lock: bool = False
    ) -> Conversation | None:
        row = self.connection.execute(
            f"SELECT {CONVERSATION_COLUMNS} FROM tutor.conversations "
            "WHERE id = %s AND actor_id = %s" + (" FOR UPDATE" if lock else ""),
            (conversation_id, actor.id),
        ).fetchone()
        return self.view(row) if row else None

    def hide_from_recents(self, actor: Actor, conversation_id: UUID) -> Conversation:
        row = self.connection.execute(
            "UPDATE tutor.conversations SET hidden_from_recents=true "
            f"WHERE id=%s AND actor_id=%s RETURNING {CONVERSATION_COLUMNS}",
            (conversation_id, actor.id),
        ).fetchone()
        return self.view(row)

    def turns(self, conversation_id: UUID) -> list[Turn]:
        rows = self.connection.execute(
            f"SELECT {TURN_COLUMNS} FROM (SELECT {TURN_COLUMNS} FROM tutor.turns "
            "WHERE conversation_id = %s ORDER BY created_at DESC, id DESC LIMIT 100) t "
            "ORDER BY created_at, id",
            (conversation_id,),
        ).fetchall()
        return [Turn(**row) for row in rows]

    def get_turn(self, conversation_id: UUID, turn_id: UUID) -> Turn | None:
        row = self.connection.execute(
            f"SELECT {TURN_COLUMNS} FROM tutor.turns WHERE conversation_id = %s AND id = %s",
            (conversation_id, turn_id),
        ).fetchone()
        return Turn(**row) if row else None

    def requested_turn(self, conversation_id: UUID, key: str) -> Turn | None:
        row = self.connection.execute(
            f"SELECT {TURN_COLUMNS} FROM tutor.turns "
            "WHERE conversation_id=%s AND idempotency_key=%s",
            (conversation_id, key),
        ).fetchone()
        return Turn(**row) if row else None

    def request_turn(
        self,
        conversation_id: UUID,
        key: str,
        text: str,
        purpose: str = "teaching",
        plan_base_revision: int | None = None,
        lesson_request_id: UUID | None = None,
        teaching_intent_id: UUID | None = None,
    ) -> tuple[Turn, bool]:
        row = self.connection.execute(
            f"INSERT INTO tutor.turns(id, conversation_id, idempotency_key, user_text, "
            f"purpose, plan_base_revision, lesson_request_id,teaching_intent_id) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            f"ON CONFLICT DO NOTHING RETURNING {TURN_COLUMNS}",
            (uuid4(), conversation_id, key, text, purpose, plan_base_revision, lesson_request_id,
             teaching_intent_id),
        ).fetchone()
        if row:
            return Turn(**row), True
        return Turn(
            **self.connection.execute(
                f"SELECT {TURN_COLUMNS} FROM tutor.turns "
                "WHERE conversation_id = %s AND idempotency_key = %s",
                (conversation_id, key),
            ).fetchone()
        ), False

    def complete(self, turn_id: UUID, text: str) -> None:
        self.connection.execute(
            "UPDATE tutor.turns SET assistant_text = %s, completed_at = now() "
            "WHERE id = %s AND assistant_text IS NULL",
            (text, turn_id),
        )

    def bind_material_demand(self, turn_id, demand_id):
        self.connection.execute(
            "UPDATE tutor.turns SET material_demand_id=%s WHERE id=%s", (demand_id, turn_id),
        )

    def material_consumer_turns(self, actor_id, demand_id):
        return [
            row["id"] for row in self.connection.execute(
                "SELECT t.id FROM tutor.turns t JOIN tutor.conversations c "
                "ON c.id=t.conversation_id WHERE c.actor_id=%s AND t.material_demand_id=%s",
                (actor_id, demand_id),
            ).fetchall()
        ]

    def planning_state(self, turn_id, state):
        from psycopg.types.json import Jsonb

        self.connection.execute(
            "UPDATE tutor.turns SET planning_state=%s,planning_requested=%s WHERE id=%s",
            (Jsonb(state.model_dump(mode="json")), state.plan_requested, turn_id),
        )

    def reopen_material_wait(self, turn_id):
        self.connection.execute(
            "UPDATE tutor.turns SET assistant_text=NULL,completed_at=NULL,"
            "planning_state=jsonb_set(planning_state,'{material_blocked}','false') "
            "WHERE id=%s AND purpose='planning' "
            "AND planning_state->>'material_blocked'='true'", (turn_id,),
        )

    def ready_to_plan(self, conversation_id, revision=None, *, exclude_turn=None):
        turn = next((
            item for item in reversed(self.turns(conversation_id))
            if item.purpose == "planning" and item.id != exclude_turn
        ), None)
        saved = self.connection.execute(
            "SELECT revision FROM tutor.route_requirements WHERE conversation_id=%s",
            (conversation_id,),
        ).fetchone()
        if (
            not turn or not turn.completed_at or not turn.planning_state
            or not turn.planning_state.information_complete
            or turn.planning_state.missing_information or not saved
            or saved["revision"] != turn.planning_state.requirements_revision
            or (revision is not None and revision != saved["revision"])
        ):
            raise BusinessError(
                "precondition_failed", "请先补齐制定计划所需的信息，再开始制定计划。",
            )
        return turn.planning_state

    def stage_reply(self, turn_id, candidate_call_id, text):
        from psycopg.types.json import Jsonb

        from leornian.delivery.events import Events
        from leornian.modules.tutor.contracts import StageReply

        owner = self.connection.execute(
            "SELECT c.actor_id FROM tutor.turns t JOIN tutor.conversations c "
            "ON c.id=t.conversation_id WHERE t.id=%s", (turn_id,),
        ).fetchone()
        events = Events(self.connection)
        reply = StageReply(
            id=candidate_call_id, text=text, created_at=datetime.now(UTC),
            thinking_text=events.thinking(owner["actor_id"], [turn_id]).get(str(turn_id)),
            thinking_steps=events.thinking_steps(
                owner["actor_id"], [turn_id],
            ).get(str(turn_id), []),
        )
        row = self.connection.execute(
            "UPDATE tutor.turns SET stage_replies=stage_replies||%s::jsonb "
            "WHERE id=%s AND NOT stage_replies @> %s::jsonb RETURNING id",
            (Jsonb([reply.model_dump(mode="json")]), turn_id,
             Jsonb([{"id": str(candidate_call_id)}])),
        ).fetchone()
        return reply if row else None

    def bind_focus(self, turn_id, focus):
        from psycopg.types.json import Jsonb

        self.connection.execute(
            "UPDATE tutor.turns SET context_focus=%s WHERE id=%s",
            (Jsonb(focus.model_dump(mode="json")), turn_id),
        )

    def bind_interaction(self, turn_id, interaction, pacing=None):
        from psycopg.types.json import Jsonb

        self.connection.execute(
            "UPDATE tutor.turns SET learning_interaction=%s,pacing=%s "
            "WHERE id=%s AND assistant_text IS NULL",
            (Jsonb(interaction.model_dump(mode="json")),
             Jsonb(pacing.model_dump(mode="json")) if pacing else None, turn_id),
        )

    def teaching_history(self, conversation_id, focus, branch_id=None):
        rows = self.connection.execute(
            f"SELECT {TURN_COLUMNS} FROM tutor.turns WHERE conversation_id=%s "
            "AND purpose='teaching' AND completed_at IS NOT NULL "
            "AND (teaching_branch_id IS NOT DISTINCT FROM %s OR id=("
            "SELECT a.source_turn_id FROM tutor.teaching_branches b "
            "JOIN tutor.learning_artifacts a ON a.id=b.anchor_artifact_id WHERE b.id=%s)) "
            "AND (context_focus->>'kind'='goal' OR "
            "(context_focus->>'plan_id'=%s AND context_focus->>'expected_plan_revision'=%s "
            "AND context_focus->>'node_key'=%s)) ORDER BY created_at,id",
            (
                conversation_id,
                branch_id,
                branch_id,
                str(focus.plan_id),
                str(focus.expected_plan_revision),
                focus.node_key,
            ),
        ).fetchall()
        return [Turn(**row) for row in rows]

    def page(self, conversation_id, before=None, limit=50):
        anchor = self.get_turn(conversation_id, before) if before else None
        if before and not anchor:
            raise BusinessError("not_found", "History cursor does not belong to this conversation.")
        rows = self.connection.execute(
            f"SELECT {TURN_COLUMNS} FROM tutor.turns WHERE conversation_id=%s "
            + ("AND (created_at,id)<(%s,%s) " if anchor else "")
            + "ORDER BY created_at DESC,id DESC LIMIT %s",
            (conversation_id, *((anchor.created_at, anchor.id) if anchor else ()), limit),
        ).fetchall()
        return [Turn(**row) for row in rows]

    def list_conversations(self, actor: Actor) -> list[Conversation]:
        rows = self.connection.execute(
            f"SELECT {CONVERSATION_COLUMNS} FROM tutor.conversations "
            "WHERE actor_id = %s ORDER BY created_at DESC, id DESC LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [self.view(row) for row in rows]

    def gate_context(self, actor):
        rows = self.connection.execute(
            "SELECT t.id,CASE WHEN t.teaching_intent_id IS NULL THEN t.user_text ELSE '' END "
            "AS user_text,t.assistant_text FROM tutor.turns t "
            "JOIN tutor.conversations c ON c.id=t.conversation_id "
            "WHERE c.actor_id=%s AND t.purpose!='item_supply' AND t.completed_at IS NOT NULL "
            "ORDER BY t.created_at,t.id",
            (actor.id,),
        ).fetchall()
        return [{**row, "id": str(row["id"])} for row in rows]
