from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.delivery.contracts import EventPayload, PublicEvent
from leornian.modules.identity.contracts import Actor
from leornian.modules.tutor.thinking_contracts import ThinkingStep
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
                or payload.plan_id
                or payload.pack_id
                or payload.artifact_job_id
                or payload.artifact_id
                or payload.learning_artifact_id
                or payload.document_id
                or payload.material_update_offer_id
                or payload.material_update_decision_id
                or payload.notification_id
                or payload.conversation_id
                or payload.goal_id,
                causation_id,
                Jsonb(payload.model_dump(mode="json")),
            ),
        )

    def cursor(self, actor: Actor) -> int:
        row = self.connection.execute(
            "SELECT last_sequence FROM delivery.streams WHERE actor_id = %s", (actor.id,)
        ).fetchone()
        return row["last_sequence"] if row else 0

    def thinking(self, actor_id: UUID, turn_ids: list[UUID], *, before=None) -> dict[str, str]:
        if not turn_ids:
            return {}
        rows = self.connection.execute(
            "SELECT DISTINCT ON (payload->>'turn_id') "
            "payload->>'turn_id' AS turn_id, payload->>'thinking_text' AS text "
            "FROM delivery.events WHERE actor_id=%s AND event_type='tutor.thinking' "
            "AND payload->>'turn_id'=ANY(%s) AND payload->>'thinking_text' IS NOT NULL "
            + ("AND occurred_at<=%s " if before else "")
            +
            "ORDER BY payload->>'turn_id', sequence DESC",
            (actor_id, [str(turn_id) for turn_id in turn_ids], *((before,) if before else ())),
        ).fetchall()
        return {row["turn_id"]: row["text"] for row in rows}

    def thinking_step(self, actor_id: UUID, step_id: UUID) -> ThinkingStep | None:
        row = self.connection.execute(
            "SELECT payload->'thinking_step' AS step FROM delivery.events "
            "WHERE actor_id=%s AND event_type='tutor.thinking' "
            "AND payload->'thinking_step'->>'id'=%s ORDER BY sequence DESC LIMIT 1",
            (actor_id, str(step_id)),
        ).fetchone()
        return ThinkingStep(**row["step"]) if row else None

    def thinking_steps(
        self, actor_id: UUID, turn_ids: list[UUID], *, before=None,
    ) -> dict[str, list[ThinkingStep]]:
        if not turn_ids:
            return {}
        rows = self.connection.execute(
            "SELECT turn_id,step FROM ("
            "SELECT DISTINCT ON (payload->'thinking_step'->>'id') "
            "payload->>'turn_id' AS turn_id,payload->'thinking_step' AS step,"
            "min(sequence) OVER (PARTITION BY payload->'thinking_step'->>'id') AS first_sequence "
            "FROM delivery.events WHERE actor_id=%s AND event_type='tutor.thinking' "
            "AND payload->>'turn_id'=ANY(%s) AND payload->'thinking_step'->>'id' IS NOT NULL "
            + ("AND occurred_at<=%s " if before else "")
            +
            "ORDER BY payload->'thinking_step'->>'id',sequence DESC"
            ") steps ORDER BY first_sequence",
            (actor_id, [str(turn_id) for turn_id in turn_ids], *((before,) if before else ())),
        ).fetchall()
        result = {}
        for row in rows:
            result.setdefault(row["turn_id"], []).append(ThinkingStep(**row["step"]))
        return result

    def attach_reply_thinking(self, actor_id, turn, text, steps):
        stages, owned = [], set()
        for reply in turn.stage_replies:
            stage_steps = reply.thinking_steps or self.thinking_steps(
                actor_id, [turn.id], before=reply.created_at,
            ).get(str(turn.id), [])
            stage_steps = [step for step in stage_steps if step.id not in owned]
            stages.append(reply.model_copy(update={
                "thinking_steps": stage_steps,
                "thinking_text": reply.thinking_text or "\n\n".join(
                    step.detail for step in stage_steps if step.kind == "thinking"
                ) or None,
            }))
            owned.update(step.id for step in stage_steps)
        remaining = [step for step in steps if step.id not in owned]
        return turn.model_copy(update={
            "stage_replies": stages, "thinking_steps": remaining,
            "thinking_text": "\n\n".join(
                step.detail for step in remaining if step.kind == "thinking"
            ) or (text if not stages else None),
        })

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
