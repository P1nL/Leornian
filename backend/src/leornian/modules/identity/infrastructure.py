from datetime import datetime
from uuid import UUID

from psycopg import Connection

from leornian.modules.identity.contracts import Actor, Session


class PgIdentityStore:
    def __init__(
        self, connection: Connection, *, lock_session: bool = False, serialize_actor: bool = False
    ):
        self.connection = connection
        self.lock_session = lock_session
        self.serialize_actor = serialize_actor

    def create(self, session: Session, digest: str) -> None:
        self.connection.execute(
            "INSERT INTO identity.learners(id, display_name) VALUES (%s, %s)",
            (session.actor.id, session.actor.display_name),
        )
        self.issue_session(session, digest)

    def issue_session(self, session: Session, digest: str) -> None:
        self.connection.execute(
            "INSERT INTO identity.sessions(token_digest, actor_id, expires_at) VALUES (%s, %s, %s)",
            (digest, session.actor.id, session.expires_at),
        )

    def renew_session(self, digest: str, expires_at: datetime) -> tuple[Actor, datetime] | None:
        row = self.connection.execute(
            "UPDATE identity.sessions s SET expires_at = GREATEST(s.expires_at, %s) "
            "FROM identity.learners l WHERE s.actor_id = l.id AND l.active "
            "AND s.token_digest = %s AND s.expires_at > now() AND s.revoked_at IS NULL "
            "RETURNING l.id, l.display_name, s.expires_at",
            (expires_at, digest),
        ).fetchone()
        if row is None:
            return None
        return Actor(id=row["id"], display_name=row["display_name"]), row["expires_at"]

    def revoke_session(self, digest: str) -> None:
        self.connection.execute(
            "UPDATE identity.sessions SET revoked_at = now() "
            "WHERE token_digest = %s AND revoked_at IS NULL",
            (digest,),
        )

    def authenticate(self, digest: str) -> Actor | None:
        row = self.connection.execute(
            "SELECT l.id, l.display_name FROM identity.sessions s "
            "JOIN identity.learners l ON l.id = s.actor_id "
            "WHERE s.token_digest = %s AND s.expires_at > now() "
            "AND s.revoked_at IS NULL AND l.active"
            + (" FOR SHARE OF l, s" if self.lock_session or self.serialize_actor else ""),
            (digest,),
        ).fetchone()
        if row and self.serialize_actor:
            # Serialize actor commands without an UPDATE lock that could deadlock with
            # Runtime's run -> current-session SHARE checks during an idempotent replay.
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("actor-command:" + str(row["id"]),),
            )
        return Actor(**row) if row else None

    def active(self, actor: Actor) -> bool:
        return (
            self.connection.execute(
                "SELECT id FROM identity.learners WHERE id = %s AND active FOR SHARE", (actor.id,)
            ).fetchone()
            is not None
        )

    def get_actor(self, actor_id: UUID) -> Actor | None:
        row = self.connection.execute(
            "SELECT id, display_name FROM identity.learners WHERE id = %s AND active FOR SHARE",
            (actor_id,),
        ).fetchone()
        return Actor(**row) if row else None
