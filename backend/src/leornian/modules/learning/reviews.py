from uuid import UUID, uuid4

from psycopg import Connection

from leornian.modules.identity.contracts import Actor
from leornian.modules.learning.review_contracts import ReviewCard, ReviewInput, ReviewStatus
from leornian.shared_kernel.errors import BusinessError

COLUMNS = (
    "id, track_id, revision, status, next_due_at, last_rating, reviewed_at, "
    "(status = 'scheduled' AND next_due_at <= now()) AS due"
)
INTERVAL_DAYS = {"again": 1, "good": 3, "easy": 7}


class Reviews:
    def __init__(self, connection: Connection):
        self.connection = connection

    def schedule_completed(self, actor: Actor, track_id: UUID) -> bool:
        return (
            self.connection.execute(
                "INSERT INTO learning.review_cards(id, actor_id, track_id) "
                "SELECT %s, %s, id FROM learning.tracks WHERE id = %s "
                "AND actor_id = %s AND status = 'completed' "
                "ON CONFLICT (track_id) DO NOTHING RETURNING id",
                (uuid4(), actor.id, track_id, actor.id),
            ).fetchone()
            is not None
        )

    def list(self, actor: Actor) -> list[ReviewCard]:
        return [
            ReviewCard(**row)
            for row in self.connection.execute(
                f"SELECT {COLUMNS} FROM learning.review_cards WHERE actor_id = %s "
                "ORDER BY (status = 'scheduled') DESC, next_due_at, id LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def get(self, actor: Actor, card_id: UUID, *, lock: bool = False) -> ReviewCard:
        row = self.connection.execute(
            f"SELECT {COLUMNS} FROM learning.review_cards WHERE id = %s AND actor_id = %s "
            + ("FOR UPDATE" if lock else ""),
            (card_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Review card not found.")
        return ReviewCard(**row)

    def respond(
        self, actor: Actor, card_id: UUID, key: str, data: ReviewInput
    ) -> tuple[ReviewCard, bool]:
        card = self.get(actor, card_id, lock=True)
        previous = self.connection.execute(
            "SELECT card_id, rating, expected_revision FROM learning.review_responses "
            "WHERE actor_id = %s AND idempotency_key = %s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if previous != {"card_id": card_id, **data.model_dump()}:
                raise BusinessError("idempotency_conflict", "Review key has different content.")
            return card, False
        if card.revision != data.expected_revision:
            raise BusinessError("stale_version", "Review revision changed.")
        if card.status != "scheduled" or not card.due:
            raise BusinessError("precondition_failed", "Review is paused or not due.")
        created = self.connection.execute(
            "INSERT INTO learning.review_responses(id, actor_id, card_id, idempotency_key, "
            "rating, expected_revision) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (actor_id, idempotency_key) DO NOTHING RETURNING id",
            (uuid4(), actor.id, card_id, key, data.rating, data.expected_revision),
        ).fetchone()
        if not created:
            raise BusinessError("idempotency_conflict", "Review key was used for another response.")
        self.connection.execute(
            "UPDATE learning.review_cards SET revision = revision + 1, last_rating = %s, "
            "reviewed_at = now(), next_due_at = now() + make_interval(days => %s) WHERE id = %s",
            (data.rating, INTERVAL_DAYS[data.rating], card_id),
        )
        return self.get(actor, card_id), True

    def change_status(
        self, actor: Actor, card_id: UUID, data: ReviewStatus
    ) -> tuple[ReviewCard, bool]:
        card = self.get(actor, card_id, lock=True)
        if card.status == data.status:
            return card, False
        if card.revision != data.expected_revision:
            raise BusinessError("stale_version", "Review revision changed.")
        self.connection.execute(
            "UPDATE learning.review_cards SET status = %s, revision = revision + 1 WHERE id = %s",
            (data.status, card_id),
        )
        return self.get(actor, card_id), True
