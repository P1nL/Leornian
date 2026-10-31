from uuid import UUID, uuid4

from psycopg import Connection

from leornian.modules.identity.contracts import Actor
from leornian.modules.learning.journey_contracts import Track
from leornian.shared_kernel.errors import BusinessError

COLUMNS = "id, goal_id, course_version, revision, status, created_at, confirmed_at, completed_at"


class Journey:
    def __init__(self, connection: Connection):
        self.connection = connection

    def draft(self, actor: Actor, goal_id: UUID) -> tuple[Track, bool]:
        row = self.connection.execute(
            f"INSERT INTO learning.tracks(id, actor_id, goal_id, course_version) "
            f"VALUES (%s, %s, %s, 'python-even-sum.v1') ON CONFLICT DO NOTHING RETURNING {COLUMNS}",
            (uuid4(), actor.id, goal_id),
        ).fetchone()
        if row:
            return Track(**row), True
        return Track(
            **self.connection.execute(
                f"SELECT {COLUMNS} FROM learning.tracks WHERE actor_id = %s AND goal_id = %s",
                (actor.id, goal_id),
            ).fetchone()
        ), False

    def get(self, actor: Actor, track_id: UUID, *, lock: bool = False) -> Track:
        row = self.connection.execute(
            f"SELECT {COLUMNS} FROM learning.tracks WHERE id = %s AND actor_id = %s"
            + (" FOR UPDATE" if lock else ""),
            (track_id, actor.id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Learning track not found.")
        return Track(**row)

    def list(self, actor: Actor) -> list[Track]:
        return [
            Track(**row)
            for row in self.connection.execute(
                f"SELECT {COLUMNS} FROM learning.tracks WHERE actor_id = %s "
                "ORDER BY created_at DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def for_goal(self, actor: Actor, goal_id: UUID) -> Track | None:
        row = self.connection.execute(
            f"SELECT {COLUMNS} FROM learning.tracks WHERE actor_id = %s AND goal_id = %s",
            (actor.id, goal_id),
        ).fetchone()
        return Track(**row) if row else None

    def confirm(self, actor: Actor, track_id: UUID, revision: int) -> tuple[Track, bool]:
        track = self.get(actor, track_id, lock=True)
        if track.revision != revision:
            raise BusinessError("stale_version", "Plan revision changed.")
        if track.status != "draft":
            return track, False
        self.connection.execute(
            "UPDATE learning.tracks SET status = 'confirmed', confirmed_at = now() WHERE id = %s",
            (track_id,),
        )
        return self.get(actor, track_id), True

    def apply_assessment(
        self, actor: Actor, track_id: UUID, attempt_id: UUID, revision: int
    ) -> bool:
        track = self.get(actor, track_id, lock=True)
        if track.revision != revision or track.status not in {"confirmed", "completed"}:
            raise BusinessError(
                "stale_version", "Assessment does not match the current confirmed plan."
            )
        first = self.connection.execute(
            "INSERT INTO learning.assessment_inbox(attempt_id, track_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING RETURNING attempt_id",
            (attempt_id, track_id),
        ).fetchone()
        if not first or track.status == "completed":
            return False
        self.connection.execute(
            "UPDATE learning.tracks SET status = 'completed', completed_at = now() WHERE id = %s",
            (track_id,),
        )
        return True
