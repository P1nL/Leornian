from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from psycopg import Connection

from leornian.modules.identity.contracts import Actor
from leornian.shared_kernel.contracts import Contract
from leornian.shared_kernel.errors import BusinessError


class Job(Contract):
    id: UUID
    kind: Literal["learning.create_goal"]
    status: Literal["queued", "succeeded", "failed"]
    result_ref: UUID | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class Accepted(Contract):
    status: Literal["accepted"] = "accepted"
    job_id: UUID


class JobWork(Contract):
    id: UUID
    actor_id: UUID
    input_ref: UUID
    status: str
    event_id: UUID


JOB_COLUMNS = "id, kind, status, result_ref, error_code, created_at, completed_at"


class Jobs:
    def __init__(self, connection: Connection):
        self.connection = connection

    def enqueue(self, actor: Actor, request_id: UUID) -> tuple[Job, bool]:
        row = self.connection.execute(
            f"INSERT INTO platform.jobs(id, actor_id, kind, input_ref) "
            f"VALUES (%s, %s, 'learning.create_goal', %s) "
            f"ON CONFLICT (kind, input_ref) DO NOTHING RETURNING {JOB_COLUMNS}",
            (uuid4(), actor.id, request_id),
        ).fetchone()
        if row is None:
            return Job(
                **self.connection.execute(
                    f"SELECT {JOB_COLUMNS} FROM platform.jobs "
                    "WHERE input_ref = %s AND actor_id = %s",
                    (request_id, actor.id),
                ).fetchone()
            ), False
        job = Job(**row)
        self.connection.execute(
            "INSERT INTO platform.outbox(event_id, job_id) VALUES (%s, %s)", (uuid4(), job.id)
        )
        return job, True

    def get(self, actor: Actor, job_id: UUID) -> Job:
        row = self.connection.execute(
            f"SELECT {JOB_COLUMNS} FROM platform.jobs WHERE id = %s AND actor_id = %s",
            (job_id, actor.id),
        ).fetchone()
        if row is None:
            raise BusinessError("not_found", "Job not found.")
        return Job(**row)

    def list(self, actor: Actor) -> list[Job]:
        rows = self.connection.execute(
            f"SELECT {JOB_COLUMNS} FROM platform.jobs "
            "WHERE actor_id = %s ORDER BY created_at DESC, id DESC LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [Job(**row) for row in rows]

    def lock(self, event_id: UUID) -> JobWork | None:
        row = self.connection.execute(
            "SELECT j.id, j.actor_id, j.input_ref, j.status, o.event_id "
            "FROM platform.jobs j JOIN platform.outbox o ON o.job_id = j.id "
            "WHERE o.event_id = %s FOR UPDATE OF j",
            (event_id,),
        ).fetchone()
        return JobWork(**row) if row else None

    def consume(self, event_id: UUID) -> bool:
        return (
            self.connection.execute(
                "INSERT INTO platform.inbox(consumer, event_id) "
                "VALUES ('learning.create_goal', %s) "
                "ON CONFLICT DO NOTHING RETURNING event_id",
                (event_id,),
            ).fetchone()
            is not None
        )

    def succeed(self, job_id: UUID, goal_id: UUID) -> None:
        self.connection.execute(
            "UPDATE platform.jobs SET status = 'succeeded', result_ref = %s, completed_at = now() "
            "WHERE id = %s AND status = 'queued'",
            (goal_id, job_id),
        )

    def fail(self, job_id: UUID, code: str) -> None:
        self.connection.execute(
            "UPDATE platform.jobs SET status = 'failed', error_code = %s, completed_at = now() "
            "WHERE id = %s AND status = 'queued'",
            (code, job_id),
        )
