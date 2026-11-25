"""Original Assessment owns locked knowledge responses and bounded comparisons."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.assessment.contracts import ResponseResult
from leornian.modules.item_bank.contracts import compare_response
from leornian.shared_kernel.errors import BusinessError


class Responses:
    def __init__(self, connection):
        self.connection = connection

    def submit(self, actor, pack_id, key, data, material):
        try:
            correct = compare_response(material.public(), data.response, material.answer)
        except ValueError as error:
            raise BusinessError("precondition_failed", str(error)) from None
        previous = self.connection.execute(
            "SELECT * FROM assessment.response_results WHERE actor_id=%s "
            "AND (idempotency_key=%s OR (pack_id=%s AND slot=%s)) FOR UPDATE",
            (actor.id, key, pack_id, data.slot),
        ).fetchall()
        if previous:
            if len(previous) != 1 or any(previous[0][name] != value for name, value in {
                "pack_id": pack_id, "slot": data.slot, "idempotency_key": key,
                "response": data.response.model_dump(mode="json"),
            }.items()):
                raise BusinessError("idempotency_conflict", "This response is already locked.")
            return self.public(previous[0]), False
        profiles = {
            "multiple": "knowledge-multiple.v1", "prediction": "knowledge-prediction.v1",
            "ordering": "knowledge-order.v1", "line_review": "knowledge-line-location.v1",
            "short": "knowledge-reference.v1",
        }
        row = self.connection.execute(
            "INSERT INTO assessment.response_results"
            "(id,actor_id,pack_id,slot,idempotency_key,response,correct,profile_version,"
            "explanation,reference,findings) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4(), actor.id, pack_id, data.slot, key,
                Jsonb(data.response.model_dump(mode="json")), correct, profiles[data.response.type],
                material.answer.explanation,
                Jsonb(material.answer.response.model_dump(mode="json")),
                Jsonb([f.model_dump(mode="json") for f in material.answer.findings]),
            ),
        ).fetchone()
        return self.public(row), True

    @staticmethod
    def public(row):
        return ResponseResult.model_validate({
            k: row[k] for k in ResponseResult.model_fields
        })

    def get(self, actor, result_id):
        row = self.connection.execute(
            "SELECT * FROM assessment.response_results WHERE actor_id=%s AND id=%s",
            (actor.id, result_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Response result not found.")
        return self.public(row)

    def for_pack(self, actor, pack_id):
        return [self.public(row) for row in self.connection.execute(
            "SELECT * FROM assessment.response_results WHERE actor_id=%s AND pack_id=%s "
            "ORDER BY created_at,id", (actor.id, pack_id),
        ).fetchall()]
