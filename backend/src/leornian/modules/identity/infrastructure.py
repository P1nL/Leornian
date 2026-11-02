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
        self.connection.execute(
            "INSERT INTO identity.sessions(token_digest, actor_id, expires_at) VALUES (%s, %s, %s)",
            (digest, session.actor.id, session.expires_at),
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
