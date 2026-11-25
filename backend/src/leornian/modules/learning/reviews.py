from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.learning.fsrs_schedule import (
    ALGORITHM_VERSION,
    PARAMETER_VERSION,
    initial_state,
    schedule,
)
from leornian.modules.learning.review_contracts import ReviewCard, ReviewInput, ReviewStatus
from leornian.shared_kernel.errors import BusinessError

COLUMNS = (
    "id,track_id,goal_id,plan_id,plan_revision,node_key,source_receipt,prompt,"
    "revision,status,next_due_at,last_rating,reviewed_at,"
    "scheduling_state,algorithm_version,parameter_version,"
    "(status = 'scheduled' AND next_due_at <= now()) AS due"
)


class Reviews:
    def __init__(self, connection: Connection):
        self.connection = connection

    def schedule_completed(self, actor: Actor, track_id: UUID) -> bool:
        card_id = uuid4()
        created = self.connection.execute(
                "INSERT INTO learning.review_cards(id, actor_id, track_id,goal_id) "
                "SELECT %s, %s, id,goal_id FROM learning.tracks WHERE id = %s "
                "AND actor_id = %s AND status = 'completed' "
                "ON CONFLICT (track_id) DO NOTHING RETURNING id,next_due_at",
                (card_id, actor.id, track_id, actor.id),
            ).fetchone()
        if created:
            self.connection.execute(
                "UPDATE learning.review_cards SET scheduling_state=%s,algorithm_version=%s,"
                "parameter_version=%s WHERE id=%s",
                (Jsonb(initial_state(card_id.int % (2**63), created["next_due_at"])),
                 ALGORITHM_VERSION, PARAMETER_VERSION, card_id),
            )
        return created is not None

    def schedule_node_completed(
        self, actor, plan_id, plan_revision, node_key, source_receipt, prompt=None,
    ):
        completed = self.connection.execute(
            "SELECT 1 FROM learning.node_progress WHERE actor_id=%s AND plan_id=%s "
            "AND plan_revision=%s AND node_key=%s AND evidence_gate_id=%s "
            "UNION ALL SELECT 1 FROM learning.execution_evidence WHERE actor_id=%s AND plan_id=%s "
            "AND plan_revision=%s AND node_key=%s AND gate_id=%s",
            (actor.id, plan_id, plan_revision, node_key, source_receipt,
             actor.id, plan_id, plan_revision, node_key, source_receipt),
        ).fetchone()
        if not completed:
            raise BusinessError("precondition_failed", "A committed node completion is required.")
        plan = self.connection.execute(
            "SELECT p.goal_id,r.document FROM learning.plans p JOIN learning.plan_revisions r "
            "ON r.plan_id=p.id WHERE p.id=%s AND p.actor_id=%s AND r.revision=%s",
            (plan_id, actor.id, plan_revision),
        ).fetchone()
        node = next(
            (node for node in plan["document"]["nodes"] if node["key"] == node_key), None,
        ) if plan else None
        if not node:
            raise BusinessError("not_found", "Completed node version not found.")
        prompt = prompt or (
            f"不看原课文，回忆「{node['title']}」：{node['objective']}。"
            "用自己的话解释关键步骤，并说明一种容易出错的情形。"
        )
        card_id = uuid4()
        created = self.connection.execute(
            "INSERT INTO learning.review_cards(id,actor_id,goal_id,plan_id,plan_revision,"
            "node_key,source_receipt,prompt) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING next_due_at",
            (card_id, actor.id, plan["goal_id"], plan_id, plan_revision,
             node_key, source_receipt, prompt),
        ).fetchone()
        if created:
            self.connection.execute(
                "UPDATE learning.review_cards SET scheduling_state=%s,algorithm_version=%s,"
                "parameter_version=%s WHERE id=%s",
                (Jsonb(initial_state(card_id.int % (2**63), created["next_due_at"])),
                 ALGORITHM_VERSION, PARAMETER_VERSION, card_id),
            )
        return created is not None

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
            "ON CONFLICT (actor_id, idempotency_key) DO NOTHING RETURNING id,answered_at",
            (uuid4(), actor.id, card_id, key, data.rating, data.expected_revision),
        ).fetchone()
        if not created:
            raise BusinessError("idempotency_conflict", "Review key was used for another response.")
        before, after, log, due, parameters = schedule(
            card.scheduling_state, data.rating, created["answered_at"], card.id.int % (2**63),
        )
        self.connection.execute(
            "UPDATE learning.review_cards SET revision = revision + 1, last_rating = %s, "
            "reviewed_at=%s,next_due_at=%s,scheduling_state=%s,algorithm_version=%s,"
            "parameter_version=%s WHERE id=%s",
            (data.rating, created["answered_at"], due, Jsonb(after),
             ALGORITHM_VERSION, PARAMETER_VERSION, card_id),
        )
        self.connection.execute(
            "INSERT INTO learning.review_logs(id,actor_id,card_id,response_id,evidence_kind,"
            "source_receipt,rating,rating_contract,algorithm_version,parameter_version,"
            "scheduler,previous_state,next_state,algorithm_log,reviewed_at,due_at) "
            "VALUES(%s,%s,%s,%s,'self_rating',%s,%s,'self-rating-three.v1',%s,%s,%s,%s,%s,%s,%s,%s)",
            (uuid4(), actor.id, card_id, created["id"], created["id"], data.rating,
             ALGORITHM_VERSION, PARAMETER_VERSION, Jsonb(parameters), Jsonb(before),
             Jsonb(after), Jsonb(log), created["answered_at"], due),
        )
        self.connection.execute(
            "UPDATE learning.review_activities SET state='completed',source_receipt=%s,"
            "updated_at=now() WHERE card_id=%s AND card_revision=%s "
            "AND state IN ('due','presented')",
            (created["id"], card_id, data.expected_revision),
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
        self.connection.execute(
            "UPDATE learning.review_activities SET state='cancelled',updated_at=now() "
            "WHERE card_id=%s AND state IN ('due','presented')",
            (card_id,),
        )
        return self.get(actor, card_id), True
