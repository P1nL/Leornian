from uuid import UUID, uuid4

from psycopg import Connection

from leornian.modules.identity.contracts import Actor
from leornian.modules.tutor.contracts import Conversation, Turn
from leornian.shared_kernel.errors import BusinessError

TURN_COLUMNS = (
    "id, user_text, assistant_text, created_at, completed_at, purpose, "
    "plan_base_revision, lesson_request_id, context_focus"
)


class PgTutorStore:
    def __init__(self, connection: Connection):
        self.connection = connection

    def conversation(self, actor: Actor, goal_id: UUID) -> Conversation:
        self.connection.execute(
            "INSERT INTO tutor.conversations(id, actor_id, goal_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (actor_id, goal_id) DO NOTHING",
            (uuid4(), actor.id, goal_id),
        )
        return Conversation(
            **self.connection.execute(
                "SELECT id, goal_id, created_at FROM tutor.conversations "
                "WHERE actor_id = %s AND goal_id = %s",
                (actor.id, goal_id),
            ).fetchone()
        )

    def get(
        self, actor: Actor, conversation_id: UUID, *, lock: bool = False
    ) -> Conversation | None:
        row = self.connection.execute(
            "SELECT id, goal_id, created_at FROM tutor.conversations "
            "WHERE id = %s AND actor_id = %s" + (" FOR UPDATE" if lock else ""),
            (conversation_id, actor.id),
        ).fetchone()
        return Conversation(**row) if row else None

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

    def request_turn(
        self,
        conversation_id: UUID,
        key: str,
        text: str,
        purpose: str = "teaching",
        plan_base_revision: int | None = None,
        lesson_request_id: UUID | None = None,
    ) -> tuple[Turn, bool]:
        row = self.connection.execute(
            f"INSERT INTO tutor.turns(id, conversation_id, idempotency_key, user_text, "
            f"purpose, plan_base_revision, lesson_request_id) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            f"ON CONFLICT DO NOTHING RETURNING {TURN_COLUMNS}",
            (uuid4(), conversation_id, key, text, purpose, plan_base_revision, lesson_request_id),
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

    def bind_focus(self, turn_id, focus):
        from psycopg.types.json import Jsonb

        self.connection.execute(
            "UPDATE tutor.turns SET context_focus=%s WHERE id=%s",
            (Jsonb(focus.model_dump(mode="json")), turn_id),
        )

    def teaching_history(self, conversation_id, focus):
        rows = self.connection.execute(
            f"SELECT {TURN_COLUMNS} FROM tutor.turns WHERE conversation_id=%s "
            "AND purpose='teaching' AND completed_at IS NOT NULL "
            "AND (context_focus->>'kind'='goal' OR "
            "(context_focus->>'plan_id'=%s AND context_focus->>'expected_plan_revision'=%s "
            "AND context_focus->>'node_key'=%s)) ORDER BY created_at,id",
            (
                conversation_id,
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
            "SELECT id, goal_id, created_at FROM tutor.conversations "
            "WHERE actor_id = %s ORDER BY created_at DESC, id DESC LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [Conversation(**row) for row in rows]

    def gate_context(self, actor):
        rows = self.connection.execute(
            "SELECT t.id,t.user_text,t.assistant_text FROM tutor.turns t "
            "JOIN tutor.conversations c ON c.id=t.conversation_id "
            "WHERE c.actor_id=%s AND t.purpose!='item_supply' AND t.completed_at IS NOT NULL "
            "ORDER BY t.created_at,t.id",
            (actor.id,),
        ).fetchall()
        return [{**row, "id": str(row["id"])} for row in rows]
