import json
from collections import Counter
from uuid import uuid4

from leornian.modules.assessment.program_contracts import (
    ProgramPracticeAttempt,
    ProgramPracticeHistory,
    ProgramSampleResult,
    ProgramTransferAttempt,
)
from leornian.modules.execution.contracts import HttpScenarioResult, SqlTableResult, WebCheckResult
from leornian.shared_kernel.errors import BusinessError
from psycopg.types.json import Jsonb
from pydantic import ValidationError


class ProgramAssessment:
    """Original assessment owner: immutable private cases and explicit practice attempts."""

    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, attempt_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE actor_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""), (actor.id, attempt_id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Program attempt not found.")
        return row

    def for_pack(self, actor, pack_id, purpose):
        return self.connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE actor_id=%s AND pack_id=%s "
            "AND purpose=%s ORDER BY slot,attempt_number", (actor.id, pack_id, purpose),
        ).fetchall()

    def latest(self, actor, pack_id, slot, purpose="training", *, lock=False):
        return self.connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE actor_id=%s AND pack_id=%s "
            "AND slot=%s AND purpose=%s ORDER BY attempt_number DESC LIMIT 1"
            + (" FOR UPDATE" if lock else ""),
            (actor.id, pack_id, slot, purpose),
        ).fetchone()

    def create(
        self, actor, pack_id, item, answer, key, purpose, *,
        practice=None, gate_id=None, transfer_id=None,
    ):
        try:
            answer = item.normalize_answer(answer)
            program = item.execution(answer)
        except ValueError as error:
            raise BusinessError("precondition_failed", str(error)) from None
        answer_data = answer.model_dump(mode="json")
        previous_id = practice.previous_attempt_id if practice else None
        retry = practice.retry if practice else False
        old = self.connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE actor_id=%s AND idempotency_key=%s",
            (actor.id, key),
        ).fetchone()
        if old:
            if (
                old["pack_id"], old["slot"], old["answer"], old["purpose"],
                old["previous_attempt_id"], old["retry_requested"],
                old["gate_id"], old["transfer_id"],
            ) != (
                pack_id, item.slot, answer_data, purpose, previous_id, retry, gate_id, transfer_id,
            ):
                raise BusinessError("idempotency_conflict", "Program submission changed.")
            return old, False
        latest = self.latest(actor, pack_id, item.slot, purpose, lock=True)
        if purpose in {"qualification", "gate", "transfer"}:
            if latest or practice is not None:
                raise BusinessError("precondition_failed", "This exact program purpose is locked.")
            if (purpose == "gate") != (gate_id is not None) or (
                purpose == "transfer"
            ) != (transfer_id is not None):
                raise BusinessError(
                    "precondition_failed", "Exact program purpose binding required.",
                )
        elif purpose == "training" and practice is not None:
            if (latest["id"] if latest else None) != previous_id:
                raise BusinessError("stale_version", "The exact latest program attempt changed.")
            if latest and latest["status"] == "queued":
                raise BusinessError("precondition_failed", "The previous program is still pending.")
            if retry:
                if not latest or latest["status"] != "error" or latest["answer"] != answer_data:
                    raise BusinessError(
                        "precondition_failed", "Retry needs the same errored answer.",
                    )
            elif latest and latest["answer"] == answer_data:
                raise BusinessError(
                    "precondition_failed", "Change the program or explicitly retry.",
                )
        else:
            raise BusinessError(
                "precondition_failed", "Only explicit ordinary practice can repeat.",
            )
        attempt_id = uuid4()
        sql = item.language == "sql_query"
        self.connection.execute(
            "INSERT INTO assessment.program_attempts(id,actor_id,pack_id,slot,purpose,"
            "idempotency_key,environment,answer,execution_input,test_cases,comparison_profile,"
            "comparison_order,attempt_number,previous_attempt_id,retry_requested,"
            "sample_case_index,gate_id,transfer_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                attempt_id, actor.id, pack_id, item.slot, purpose, key,
                Jsonb(item.environment.model_dump(mode="json")), Jsonb(answer_data),
                Jsonb(program.model_dump(mode="json")),
                Jsonb([case.model_dump(mode="json") for case in item.tests]),
                item.comparison_profile,
                item.comparison if sql else None,
                latest["attempt_number"] + 1 if latest else 1, previous_id, retry,
                item.tests.index(item.sample),
                gate_id, transfer_id,
            ),
        )
        return self.row(actor, attempt_id), True

    @staticmethod
    def public(row):
        if row["purpose"] != "training":
            raise BusinessError("not_found", "Ordinary program attempt not found.")
        return ProgramPracticeAttempt(**{
            key: row[key] for key in ProgramPracticeAttempt.model_fields if key in row
        })

    @staticmethod
    def transfer_public(row):
        if row["purpose"] != "transfer":
            raise BusinessError("not_found", "Program transfer attempt not found.")
        return ProgramTransferAttempt(**{
            key: row[key] for key in ProgramTransferAttempt.model_fields
        })

    def request(self, actor, key):
        row = self.connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE actor_id=%s AND idempotency_key=%s "
            "AND purpose='training'", (actor.id, key),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "No committed ordinary program request.")
        return self.public(row)

    def history(self, actor, pack_id, slot, before=None, limit=20):
        latest = self.latest(actor, pack_id, slot)
        sequence = None
        if before is not None:
            cursor = self.row(actor, before)
            if (cursor["pack_id"], cursor["slot"], cursor["purpose"]) != (
                pack_id, slot, "training",
            ):
                raise BusinessError("not_found", "Program history cursor not found.")
            sequence = cursor["attempt_number"]
        rows = self.connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE actor_id=%s AND pack_id=%s "
            "AND slot=%s AND purpose='training' AND (%s::int IS NULL OR attempt_number<%s) "
            "ORDER BY attempt_number DESC LIMIT %s",
            (actor.id, pack_id, slot, sequence, sequence, limit + 1),
        ).fetchall()
        return ProgramPracticeHistory(
            latest_attempt_id=latest["id"] if latest else None,
            attempts=[self.public(row) for row in rows[:limit]],
            next_before=rows[limit - 1]["id"] if len(rows) > limit else None,
        )

    @staticmethod
    def matches_sql(actual, expected, order):
        try:
            actual = SqlTableResult.model_validate(actual)
            expected = SqlTableResult.model_validate(expected)
        except (ValidationError, TypeError):
            return False
        if actual.columns != expected.columns:
            return False
        left = [tuple(zip(row, kinds, strict=True)) for row, kinds in
                zip(actual.rows, actual.types, strict=True)]
        right = [tuple(zip(row, kinds, strict=True)) for row, kinds in
                 zip(expected.rows, expected.types, strict=True)]
        return left == right if order == "ordered" else Counter(left) == Counter(right)

    @staticmethod
    def normalize_stdio(value):
        return value.replace("\r\n", "\n").removesuffix("\n")

    @staticmethod
    def matches_http(actual, test):
        try:
            result = HttpScenarioResult.model_validate_json(actual)
        except (ValueError, TypeError):
            return False
        if len(result.responses) != len(test["expected"]):
            return False
        for response, expected in zip(result.responses, test["expected"], strict=True):
            if response.status != expected["status"]:
                return False
            try:
                left = json.dumps(json.loads(response.body), sort_keys=True, ensure_ascii=False)
                right = json.dumps(json.loads(expected["body"]), sort_keys=True, ensure_ascii=False)
            except (ValueError, TypeError):
                left, right = response.body, expected["body"]
            if left != right:
                return False
        return True

    def require_training(self, actor, pack_id):
        from leornian.modules.assessment.transfers import Transfers

        rows = [self.latest(actor, pack_id, slot) for slot in ("practice_1", "practice_2")]
        if any(not row or row["status"] in {"queued", "error"} for row in rows):
            raise BusinessError("precondition_failed", "Complete both actual program practices.")
        if any(row["status"] != "passed" for row in rows):
            remediation = self.latest(actor, pack_id, "remediation_1")
            kind = {
                "sql-query.v1": "sql_query", "python-project-io.v1": "python_project",
                "project-stdio.v1": "project_stdio", "web-check.v1": "web_project",
                "project-http.v1": "http_project",
            }[rows[0]["environment"]["profile"]]
            if not remediation or (
                remediation["status"] != "passed" and not Transfers(self.connection).passed_for(
                    actor, remediation["id"], kind=kind,
                )
            ):
                raise BusinessError("precondition_failed", "Pass the assigned program remediation.")

    @staticmethod
    def web_observations(row, cases):
        if len(cases) != 1:
            return None
        case = cases[0]
        if case.outcome != "completed" or case.exit_code != 0:
            return {}
        try:
            result = WebCheckResult.model_validate_json(case.stdout)
        except (ValueError, TypeError):
            return None
        actual = {value.key: value.actual for value in result.results}
        if set(actual) != {test["check"]["key"] for test in row["test_cases"]}:
            return None
        return actual

    @staticmethod
    def public_sample(row, cases):
        index = row["sample_case_index"]
        web = row["comparison_profile"] == "web-check.v1"
        if row["purpose"] != "training" or index is None or len(cases) != (1 if web else 3):
            return None
        # The owner's frozen sample identity selects one case, never the entire private report.
        case = cases[0 if web else index]
        output, integer_text, text_output = None, None, None
        if case.outcome == "completed" and case.exit_code == 0:
            try:
                if row["comparison_profile"] == "stdio-text.v1":
                    text_output = case.stdout
                    actual = None
                elif row["comparison_profile"] == "http-response.v1":
                    output = HttpScenarioResult.model_validate_json(case.stdout)
                    actual = None
                elif web:
                    observations = ProgramAssessment.web_observations(row, cases)
                    key = row["test_cases"][index]["check"]["key"]
                    if observations is not None and key in observations:
                        output = WebCheckResult(results=[{
                            "key": key, "actual": observations[key],
                        }])
                    actual = None
                else:
                    actual = json.loads(case.stdout)
                if row["comparison_profile"] == "sql-result-typed.v1":
                    output = SqlTableResult.model_validate(actual)
                elif type(actual) is int:
                    integer_text = str(actual)
                    # Keep public values exact for JavaScript readers, including wrong answers.
                    output = actual if abs(actual) <= 9_007_199_254_740_991 else None
            except (ValueError, TypeError):
                pass
        return ProgramSampleResult(
            outcome=case.outcome, exit_code=case.exit_code, output=output,
            integer_text=integer_text, text_output=text_output,
        ).model_dump(mode="json")

    def complete(self, row, cases, compilation=None):
        if row["status"] != "queued":
            return row
        passed = 0
        compilation_failed = compilation and (
            compilation.outcome != "completed" or compilation.exit_code != 0
        )
        web = row["comparison_profile"] == "web-check.v1"
        observations = self.web_observations(row, cases) if web else None
        invalid = (
            not compilation_failed
            and (len(cases) != (1 if web else 3) or web and observations is None)
        ) or (
            compilation_failed
            and any(case.stdout or case.outcome == "completed" and case.exit_code == 0
                    for case in cases)
        )
        if web and observations is not None:
            for test in row["test_cases"]:
                actual = observations.get(test["check"]["key"])
                expected = test["expected"]
                passed += int(type(actual) is type(expected) and actual == expected)
        elif not web and not invalid and not compilation_failed:
            for case, test in zip(cases, row["test_cases"], strict=True):
                if case.outcome != "completed" or case.exit_code != 0:
                    continue
                if row["comparison_profile"] == "stdio-text.v1":
                    passed += int(
                        self.normalize_stdio(case.stdout) == self.normalize_stdio(test["expected"])
                    )
                    continue
                if row["comparison_profile"] == "http-response.v1":
                    passed += int(self.matches_http(case.stdout, test))
                    continue
                try:
                    actual = json.loads(case.stdout)
                except (ValueError, TypeError):
                    continue
                if row["comparison_profile"] == "sql-result-typed.v1":
                    matched = self.matches_sql(actual, test["expected"], row["comparison_order"])
                else:
                    matched = type(actual) is int and actual == test["expected"]
                passed += int(matched)
        if compilation_failed:
            passed = 0
        infrastructure_error = (
            any(c.outcome == "infrastructure_error" for c in cases)
            or compilation and compilation.outcome == "infrastructure_error"
        )
        status = (
            "error" if invalid or infrastructure_error
            else "passed" if passed == 3 else "not_passed"
        )
        error_code = (
            "invalid_execution_report" if invalid else
            "runner_environment_unavailable"
            if infrastructure_error else None
        )
        sample = None if compilation_failed else self.public_sample(row, cases)
        feedback = (
            "Compilation did not complete successfully; no learner case was executed."
            if compilation_failed else
            f"Passed {passed}/3 frozen cases; practice is not mastery or Gate evidence."
        )
        self.connection.execute(
            "UPDATE assessment.program_attempts SET status=%s,passed_cases=%s,feedback=%s,"
            "error_code=%s,sample_result=%s,compilation=%s,completed_at=now() "
            "WHERE id=%s AND status='queued'",
            (
                status, passed, feedback, error_code,
                Jsonb(sample) if sample is not None else None,
                Jsonb(compilation.model_dump(mode="json")) if compilation else None, row["id"],
            ),
        )
        return {
            **row, "status": status, "passed_cases": passed, "error_code": error_code,
            "sample_result": sample, "compilation": compilation, "feedback": feedback,
        }

    def fail(self, attempt_id, reason, code="execution_not_applicable"):
        self.connection.execute(
            "UPDATE assessment.program_attempts SET status='error',feedback=%s,error_code=%s,"
            "completed_at=now() WHERE id=%s AND status='queued'", (reason, code, attempt_id),
        )

    def list(self, actor):
        rows = self.connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE actor_id=%s AND purpose='training' "
            "ORDER BY created_at DESC,id LIMIT 100", (actor.id,),
        ).fetchall()
        return [self.public(row) for row in rows]
