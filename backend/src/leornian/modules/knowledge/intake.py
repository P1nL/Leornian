import json
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.intake_contracts import MaterialDemand, MaterialJob
from leornian.modules.knowledge.materials import digest
from leornian.shared_kernel.errors import BusinessError

JOB_COLUMNS = (
    "id,root_id,demand_id,demand_revision,revision,state,phase,reason_code,issues,"
    "document_id,document_revision,upload_id,prepared_scope,created_at,updated_at,"
    "background_deferred"
)


class MaterialIntake:
    """Knowledge-owned demands and resumable, non-publishing material preparation."""

    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def demand_request(data):
        excluded = {"goal_text"} if data.goal_text is None else set()
        if data.scope_mode == "facets":
            excluded.add("scope_mode")
        if data.preparation == "complete":
            excluded.add("preparation")
        return data.model_dump(
            mode="json", exclude=excluded
        )

    def demand(self, actor, demand_id):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_demands WHERE id=%s AND actor_id=%s",
            (demand_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material demand not found.")
        return MaterialDemand(
            **row["specification"],
            id=row["id"],
            revision=row["revision"],
            consumer_ref=row["consumer_ref"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def demands(self, actor, goal_id, *, before=None, limit=20):
        rows = self.connection.execute(
            "SELECT id FROM knowledge.material_demands WHERE actor_id=%s AND goal_id=%s "
            "AND (%s::uuid IS NULL OR (created_at,id)<"
            "(SELECT created_at,id FROM knowledge.material_demands WHERE id=%s AND actor_id=%s)) "
            "ORDER BY created_at DESC,id DESC LIMIT %s",
            (actor.id, goal_id, before, before, actor.id, limit),
        ).fetchall()
        return [self.demand(actor, row["id"]) for row in rows]

    def replay_demand(self, actor, key, data):
        request = self.demand_request(data)
        previous = self.connection.execute(
            "SELECT * FROM knowledge.material_demand_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if previous["request"] != request:
                raise BusinessError("idempotency_conflict", "Material demand key changed.")
            return self.demand(actor, previous["demand_id"])
        return None

    def create_demand(self, actor, key, data):
        previous = self.replay_demand(actor, key, data)
        if previous:
            return previous
        request = self.demand_request(data)
        demand_id = uuid4()
        self.connection.execute(
            "INSERT INTO knowledge.material_demands"
            "(id,actor_id,goal_id,specification,consumer_ref) VALUES (%s,%s,%s,%s,%s)",
            (
                demand_id,
                actor.id,
                data.goal_id,
                Jsonb(request),
                "learner-material-demand:" + str(demand_id),
            ),
        )
        self.connection.execute(
            "INSERT INTO knowledge.material_demand_commands"
            "(actor_id,command_key,request,demand_id) VALUES (%s,%s,%s,%s)",
            (actor.id, key, Jsonb(request), demand_id),
        )
        return self.demand(actor, demand_id)

    def consumer_demand(self, actor, consumer_ref):
        row = self.connection.execute(
            "SELECT id FROM knowledge.material_demands WHERE actor_id=%s AND consumer_ref=%s",
            (actor.id, consumer_ref),
        ).fetchone()
        return self.demand(actor, row["id"]) if row else None

    def reusable_consumer_demand(self, actor, prefix, data):
        row = self.connection.execute(
            "SELECT id FROM knowledge.material_demands WHERE actor_id=%s "
            "AND starts_with(consumer_ref,%s) AND status<>'cancelled' "
            "AND specification=%s ORDER BY (status='ready') DESC,created_at DESC,id LIMIT 1",
            (actor.id, prefix + ":", Jsonb(self.demand_request(data))),
        ).fetchone()
        return self.demand(actor, row["id"]) if row else None

    def planning_batches(self, actor, goal_id):
        rows = self.connection.execute(
            "SELECT id FROM knowledge.material_demands WHERE actor_id=%s AND goal_id=%s "
            "AND specification->>'purpose'='planning' AND consumer_ref LIKE 'planning-batch:%%' "
            "AND status<>'cancelled' ORDER BY created_at,id",
            (actor.id, goal_id),
        ).fetchall()
        return [self.demand(actor, row["id"]) for row in rows]

    def planning_inputs(self, actor, goal_id):
        uploads = self.connection.execute(
            "SELECT id,content_digest,specification->'material'->>'title' AS title,"
            "specification->'material'->>'format' AS format,state "
            "FROM knowledge.material_uploads WHERE actor_id=%s "
            "AND specification->'material'->>'goal_id'=%s AND source_id IS NULL "
            "AND state='stored' AND specification->'material'->'purposes' ? 'planning' "
            "AND (retain_until IS NULL OR retain_until>now()) "
            "AND ((specification->'material'->>'use_until')::timestamptz IS NULL "
            "OR (specification->'material'->>'use_until')::timestamptz>now()) ORDER BY id",
            (actor.id, str(goal_id)),
        ).fetchall()
        texts = self.connection.execute(
            "SELECT d.id,v.revision,v.content_digest,v.title,v.format,"
            "v.processing_state AS state FROM knowledge.documents d "
            "JOIN knowledge.document_versions v ON v.document_id=d.id "
            "AND v.revision=d.latest_revision "
            "JOIN knowledge.document_permissions p ON p.document_id=d.id "
            "AND p.document_revision=v.revision WHERE d.actor_id=%s AND d.goal_id=%s "
            "AND v.upload_id IS NULL AND v.content_state='retained' AND p.status='allowed' "
            "AND p.purposes ? 'planning' AND (p.use_until IS NULL OR p.use_until>now()) "
            "AND (p.retain_until IS NULL OR p.retain_until>now()) ORDER BY d.id",
            (actor.id, goal_id),
        ).fetchall()
        return [
            {**item, "id": str(item["id"]), "input_key": f"upload:{item['content_digest']}"}
            for item in uploads
        ] + [
            {**item, "id": str(item["id"]),
             "input_key": f"text:{item['id']}:{item['revision']}:{item['content_digest']}"}
            for item in texts
        ]

    def supersede_planning_consumers(self, actor, goal_id, consumer_refs):
        rows = self.connection.execute(
            "UPDATE knowledge.material_demands SET status='cancelled' "
            "WHERE actor_id=%s AND goal_id=%s AND consumer_ref=ANY(%s::text[]) "
            "AND specification->>'purpose'='planning' AND status='open' RETURNING id",
            (actor.id, goal_id, consumer_refs),
        ).fetchall()
        ids = [row["id"] for row in rows]
        if not ids:
            return
        self.connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET status='cancelled',"
            "error_code='planning_scope_superseded',lease_token=NULL,lease_until=NULL "
            "WHERE demand_id=ANY(%s::uuid[]) AND status NOT IN ('ready','blocked_unknown')", (ids,),
        )
        self.connection.execute(
            "UPDATE knowledge.material_searches SET status='cancelled',"
            "error_code='planning_scope_superseded',lease_token=NULL,lease_until=NULL "
            "WHERE actor_id=%s AND request->>'demand_id'=ANY(%s::text[]) "
            "AND status NOT IN ('ready','blocked_unknown')",
            (actor.id, [str(value) for value in ids]),
        )

    def ensure_consumer_demand(self, actor, consumer_ref, data):
        request = self.demand_request(data)
        self.connection.execute(
            "INSERT INTO knowledge.material_demands"
            "(id,actor_id,goal_id,specification,consumer_ref) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (actor_id,consumer_ref) DO NOTHING",
            (uuid4(), actor.id, data.goal_id, Jsonb(request), consumer_ref),
        )
        demand = self.consumer_demand(actor, consumer_ref)
        actual = demand.model_dump(
            mode="json", include=set(type(data).model_fields),
            exclude=(
                ({"scope_mode"} if data.scope_mode == "facets" else set())
                | ({"goal_text"} if data.goal_text is None else set())
                | ({"preparation"} if data.preparation == "complete" else set())
            ),
        )
        if actual != request:
            raise BusinessError("stale_version", "Consumer material demand changed.")
        return demand

    def job(self, actor, job_id):
        row = self.connection.execute(
            "SELECT " + JOB_COLUMNS + ",request_identity "
            "FROM knowledge.material_jobs WHERE id=%s AND actor_id=%s",
            (job_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material job not found.")
        steps = self.connection.execute(
            "SELECT revision,state,phase,reason_code,issues,created_at "
            "FROM knowledge.material_job_steps WHERE job_id=%s ORDER BY revision",
            (job_id,),
        ).fetchall()
        identity = row.pop("request_identity")
        if row["upload_id"]:
            material = self.connection.execute(
                "SELECT specification->'material' AS material FROM knowledge.material_uploads "
                "WHERE id=%s AND actor_id=%s",
                (row["upload_id"], actor.id),
            ).fetchone()["material"]
        else:
            material = identity["material"]
        return MaterialJob(**row, title=material["title"], format=material["format"], steps=steps)

    def jobs(self, actor, demand_id, *, before=None, limit=20):
        self.demand(actor, demand_id)
        rows = self.connection.execute(
            "SELECT id FROM knowledge.material_jobs WHERE actor_id=%s AND demand_id=%s "
            "AND (%s::uuid IS NULL OR (created_at,id)<"
            "(SELECT created_at,id FROM knowledge.material_jobs WHERE id=%s AND actor_id=%s)) "
            "ORDER BY created_at DESC,id DESC LIMIT %s",
            (actor.id, demand_id, before, before, actor.id, limit),
        ).fetchall()
        return [self.job(actor, row["id"]) for row in rows]

    def pending_goal_uploads(self, actor, goal_id):
        rows = self.connection.execute(
            "SELECT j.id FROM knowledge.material_jobs j "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "JOIN knowledge.material_uploads u ON u.id=j.upload_id "
            "WHERE j.actor_id=%s AND d.goal_id=%s AND u.source_id IS NULL "
            "AND j.state NOT IN ('ready','cancelled') AND d.status<>'cancelled' "
            "ORDER BY j.created_at,j.id",
            (actor.id, goal_id),
        ).fetchall()
        return [self.job(actor, row["id"]) for row in rows]

    @staticmethod
    def request_identity(data):
        if hasattr(data, "upload_id"):
            return data.model_dump(mode="json")
        return {
            "expected_demand_revision": data.expected_demand_revision,
            "material": {
                **data.material.model_dump(mode="json", exclude={"text"}),
                "text_digest": digest(data.material.text),
            },
        }

    def replay_job(self, actor, demand_id, key, data):
        request = {"demand_id": str(demand_id), **self.request_identity(data)}
        previous = self.connection.execute(
            "SELECT * FROM knowledge.material_job_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if previous["request"] != request:
                raise BusinessError("idempotency_conflict", "Material preparation key changed.")
            return self.job(actor, previous["job_id"])
        return None

    def submit_text(self, actor, session_digest, demand_id, key, data):
        previous = self.replay_job(actor, demand_id, key, data)
        if previous:
            return previous
        demand = self.demand(actor, demand_id)
        self.validate_input(demand, data.material, data.expected_demand_revision)
        return self._save_job(actor, session_digest, demand_id, key, data, data.material.text)

    def prepare_revision(self, actor, session_digest, demand_id, document_id, revision):
        from leornian.modules.knowledge.materials import Materials

        demand = self.demand(actor, demand_id)
        version = Materials(self.connection).require_use(
            actor, document_id, revision, demand.purpose, goal_id=demand.goal_id
        )
        Materials(self.connection).require_use(actor, document_id, revision, "indexing")
        if demand.status == "cancelled":
            raise BusinessError("source_not_current", "Material demand was cancelled.")
        identity = {
            "expected_demand_revision": demand.revision,
            "material": {
                "document_id": str(document_id), "document_revision": revision,
                "title": version.title, "format": version.format,
            },
        }
        fingerprint = digest(json.dumps(identity, sort_keys=True, separators=(",", ":")))
        job_id = uuid4()
        row = self.connection.execute(
            "INSERT INTO knowledge.material_jobs"
            "(id,root_id,demand_id,actor_id,session_digest,demand_revision,request_identity,"
            "request_digest,retain_until,document_id,document_revision,state,phase,issues) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'waiting_dependency','indexing',%s) "
            "ON CONFLICT (actor_id,demand_id,request_digest) DO NOTHING RETURNING id",
            (
                job_id, job_id, demand.id, actor.id, session_digest, demand.revision,
                Jsonb(identity), fingerprint, version.permission.retain_until,
                document_id, revision,
                Jsonb([] if version.processing_state == "parsed" else ["material_quality_pending"]),
            ),
        ).fetchone()
        if row:
            self.record_step(row["id"])
        else:
            job_id = self.connection.execute(
                "SELECT id FROM knowledge.material_jobs WHERE actor_id=%s AND demand_id=%s "
                "AND request_digest=%s", (actor.id, demand.id, fingerprint),
            ).fetchone()["id"]
        return self.job(actor, job_id)

    @staticmethod
    def validate_input(demand, material, expected_revision):
        if demand.revision != expected_revision:
            raise BusinessError("stale_version", "Material demand changed.")
        if demand.status != "open":
            raise BusinessError("precondition_failed", "Material demand is not open.")
        if material.goal_id != demand.goal_id:
            raise BusinessError("not_found", "Material belongs to another goal.")
        if demand.purpose not in material.purposes:
            raise BusinessError("precondition_failed", "Demand purpose was not authorized.")
        now = datetime.now(UTC)
        if any(
            d is not None and d <= now
            for d in (
                material.use_until,
                material.retain_until,
            )
        ):
            raise BusinessError("source_not_current", "A real material deadline has passed.")

    def submit_file(self, actor, session_digest, demand_id, key, data, upload):
        return self._save_job(actor, session_digest, demand_id, key, data, upload=upload)

    def _save_job(self, actor, session_digest, demand_id, key, data, text=None, upload=None):
        identity = self.request_identity(data)
        request_digest = digest(json.dumps(identity, sort_keys=True, separators=(",", ":")))
        existing = self.connection.execute(
            "SELECT id FROM knowledge.material_jobs "
            "WHERE actor_id=%s AND demand_id=%s AND request_digest=%s",
            (actor.id, demand_id, request_digest),
        ).fetchone()
        job_id = existing["id"] if existing else uuid4()
        if not existing:
            self.connection.execute(
                "INSERT INTO knowledge.material_jobs"
                "(id,root_id,demand_id,actor_id,session_digest,demand_revision,"
                "request_identity,request_digest,input_text,retain_until,upload_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    job_id,
                    job_id,
                    demand_id,
                    actor.id,
                    session_digest,
                    data.expected_demand_revision,
                    Jsonb(identity),
                    request_digest,
                    text,
                    upload["retain_until"] if upload else data.material.retain_until,
                    upload["id"] if upload else None,
                ),
            )
            self.record_step(job_id)
        self.connection.execute(
            "INSERT INTO knowledge.material_job_commands"
            "(actor_id,command_key,request,job_id) VALUES (%s,%s,%s,%s)",
            (actor.id, key, Jsonb({"demand_id": str(demand_id), **identity}), job_id),
        )
        return self.job(actor, job_id)

    def record_step(self, job_id):
        self.connection.execute(
            "INSERT INTO knowledge.material_job_steps"
            "(job_id,revision,state,phase,reason_code,issues) "
            "SELECT id,revision,state,phase,reason_code,issues "
            "FROM knowledge.material_jobs WHERE id=%s",
            (job_id,),
        )

    def defer_background(self, job_id):
        self.connection.execute(
            "UPDATE knowledge.material_jobs SET background_deferred=true,"
            "reason_code=CASE WHEN state='blocked_unknown' THEN reason_code "
            "ELSE 'source_depth_not_selected' END "
            "WHERE id=%s AND state NOT IN ('ready','cancelled') "
            "AND (lease_until IS NULL OR lease_until<=now())", (job_id,),
        )

    def transition(
        self,
        job_id,
        state,
        phase,
        *,
        reason=None,
        issues=(),
        document=None,
        lease=None,
        discard_input=False,
    ):
        row = self.connection.execute(
            "UPDATE knowledge.material_jobs SET state=%s,phase=%s,reason_code=%s,issues=%s,"
            "revision=revision+1,updated_at=now(),next_run_at=now(),lease_token=%s,"
            "published_at=CASE WHEN %s AND %s='waiting_dependency' "
            "THEN NULL ELSE published_at END,"
            "lease_until=CASE WHEN %s::uuid IS NULL THEN NULL ELSE now()+interval '2 minutes' END,"
            "input_text=CASE WHEN %s THEN NULL ELSE input_text END,"
            "document_id=COALESCE(%s,document_id),document_revision=COALESCE(%s,document_revision) "
            "WHERE id=%s RETURNING id",
            (
                state,
                phase,
                reason,
                Jsonb(list(issues)),
                lease,
                reason in {"indexing_pending", "ocr_pages_pending"},
                state,
                lease,
                discard_input,
                document.document_id if document else None,
                document.revision if document else None,
                job_id,
            ),
        ).fetchone()
        if row:
            self.record_step(job_id)
            if state == "cancelled":
                self.connection.execute(
                    "UPDATE knowledge.source_observations SET status='cancelled',error_code=%s,"
                    "lease_token=NULL,lease_until=NULL WHERE job_id=%s "
                    "AND status NOT IN ('changed','unchanged','noise_only','blocked_unknown')",
                    (reason, job_id),
                )
            if state == "ready":
                self.connection.execute(
                    "UPDATE knowledge.material_discovery_jobs d SET status='queued',"
                    "error_code=NULL,next_run_at=now(),published_at=NULL "
                    "FROM knowledge.material_demands requested,"
                    "knowledge.material_demands supplied,knowledge.material_jobs j "
                    "WHERE j.id=%s AND supplied.id=j.demand_id "
                    "AND requested.id=d.demand_id AND d.actor_id=j.actor_id "
                    "AND requested.goal_id=supplied.goal_id "
                    "AND d.status IN ('waiting_dependency','blocked_unknown')",
                    (job_id,),
                )
                self.connection.execute(
                    "UPDATE knowledge.source_observations SET next_run_at=now(),published_at=NULL "
                    "WHERE job_id=%s AND status IN "
                    "('processing','waiting_dependency','blocked_unknown')", (job_id,),
                )

    def cancel(self, actor, job_id):
        job = self.job(actor, job_id)
        rows = self.connection.execute(
            "SELECT id,phase FROM knowledge.material_jobs "
            "WHERE root_id=(SELECT root_id FROM knowledge.material_jobs WHERE id=%s) "
            "AND actor_id=%s AND state<>'cancelled' ORDER BY id FOR UPDATE",
            (job_id, actor.id),
        ).fetchall()
        for row in rows:
            self.transition(
                row["id"],
                "cancelled",
                row["phase"],
                reason="learner_cancelled",
                discard_input=True,
            )
        self.connection.execute(
            "UPDATE knowledge.material_demands SET status='open' WHERE id=%s AND status='ready' "
            "AND NOT EXISTS(SELECT 1 FROM knowledge.material_jobs "
            "WHERE demand_id=%s AND state='ready')", (job.demand_id, job.demand_id),
        )
        return self.job(actor, job_id)

    def stop_preparation_jobs(self, actor, job_ids):
        rows = self.connection.execute(
            "SELECT id,phase FROM knowledge.material_jobs WHERE actor_id=%s AND id=ANY(%s) "
            "AND state NOT IN ('ready','cancelled') ORDER BY id FOR UPDATE",
            (actor.id, job_ids),
        ).fetchall()
        for row in rows:
            self.transition(
                row["id"], "cancelled", row["phase"], reason="learner_cancelled",
            )
        return [row["id"] for row in rows]
