import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.assessment.python_contracts import PythonAttempt
from leornian.modules.assessment.transfers import Transfers
from leornian.shared_kernel.errors import BusinessError


class PythonAssessment:
    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, attempt_id):
        row = self.connection.execute(
            "SELECT * FROM assessment.python_attempts WHERE actor_id=%s AND id=%s",
            (actor.id, attempt_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Execution attempt not found.")
        return row

    def create(self, actor, pack_id, item, code, key, purpose, gate_id=None, *, transfer_id=None):
        previous = self.connection.execute(
            "SELECT * FROM assessment.python_attempts WHERE actor_id=%s AND idempotency_key=%s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if (
                previous["pack_id"],
                previous["slot"],
                previous["code"],
                previous["purpose"],
                previous["gate_id"],
                previous["transfer_id"],
            ) != (pack_id, item.slot, code, purpose, gate_id, transfer_id):
                raise BusinessError(
                    "idempotency_conflict", "Code submission has different content."
                )
            return previous, False
        if self.connection.execute(
            "SELECT 1 FROM assessment.python_attempts WHERE pack_id=%s AND slot=%s AND purpose=%s",
            (pack_id, item.slot, purpose),
        ).fetchone():
            raise BusinessError(
                "precondition_failed", "This exact execution task is already locked."
            )
        attempt_id = uuid4()
        self.connection.execute(
            "INSERT INTO assessment.python_attempts(id,actor_id,pack_id,slot,purpose,gate_id,"
            "idempotency_key,code,test_cases,transfer_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                attempt_id,
                actor.id,
                pack_id,
                item.slot,
                purpose,
                gate_id,
                key,
                code,
                Jsonb([case.model_dump(mode="json") for case in item.tests]),
                transfer_id,
            ),
        )
        return self.row(actor, attempt_id), True

    def public(self, row):
        if row["purpose"] == "qualification":
            raise BusinessError("not_found", "Execution attempt not found.")
        fields = {key: row[key] for key in PythonAttempt.model_fields if key in row}
        if row["purpose"] == "gate":
            gate = self.connection.execute(
                "SELECT status FROM assessment.concept_gates WHERE id=%s", (row["gate_id"],)
            ).fetchone()
            if gate["status"] in {"preparing", "ready", "in_progress", "submitted"}:
                fields.update(status="queued", passed_cases=0, feedback=None, completed_at=None)
        return PythonAttempt(**fields)

    def list(self, actor):
        return [
            self.public(row)
            for row in self.connection.execute(
                "SELECT * FROM assessment.python_attempts WHERE actor_id=%s "
                "AND purpose!='qualification' ORDER BY created_at DESC,id LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def for_pack(self, actor, pack_id, purpose):
        return self.connection.execute(
            "SELECT * FROM assessment.python_attempts "
            "WHERE actor_id=%s AND pack_id=%s AND purpose=%s"
            " ORDER BY slot",
            (actor.id, pack_id, purpose),
        ).fetchall()

    def complete(self, row, cases):
        if row["status"] != "queued":
            return row
        passed = 0
        if len(cases) == 3:
            for case, test in zip(cases, row["test_cases"], strict=True):
                if case.outcome != "completed" or case.exit_code != 0:
                    continue
                try:
                    actual = json.loads(case.stdout.strip())
                except (ValueError, TypeError):
                    continue
                if type(actual) is int and actual == test["expected"]:
                    passed += 1
        status = (
            "error"
            if len(cases) != 3 or any(c.outcome == "infrastructure_error" for c in cases)
            else "passed"
            if passed == 3
            else "not_passed"
        )
        self.connection.execute(
            "UPDATE assessment.python_attempts SET status=%s,passed_cases=%s,feedback=%s,"
            "completed_at=now() WHERE id=%s AND status='queued'",
            (status, passed, f"通过 {passed}/3 组绑定用例；不代表完整掌握。", row["id"]),
        )
        return {**row, "status": status, "passed_cases": passed}

    def fail(self, attempt_id, reason):
        self.connection.execute(
            "UPDATE assessment.python_attempts SET status='error',feedback=%s,completed_at=now() "
            "WHERE id=%s AND status='queued'",
            (reason, attempt_id),
        )

    def require_training(self, actor, pack_id):
        rows = {row["slot"]: row for row in self.for_pack(actor, pack_id, "training")}
        if not all(
            slot in rows and rows[slot]["status"] in {"passed", "not_passed"}
            for slot in ("practice_1", "practice_2")
        ):
            raise BusinessError("precondition_failed", "Complete both locked execution practices.")
        if any(rows[slot]["status"] != "passed" for slot in ("practice_1", "practice_2")):
            remediation = rows.get("remediation_1")
            if not remediation or (
                remediation["status"] != "passed"
                and not (
                    remediation["status"] == "not_passed"
                    and Transfers(self.connection).passed_for(
                        actor, remediation["id"], kind="python_io"
                    )
                )
            ):
                raise BusinessError(
                    "precondition_failed", "Pass assigned execution remediation first."
                )
