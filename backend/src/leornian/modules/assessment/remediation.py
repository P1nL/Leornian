from uuid import uuid4

from leornian.modules.assessment.gate_contracts import Remediation
from leornian.shared_kernel.errors import BusinessError


class Remediations:
    def __init__(self, connection):
        self.connection = connection

    def attach(self, actor, result):
        existing = self.for_pack(actor, result.pack_id)
        if not existing:
            row = self.connection.execute(
                "INSERT INTO assessment.remediations(id,actor_id,pack_id,parent_result_id) "
                "VALUES(%s,%s,%s,%s) RETURNING *",
                (uuid4(), actor.id, result.pack_id, result.id),
            ).fetchone()
            existing = self.public(row)
        self.connection.execute(
            "INSERT INTO assessment.remediation_triggers(result_id,remediation_id) "
            "VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (result.id, existing.id),
        )
        return existing

    def complete(self, actor, result):
        remediation = self.for_pack(actor, result.pack_id)
        if not remediation:
            raise BusinessError("precondition_failed", "No remediation was assigned.")
        self.connection.execute(
            "UPDATE assessment.remediations SET status=%s,transfer_required=%s WHERE id=%s "
            "AND status='available'",
            ("passed" if result.correct else "not_passed", not result.correct, remediation.id),
        )
        return self.for_pack(actor, result.pack_id)

    def for_pack(self, actor, pack_id):
        row = self.connection.execute(
            "SELECT * FROM assessment.remediations WHERE actor_id=%s AND pack_id=%s",
            (actor.id, pack_id),
        ).fetchone()
        return self.public(row) if row else None

    def get(self, actor, remediation_id):
        row = self.connection.execute(
            "SELECT * FROM assessment.remediations WHERE actor_id=%s AND id=%s",
            (actor.id, remediation_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Remediation not found.")
        return self.public(row)

    @staticmethod
    def public(row):
        return Remediation(**{key: row[key] for key in Remediation.model_fields})

    def list(self, actor):
        return [
            self.public(row)
            for row in self.connection.execute(
                "SELECT * FROM assessment.remediations WHERE actor_id=%s "
                "ORDER BY created_at DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]
