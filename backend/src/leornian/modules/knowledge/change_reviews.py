from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.change_contracts import MaterialChangeReview
from leornian.modules.knowledge.changes import MaterialChanges
from leornian.shared_kernel.errors import BusinessError


class MaterialChangeReviews:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def public(row):
        return MaterialChangeReview(
            **{name: row[name] for name in MaterialChangeReview.model_fields if name != "contract"}
        )

    def ensure(self, actor, session_digest, report):
        if report.classification == "unchanged":
            return None
        self.connection.execute(
            "INSERT INTO knowledge.material_change_reviews(id,actor_id,check_id,session_digest) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (check_id) DO NOTHING",
            (uuid4(), actor.id, report.id, session_digest),
        )
        return self.for_check(actor, report.id)

    def for_check(self, actor, check_id):
        MaterialChanges(self.connection).get(actor, check_id)
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_change_reviews WHERE actor_id=%s AND check_id=%s",
            (actor.id, check_id),
        ).fetchone()
        return self.public(row) if row else None

    def current(self, actor, review_id, lease=None):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_change_reviews WHERE id=%s AND actor_id=%s "
            "FOR UPDATE",
            (review_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material change review not found.")
        if row["status"] == "cancelled":
            raise BusinessError("precondition_failed", "Material change review was cancelled.")
        if lease and (
            row["lease_token"] != lease
            or row["lease_until"] <= datetime.now(UTC)
            or row["status"] != "processing"
        ):
            raise BusinessError("lease_lost", "Material change review lease expired.")
        report = MaterialChanges(self.connection).get(actor, row["check_id"])
        return row, report

    def finish(self, review_id, result):
        self.connection.execute(
            "UPDATE knowledge.material_change_reviews SET status=%s,result=%s,"
            "error_code=%s,lease_token=NULL,lease_until=NULL WHERE id=%s",
            (
                "waiting_dependency" if result.classification == "uncertain" else "reviewed",
                Jsonb(result.model_dump(mode="json")),
                "change_review_uncertain" if result.classification == "uncertain" else None,
                review_id,
            ),
        )
        if result.classification == "semantic_change":
            from leornian.modules.knowledge.updates import MaterialUpdates

            row = self.connection.execute(
                "SELECT actor_id,session_digest,check_id FROM knowledge.material_change_reviews "
                "WHERE id=%s", (review_id,),
            ).fetchone()
            MaterialUpdates(self.connection).ensure(
                row["actor_id"], row["session_digest"], review_id, row["check_id"]
            )

    def cancel(self, actor, check_id):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_change_reviews WHERE actor_id=%s AND check_id=%s "
            "FOR UPDATE",
            (actor.id, check_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material change review not found.")
        self.connection.execute(
            "UPDATE knowledge.material_change_reviews SET status='cancelled',"
            "lease_token=NULL,lease_until=NULL WHERE id=%s",
            (row["id"],),
        )
        view = self.public({**row, "status": "cancelled", "result": None})
        return row["operation_id"], view
