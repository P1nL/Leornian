from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.assessment.assistance_contracts import PracticeAssistanceReceipt
from leornian.modules.assessment.hint_contracts import PracticeHintReceipt
from leornian.shared_kernel.errors import BusinessError


class PracticeAssistance:
    """Owns immutable assistance facts; it does not answer or score a practice."""

    def __init__(self, connection):
        self.connection = connection

    def get(self, actor, pack_id, slot):
        row = self.connection.execute(
            "SELECT * FROM assessment.practice_assistance WHERE actor_id=%s AND pack_id=%s "
            "AND slot=%s", (actor.id, pack_id, slot),
        ).fetchone()
        return self.public(row) if row else None

    def record(self, actor, pack_id, revision, slot, public_identity, content):
        row = self.connection.execute(
            "INSERT INTO assessment.practice_assistance"
            "(id,actor_id,pack_id,pack_revision,slot,public_identity,content) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *",
            (uuid4(), actor.id, pack_id, revision, slot, public_identity,
             Jsonb(content.model_dump(mode="json"))),
        ).fetchone()
        if row is None:
            raise BusinessError("precondition_failed", "This direct answer is already delivered.")
        return self.public(row)

    def hints(self, actor, pack_id, slot):
        rows = self.connection.execute(
            "SELECT * FROM assessment.practice_hints WHERE actor_id=%s AND pack_id=%s "
            "AND slot=%s ORDER BY level", (actor.id, pack_id, slot),
        ).fetchall()
        return [
            PracticeHintReceipt.model_validate({
                key: value for key, value in row.items() if key != "actor_id"
            }) for row in rows
        ]

    def record_hint(self, actor, pack_id, revision, slot, public_identity, hint_identity, content):
        previous = self.hints(actor, pack_id, slot)
        if content.level != len(previous) + 1 or any(
            receipt.hint_identity != hint_identity for receipt in previous
        ):
            raise BusinessError(
                "precondition_failed", "Continue H1-H3 in order from the same checked series."
            )
        row = self.connection.execute(
            "INSERT INTO assessment.practice_hints"
            "(id,actor_id,pack_id,pack_revision,slot,public_identity,hint_identity,level,content) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *",
            (uuid4(), actor.id, pack_id, revision, slot, public_identity, hint_identity,
             content.level, Jsonb(content.model_dump(mode="json"))),
        ).fetchone()
        if row is None:
            raise BusinessError("precondition_failed", "This hint has already been delivered.")
        return PracticeHintReceipt.model_validate({
            key: value for key, value in row.items() if key != "actor_id"
        })

    @staticmethod
    def public(row):
        return PracticeAssistanceReceipt.model_validate({
            key: value for key, value in row.items() if key != "actor_id"
        })
