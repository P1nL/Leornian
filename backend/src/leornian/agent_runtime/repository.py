from __future__ import annotations

import json
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.agent_runtime.contracts import Lease, Receipt, Run, StoredCall
from leornian.shared_kernel.errors import BusinessError

RUN_COLUMNS = (
    "r.id, r.scope_id AS conversation_id, r.input_ref AS turn_id, r.status, "
    "r.cancel_requested, r.error_code, r.created_at, r.completed_at, "
    "CASE r.policy_version WHEN 'planner.v1' THEN 'planning' WHEN 'lesson.v1' THEN 'lesson' "
    "ELSE 'teaching' END AS purpose, "
    "(SELECT count(*) FROM runtime.tool_invocations t WHERE t.run_id = r.id) AS tool_count, "
    "(r.status = 'blocked_unknown' AND EXISTS (SELECT 1 FROM runtime.external_calls c "
    "WHERE c.run_id = r.id AND c.status = 'result_recorded' AND NOT c.applied) "
    "AND NOT r.cancel_requested) AS can_resume"
)


class Runs:
    def __init__(self, connection: Connection):
        self.connection = connection

    def create(
        self,
        actor_id: UUID,
        conversation_id: UUID,
        turn_id: UUID,
        digest: str,
        policy_version: str = "tutor.v1",
    ) -> Run:
        run_id = uuid4()
        self.connection.execute(
            "INSERT INTO runtime.runs(id, actor_id, scope_id, input_ref, "
            "session_digest, policy_version) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (run_id, actor_id, conversation_id, turn_id, digest, policy_version),
        )
        self.connection.execute("INSERT INTO runtime.wakeups(run_id) VALUES (%s)", (run_id,))
        return self.get(actor_id, run_id)

    def get(self, actor_id: UUID, run_id: UUID) -> Run:
        row = self.connection.execute(
            f"SELECT {RUN_COLUMNS} FROM runtime.runs r WHERE r.id = %s AND r.actor_id = %s",
            (run_id, actor_id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Teaching run not found.")
        return Run(**row)

    def list(self, actor_id: UUID) -> list[Run]:
        rows = self.connection.execute(
            f"SELECT {RUN_COLUMNS} FROM runtime.runs r WHERE r.actor_id = %s "
            "ORDER BY r.created_at DESC, r.id DESC LIMIT 100",
            (actor_id,),
        ).fetchall()
        return [Run(**row) for row in rows]

    def for_turn(self, actor_id: UUID, turn_id: UUID) -> Run:
        row = self.connection.execute(
            "SELECT id FROM runtime.runs WHERE input_ref = %s AND actor_id = %s",
            (turn_id, actor_id),
        ).fetchone()
        return self.get(actor_id, row["id"])

    def active(self, conversation_id: UUID) -> bool:
        return (
            self.connection.execute(
                "SELECT id FROM runtime.runs WHERE scope_id = %s "
                "AND status IN ('queued', 'running', 'blocked_unknown')",
                (conversation_id,),
            ).fetchone()
            is not None
        )

    def lock(self, run_id: UUID) -> dict | None:
        return self.connection.execute(
            "SELECT *, lease_until > now() AS lease_valid FROM runtime.runs "
            "WHERE id = %s FOR UPDATE",
            (run_id,),
        ).fetchone()

    def claim(self, row: dict, seconds: int) -> Lease:
        lease = Lease(run_id=row["id"], token=uuid4())
        self.connection.execute(
            "UPDATE runtime.runs SET status = 'running', lease_token = %s, "
            "lease_until = now() + make_interval(secs => %s), error_code = NULL WHERE id = %s",
            (lease.token, seconds, row["id"]),
        )
        return lease

    def finish(self, run_id: UUID, status: str, code: str | None = None) -> None:
        if status in {"failed", "cancelled"}:
            self.connection.execute(
                "UPDATE runtime.external_calls SET status = 'not_sent' "
                "WHERE run_id = %s AND status = 'prepared'",
                (run_id,),
            )
        self.connection.execute(
            "UPDATE runtime.runs SET status = %s, error_code = %s, lease_token = NULL, "
            "lease_until = NULL, completed_at = CASE WHEN %s = 'blocked_unknown' "
            "THEN NULL ELSE now() END WHERE id = %s",
            (status, code, status, run_id),
        )

    def messages(self, run_id: UUID, messages: list[dict]) -> None:
        self.connection.execute(
            "UPDATE runtime.runs SET messages = %s WHERE id = %s",
            (Jsonb(messages), run_id),
        )

    def bind_sources(self, run_id: UUID, refs: list[dict]) -> None:
        self.connection.execute(
            "UPDATE runtime.runs SET context_refs = %s WHERE id = %s",
            (Jsonb(refs), run_id),
        )

    def latest(self, run_id: UUID) -> StoredCall | None:
        row = self.connection.execute(
            "SELECT id, step, status, endpoint, request, response_body, http_status, applied "
            "FROM runtime.external_calls WHERE run_id = %s ORDER BY step DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return StoredCall(**row) if row else None

    def prepare(self, run_id: UUID, endpoint: str, request: dict) -> StoredCall:
        latest = self.latest(run_id)
        call_id = uuid4()
        self.connection.execute(
            "INSERT INTO runtime.external_calls(id, run_id, step, status, endpoint, request) "
            "VALUES (%s, %s, %s, 'prepared', %s, %s)",
            (call_id, run_id, latest.step + 1 if latest else 1, endpoint, Jsonb(request)),
        )
        return self.latest(run_id)

    def dispatch(self, call_id: UUID) -> bool:
        return (
            self.connection.execute(
                "UPDATE runtime.external_calls SET status = 'dispatching', dispatched_at = now() "
                "WHERE id = %s AND status = 'prepared' RETURNING id",
                (call_id,),
            ).fetchone()
            is not None
        )

    def record(
        self, call_id: UUID, receipt: Receipt | None = None, *, unknown: bool = False
    ) -> None:
        if unknown:
            self.connection.execute(
                "UPDATE runtime.external_calls SET status = 'unknown', "
                "error_code = 'transport_unknown' "
                "WHERE id = %s AND status = 'dispatching'",
                (call_id,),
            )
            return
        usage = None
        try:
            data = json.loads(receipt.body)
            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                usage = Jsonb(data["usage"])
        except ValueError:
            pass
        # An explicit 4xx receipt is a known rejection. 5xx may hide upstream work.
        status = (
            "result_recorded"
            if 200 <= receipt.http_status < 300
            else "failed_known"
            if 400 <= receipt.http_status < 500
            else "unknown"
        )
        self.connection.execute(
            "UPDATE runtime.external_calls SET status = %s, response_body = %s, http_status = %s, "
            "provider_request_id = %s, usage = %s, recorded_at = now(), error_code = NULL "
            "WHERE id = %s AND status IN ('dispatching', 'unknown')",
            (
                status,
                receipt.body,
                receipt.http_status,
                receipt.provider_request_id,
                usage,
                call_id,
            ),
        )

    def call_run(self, call_id: UUID) -> UUID:
        return self.connection.execute(
            "SELECT run_id FROM runtime.external_calls WHERE id = %s",
            (call_id,),
        ).fetchone()["run_id"]

    def mark_unknown(self, run_id: UUID) -> None:
        self.connection.execute(
            "UPDATE runtime.external_calls SET status = 'unknown', error_code = 'lost_receipt' "
            "WHERE run_id = %s AND status = 'dispatching'",
            (run_id,),
        )

    def tool(self, run_id: UUID, call: StoredCall, tool, result: dict) -> None:
        self.connection.execute(
            "INSERT INTO runtime.tool_invocations(id, run_id, external_call_id, provider_tool_id, "
            "name, arguments, result) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (uuid4(), run_id, call.id, tool.id, tool.name, Jsonb(tool.arguments), Jsonb(result)),
        )

    def applied(self, call_id: UUID) -> None:
        self.connection.execute(
            "UPDATE runtime.external_calls SET applied = true WHERE id = %s", (call_id,)
        )

    def tool_count(self, run_id: UUID) -> int:
        return self.connection.execute(
            "SELECT count(*) AS count FROM runtime.tool_invocations WHERE run_id = %s",
            (run_id,),
        ).fetchone()["count"]

    def cancel(self, run_id: UUID) -> None:
        self.connection.execute(
            "UPDATE runtime.runs SET cancel_requested = true WHERE id = %s",
            (run_id,),
        )
        self.connection.execute(
            "UPDATE runtime.external_calls SET status = 'not_sent' "
            "WHERE run_id = %s AND status = 'prepared'",
            (run_id,),
        )

    def resume(self, run_id: UUID) -> None:
        self.connection.execute(
            "UPDATE runtime.runs SET status = 'queued', error_code = NULL, lease_token = NULL, "
            "lease_until = NULL WHERE id = %s",
            (run_id,),
        )
        self.connection.execute(
            "UPDATE runtime.wakeups SET published_at = NULL WHERE run_id = %s",
            (run_id,),
        )
