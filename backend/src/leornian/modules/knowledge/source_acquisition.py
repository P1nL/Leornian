import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.goal_coverage_contracts import SOURCE_DEFECTS, MaterialGoalFinding
from leornian.modules.knowledge.retrieval_contracts import MaterialCoverage
from leornian.modules.knowledge.source_contracts import (
    MaterialDiscovery,
    MaterialSource,
    MaterialSourceInput,
    MaterialSourceObservation,
)
from leornian.modules.knowledge.source_network import approved_source_url
from leornian.shared_kernel.errors import BusinessError

DEFAULT_SOURCE_DEPTH = 1
MAX_GAP_SOURCE_DEPTH = 2


def identity(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def ordinary_node_reading(demand):
    return (demand.purpose == "teaching" and demand.scope_mode == "teaching_goal"
            and demand.consumer_ref.startswith("node-material:") and demand.status != "cancelled")


def teaching_reading_refs(coverage, selection_id, state, bound_refs=()):
    excluded = {tuple(version) for version in state.get("excluded_versions", [])}
    findings = [MaterialGoalFinding(**item) for item in state.get("excluded_findings", [])
                if item["issue"] in SOURCE_DEFECTS]
    refs = bound_refs
    if not refs and coverage and coverage.basis == "semantic-goal-evidence.v1":
        refs = [ref.model_copy(update={"selection_id": selection_id})
                for facet in coverage.required if facet.status in {"supported", "partial"}
                for ref in facet.evidence]
    return list({ref.model_dump_json(): ref for ref in refs
                 if (str(ref.document_id), ref.document_revision) not in excluded
                 and not any(finding.affects(ref) for finding in findings)}.values())


class MaterialSources:
    def __init__(self, connection):
        self.connection = connection

    def observation_index_mode(self, observation_id):
        exact_text = self.connection.execute(
            "SELECT 1 FROM knowledge.material_source_check_commands c "
            "JOIN knowledge.material_discovery_jobs j "
            "ON c.command_key LIKE 'discovery:'||j.id::text||':shallow-v1:%%' "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "WHERE c.observation_id=%s AND d.status<>'cancelled' "
            "AND j.demand_revision=d.revision "
            "AND (d.specification->>'purpose'='planning' "
            "OR starts_with(d.consumer_ref,'node-material:')) LIMIT 1",
            (observation_id,),
        ).fetchone()
        return "lexical" if exact_text else "hybrid"

    def job_selected(self, job_id):
        origins = self.connection.execute(
            "SELECT r.depth,o.request_identity,o.command_key,EXISTS("
            "SELECT 1 FROM knowledge.material_source_check_commands c "
            "JOIN knowledge.material_discovery_jobs d "
            "ON c.command_key LIKE 'discovery:'||d.id::text||':shallow-v1:%%' "
            "JOIN knowledge.material_demands m ON m.id=d.demand_id "
            "WHERE c.observation_id=o.id AND m.status<>'cancelled' "
            "AND d.demand_revision=m.revision AND d.status IN "
            "('queued','processing','waiting_config','waiting_dependency') "
            "AND coalesce(d.error_code,'') NOT IN "
            "('material_discovery_exhausted','node_material_review_failed')) "
            "AS requested FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
            "JOIN knowledge.material_jobs j ON j.id=%s "
            "WHERE o.job_id=j.id OR o.upload_id=j.upload_id", (job_id,),
        ).fetchall()
        return not origins or any(
            (
                item["depth"] <= DEFAULT_SOURCE_DEPTH
                or (item["depth"] <= MAX_GAP_SOURCE_DEPTH
                    and item["request_identity"].get("missing_topics"))
            )
            and (not item["command_key"].startswith("discovery:") or item["requested"])
            for item in origins
        )

    def row(self, actor, source_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_source_registrations WHERE id=%s AND actor_id=%s"
            + (" FOR UPDATE" if lock else " FOR SHARE"),
            (source_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Approved material source not found.")
        return row

    @staticmethod
    def view(row):
        return MaterialSource(
            **row["specification"],
            **{
                k: row[k]
                for k in ("id", "revision", "admission", "basis", "catalog_id", "created_at")
            },
        )

    def require(self, actor, source_id, *, purpose=None, revision=None, lock=False):
        row = self.row(actor, source_id, lock=lock)
        data = MaterialSourceInput(**row["specification"])
        if revision is not None and row["revision"] != revision:
            raise BusinessError("stale_version", "Approved source revision changed.")
        if (
            row["admission"] != "allowed"
            or any(
                end is not None and end <= datetime.now(UTC)
                for end in (data.use_until, data.retain_until)
            )
            or (purpose and purpose not in data.purposes)
        ):
            raise BusinessError("source_not_current", "Source use is not currently authorized.")
        return row, data

    def register(self, actor, session_digest, key, data, *, catalog_id=None, basis=None):
        request = data.model_dump(mode="json")
        identity_data = {"source": request, "catalog_id": catalog_id}
        if basis is not None:
            if basis not in {"learning_catalog", "public_discovery"}:
                raise ValueError("Unsupported automatic source authorization basis")
            identity_data["basis"] = basis
        fingerprint = identity(identity_data)
        command = self.connection.execute(
            "SELECT * FROM knowledge.material_source_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if command:
            if command["request_digest"] != fingerprint:
                raise BusinessError("idempotency_conflict", "Approved source key changed.")
            return self.view(self.row(actor, command["source_id"]))
        if any(
            end is not None and end <= datetime.now(UTC)
            for end in (data.use_until, data.retain_until)
        ):
            raise BusinessError("source_not_current", "A source deadline has already passed.")
        existing = self.connection.execute(
            "SELECT id FROM knowledge.material_source_registrations WHERE actor_id=%s "
            "AND goal_id=%s AND request_digest=%s",
            (actor.id, data.goal_id, fingerprint),
        ).fetchone()
        source_id = existing["id"] if existing else uuid4()
        if not existing:
            self.connection.execute(
                "INSERT INTO knowledge.material_source_registrations"
                "(id,actor_id,goal_id,session_digest,basis,catalog_id,specification,"
                "request_digest) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    source_id,
                    actor.id,
                    data.goal_id,
                    session_digest,
                    basis or ("official_catalog" if catalog_id else "explicit_approval"),
                    catalog_id,
                    Jsonb(request),
                    fingerprint,
                ),
            )
            self.add_resource(source_id, data.entry_url)
            self.connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET status='queued',error_code=NULL,"
                "next_run_at=now() WHERE actor_id=%s AND status='waiting_dependency' "
                "AND coalesce(error_code,'') NOT IN "
                "('material_discovery_exhausted','node_material_review_failed') "
                "AND demand_id IN (SELECT id FROM knowledge.material_demands WHERE goal_id=%s "
                "AND status<>'cancelled')",
                (actor.id, data.goal_id),
            )
        self.connection.execute(
            "INSERT INTO knowledge.material_source_commands"
            "(actor_id,command_key,request_digest,source_id) VALUES (%s,%s,%s,%s)",
            (actor.id, key, fingerprint, source_id),
        )
        return self.view(self.row(actor, source_id))

    def list(self, actor, goal_id):
        rows = self.connection.execute(
            "SELECT * FROM knowledge.material_source_registrations "
            "WHERE actor_id=%s AND goal_id=%s ORDER BY created_at,id",
            (actor.id, goal_id),
        ).fetchall()
        return [self.view(row) for row in rows]

    def curriculum_catalog(self, actor, goal_id, document_ids=None):
        """Expose observed outlines within current grants for the selected evidence."""
        rows = self.connection.execute(
            "SELECT DISTINCT s.id FROM knowledge.material_source_registrations s "
            "JOIN knowledge.source_observations o ON o.source_id=s.id "
            "WHERE s.actor_id=%s AND s.goal_id=%s "
            "AND (%s::uuid[] IS NULL OR o.document_id=ANY(%s::uuid[])) "
            "ORDER BY s.id",
            (actor.id, goal_id,
             list(document_ids) if document_ids is not None else None,
             list(document_ids) if document_ids is not None else None),
        ).fetchall()
        result = []
        for row in rows:
            try:
                _registration, data = self.require(actor, row["id"], purpose="planning")
            except BusinessError as error:
                if error.code == "source_not_current":
                    continue
                raise
            resources = self.connection.execute(
                "SELECT r.url,r.link_label,o.document_id,o.request_identity "
                "FROM knowledge.material_source_resources r "
                "LEFT JOIN LATERAL (SELECT document_id,request_identity "
                "FROM knowledge.source_observations WHERE resource_id=r.id "
                "AND status IN ('changed','unchanged','noise_only') "
                "ORDER BY created_at DESC,id DESC LIMIT 1) o ON true "
                "WHERE r.source_id=%s ORDER BY r.depth,r.link_order,r.url",
                (row["id"],),
            ).fetchall()
            chapters = {}
            for resource in resources:
                if resource["link_label"]:
                    chapters[resource["url"]] = {
                        "title": resource["link_label"], "source_url": resource["url"],
                    }
                structure = (resource["request_identity"] or {}).get("source_structure", {})
                if structure.get("role") == "directory":
                    for chapter in structure.get("chapter_candidates", []):
                        try:
                            url = approved_source_url(chapter["url"], data.allowed_prefixes)
                        except BusinessError:
                            continue
                        if chapter["title"]:
                            chapters[url] = {"title": chapter["title"], "source_url": url}
            result.append({
                "source_id": str(row["id"]), "title": data.title,
                "source_url": data.entry_url,
                "evidence_document_ids": sorted({
                    str(resource["document_id"]) for resource in resources
                    if resource["document_id"] and (
                        document_ids is None or resource["document_id"] in document_ids
                    )
                }),
                "chapters": list(chapters.values()),
            })
        return result

    def document_origins(self, actor, document_ids):
        return self.connection.execute(
            "SELECT r.*,j.document_id AS origin_document_id,s.catalog_id,"
            "j.document_revision AS origin_revision,v.format,v.parser_version,"
            "s.specification->>'entry_url' AS entry_url,"
            "s.specification->>'title' AS source_title,"
            "s.specification->'topics' AS source_topics,"
            "s.specification->>'framework' AS source_framework "
            "FROM knowledge.material_jobs j JOIN knowledge.source_observations o "
            "ON o.job_id=j.id "
            "JOIN knowledge.document_versions v ON v.document_id=j.document_id "
            "AND v.revision=j.document_revision "
            "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
            "JOIN knowledge.material_source_registrations s ON s.id=r.source_id "
            "WHERE s.actor_id=%s AND j.document_id=ANY(%s::uuid[])",
            (actor.id, list(document_ids)),
        ).fetchall()

    def add_resource(self, source_id, url, depth=0, *, label="", order=0):
        self.connection.execute(
            "INSERT INTO knowledge.material_source_resources"
            "(id,source_id,url,depth,link_label,link_order) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(source_id,url) DO UPDATE SET "
            "depth=LEAST(knowledge.material_source_resources.depth,EXCLUDED.depth),"
            "link_label=CASE WHEN EXCLUDED.link_label<>'' THEN EXCLUDED.link_label "
            "ELSE knowledge.material_source_resources.link_label END,"
            "link_order=CASE WHEN EXCLUDED.depth<=knowledge.material_source_resources.depth "
            "THEN EXCLUDED.link_order ELSE knowledge.material_source_resources.link_order END",
            (uuid4(), source_id, url, depth, label, order),
        )
        return self.connection.execute(
            "SELECT * FROM knowledge.material_source_resources WHERE source_id=%s AND url=%s",
            (source_id, url),
        ).fetchone()

    def schedule(
        self, actor, source_id, session_digest, key, *,
        resource_id=None, revision=None, missing_topics=None,
    ):
        row, data = self.require(actor, source_id, revision=revision, lock=True)
        resource = self.connection.execute(
            "SELECT * FROM knowledge.material_source_resources WHERE source_id=%s AND "
            + ("id=%s" if resource_id else "url=%s")
            + " FOR UPDATE",
            (source_id, resource_id or data.entry_url),
        ).fetchone()
        if not resource:
            raise BusinessError("not_found", "Source resource not found.")
        request = {"resource_id": str(resource["id"]), "revision": row["revision"]}
        if resource.get("acquisition_provider", "direct") != "direct":
            request["acquisition_provider"] = resource["acquisition_provider"]
        if missing_topics:
            request["missing_topics"] = missing_topics
        fingerprint = identity(request)
        command = self.connection.execute(
            "SELECT * FROM knowledge.material_source_check_commands "
            "WHERE source_id=%s AND command_key=%s",
            (source_id, key),
        ).fetchone()
        if command:
            if command["request_digest"] != fingerprint:
                raise BusinessError("idempotency_conflict", "Source check key changed.")
            return self.observation(actor, command["observation_id"])
        active = self.connection.execute(
            "SELECT o.id FROM knowledge.source_observations o "
            "LEFT JOIN knowledge.material_jobs j ON j.id=o.job_id WHERE o.resource_id=%s "
            "AND (o.status IN ('queued','fetching','processing') OR j.state='blocked_unknown' "
            "OR (j.background_deferred AND j.state NOT IN ('ready','cancelled'))) "
            "ORDER BY (o.status IN ('queued','fetching','processing')) DESC,"
            "o.created_at DESC LIMIT 1",
            (resource["id"],),
        ).fetchone()
        observation_id = active["id"] if active else uuid4()
        if not active:
            approved_source_url(resource["url"], data.allowed_prefixes)
            self.connection.execute(
                "INSERT INTO knowledge.source_observations"
                "(id,source_id,source_revision,resource_id,actor_id,session_digest,"
                "command_key,request_identity) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    observation_id,
                    source_id,
                    row["revision"],
                    resource["id"],
                    actor.id,
                    session_digest,
                    key,
                    Jsonb(
                        {
                            **request,
                            "url": resource["url"],
                            "etag": resource["etag"] if resource["document_id"] else None,
                            "last_modified": (
                                resource["last_modified"] if resource["document_id"] else None
                            ),
                        }
                    ),
                ),
            )
        self.connection.execute(
            "INSERT INTO knowledge.material_source_check_commands"
            "(source_id,command_key,request_digest,observation_id) VALUES (%s,%s,%s,%s)",
            (source_id, key, fingerprint, observation_id),
        )
        self.connection.execute(
            "UPDATE knowledge.material_jobs SET background_deferred=false,"
            "reason_code=CASE WHEN reason_code='source_depth_not_selected' "
            "THEN NULL ELSE reason_code END WHERE id IN ("
            "SELECT job_id FROM knowledge.source_observations WHERE id=%s) "
            "AND state NOT IN ('ready','cancelled','blocked_unknown')",
            (observation_id,),
        )
        return self.observation(actor, observation_id)

    def observation_row(self, actor, observation_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM knowledge.source_observations WHERE id=%s AND actor_id=%s"
            + (" FOR UPDATE" if lock else ""),
            (observation_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Source observation not found.")
        return row

    def observation(self, actor, observation_id):
        row = self.observation_row(actor, observation_id)
        return MaterialSourceObservation(
            **{k: row[k] for k in MaterialSourceObservation.model_fields}
        )

    def latest_observation(self, actor, resource_id):
        row = self.connection.execute(
            "SELECT id FROM knowledge.source_observations WHERE actor_id=%s AND resource_id=%s "
            "AND status<>'cancelled' ORDER BY created_at DESC,id DESC LIMIT 1",
            (actor.id, resource_id),
        ).fetchone()
        return self.observation(actor, row["id"]) if row else None

    def ensure_discovery(self, actor, session_digest, demand):
        self.connection.execute(
            "INSERT INTO knowledge.material_discovery_jobs"
            "(id,actor_id,demand_id,demand_revision,session_digest,missing_facets) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(demand_id,demand_revision) DO NOTHING",
            (
                uuid4(),
                actor.id,
                demand.id,
                demand.revision,
                session_digest,
                Jsonb(
                    [demand.goal_text]
                    if demand.scope_mode == "teaching_goal"
                    else demand.required_facets
                ),
            ),
        )
        return self.discovery(actor, demand.id, demand.revision)

    def discovery(self, actor, demand_id, revision=None):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_discovery_jobs WHERE actor_id=%s AND demand_id=%s "
            "AND (%s::integer IS NULL OR demand_revision=%s) ORDER BY demand_revision DESC LIMIT 1",
            (actor.id, demand_id, revision, revision),
        ).fetchone()
        if not row:
            return None
        return MaterialDiscovery(**{k: row[k] for k in MaterialDiscovery.model_fields})

    def node_teaching_refs(self, actor, demand, bound_refs=()):
        row = self.connection.execute(
            "SELECT v.id,v.coverage,d.acquisition_state FROM knowledge.material_discovery_jobs d "
            "LEFT JOIN knowledge.material_searches s ON s.id=d.search_id AND s.status='ready' "
            "LEFT JOIN knowledge.material_selections v ON v.id=s.selection_id "
            "AND v.actor_id=d.actor_id "
            "AND v.demand_id=d.demand_id AND v.goal_id=%s AND v.purpose='teaching' "
            "WHERE d.actor_id=%s AND d.demand_id=%s AND d.demand_revision=%s "
            "AND (d.status='ready' OR "
            "(d.status='waiting_dependency' AND d.error_code='material_discovery_exhausted'))",
            (demand.goal_id, actor.id, demand.id, demand.revision),
        ).fetchone()
        if not row:
            return []
        return teaching_reading_refs(
            MaterialCoverage(**row["coverage"]) if row["coverage"] else None,
            row["id"], row["acquisition_state"], bound_refs,
        )

    def stop_preparation(self, actor, demand):
        """Stop this consumer's unfinished work and preserve reusable material contents."""
        from leornian.modules.knowledge.intake import MaterialIntake

        rows = self.connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET status='cancelled',"
            "error_code='learner_cancelled',lease_token=NULL,lease_until=NULL "
            "WHERE actor_id=%s AND demand_id=%s AND status NOT IN ('ready','cancelled') "
            "RETURNING id", (actor.id, demand.id),
        ).fetchall()
        self.connection.execute(
            "UPDATE knowledge.material_demands SET status='cancelled' "
            "WHERE id=%s AND actor_id=%s AND status='open'", (demand.id, actor.id),
        )
        discovery_ids = [row["id"] for row in rows]
        patterns = [f"discovery:{value}:shallow-v1:%" for value in discovery_ids]
        observations = self.connection.execute(
            "SELECT DISTINCT o.id,o.job_id FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_check_commands c ON c.observation_id=o.id "
            "WHERE o.actor_id=%s AND c.command_key LIKE ANY(%s) AND NOT EXISTS("
            "SELECT 1 FROM knowledge.material_source_check_commands other "
            "JOIN knowledge.material_discovery_jobs d "
            "ON other.command_key LIKE 'discovery:'||d.id::text||':shallow-v1:%%' "
            "WHERE other.observation_id=o.id AND d.status NOT IN ('ready','cancelled')) "
            "AND NOT EXISTS(SELECT 1 FROM knowledge.material_source_check_commands other "
            "WHERE other.observation_id=o.id AND other.command_key NOT LIKE 'discovery:%%')",
            (actor.id, patterns),
        ).fetchall()
        observation_ids = [row["id"] for row in observations]
        self.connection.execute(
            "UPDATE knowledge.source_observations SET status='cancelled',"
            "error_code='learner_cancelled',lease_token=NULL,lease_until=NULL "
            "WHERE id=ANY(%s) AND status IN "
            "('queued','fetching','processing','waiting_config','waiting_dependency',"
            "'blocked_unknown')", (observation_ids,),
        )
        job_ids = {
            row["job_id"] for row in observations
            if row["job_id"] and not self.job_selected(row["job_id"])
        }
        stopped_jobs = MaterialIntake(self.connection).stop_preparation_jobs(actor, list(job_ids))
        searches = self.connection.execute(
            "UPDATE knowledge.material_searches SET status='cancelled',"
            "error_code='learner_cancelled',lease_token=NULL,lease_until=NULL "
            "WHERE actor_id=%s AND request->>'demand_id'=%s AND status<>'ready' RETURNING id",
            (actor.id, str(demand.id)),
        ).fetchall()
        search_ids = [row["id"] for row in searches]
        parts = self.connection.execute(
            "UPDATE knowledge.material_goal_coverage_parts SET state='cancelled' "
            "WHERE search_id=ANY(%s) AND state NOT IN ('reviewed','purged') RETURNING run_id",
            (search_ids,),
        ).fetchall()
        web = self.connection.execute(
            "UPDATE knowledge.material_web_requests SET retired=true "
            "WHERE actor_id=%s AND NOT applied AND (discovery_id=ANY(%s) "
            "OR observation_id=ANY(%s)) RETURNING id",
            (actor.id, discovery_ids, observation_ids),
        ).fetchall()
        operations = self.connection.execute(
            "SELECT id FROM knowledge.material_operations WHERE job_id=ANY(%s) "
            "UNION ALL SELECT id FROM knowledge.material_search_operations "
            "WHERE search_id=ANY(%s)", (stopped_jobs, search_ids),
        ).fetchall()
        return {
            "operations": [row["id"] for row in [*web, *operations]],
            "runs": [row["run_id"] for row in parts if row["run_id"]],
        }

    def inherit_acquisition_budget(
        self, actor, previous_demand, next_demand, *, chain_started_at,
    ):
        rows = self.connection.execute(
            "SELECT d.id,d.demand_id,d.acquisition_state,d.created_at,m.goal_id "
            "FROM knowledge.material_discovery_jobs d "
            "JOIN knowledge.material_demands m ON m.id=d.demand_id "
            "WHERE d.actor_id=%s AND d.demand_id=ANY(%s) ORDER BY d.created_at,d.id",
            (actor.id, [previous_demand, next_demand]),
        ).fetchall()
        previous = next((row for row in rows if row["demand_id"] == previous_demand), None)
        current = next((row for row in rows if row["demand_id"] == next_demand), None)
        if not previous or not current or previous["goal_id"] != current["goal_id"]:
            return
        if any(row["created_at"] < chain_started_at for row in (previous, current)):
            return
        if current["acquisition_state"].get("budget_root") or previous["id"] == current["id"]:
            return
        root = previous["acquisition_state"].get("budget_root", str(previous["id"]))
        self.connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state="
            "acquisition_state||%s WHERE id=%s",
            (Jsonb({"budget_root": root}), current["id"]),
        )

    def attach_search(self, actor, discovery_id, search_id):
        row = self.connection.execute(
            "SELECT d.* FROM knowledge.material_discovery_jobs d "
            "JOIN knowledge.material_searches s ON s.id=%s AND s.actor_id=d.actor_id "
            "WHERE d.id=%s AND d.actor_id=%s AND s.request->>'demand_id'=d.demand_id::text "
            "AND (s.request->>'expected_demand_revision')::integer=d.demand_revision "
            "FOR UPDATE OF d",
            (search_id, discovery_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Search does not belong to this material demand.")
        if row["search_id"] not in {None, search_id}:
            raise BusinessError("precondition_failed", "This material scope already has a search.")
        self.connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET search_id=%s WHERE id=%s",
            (search_id, discovery_id),
        )
        return self.discovery(actor, row["demand_id"], row["demand_revision"])
