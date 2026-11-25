from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.tutor.evaluation_contracts import Evaluation
from leornian.shared_kernel.errors import BusinessError


class Evaluations:
    """An immutable, already-public receipt is the only origin of teaching evaluation."""

    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, evaluation_id):
        row = self.connection.execute(
            "SELECT * FROM tutor.evaluations WHERE actor_id=%s AND id=%s",
            (actor.id, evaluation_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Teaching evaluation not found.")
        return row

    def receipt_context(self, actor, receipt_id):
        row = self.connection.execute(
            "SELECT id,pack_id,source_kind,source_id,context_data FROM tutor.evaluations "
            "WHERE actor_id=%s AND source_id=%s",
            (actor.id, receipt_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "No already-public feedback exists for this receipt.")
        return row

    def for_run(self, actor, run_id):
        row = self.connection.execute(
            "SELECT id FROM tutor.evaluations WHERE actor_id=%s AND run_id=%s",
            (actor.id, run_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Evaluation run not found.")
        return self.row(actor, row["id"])

    def enqueue(self, actor, pack_id, source_kind, source_id, question, result):
        self.connection.execute(
            "INSERT INTO tutor.evaluations(id,actor_id,pack_id,source_kind,source_id,context_data) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(actor_id,source_kind,source_id) DO NOTHING",
            (
                uuid4(),
                actor.id,
                pack_id,
                source_kind,
                source_id,
                Jsonb(
                    {
                        "question": question.model_dump(mode="json"),
                        "receipt": result.model_dump(mode="json"),
                    }
                ),
            ),
        )

    @staticmethod
    def summary(row):
        return Evaluation(
            **{
                key: row[key]
                for key in (
                    "id",
                    "pack_id",
                    "source_kind",
                    "source_id",
                    "run_id",
                    "document",
                    "created_at",
                )
            },
            correct=row["context_data"]["receipt"]["correct"],
        )

    def list(self, actor):
        rows = self.connection.execute(
            "SELECT * FROM tutor.evaluations WHERE actor_id=%s "
            "ORDER BY created_at DESC,id LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [self.summary(row) for row in rows]

    def bind(self, evaluation_id, run_id):
        self.connection.execute(
            "UPDATE tutor.evaluations SET run_id=%s WHERE id=%s AND run_id IS NULL",
            (run_id, evaluation_id),
        )

    def record(self, row, document):
        if document.recorded_correct != row["context_data"]["receipt"]["correct"]:
            raise BusinessError("invalid_evaluation_output", "Evaluation cannot change scoring.")
        self.connection.execute(
            "UPDATE tutor.evaluations SET document=%s WHERE id=%s AND document IS NULL",
            (Jsonb(document.model_dump(mode="json")), row["id"]),
        )
