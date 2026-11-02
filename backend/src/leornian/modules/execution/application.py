from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.execution.contracts import RunnerReport
from leornian.modules.identity.contracts import Actor
from leornian.shared_kernel.errors import BusinessError


class Execution:
    def __init__(self, connection: Connection):
        self.connection = connection

    def enqueue(self, actor: Actor, attempt_id: UUID, session_digest: str) -> None:
        self.connection.execute(
            "INSERT INTO execution.jobs(id, actor_id, input_ref, session_digest) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (input_ref) DO NOTHING",
            (uuid4(), actor.id, attempt_id, session_digest),
        )

    def claim(self, runner_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM execution.jobs WHERE status = 'queued' "
            "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED",
        ).fetchone()
        if row is None:
            return None
        claim_token = uuid4()
        self.connection.execute(
            "UPDATE execution.jobs SET status = 'running', claim_token = %s, runner_id = %s, "
            "lease_until = now() + interval '90 seconds' WHERE id = %s",
            (claim_token, runner_id, row["id"]),
        )
        return {**row, "claim_token": claim_token}

    def enqueue_python(self, actor, attempt_id, session_digest):
        self.connection.execute(
            "INSERT INTO execution.jobs(id,actor_id,python_input_ref,session_digest) "
            "VALUES(%s,%s,%s,%s) ON CONFLICT(python_input_ref) DO NOTHING",
            (uuid4(), actor.id, attempt_id, session_digest),
        )

    def abandon(self, job_id: UUID, code: str) -> None:
        self.connection.execute(
            "UPDATE execution.jobs SET status = 'expired', report = %s, reported_at = now() "
            "WHERE id = %s AND status IN ('queued', 'running')",
            (Jsonb({"error_code": code}), job_id),
        )

    def reference(self, job_id: UUID) -> dict:
        row = self.connection.execute(
            "SELECT id, actor_id, input_ref, python_input_ref,session_digest "
            "FROM execution.jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Execution not found.")
        return row

    def expired(self) -> list[dict]:
        return self.connection.execute(
            "SELECT * FROM execution.jobs WHERE status = 'running' AND lease_until < now() "
            "AND input_ref IS NOT NULL "
            "ORDER BY lease_until LIMIT 25 FOR UPDATE SKIP LOCKED",
        ).fetchall()

    def expired_python(self):
        return self.connection.execute(
            "SELECT id,actor_id,python_input_ref FROM execution.jobs WHERE status='running' "
            "AND lease_until<now() AND python_input_ref IS NOT NULL "
            "ORDER BY lease_until,id LIMIT 25"
        ).fetchall()

    def lock_expired_python(self, job_id):
        return self.connection.execute(
            "SELECT * FROM execution.jobs WHERE id=%s AND status='running' AND lease_until<now() "
            "AND python_input_ref IS NOT NULL FOR UPDATE SKIP LOCKED",
            (job_id,),
        ).fetchone()

    def report(self, job_id: UUID, report: RunnerReport) -> tuple[dict, bool, bool]:
        row = self.connection.execute(
            "SELECT *, lease_until > now() AS lease_valid FROM execution.jobs "
            "WHERE id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Execution not found.")
        if row["claim_token"] != report.claim_token:
            raise BusinessError("stale_version", "Runner claim token changed.")
        payload = report.model_dump(mode="json")
        previous = row["report"] or {}
        recorded = previous.get("late_receipt") if row["status"] == "expired" else previous
        if row["status"] == "reported" or recorded and row["status"] == "expired":
            if recorded != payload:
                raise BusinessError("idempotency_conflict", "Report has already been recorded.")
            return row, False, False
        if row["status"] != "running" or not row["lease_valid"]:
            # Preserve a receipt from the actual claimant, but never apply a late execution.
            self.connection.execute(
                "UPDATE execution.jobs SET status = 'expired', report = %s, reported_at = now() "
                "WHERE id = %s",
                (
                    Jsonb(
                        {
                            "error_code": previous.get("error_code", "runner_lease_expired"),
                            "late_receipt": payload,
                        }
                    ),
                    job_id,
                ),
            )
            return row, True, False
        self.connection.execute(
            "UPDATE execution.jobs SET status = 'reported', report = %s, reported_at = now() "
            "WHERE id = %s",
            (Jsonb(payload), job_id),
        )
        return row, True, True
