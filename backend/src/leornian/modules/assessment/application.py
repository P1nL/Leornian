from __future__ import annotations

import json
from uuid import UUID, uuid4

from psycopg import Connection

from leornian.modules.assessment.contracts import AssessmentResult, Attempt
from leornian.modules.execution.contracts import CaseOutput
from leornian.modules.identity.contracts import Actor
from leornian.shared_kernel.errors import BusinessError

COLUMNS = (
    "id, track_id, item_version, status, feedback, passed_cases, "
    "total_cases, created_at, completed_at"
)


def evaluate(cases: list[CaseOutput]) -> AssessmentResult:
    if len(cases) != 3:
        return AssessmentResult(
            passed=False, passed_cases=0, feedback="执行用例不完整，不能判定通过。"
        )
    expected = [6, 0, 14]
    passed = 0
    for case, value in zip(cases, expected, strict=True):
        if case.outcome != "completed" or case.exit_code != 0:
            continue
        try:
            actual = json.loads(case.stdout.strip())
        except (ValueError, TypeError):
            continue
        if type(actual) is int and actual == value:
            passed += 1
    return AssessmentResult(
        passed=passed == 3,
        passed_cases=passed,
        feedback="三组基础用例通过，本课练习完成；不代表独立掌握度认证。"
        if passed == 3
        else f"通过 {passed}/3 组基础用例。检查空数组、负偶数、累加逻辑及仅输出数字的要求。",
    )


class Assessment:
    def __init__(self, connection: Connection):
        self.connection = connection

    def submit(
        self,
        actor: Actor,
        track_id: UUID,
        revision: int,
        key: str,
        code: str,
    ) -> tuple[Attempt, bool]:
        row = self.connection.execute(
            "INSERT INTO assessment.attempts(id, actor_id, track_id, course_revision, "
            "item_version, "
            "idempotency_key, code) VALUES (%s, %s, %s, %s, 'python-even-sum.v1', %s, %s) "
            f"ON CONFLICT DO NOTHING RETURNING {COLUMNS}",
            (uuid4(), actor.id, track_id, revision, key, code),
        ).fetchone()
        if row:
            return Attempt(**row), True
        previous = self.connection.execute(
            f"SELECT {COLUMNS}, code FROM assessment.attempts "
            "WHERE actor_id = %s AND idempotency_key = %s",
            (actor.id, key),
        ).fetchone()
        previous_code = previous.pop("code")
        if previous_code != code or previous["track_id"] != track_id:
            raise BusinessError("idempotency_conflict", "This submission key has different code.")
        return Attempt(**previous), False

    def get(self, actor: Actor, attempt_id: UUID) -> Attempt:
        row = self.connection.execute(
            f"SELECT {COLUMNS} FROM assessment.attempts WHERE id = %s AND actor_id = %s",
            (attempt_id, actor.id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Attempt not found.")
        return Attempt(**row)

    def list(self, actor: Actor) -> list[Attempt]:
        return [
            Attempt(**row)
            for row in self.connection.execute(
                f"SELECT {COLUMNS} FROM assessment.attempts WHERE actor_id = %s "
                "ORDER BY created_at DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def execution_input(self, actor: Actor, attempt_id: UUID) -> dict:
        row = self.connection.execute(
            "SELECT code, item_version, track_id, course_revision FROM assessment.attempts "
            "WHERE id = %s AND actor_id = %s",
            (attempt_id, actor.id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Attempt not found.")
        return row

    def recent_for_track(self, actor: Actor, track_id: UUID) -> list[Attempt]:
        return [
            Attempt(**row)
            for row in self.connection.execute(
                f"SELECT {COLUMNS} FROM assessment.attempts WHERE actor_id = %s AND track_id = %s "
                "ORDER BY created_at DESC, id DESC LIMIT 3",
                (actor.id, track_id),
            ).fetchall()
        ]

    def complete(self, attempt_id: UUID, cases: list[CaseOutput]) -> AssessmentResult:
        result = evaluate(cases)
        infrastructure_error = any(case.outcome == "infrastructure_error" for case in cases)
        status = "error" if infrastructure_error else "passed" if result.passed else "not_passed"
        self.connection.execute(
            "UPDATE assessment.attempts SET status = %s, feedback = %s, passed_cases = %s, "
            "completed_at = now() WHERE id = %s AND status = 'queued'",
            (status, result.feedback, result.passed_cases, attempt_id),
        )
        return result

    def fail(self, attempt_id: UUID, code: str) -> bool:
        return (
            self.connection.execute(
                "UPDATE assessment.attempts SET status = 'error', feedback = %s, "
                "completed_at = now() "
                "WHERE id = %s AND status = 'queued' RETURNING id",
                (code, attempt_id),
            ).fetchone()
            is not None
        )
