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

    def claim(
        self, runner_id: str, program_environments=(), *, example_terminal=False,
    ) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM execution.jobs WHERE status = 'queued' "
            "AND (example_terminal IS NULL OR %s) "
            "AND (program_environment IS NULL OR program_environment IN "
            "(SELECT jsonb_array_elements(%s::jsonb))) "
            "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED",
            (example_terminal,
             Jsonb([value.model_dump(mode="json") for value in program_environments])),
        ).fetchone()
        if row is None:
            return None
        claim_token = uuid4()
        self.connection.execute(
            "UPDATE execution.jobs SET status = 'running', claim_token = %s, runner_id = %s, "
            "lease_until = now() + CASE WHEN program_environment IS NULL "
            "THEN interval '90 seconds' "
            "WHEN program_environment->>'profile'='project-http.v1' THEN interval '600 seconds' "
            "ELSE interval '300 seconds' END WHERE id = %s",
            (claim_token, runner_id, row["id"]),
        )
        return {**row, "claim_token": claim_token}

    def enqueue_python(self, actor, attempt_id, session_digest):
        self.connection.execute(
            "INSERT INTO execution.jobs(id,actor_id,python_input_ref,session_digest) "
            "VALUES(%s,%s,%s,%s) ON CONFLICT(python_input_ref) DO NOTHING",
            (uuid4(), actor.id, attempt_id, session_digest),
        )

    def enqueue_program(self, actor, attempt_id, session_digest, environment):
        self.connection.execute(
            "INSERT INTO execution.jobs(id,actor_id,program_input_ref,session_digest,"
            "program_environment) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT(program_input_ref) DO NOTHING",
            (uuid4(), actor.id, attempt_id, session_digest, Jsonb(environment)),
        )

    def example(self, actor, command_id, *, lock=False):
        return self.connection.execute(
            "SELECT * FROM execution.jobs WHERE actor_id=%s AND example_input IS NOT NULL "
            "AND example_input->>'command_id'=%s" + (" FOR UPDATE" if lock else ""),
            (actor.id, str(command_id)),
        ).fetchone()

    def latest_reported_example(self, actor, conversation_id, artifact_id, revision, before):
        return self.connection.execute(
            "SELECT component_id,language,phase,observed->>'outcome' AS outcome,"
            "(observed->>'exit_code')::int AS exit_code FROM ("
            "SELECT example_input->>'component_id' AS component_id,"
            "example_input->>'language' AS language,"
            "CASE WHEN report#>'{cases,0}' IS NULL THEN 'compilation' ELSE 'execution' END "
            "AS phase,coalesce(report#>'{cases,0}',report->'compilation') AS observed "
            "FROM execution.jobs WHERE actor_id=%s AND status='reported' AND reported_at<=%s "
            "AND example_input->>'conversation_id'=%s AND example_input->>'artifact_id'=%s "
            "AND NOT (example_input ? 'practice_only') "
            "AND example_input->>'expected_artifact_revision'=%s "
            "ORDER BY reported_at DESC,id DESC LIMIT 1) AS latest",
            (actor.id, before, str(conversation_id), str(artifact_id), str(revision)),
        ).fetchone()

    def reported_example_outcomes(self, actor, conversation_id, artifact_id, revision, before):
        rows = self.connection.execute(
            "WITH reports AS (SELECT id,reported_at,example_input->>'command_id' AS command_id,"
            "example_input->>'component_id' AS component_id,example_input->>'language' AS language,"
            "CASE WHEN report#>>'{cases,0,outcome}' IS NOT NULL THEN 'execution' "
            "WHEN report#>>'{compilation,outcome}' IS NOT NULL THEN 'compilation' "
            "ELSE 'runner' END AS phase,coalesce(report#>>'{cases,0,outcome}',"
            "report#>>'{compilation,outcome}',report->>'error_code') AS outcome,"
            "coalesce(report#>>'{cases,0,exit_code}',report#>>'{compilation,exit_code}')::int "
            "AS exit_code FROM execution.jobs WHERE actor_id=%s AND status='reported' "
            "AND reported_at<=%s AND example_input->>'conversation_id'=%s "
            "AND NOT (example_input ? 'practice_only') "
            "AND example_input->>'artifact_id'=%s "
            "AND example_input->>'expected_artifact_revision'=%s"
            "), ranked AS (SELECT *,count(*) OVER grp AS report_count,row_number() OVER "
            "(grp ORDER BY reported_at DESC,id DESC) AS position FROM reports "
            "WINDOW grp AS (PARTITION BY component_id,language,phase,outcome,(exit_code=0))) "
            "SELECT component_id,language,phase,outcome,exit_code,command_id,reported_at,"
            "report_count "
            "FROM ranked WHERE position=1 ORDER BY reported_at DESC,id DESC",
            (actor.id, before, str(conversation_id), str(artifact_id), str(revision)),
        ).fetchall()
        return [{**row, "reported_at": row["reported_at"].isoformat()} for row in rows]

    def enqueue_example(self, actor, digest, example, environment):
        terminal = {"ready": False, "stopping": False, "transcript": "", "inputs": [], "frame": 0}
        return self.connection.execute(
            "INSERT INTO execution.jobs(id,actor_id,session_digest,example_input,"
            "program_environment,example_terminal) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
            (uuid4(), actor.id, digest, Jsonb(example), Jsonb(environment) if environment else None,
             Jsonb(terminal) if example.get("interactive") else None),
        ).fetchone()

    def detach_example(self, job_id):
        self.connection.execute(
            "UPDATE execution.jobs SET example_input=example_input || '{\"practice_only\":true}' "
            "WHERE id=%s AND status='running' AND NOT (example_input ? 'practice_only')",
            (job_id,),
        )

    def save_terminal(self, row):
        self.connection.execute(
            "UPDATE execution.jobs SET example_terminal=%s WHERE id=%s",
            (Jsonb(row["example_terminal"]), row["id"]),
        )

    def send_terminal_line(self, row, line):
        terminal = row["example_terminal"]
        entry = line.model_dump(mode="json")
        for previous in terminal["inputs"]:
            if previous["input_id"] == entry["input_id"]:
                if previous != entry:
                    raise BusinessError("idempotency_conflict", "这次输入已发送。")
                return
        if row["status"] != "running" or not terminal["ready"] or terminal["stopping"]:
            raise BusinessError("precondition_failed", "程序当前不接收输入。")
        self.current_claim(row["id"], row["claim_token"])
        lines = terminal["inputs"]
        if len(lines) >= 128 or sum(len(item["text"]) + 1 for item in [*lines, entry]) > 8192:
            raise BusinessError("precondition_failed", "本次终端输入已达上限，请重新运行。")
        lines.append(entry)
        terminal["transcript"] += line.text + "\n"
        self.save_terminal(row)

    def stop_terminal(self, row):
        if row["status"] == "queued":
            self.abandon(row["id"], "learner_cancelled")
            row.update(status="expired", report={"error_code": "learner_cancelled"})
        elif row["status"] == "running" and not (
            row["example_terminal"]["stopping"] or row["example_terminal"].get("closed")
        ):
            row["example_terminal"]["stopping"] = True
            self.save_terminal(row)

    def terminal_exchange(self, job_id, data):
        row = self.current_claim(job_id, data.claim_token, lock=True)
        terminal = row["example_terminal"]
        if not terminal or terminal["stopping"] or terminal.get("closed"):
            raise BusinessError("precondition_failed", "该运行不接收终端数据。")
        if (data.after_input > len(terminal["inputs"])
                or data.frame != terminal["frame"] + bool(data.text)):
            raise BusinessError("stale_version", "终端数据顺序不一致。")
        if not terminal["ready"] or data.text or data.closed:
            terminal["ready"], terminal["closed"] = not data.closed, data.closed
            terminal["transcript"] += data.text
            if len(terminal["transcript"]) > 16384:
                raise BusinessError("precondition_failed", "本次终端输出已达上限。")
            terminal["frame"] = data.frame
            self.save_terminal(row)
        return {"lines": [] if data.closed else [
            item["text"] for item in terminal["inputs"][data.after_input:]
        ]}

    def shared_teaching_example(self, actor, conversation_id, revisions, before):
        if not revisions:
            return None
        return self.connection.execute(
            "SELECT example_input->>'artifact_id' AS artifact_id,"
            "example_input->>'command_id' AS command_id,example_input->>'code' AS code,"
            "example_input->>'component_id' AS component_id,example_input->>'language' AS language "
            "FROM execution.jobs WHERE actor_id=%s AND status='reported' AND reported_at<=%s "
            "AND example_input->>'conversation_id'=%s AND "
            "example_input @> '{\"share_code_for_teaching\":true}'::jsonb "
            "AND NOT (example_input ? 'practice_only') "
            "AND example_input->>'expected_artifact_revision'="
            "(%s::jsonb ->> (example_input->>'artifact_id')) "
            "AND (report->>'compilation' IS NULL OR (report#>>'{compilation,outcome}'='completed' "
            "AND report#>>'{compilation,exit_code}'='0')) "
            "AND report#>>'{cases,0,outcome}'='completed' AND report#>>'{cases,0,exit_code}'='0' "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (actor.id, before, str(conversation_id), Jsonb(revisions)),
        ).fetchone()

    def expire_examples(self):
        return self.connection.execute(
            "UPDATE execution.jobs SET status='expired',reported_at=now(),"
            "report='{\"error_code\":\"runner_lease_expired\"}' WHERE example_input IS NOT NULL "
            "AND ((status='running' AND lease_until<now()) OR "
            "(status='queued' AND created_at<now()-interval '5 minutes'))"
        ).rowcount

    def abandon(self, job_id: UUID, code: str) -> None:
        self.connection.execute(
            "UPDATE execution.jobs SET status = 'expired', report = %s, reported_at = now() "
            "WHERE id = %s AND status IN ('queued', 'running')",
            (Jsonb({"error_code": code}), job_id),
        )

    def cancel_python(self, actor, attempt_id):
        row = self.connection.execute(
            "SELECT id FROM execution.jobs WHERE actor_id=%s AND python_input_ref=%s FOR UPDATE",
            (actor.id, attempt_id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Practice execution not found.")
        self.abandon(row["id"], "learner_cancelled")

    def cancel_program(self, actor, attempt_id):
        row = self.connection.execute(
            "SELECT id FROM execution.jobs WHERE actor_id=%s AND program_input_ref=%s FOR UPDATE",
            (actor.id, attempt_id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Program execution not found.")
        self.abandon(row["id"], "learner_cancelled")

    def reference(self, job_id: UUID) -> dict:
        row = self.connection.execute(
            "SELECT id, actor_id, input_ref, python_input_ref,program_input_ref,session_digest,"
            "example_input,program_environment "
            "FROM execution.jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Execution not found.")
        return row

    def current_claim(self, job_id: UUID, claim_token: UUID, *, lock=False) -> dict:
        row = self.connection.execute(
            "SELECT *,lease_until>now() AS lease_valid FROM execution.jobs WHERE id=%s"
            + (" FOR UPDATE" if lock else ""),
            (job_id,),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Execution not found.")
        if row["claim_token"] != claim_token:
            raise BusinessError("stale_version", "Runner claim token changed.")
        if row["status"] != "running" or not row["lease_valid"]:
            raise BusinessError(
                "precondition_failed", "The original execution claim is not current."
            )
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

    def expired_programs(self):
        return self.connection.execute(
            "SELECT id,actor_id,program_input_ref FROM execution.jobs WHERE status='running' "
            "AND lease_until<now() AND program_input_ref IS NOT NULL "
            "ORDER BY lease_until,id LIMIT 25",
        ).fetchall()

    def lock_expired_program(self, job_id):
        return self.connection.execute(
            "SELECT * FROM execution.jobs WHERE id=%s AND status='running' AND lease_until<now() "
            "AND program_input_ref IS NOT NULL FOR UPDATE SKIP LOCKED", (job_id,),
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
        if row["status"] == "running" and (row["example_terminal"] or {}).get("stopping"):
            self.abandon(job_id, "learner_cancelled")
            row["status"], previous = "expired", {"error_code": "learner_cancelled"}
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
