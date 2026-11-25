from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.delivery.notification_contracts import (
    MaterialUpdateNotificationContent,
    Notification,
)
from leornian.shared_kernel.errors import BusinessError


class Notifications:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def public(row):
        return Notification(**{key: row[key] for key in Notification.model_fields})

    def offer(self, actor, offer):
        content = MaterialUpdateNotificationContent(
            **offer.model_dump(include={
                "goal_id", "plan_id", "plan_revision", "node_key", "binding_id",
                "binding_revision", "document_id", "baseline_revision", "candidate_revision",
                "migration_cost",
            }),
            offer_id=offer.id,
            affected_plan_count=sum(d.kind == "plan" for d in offer.impact.dependencies),
            affected_lesson_count=sum(d.kind == "lesson" for d in offer.impact.dependencies),
        )
        row = self.connection.execute(
            "INSERT INTO delivery.notifications(id,actor_id,offer_id,kind,payload) "
            "VALUES (%s,%s,%s,'material_update',%s) ON CONFLICT (offer_id) DO NOTHING RETURNING id",
            (uuid4(), actor.id, offer.id, Jsonb(content.model_dump(mode="json"))),
        ).fetchone()
        if row:
            Events(self.connection).append(
                actor.id, "knowledge.material_update_offered", offer.id,
                EventPayload(
                    goal_id=offer.goal_id, material_update_offer_id=offer.id,
                    notification_id=row["id"],
                ),
            )
        return self.connection.execute(
            "SELECT id FROM delivery.notifications WHERE offer_id=%s AND actor_id=%s",
            (offer.id, actor.id),
        ).fetchone()["id"]

    def get(self, actor, notification_id):
        row = self.connection.execute(
            "SELECT * FROM delivery.notifications WHERE id=%s AND actor_id=%s",
            (notification_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Notification not found.")
        return self.public(row)

    def list(self, actor, before=None, limit=20):
        if before is not None:
            self.get(actor, before)
        rows = self.connection.execute(
            "SELECT * FROM delivery.notifications WHERE actor_id=%s AND "
            "(%s::uuid IS NULL OR (created_at,id)<(SELECT created_at,id "
            "FROM delivery.notifications WHERE id=%s AND actor_id=%s)) "
            "ORDER BY created_at DESC,id DESC LIMIT %s",
            (actor.id, before, before, actor.id, limit),
        ).fetchall()
        return [self.public(row) for row in rows]

    def read(self, actor, notification_id):
        self.get(actor, notification_id)
        row = self.connection.execute(
            "UPDATE delivery.notifications SET state=CASE WHEN state='unread' THEN 'read' "
            "ELSE state END,read_at=COALESCE(read_at,now()) "
            "WHERE id=%s AND actor_id=%s AND read_at IS NULL RETURNING offer_id",
            (notification_id, actor.id),
        ).fetchone()
        if row:
            self.event(actor, notification_id, row["offer_id"])
        return self.get(actor, notification_id)

    def decision(self, actor, offer_id, decision):
        state = {
            "accept_update": "accepted", "decide_later": "deferred",
            "keep_current_for_track": "kept_current",
        }[decision]
        row = self.connection.execute(
            "UPDATE delivery.notifications SET state=%s,"
            "deferred_at=CASE WHEN %s='deferred' THEN now() ELSE deferred_at END "
            "WHERE actor_id=%s AND offer_id=%s RETURNING id",
            (state, state, actor.id, offer_id),
        ).fetchone()
        if row:
            self.event(actor, row["id"], offer_id)

    def event(self, actor, notification_id, offer_id):
        Events(self.connection).append(
            actor.id, "delivery.notification_updated", notification_id,
            EventPayload(notification_id=notification_id, material_update_offer_id=offer_id),
        )
