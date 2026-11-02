from __future__ import annotations

import json
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.agent_runtime.contracts import Lease, Receipt, Run, StoredCall, ToolActivity
from leornian.agent_runtime.tools import LEGACY_TOOLS, contracts
from leornian.shared_kernel.errors import BusinessError

RUN_COLUMNS = (
    "r.id, r.scope_id AS conversation_id, r.input_ref AS turn_id, r.status, "
    "r.cancel_requested, r.error_code, r.created_at, r.completed_at, "
    "CASE r.policy_version WHEN 'planner.v1' THEN 'planning' WHEN 'lesson.v1' THEN 'lesson' "
    "WHEN 'tutor.v1' THEN 'teaching' WHEN 'gate_relation.v1' THEN 'gate' "
    "WHEN 'transfer_relation.v1' THEN 'transfer' "
    "WHEN 'evaluation.v1' THEN 'evaluation' "
    "WHEN 'artifact.v1' THEN 'artifact' "
    "ELSE 'item_supply' END AS purpose, "
    "(SELECT count(*) FROM runtime.tool_invocations t WHERE t.run_id = r.id) AS tool_count, "
    "((r.status = 'blocked_unknown' OR (r.status='failed' "
    "AND r.policy_version='gate_relation.v1' AND r.error_code='invalid_relation_batch')) "
    "AND EXISTS (SELECT 1 FROM runtime.external_calls c "
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
        tools: tuple[str, ...] | None = None,
    ) -> Run:
        run_id = uuid4()
        self.connection.execute(
            "INSERT INTO runtime.runs(id, actor_id, scope_id, input_ref, "
            "session_digest, policy_version, tool_contracts) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                actor_id,
                conversation_id,
                turn_id,
                digest,
                policy_version,
                Jsonb(
                    contracts(
                        tools
                        if tools is not None
                        else LEGACY_TOOLS
                        if policy_version == "tutor.v1"
                        else ()
                    )
                ),
            ),
        )
        self.connection.execute("INSERT INTO runtime.wakeups(run_id) VALUES (%s)", (run_id,))
        return self.get(actor_id, run_id)

    def calibration(self, endpoint, model, stage):
        rows = self.connection.execute(
            "SELECT (usage->>'prompt_tokens')::numeric/"
            "(policy_snapshot->>'estimated_input_tokens')::numeric AS ratio "
            "FROM runtime.external_calls WHERE endpoint=%s AND request->>'model'=%s "
            "AND policy_snapshot->>'stage'=%s AND status='result_recorded' "
            "AND jsonb_typeof(usage->'prompt_tokens')='number' "
            "AND (usage->>'prompt_tokens')::numeric>0 "
            "AND (policy_snapshot->>'estimated_input_tokens')::numeric>0 "
            "ORDER BY recorded_at DESC LIMIT 16",
            (endpoint, model, stage),
        ).fetchall()
        return max(float(row["ratio"]) for row in rows) if rows else 1.0

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

    def actor_active(self, actor_id):
        return (
            self.connection.execute(
                "SELECT id FROM runtime.runs WHERE actor_id=%s "
                "AND status IN ('queued','running','blocked_unknown') LIMIT 1",
                (actor_id,),
            ).fetchone()
            is not None
        )

    def lock(self, run_id: UUID) -> dict | None:
        return self.connection.execute(
            "SELECT *, lease_until > now() AS lease_valid FROM runtime.runs "
            "WHERE id = %s FOR UPDATE",
            (run_id,),
        ).fetchone()

    def actor_pending(self, actor_id):
        return self.connection.execute(
            "SELECT id,status,policy_version FROM runtime.runs WHERE actor_id=%s "
            "AND status IN ('queued','running','blocked_unknown') ORDER BY created_at LIMIT 1",
            (actor_id,),
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

    def protocol_history(self, actor_id: UUID, turn_ids: list[UUID]) -> dict:
        """Private protocol data from accepted teaching authors, never quality reviewers."""
        if not turn_ids:
            return {}
        rows = self.connection.execute(
            "SELECT DISTINCT ON (r.input_ref) r.input_ref,c.response_body,c.request "
            "FROM runtime.runs r JOIN runtime.external_calls c ON c.run_id=r.id "
            "WHERE r.actor_id=%s AND r.input_ref=ANY(%s) AND r.status='succeeded' "
            "AND c.status='result_recorded' AND c.applied "
            "AND COALESCE(c.policy_snapshot->>'stage',r.policy_version) "
            "IN ('tutor.v1','artifact.v1') "
            "ORDER BY r.input_ref,c.step DESC",
            (actor_id, turn_ids),
        ).fetchall()
        history = {}
        for row in rows:
            # The approved author's final input contains every same-turn tool exchange.
            # Stop before user/system input rather than copying its old selected history.
            tail = []
            for message in reversed(row["request"]["messages"]):
                if message["role"] not in {"assistant", "tool"}:
                    break
                tail.insert(0, message)
            message = json.loads(row["response_body"])["choices"][0]["message"]
            history[row["input_ref"]] = tail + [
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "reasoning_content": message.get("reasoning_content"),
                }
            ]
        return history

    def bind_sources(self, run_id: UUID, refs: list[dict]) -> None:
        self.connection.execute(
            "UPDATE runtime.runs SET context_refs = %s WHERE id = %s",
            (Jsonb(refs), run_id),
        )

    def latest(self, run_id: UUID) -> StoredCall | None:
        row = self.connection.execute(
            "SELECT id, step, status, endpoint, request, response_body, http_status, applied, "
            "policy_snapshot, context_manifest "
            "FROM runtime.external_calls WHERE run_id = %s ORDER BY step DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return StoredCall(**row) if row else None

    def first(self, run_id: UUID) -> StoredCall | None:
        row = self.connection.execute(
            "SELECT id, step, status, endpoint, request, response_body, http_status, applied, "
            "policy_snapshot, context_manifest "
            "FROM runtime.external_calls WHERE run_id=%s AND step=1",
            (run_id,),
        ).fetchone()
        return StoredCall(**row) if row else None

    def receipts(self, run_id):
        return self.connection.execute(
            "SELECT id,step,response_body FROM runtime.external_calls WHERE run_id=%s "
            "AND response_body IS NOT NULL ORDER BY step",
            (run_id,),
        ).fetchall()

    def repair(self, row, digest, messages, call):
        self.connection.execute(
            "UPDATE runtime.runs SET repair_base_messages=COALESCE(repair_base_messages,messages),"
            "messages=%s,session_digest=%s WHERE id=%s",
            (Jsonb(messages), digest, row["id"]),
        )
        if call:
            self.applied(
                call.id
            )  # Invalid known data consumed as invalid, never as a passing result.
        self.resume(row["id"])

    def prepare(
        self, run_id: UUID, endpoint: str, request: dict, policy=None, manifest=None
    ) -> StoredCall:
        latest = self.latest(run_id)
        call_id = uuid4()
        self.connection.execute(
            "INSERT INTO runtime.external_calls(id, run_id, step, status, endpoint, request, "
            "policy_snapshot,context_manifest) VALUES (%s,%s,%s,'prepared',%s,%s,%s,%s)",
            (
                call_id,
                run_id,
                latest.step + 1 if latest else 1,
                endpoint,
                Jsonb(request),
                Jsonb(policy or {}),
                Jsonb(manifest or {}),
            ),
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
        finish_reason = None
        try:
            data = json.loads(receipt.body)
            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                usage = Jsonb(data["usage"])
            if isinstance(data, dict) and data.get("choices"):
                finish_reason = data["choices"][0].get("finish_reason")
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
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
            "provider_request_id = %s, usage = %s, finish_reason=%s, "
            "recorded_at = now(), error_code = NULL "
            "WHERE id = %s AND status IN ('dispatching', 'unknown')",
            (
                status,
                receipt.body,
                receipt.http_status,
                receipt.provider_request_id,
                usage,
                finish_reason,
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

    def tool(
        self,
        run_id: UUID,
        call: StoredCall,
        tool,
        result: dict,
        *,
        outcome="completed",
        duration_ms=0,
    ) -> None:
        self.connection.execute(
            "INSERT INTO runtime.tool_invocations(id, run_id, external_call_id, provider_tool_id, "
            "name, arguments, result,outcome,duration_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s,%s,%s)",
            (
                uuid4(),
                run_id,
                call.id,
                tool.id,
                tool.name,
                Jsonb(tool.arguments),
                Jsonb(result),
                outcome,
                duration_ms,
            ),
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

    def activities(self, actor_id, run_id=None):
        return [
            ToolActivity(**row)
            for row in self.connection.execute(
                "SELECT t.id,t.run_id,t.name,t.contract_version,t.outcome,"
                "t.duration_ms,t.created_at "
                "FROM runtime.tool_invocations t JOIN runtime.runs r ON r.id=t.run_id "
                "WHERE r.actor_id=%s "
                + ("AND r.id=%s " if run_id else "")
                + "ORDER BY t.created_at DESC,t.id DESC LIMIT 100",
                (actor_id, *((run_id,) if run_id else ())),
            ).fetchall()
        ]

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
            "lease_until = NULL, completed_at = NULL WHERE id = %s",
            (run_id,),
        )
        self.connection.execute(
            "UPDATE runtime.wakeups SET published_at = NULL WHERE run_id = %s",
            (run_id,),
        )

    def heartbeat(self, lease: Lease, seconds: int) -> bool:
        return (
            self.connection.execute(
                "UPDATE runtime.runs SET lease_until=now()+make_interval(secs=>%s),"
                "heartbeat_at=now() "
                "WHERE id=%s AND lease_token=%s AND status='running' AND NOT cancel_requested "
                "AND lease_until>now() RETURNING id",
                (seconds, lease.run_id, lease.token),
            ).fetchone()
            is not None
        )
