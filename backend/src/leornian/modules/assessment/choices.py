from uuid import uuid4

from leornian.modules.item_bank.contracts import ChoiceInput, ChoiceResult
from leornian.shared_kernel.errors import BusinessError


class Choices:
    def __init__(self, connection):
        self.connection = connection

    def submit(self, actor, pack_id, key: str, data: ChoiceInput, material):
        previous = self.connection.execute(
            "SELECT * FROM assessment.choice_results WHERE actor_id = %s "
            "AND (idempotency_key = %s OR (pack_id = %s AND slot = %s)) FOR UPDATE",
            (actor.id, key, pack_id, data.slot),
        ).fetchall()
        if previous:
            if len(previous) != 1 or any(
                previous[0][field] != value
                for field, value in {
                    "pack_id": pack_id,
                    "slot": data.slot,
                    "selected_key": data.selected_key,
                    "idempotency_key": key,
                }.items()
            ):
                raise BusinessError("idempotency_conflict", "Practice answer is already locked.")
            return self._public(previous[0]), False
        row = self.connection.execute(
            "INSERT INTO assessment.choice_results(id, actor_id, pack_id, slot, selected_key, "
            "idempotency_key, correct, explanation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4(),
                actor.id,
                pack_id,
                data.slot,
                data.selected_key,
                key,
                data.selected_key == material.correct_key,
                material.explanation,
            ),
        ).fetchone()
        return self._public(row), True

    @staticmethod
    def _public(row):
        return ChoiceResult(**{key: row[key] for key in ChoiceResult.model_fields})

    def list(self, actor):
        return [
            self._public(row)
            for row in self.connection.execute(
                "SELECT * FROM assessment.choice_results WHERE actor_id = %s "
                "ORDER BY created_at DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def for_pack(self, actor, pack_id):
        return [
            self._public(row)
            for row in self.connection.execute(
                "SELECT * FROM assessment.choice_results WHERE actor_id=%s AND pack_id=%s "
                "ORDER BY created_at,id",
                (actor.id, pack_id),
            ).fetchall()
        ]

    def get(self, actor, result_id):
        row = self.connection.execute(
            "SELECT * FROM assessment.choice_results WHERE actor_id=%s AND id=%s",
            (actor.id, result_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Choice result not found.")
        return self._public(row)
