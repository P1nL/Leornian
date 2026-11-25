from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.learning.contracts import Goal, GoalInput, GoalRequest


class PgGoalStore:
    def __init__(self, connection: Connection):
        self.connection = connection

    def request(self, actor: Actor, key: str, data: GoalInput) -> GoalRequest:
        self.connection.execute(
            "INSERT INTO learning.goal_requests"
            "(id, actor_id, idempotency_key, title, motivation, material_scope) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (actor_id, idempotency_key) DO NOTHING",
            (
                uuid4(), actor.id, key, data.title, data.motivation,
                Jsonb(data.material_scope.model_dump(mode="json")) if data.material_scope else None,
            ),
        )
        row = self.connection.execute(
            "SELECT id, actor_id, title, motivation, material_scope FROM learning.goal_requests "
            "WHERE actor_id = %s AND idempotency_key = %s",
            (actor.id, key),
        ).fetchone()
        return GoalRequest(**row)

    def create(self, actor: Actor, request_id: UUID) -> Goal | None:
        self.connection.execute(
            "INSERT INTO learning.goals"
            "(id, request_id, actor_id, title, motivation, material_scope) "
            "SELECT %s, id, actor_id, title, motivation, material_scope "
            "FROM learning.goal_requests "
            "WHERE id = %s AND actor_id = %s ON CONFLICT (request_id) DO NOTHING",
            (uuid4(), request_id, actor.id),
        )
        row = self.connection.execute(
            "SELECT id, title, motivation, created_at, material_scope FROM learning.goals "
            "WHERE request_id = %s AND actor_id = %s",
            (request_id, actor.id),
        ).fetchone()
        return Goal(**row) if row else None

    def get_request(self, actor: Actor, key: str) -> GoalRequest | None:
        row = self.connection.execute(
            "SELECT id, actor_id, title, motivation, material_scope FROM learning.goal_requests "
            "WHERE actor_id = %s AND idempotency_key = %s",
            (actor.id, key),
        ).fetchone()
        return GoalRequest(**row) if row else None

    def list(self, actor: Actor) -> list[Goal]:
        rows = self.connection.execute(
            "SELECT id, title, motivation, created_at, material_scope FROM learning.goals "
            "WHERE actor_id = %s AND deleted_at IS NULL "
            "ORDER BY created_at DESC, id DESC LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [Goal(**row) for row in rows]

    def rename(self, actor, goal_id, title, motivation=None):
        row = self.connection.execute(
            "UPDATE learning.goals SET title=%s,motivation=COALESCE(%s,motivation) "
            "WHERE id=%s AND actor_id=%s "
            "AND deleted_at IS NULL RETURNING id,title,motivation,created_at,material_scope",
            (title, motivation, goal_id, actor.id),
        ).fetchone()
        return Goal(**row) if row else None

    def delete(self, actor, goal_id):
        return self.connection.execute(
            "UPDATE learning.goals SET deleted_at=COALESCE(deleted_at,now()) "
            "WHERE id=%s AND actor_id=%s RETURNING id", (goal_id, actor.id),
        ).fetchone() is not None

    def get(self, actor: Actor, goal_id: UUID) -> Goal | None:
        row = self.connection.execute(
            "SELECT id, title, motivation, created_at, material_scope FROM learning.goals "
            "WHERE id = %s AND actor_id = %s",
            (goal_id, actor.id),
        ).fetchone()
        return Goal(**row) if row else None
