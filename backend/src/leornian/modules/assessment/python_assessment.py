import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.assessment.python_contracts import (
    PythonAttempt,
    PythonPracticeAttempt,
    PythonPracticeHistory,
)
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

    def create(
        self, actor, pack_id, item, code, key, purpose, gate_id=None, *,
        transfer_id=None, practice=None,
    ):
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
                previous["policy_version"],
                previous["previous_attempt_id"],
                previous["retry_requested"],
            ) != (
                pack_id, item.slot, code, purpose, gate_id, transfer_id,
                "python-practice.v2" if practice else "python-io-attempt.v1",
                practice.previous_attempt_id if practice else None,
                practice.retry if practice else False,
            ):
                raise BusinessError(
                    "idempotency_conflict", "Code submission has different content."
                )
            return previous, False
        latest = self.connection.execute(
            "SELECT * FROM assessment.python_attempts "
            "WHERE actor_id=%s AND pack_id=%s AND slot=%s AND purpose=%s "
            "ORDER BY attempt_number DESC LIMIT 1 FOR UPDATE",
            (actor.id, pack_id, item.slot, purpose),
        ).fetchone()
        if practice:
            if purpose != "training" or gate_id is not None or transfer_id is not None:
                raise BusinessError("precondition_failed", "Only ordinary practice can repeat.")
            if (latest["id"] if latest else None) != practice.previous_attempt_id:
                raise BusinessError("stale_version", "The exact previous practice attempt changed.")
            if latest and latest["status"] == "queued":
                raise BusinessError(
                    "precondition_failed", "The previous execution is still pending."
                )
            if practice.retry:
                if not latest or latest["status"] != "error" or latest["code"] != code:
                    raise BusinessError(
                        "precondition_failed", "Explicit retry needs the same errored execution."
                    )
            elif latest and latest["code"] == code:
                raise BusinessError(
                    "precondition_failed", "Change the code or explicitly retry an execution error."
                )
        elif latest:
            raise BusinessError(
                "precondition_failed", "This exact execution task is already locked."
            )
        attempt_id = uuid4()
        self.connection.execute(
            "INSERT INTO assessment.python_attempts(id,actor_id,pack_id,slot,purpose,gate_id,"
            "idempotency_key,code,test_cases,transfer_id,policy_version,attempt_number,"
            "previous_attempt_id,retry_requested) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                "python-practice.v2" if practice else "python-io-attempt.v1",
                latest["attempt_number"] + 1 if latest else 1,
                practice.previous_attempt_id if practice else None,
                practice.retry if practice else False,
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
            " ORDER BY slot,attempt_number",
            (actor.id, pack_id, purpose),
        ).fetchall()

    def latest_training(self, actor, pack_id):
        return self.connection.execute(
            "SELECT DISTINCT ON (slot) * FROM assessment.python_attempts "
            "WHERE actor_id=%s AND pack_id=%s AND purpose='training' "
            "ORDER BY slot,attempt_number DESC",
            (actor.id, pack_id),
        ).fetchall()

    def require_latest_training(self, actor, row):
        latest = next(
            (r for r in self.latest_training(actor, row["pack_id"]) if r["slot"] == row["slot"]),
            None,
        )
        if latest is None or latest["id"] != row["id"]:
            raise BusinessError("stale_version", "This is not the current practice attempt.")

    def practice_public(self, row):
        if row["purpose"] != "training":
            raise BusinessError("not_found", "Ordinary practice attempt not found.")
        return PythonPracticeAttempt(
            **self.public(row).model_dump(),
            policy_version=row["policy_version"], attempt_number=row["attempt_number"],
            previous_attempt_id=row["previous_attempt_id"],
            retry_requested=row["retry_requested"],
        )

    def practice_history(self, actor, pack_id, slot, before=None, limit=20):
        latest = next(
            (row["id"] for row in self.latest_training(actor, pack_id) if row["slot"] == slot),
            None,
        )
        sequence = None
        if before is not None:
            cursor = self.row(actor, before)
            if (cursor["pack_id"], cursor["slot"], cursor["purpose"]) != (
                pack_id, slot, "training",
            ):
                raise BusinessError("not_found", "Practice history cursor not found.")
            sequence = cursor["attempt_number"]
        rows = self.connection.execute(
            "SELECT * FROM assessment.python_attempts "
            "WHERE actor_id=%s AND pack_id=%s AND slot=%s AND purpose='training' "
            "AND (%s::integer IS NULL OR attempt_number<%s) "
            "ORDER BY attempt_number DESC LIMIT %s",
            (actor.id, pack_id, slot, sequence, sequence, limit + 1),
        ).fetchall()
        page = rows[:limit]
        return PythonPracticeHistory(
            items=[self.practice_public(row) for row in page], latest_attempt_id=latest,
            next_before=page[-1]["id"] if len(rows) > limit else None,
        )

    def practice_request(self, actor, key):
        row = self.connection.execute(
            "SELECT * FROM assessment.python_attempts WHERE actor_id=%s "
            "AND idempotency_key=%s AND policy_version='python-practice.v2'",
            (actor.id, key),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "No committed practice request.")
        return self.practice_public(row)

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
        rows = {row["slot"]: row for row in self.latest_training(actor, pack_id)}
        if not all(
            slot in rows and rows[slot]["status"] in {"passed", "not_passed"}
            for slot in ("practice_1", "practice_2")
        ):
            raise BusinessError("precondition_failed", "Complete both current execution practices.")
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
