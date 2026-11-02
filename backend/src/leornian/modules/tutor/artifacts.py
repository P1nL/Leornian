"""Append-only teaching notes; not a replacement owner for lessons/items/evaluations."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.tutor.artifact_contracts import (
    ArtifactDocument,
    ArtifactJob,
    ArtifactSummary,
    ArtifactView,
)
from leornian.shared_kernel.errors import BusinessError


class Artifacts:
    def __init__(self, connection):
        self.connection = connection

    def head(self, actor, artifact_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM tutor.artifacts WHERE actor_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (actor.id, artifact_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Teaching artifact not found.")
        return row

    def get(self, actor, artifact_id, revision):
        row = self.connection.execute(
            "SELECT a.id,a.goal_id,a.focus,v.revision,v.document,v.created_at "
            "FROM tutor.artifacts a JOIN tutor.artifact_versions v ON v.artifact_id=a.id "
            "WHERE a.actor_id=%s AND a.id=%s AND v.revision=%s",
            (actor.id, artifact_id, revision),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Accepted artifact revision not found.")
        return ArtifactView(**row, title=row["document"]["title"])

    def list(self, actor, goal_id=None, focus=None, before=None, limit=100):
        anchor = self.head(actor, before) if before else None
        if anchor and goal_id and anchor["goal_id"] != goal_id:
            raise BusinessError("not_found", "Artifact cursor is outside this goal.")
        rows = self.connection.execute(
            "SELECT a.id,a.goal_id,a.focus,a.revision,v.document->>'title' AS title,a.created_at "
            "FROM tutor.artifacts a JOIN tutor.artifact_versions v "
            "ON v.artifact_id=a.id AND v.revision=a.revision WHERE a.actor_id=%s "
            + ("AND a.goal_id=%s " if goal_id else "")
            + ("AND a.focus=%s " if focus is not None else "")
            + ("AND (a.created_at,a.id)<(%s,%s) " if anchor else "")
            + "ORDER BY a.created_at DESC,a.id DESC LIMIT %s",
            (
                actor.id,
                *((goal_id,) if goal_id else ()),
                *((Jsonb(focus),) if focus is not None else ()),
                *((anchor["created_at"], anchor["id"]) if anchor else ()),
                limit,
            ),
        ).fetchall()
        return [ArtifactSummary(**row) for row in rows]

    def job(self, actor, job_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM tutor.artifact_requests WHERE actor_id=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (actor.id, job_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Artifact request not found.")
        return row

    @staticmethod
    def summary(row):
        return ArtifactJob(**{key: row[key] for key in ArtifactJob.model_fields})

    def jobs(self, actor):
        return [
            self.summary(row)
            for row in self.connection.execute(
                "SELECT * FROM tutor.artifact_requests WHERE actor_id=%s "
                "ORDER BY created_at DESC,id DESC LIMIT 100",
                (actor.id,),
            ).fetchall()
        ]

    def request(
        self,
        actor,
        conversation,
        focus,
        intent_scope,
        key,
        instruction,
        artifact_id=None,
        expected_revision=0,
        parent_run_id=None,
        session_digest="",
    ):
        old = self.connection.execute(
            "SELECT * FROM tutor.artifact_requests WHERE actor_id=%s "
            "AND intent_scope=%s AND command_key=%s",
            (actor.id, intent_scope, key),
        ).fetchone()
        if old:
            if (
                old["instruction"] != instruction
                or old["expected_revision"] != expected_revision
                or (artifact_id is not None and old["artifact_id"] != artifact_id)
                or self.head(actor, old["artifact_id"])["focus"] != focus
            ):
                raise BusinessError("idempotency_conflict", "Artifact command content changed.")
            return self.summary(old)
        if artifact_id is None:
            if expected_revision:
                raise BusinessError("stale_version", "New artifacts start at revision zero.")
            artifact_id = uuid4()
            self.connection.execute(
                "INSERT INTO tutor.artifacts(id,actor_id,conversation_id,goal_id,focus) "
                "VALUES(%s,%s,%s,%s,%s)",
                (artifact_id, actor.id, conversation.id, conversation.goal_id, Jsonb(focus)),
            )
        else:
            head = self.head(actor, artifact_id, lock=True)
            if head["conversation_id"] != conversation.id or head["focus"] != focus:
                raise BusinessError("not_found", "Artifact is outside this teaching binding.")
            if head["revision"] != expected_revision or expected_revision < 1:
                raise BusinessError("stale_version", "Read the current artifact before revising.")
        row = self.connection.execute(
            "INSERT INTO tutor.artifact_requests(id,actor_id,conversation_id,artifact_id,"
            "intent_scope,command_key,instruction,expected_revision,parent_run_id,session_digest) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4(),
                actor.id,
                conversation.id,
                artifact_id,
                intent_scope,
                key,
                instruction,
                expected_revision,
                parent_run_id,
                session_digest,
            ),
        ).fetchone()
        return self.summary(row)

    def for_run(self, run_id):
        return self.connection.execute(
            "SELECT * FROM tutor.artifact_requests WHERE run_id=%s", (run_id,)
        ).fetchone()

    def current(self, actor, job):
        head = self.head(actor, job["artifact_id"], lock=True)
        if head["revision"] != job["expected_revision"]:
            raise BusinessError("stale_version", "Another accepted revision superseded this job.")
        return head

    def record(self, actor, job, content, materials):
        head = self.current(actor, job)
        doc = ArtifactDocument.model_validate_json(content, strict=True)
        allowed = {(str(m.source_id), m.revision) for m in materials}
        if any(
            (str(ref.source_id), ref.revision) not in allowed
            for section in doc.sections
            for ref in section.source_refs
        ):
            raise BusinessError("source_not_current", "Artifact has unbound source citations.")
        revision = head["revision"] + 1
        self.connection.execute(
            "INSERT INTO tutor.artifact_versions(artifact_id,revision,request_id,document,sources) "
            "VALUES(%s,%s,%s,%s,%s)",
            (
                head["id"],
                revision,
                job["id"],
                Jsonb(doc.model_dump(mode="json")),
                Jsonb([m.model_dump(mode="json") for m in materials]),
            ),
        )
        self.connection.execute(
            "UPDATE tutor.artifacts SET revision=%s WHERE id=%s", (revision, head["id"])
        )
        self.connection.execute(
            "UPDATE tutor.artifact_requests SET status='accepted' WHERE id=%s", (job["id"],)
        )
        return self.get(actor, head["id"], revision)
