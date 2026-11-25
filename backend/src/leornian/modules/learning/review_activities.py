
from psycopg.types.json import Jsonb

from leornian.modules.learning.review_contracts import ReviewActivity, ReviewLog
from leornian.modules.learning.reviews import Reviews
from leornian.shared_kernel.errors import BusinessError


class ReviewActivities:
    def __init__(self, connection):
        self.connection = connection

    def ensure_due(self, actor=None):
        return self.connection.execute(
            "INSERT INTO learning.review_activities(id,actor_id,card_id,card_revision,due_at) "
            "SELECT gen_random_uuid(),actor_id,id,revision,next_due_at "
            "FROM learning.review_cards WHERE status='scheduled' AND next_due_at<=now() "
            + ("AND actor_id=%s " if actor else "")
            + "ON CONFLICT(card_id,card_revision) DO NOTHING RETURNING id,actor_id",
            (actor.id,) if actor else (),
        ).fetchall()

    def row(self, actor, activity_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM learning.review_activities WHERE id=%s AND actor_id=%s"
            + (" FOR UPDATE" if lock else ""), (activity_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Review activity not found.")
        return row

    def view(self, actor, row):
        card = Reviews(self.connection).get(actor, row["card_id"])
        return ReviewActivity(
            **{k: v for k, v in row.items() if k != "actor_id"}, card=card, goal_id=card.goal_id,
        )

    def lock_for_schedule(self, actor, activity_id):
        row = self.row(actor, activity_id)
        Reviews(self.connection).get(actor, row["card_id"], lock=True)
        return self.row(actor, activity_id, lock=True)

    def list(self, actor, conversation_id=None):
        return [self.view(actor, row) for row in self.connection.execute(
            "SELECT * FROM learning.review_activities WHERE actor_id=%s "
            + ("AND conversation_id=%s " if conversation_id else "")
            + "ORDER BY created_at DESC,id DESC LIMIT 100",
            (actor.id, *((conversation_id,) if conversation_id else ())),
        ).fetchall()]

    def due_for_goal(self, actor, goal_id):
        return self.connection.execute(
            "SELECT a.* FROM learning.review_activities a "
            "JOIN learning.review_cards c ON c.id=a.card_id "
            "WHERE a.actor_id=%s AND c.goal_id=%s AND a.state='due' "
            "AND c.status='scheduled' AND c.revision=a.card_revision "
            "AND c.next_due_at<=now() ORDER BY a.due_at,a.id",
            (actor.id, goal_id),
        ).fetchall()

    def require_current(self, actor, row):
        card = Reviews(self.connection).get(actor, row["card_id"], lock=True)
        if card.revision != row["card_revision"]:
            raise BusinessError("stale_version", "Review schedule changed.")
        if not card.due or row["state"] not in {"due", "presented"}:
            raise BusinessError("precondition_failed", "Review is paused, cancelled or not due.")
        return card

    def matches_focus(self, actor, row, focus):
        card = Reviews(self.connection).get(actor, row["card_id"])
        return focus.kind == "goal" or (
            card.plan_id == focus.plan_id
            and card.plan_revision == focus.expected_plan_revision
            and card.node_key == focus.node_key
        )

    def present(self, actor, row, conversation_id):
        self.require_current(actor, row)
        if row["conversation_id"] and row["conversation_id"] != conversation_id:
            raise BusinessError("stale_version", "Review is already in another conversation.")
        self.connection.execute(
            "UPDATE learning.review_activities SET conversation_id=%s,presented_at=coalesce("
            "presented_at,now()),state='presented',updated_at=now() WHERE id=%s",
            (conversation_id, row["id"]),
        )
        return self.view(actor, self.row(actor, row["id"]))

    def cancel(self, actor, row):
        if row["state"] in {"due", "presented"}:
            self.connection.execute(
                "UPDATE learning.review_activities SET state='cancelled',updated_at=now() "
                "WHERE id=%s", (row["id"],),
            )
        return self.view(actor, self.row(actor, row["id"]))

    def receipt(self, actor, activity_id, key, request=None):
        row = self.connection.execute(
            "SELECT * FROM learning.review_activity_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if row:
            if row["activity_id"] != activity_id or (
                request is not None and row["request"] != request
            ):
                raise BusinessError("idempotency_conflict", "Review activity command changed.")
            return ReviewActivity(**row["result"])
        if request is None:
            raise BusinessError("not_found", "Review activity command not found.")

    def remember(self, actor, activity_id, key, request, result):
        self.connection.execute(
            "INSERT INTO learning.review_activity_commands"
            "(actor_id,command_key,activity_id,request,result) VALUES(%s,%s,%s,%s,%s)",
            (actor.id, key, activity_id, Jsonb(request), Jsonb(result.model_dump(mode="json"))),
        )

    def logs(self, actor, card_id):
        Reviews(self.connection).get(actor, card_id)
        return [ReviewLog(**{k: v for k, v in row.items() if k != "actor_id"})
                for row in self.connection.execute(
                    "SELECT * FROM learning.review_logs WHERE actor_id=%s AND card_id=%s "
                    "ORDER BY reviewed_at DESC,id DESC LIMIT 100", (actor.id, card_id),
                ).fetchall()]
