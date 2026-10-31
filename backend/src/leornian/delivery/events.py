from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.delivery.contracts import EventPayload, PublicEvent
from leornian.modules.identity.contracts import Actor
from leornian.shared_kernel.errors import BusinessError


class Events:
    def __init__(self, connection: Connection):
        self.connection = connection

    def append(
        self,
        actor_id: UUID,
        event_type: str,
        aggregate_id: UUID,
        payload: EventPayload,
        *,
        causation_id: UUID | None = None,
    ) -> None:
        # Per-actor row locking gives commit-ordered cursors, unlike a global SQL sequence.
        self.connection.execute(
            "INSERT INTO delivery.streams(actor_id) VALUES (%s) ON CONFLICT DO NOTHING", (actor_id,)
        )
        sequence = self.connection.execute(
            "UPDATE delivery.streams SET last_sequence = last_sequence + 1 "
            "WHERE actor_id = %s RETURNING last_sequence",
            (actor_id,),
        ).fetchone()["last_sequence"]
        self.connection.execute(
            "INSERT INTO delivery.events(actor_id, sequence, event_id, event_type, aggregate_id, "
            "correlation_id, causation_id, schema_version, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s)",
            (
                actor_id,
                sequence,
                uuid4(),
                event_type,
                aggregate_id,
                payload.job_id
                or payload.run_id
                or payload.attempt_id
                or payload.track_id
                or payload.source_id
                or payload.plan_id,
                causation_id,
                Jsonb(payload.model_dump(mode="json")),
            ),
        )

    def cursor(self, actor: Actor) -> int:
        row = self.connection.execute(
            "SELECT last_sequence FROM delivery.streams WHERE actor_id = %s", (actor.id,)
        ).fetchone()
        return row["last_sequence"] if row else 0

    def recent(self, actor: Actor) -> list[PublicEvent]:
        rows = self.connection.execute(
            "SELECT sequence, event_id, event_type, aggregate_id, correlation_id, causation_id, "
            "schema_version, occurred_at, payload FROM delivery.events "
            "WHERE actor_id = %s ORDER BY sequence DESC LIMIT 12",
            (actor.id,),
        ).fetchall()
        return [PublicEvent(**row) for row in reversed(rows)]

    def list(self, actor: Actor, after: int) -> list[PublicEvent]:
        if after < 0 or after > self.cursor(actor):
            raise BusinessError("cursor_invalid", "Refresh the snapshot to reset the event cursor.")
        rows = self.connection.execute(
            "SELECT sequence, event_id, event_type, aggregate_id, correlation_id, causation_id, "
            "schema_version, occurred_at, payload FROM delivery.events "
            "WHERE actor_id = %s AND sequence > %s ORDER BY sequence LIMIT 100",
            (actor.id, after),
        ).fetchall()
        return [PublicEvent(**row) for row in rows]
