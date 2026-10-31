from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from psycopg import Connection

from leornian.modules.identity.contracts import Actor
from leornian.modules.knowledge.contracts import (
    Material,
    Source,
    SourceInput,
    SourceRef,
    SourceRevision,
)
from leornian.shared_kernel.errors import BusinessError

PROJECTION = (
    "s.id, s.goal_id, s.current_revision AS revision, s.admission, s.valid_until, "
    "s.created_at, v.title, v.source_url, v.excerpt, v.origin, "
    "(s.admission = 'admitted' AND s.valid_until > now()) AS usable "
)
JOIN = (
    "FROM knowledge.sources s JOIN knowledge.source_versions v "
    "ON v.source_id = s.id AND v.revision = s.current_revision "
)


class Knowledge:
    def __init__(self, connection: Connection):
        self.connection = connection

    def get(self, actor: Actor, source_id: UUID, *, lock: bool = False) -> Source:
        row = self.connection.execute(
            "SELECT "
            + PROJECTION
            + JOIN
            + "WHERE s.id = %s AND s.actor_id = %s "
            + ("FOR UPDATE OF s" if lock else ""),
            (source_id, actor.id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Source not found.")
        return Source(**row)

    def list(self, actor: Actor) -> list[Source]:
        return [
            Source(**row)
            for row in self.connection.execute(
                "SELECT " + PROJECTION + JOIN + "WHERE s.actor_id = %s "
                "ORDER BY s.created_at DESC, s.id LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def create(
        self, actor: Actor, goal_id: UUID, key: str, data: SourceInput
    ) -> tuple[Source, bool]:
        row = self.connection.execute(
            "INSERT INTO knowledge.sources(id, actor_id, goal_id, idempotency_key) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
            (uuid4(), actor.id, goal_id, key),
        ).fetchone()
        if row:
            self._version(row["id"], 1, data)
            return self.get(actor, row["id"]), True
        row = self.connection.execute(
            "SELECT id, goal_id FROM knowledge.sources "
            "WHERE actor_id = %s AND idempotency_key = %s",
            (actor.id, key),
        ).fetchone()
        original = self.connection.execute(
            "SELECT title, source_url, excerpt FROM knowledge.source_versions "
            "WHERE source_id = %s AND revision = 1",
            (row["id"],),
        ).fetchone()
        if row["goal_id"] != goal_id or original != data.model_dump():
            raise BusinessError("idempotency_conflict", "Source request key has different content.")
        return self.get(actor, row["id"]), False

    def _version(self, source_id: UUID, revision: int, data: SourceInput) -> None:
        self.connection.execute(
            "INSERT INTO knowledge.source_versions"
            "(source_id, revision, title, source_url, excerpt) "
            "VALUES (%s, %s, %s, %s, %s)",
            (source_id, revision, data.title, data.source_url, data.excerpt),
        )

    def revise(self, actor: Actor, source_id: UUID, data: SourceRevision) -> tuple[Source, bool]:
        source = self.get(actor, source_id, lock=True)
        fields = data.model_dump(exclude={"expected_revision"})
        if source.revision == data.expected_revision + 1 and all(
            getattr(source, key) == value for key, value in fields.items()
        ):
            return source, False
        self._revision(source, data.expected_revision)
        self._version(source_id, source.revision + 1, data)
        self.connection.execute(
            "UPDATE knowledge.sources SET current_revision = current_revision + 1, "
            "admission = 'pending', valid_until = NULL, admitted_at = NULL, revoked_at = NULL "
            "WHERE id = %s",
            (source_id,),
        )
        return self.get(actor, source_id), True

    @staticmethod
    def _revision(source: Source, revision: int):
        if source.revision != revision:
            raise BusinessError("stale_version", "Source revision changed.")

    def admit(
        self, actor: Actor, source_id: UUID, revision: int, valid_until: datetime
    ) -> tuple[Source, bool]:
        if valid_until.tzinfo is None or valid_until <= datetime.now(UTC):
            raise BusinessError(
                "source_not_current", "Source admission needs a future expiry with timezone."
            )
        source = self.get(actor, source_id, lock=True)
        self._revision(source, revision)
        if source.admission == "admitted" and source.valid_until == valid_until:
            return source, False
        self.connection.execute(
            "UPDATE knowledge.sources SET admission = 'admitted', valid_until = %s, "
            "admitted_at = now(), revoked_at = NULL WHERE id = %s",
            (valid_until, source_id),
        )
        return self.get(actor, source_id), True

    def revoke(self, actor: Actor, source_id: UUID, revision: int) -> tuple[Source, bool]:
        source = self.get(actor, source_id, lock=True)
        self._revision(source, revision)
        if source.admission == "revoked":
            return source, False
        self.connection.execute(
            "UPDATE knowledge.sources SET admission = 'revoked', revoked_at = now() WHERE id = %s",
            (source_id,),
        )
        return self.get(actor, source_id), True

    def materials(self, actor: Actor, goal_id: UUID) -> list[Material]:
        rows = self.connection.execute(
            "SELECT " + PROJECTION + JOIN + "WHERE s.actor_id = %s AND s.goal_id = %s "
            "AND s.admission = 'admitted' AND s.valid_until > now() "
            "ORDER BY s.created_at DESC, s.id LIMIT 3 FOR SHARE OF s",
            (actor.id, goal_id),
        ).fetchall()
        return [self._material(Source(**row)) for row in rows]

    def current(self, actor: Actor, goal_id: UUID, refs: list[SourceRef]) -> list[Material]:
        result = []
        for ref in sorted(refs, key=lambda item: str(item.source_id)):
            row = self.connection.execute(
                "SELECT " + PROJECTION + JOIN + "WHERE s.id = %s AND s.actor_id = %s "
                "AND s.goal_id = %s FOR SHARE OF s",
                (ref.source_id, actor.id, goal_id),
            ).fetchone()
            if not row or not row["usable"] or row["revision"] != ref.revision:
                raise BusinessError(
                    "source_not_current", "Bound source expired, changed or was revoked."
                )
            result.append(self._material(Source(**row)))
        return result

    @staticmethod
    def _material(source: Source) -> Material:
        return Material(
            source_id=source.id,
            revision=source.revision,
            title=source.title,
            source_url=source.source_url,
            excerpt=source.excerpt,
            origin=source.origin,
            valid_until=source.valid_until,
        )
