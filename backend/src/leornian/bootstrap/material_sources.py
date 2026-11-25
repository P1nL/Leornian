import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.agent_runtime.repository import Runs
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.file_contracts import (
    FileMaterialInput,
    MaterialFileJobInput,
    MaterialUploadInput,
)
from leornian.modules.knowledge.file_parser import (
    HTML_MAIN_PARSER_VERSION,
    extract_file,
)
from leornian.modules.knowledge.file_store import OriginalFileStore
from leornian.modules.knowledge.files import MaterialFiles
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.source_acquisition import (
    DEFAULT_SOURCE_DEPTH,
    MAX_GAP_SOURCE_DEPTH,
    MaterialSources,
)
from leornian.modules.knowledge.source_extraction import (
    SourceLinks,
    content_format,
    teaching_identity,
)
from leornian.modules.knowledge.source_network import ApprovedSourceClient, SourceResponse
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.shared_kernel.errors import BusinessError

TERMINAL = {"unchanged", "noise_only", "changed", "cancelled", "blocked_unknown"}


class MaterialSourceWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings
        self.store = OriginalFileStore(settings.material_storage_dir)

    @staticmethod
    def source_structure_in(connection, row, data, resource, content, parsed):
        links = SourceLinks(resource["url"], data.allowed_prefixes, include_navigation=True)
        links.feed(content.decode("utf-8"))
        links.close()
        if data.discover_links and resource["depth"] < MAX_GAP_SOURCE_DEPTH:
            sources = MaterialSources(connection)
            for order, url in enumerate(links.links):
                sources.add_resource(
                    row["source_id"], url, resource["depth"] + 1,
                    label=links.link_labels.get(url, ""), order=order,
                )
        structure = {
            "version": "source-structure.v2", "parser_version": HTML_MAIN_PARSER_VERSION,
            "raw_digest": row["raw_digest"],
            "role": "directory" if links.is_directory(parsed) else "body",
            "chapter_candidates": [
                {"url": url, "title": links.link_labels.get(url, "")[:160]}
                for url in links.candidates[:80]
            ],
        }
        connection.execute(
            "UPDATE knowledge.source_observations SET request_identity="
            "request_identity||%s WHERE id=%s",
            (Jsonb({"source_structure": structure}), row["id"]),
        )
        return structure

    def directory_versions_in(self, connection, actor, origins):
        directories, seen = set(), {}
        for origin in origins:
            version = (origin["origin_document_id"], origin["origin_revision"])
            key = (origin["id"], *version)
            if key not in seen:
                row = connection.execute(
                    "SELECT * FROM knowledge.source_observations WHERE resource_id=%s "
                    "AND document_id=%s AND document_revision=%s AND original_id IS NOT NULL "
                    "ORDER BY created_at DESC,id DESC LIMIT 1", key,
                ).fetchone()
                structure = (row["request_identity"].get("source_structure") or {}) if row else {}
                if row and origin["format"] == "html" and (
                    structure.get("version") != "source-structure.v2"
                    or structure.get("parser_version") != HTML_MAIN_PARSER_VERSION
                    or structure.get("raw_digest") != row["raw_digest"]
                ):
                    _registration, data = MaterialSources(connection).require(
                        actor, row["source_id"],
                    )
                    content = self.store.read(actor.id, row["original_id"])
                    self.store.check(content, row["raw_digest"], row["raw_byte_size"])
                    structure = self.source_structure_in(
                        connection, row, data, origin, content, extract_file(content, "html-main"),
                    )
                seen[key] = structure.get("role") == "directory"
            if seen[key]:
                directories.add(version)
        return directories

    def register(self, token, key, data):
        with self.database.transaction() as connection:
            auth = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = auth.authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, data.goal_id)
            return MaterialSources(connection).register(actor, auth.digest(token), key, data)

    def registration_receipt(self, token, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = connection.execute(
                "SELECT source_id FROM knowledge.material_source_commands "
                "WHERE actor_id=%s AND command_key=%s",
                (actor.id, key),
            ).fetchone()
            if not row:
                raise BusinessError("not_found", "Approved source command not found.")
            sources = MaterialSources(connection)
            return sources.view(sources.row(actor, row["source_id"]))

    def check_receipt(self, token, source_id, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            sources = MaterialSources(connection)
            sources.row(actor, source_id)
            row = connection.execute(
                "SELECT observation_id FROM knowledge.material_source_check_commands "
                "WHERE source_id=%s AND command_key=%s",
                (source_id, key),
            ).fetchone()
            if not row:
                raise BusinessError("not_found", "Source read command not found.")
            return sources.observation(actor, row["observation_id"])

    def revocation_receipt(self, token, source_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            sources = MaterialSources(connection)
            row = sources.row(actor, source_id)
            if row["admission"] != "revoked":
                raise BusinessError("not_found", "Source revocation has not occurred.")
            return sources.view(row)

    def list(self, token, goal_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
            return MaterialSources(connection).list(actor, goal_id)

    def get(self, token, source_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            sources = MaterialSources(connection)
            return sources.view(sources.row(actor, source_id))

    def check(self, token, source_id, key, data, *, resource_id=None):
        with self.database.transaction() as connection:
            auth = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = auth.authenticate(token)
            return MaterialSources(connection).schedule(
                actor,
                source_id,
                auth.digest(token),
                key,
                resource_id=resource_id,
                revision=data.expected_revision,
            )

    def observation(self, token, observation_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return MaterialSources(connection).observation(actor, observation_id)

    def original(self, token, observation_id, purpose):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            sources = MaterialSources(connection)
            row = sources.observation_row(actor, observation_id, lock=True)
            resource = connection.execute(
                "SELECT depth FROM knowledge.material_source_resources WHERE id=%s",
                (row["resource_id"],),
            ).fetchone()
            unselected = resource["depth"] > MAX_GAP_SOURCE_DEPTH or (
                resource["depth"] > DEFAULT_SOURCE_DEPTH
                and not row["request_identity"].get("missing_topics")
            )
            if unselected and row["dispatched_at"] is None:
                connection.execute(
                    "UPDATE knowledge.source_observations SET status='cancelled',"
                    "error_code='source_depth_not_selected',lease_token=NULL,lease_until=NULL "
                    "WHERE id=%s", (observation_id,),
                )
                return None
            sources.require(actor, row["source_id"], purpose=purpose)
            if row["content_purged"] or not row["original_id"]:
                raise BusinessError("source_not_current", "Observed original is unavailable.")
            document = (
                {"document_id": row["document_id"], "revision": row["document_revision"]}
                if row["document_id"]
                else connection.execute(
                    "SELECT document_id,revision FROM knowledge.document_versions "
                    "WHERE upload_id=%s ORDER BY revision DESC LIMIT 1",
                    (row["upload_id"],),
                ).fetchone()
            )
            if document:
                Materials(connection).require_use(
                    actor, document["document_id"], document["revision"], purpose
                )
            content = self.store.read(actor.id, row["original_id"])
            self.store.check(content, row["raw_digest"], row["raw_byte_size"])
            return content

    def revoke(self, token, source_id, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            sources = MaterialSources(connection)
            row = sources.row(actor, source_id, lock=True)
            if row["revision"] != data.expected_revision:
                raise BusinessError("stale_version", "Approved source changed.")
            if row["admission"] != "revoked":
                connection.execute(
                    "UPDATE knowledge.material_source_registrations "
                    "SET admission='revoked',revision=revision+1 WHERE id=%s",
                    (source_id,),
                )
                versions = connection.execute(
                    "SELECT DISTINCT v.document_id,v.revision FROM knowledge.document_versions v "
                    "JOIN knowledge.source_observations o ON o.upload_id=v.upload_id "
                    "WHERE o.source_id=%s ORDER BY v.document_id,v.revision",
                    (source_id,),
                ).fetchall()
                materials = Materials(connection)
                for version in versions:
                    current = materials.version(actor, version["document_id"], version["revision"])
                    revoked = materials.revoke(
                        actor, current.document_id, current.revision, current.permission.revision
                    )
                    if revoked.permission.revision != current.permission.revision:
                        Events(connection).append(
                            actor.id,
                            "knowledge.material_permission_changed",
                            current.document_id,
                            EventPayload(
                                document_id=current.document_id,
                                document_revision=current.revision,
                                goal_id=current.goal_id,
                            ),
                        )
                jobs = connection.execute(
                    "SELECT j.id FROM knowledge.material_jobs j "
                    "JOIN knowledge.material_uploads u ON u.id=j.upload_id "
                    "WHERE u.source_id=%s AND j.state NOT IN ('ready','cancelled') ORDER BY j.id",
                    (source_id,),
                ).fetchall()
                for job in jobs:
                    MaterialIntake(connection).cancel(actor, job["id"])
                operations = connection.execute(
                    "SELECT o.id FROM knowledge.material_operations o "
                    "JOIN knowledge.material_jobs j ON j.id=o.job_id "
                    "JOIN knowledge.material_uploads u ON u.id=j.upload_id WHERE u.source_id=%s",
                    (source_id,),
                ).fetchall()
                Runs(connection).cancel_operations([operation["id"] for operation in operations])
                connection.execute(
                    "UPDATE knowledge.source_observations SET status='cancelled',"
                    "error_code='source_not_current',lease_token=NULL,lease_until=NULL "
                    "WHERE source_id=%s AND status NOT IN ('unchanged','noise_only','changed')",
                    (source_id,),
                )
            return sources.view(sources.row(actor, source_id))

    @staticmethod
    def current(connection, actor, observation_id, lease, *, before_fetch=False):
        sources = MaterialSources(connection)
        seed = sources.observation_row(actor, observation_id)
        Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
            seed["session_digest"]
        )
        _source, data = sources.require(actor, seed["source_id"], revision=seed["source_revision"])
        row = sources.observation_row(actor, observation_id, lock=True)
        if row["status"] not in {"fetching", "processing"} or (
            row["lease_token"] != lease or row["lease_until"] <= datetime.now(UTC)
        ):
            raise BusinessError("lease_lost", "Source observation is no longer current.")
        resource = connection.execute(
            "SELECT * FROM knowledge.material_source_resources WHERE id=%s FOR UPDATE",
            (row["resource_id"],),
        ).fetchone()
        if row["command_key"].startswith(("discovery:", "preserve-original:")) and (
            row["recorded_at"] is None
        ):
            consumers = connection.execute(
                "SELECT d.status,d.error_code,m.status AS demand_status,"
                "(d.demand_revision=m.revision) AS current_revision,CASE WHEN "
                "d.acquisition_state->'node_example_lookup'->'attempted' ? %s THEN "
                "(d.acquisition_state->'node_example_lookup'->>'deadline_at')::timestamptz END "
                "AS example_deadline "
                "FROM knowledge.material_source_check_commands c "
                "JOIN knowledge.source_observations selected ON selected.id=c.observation_id "
                "JOIN knowledge.material_discovery_jobs d "
                "ON c.command_key LIKE 'discovery:'||d.id::text||':shallow-v1:%%' "
                "JOIN knowledge.material_demands m ON m.id=d.demand_id "
                "WHERE selected.resource_id=%s AND (selected.id=%s "
                "OR 'preserve-original:'||selected.id::text=%s)",
                (resource["url"], resource["id"], row["id"], row["command_key"]),
            ).fetchall()
            active = [item for item in consumers
                if item["status"] not in {"cancelled", "ready", "blocked_unknown"}
                and item["error_code"] not in {
                    "material_discovery_exhausted", "node_material_review_failed",
                }
                and item["demand_status"] != "cancelled" and item["current_revision"]
            ]
            if consumers and not active:
                raise BusinessError(
                    "source_task_cancelled", "The requesting task is no longer active.",
                )
            if before_fetch and active and all(item["example_deadline"] for item in active):
                row["example_deadline"] = max(item["example_deadline"] for item in active)
                if row["example_deadline"] <= datetime.now(UTC):
                    raise BusinessError("material_example_deadline", "示例补读时间已用完。")
        return row, data, resource

    def claim(self, observation_id):
        with self.database.transaction() as connection:
            seed = connection.execute(
                "SELECT actor_id,session_digest FROM knowledge.source_observations WHERE id=%s",
                (observation_id,),
            ).fetchone()
            if not seed:
                return None
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                seed["session_digest"]
            )
            sources = MaterialSources(connection)
            row = sources.observation_row(actor, observation_id, lock=True)
            recorded_storage_wait = (
                row["status"] == "waiting_dependency"
                and row["error_code"] == "material_storage_unavailable"
                and row["recorded_at"] is not None
                and row["original_id"] is not None
                and not row["content_purged"]
            )
            if row["status"] in TERMINAL or (
                row["status"] == "waiting_dependency" and not recorded_storage_wait
            ):
                return None
            if row["lease_until"] and row["lease_until"] > datetime.now(UTC):
                return None
            if row["status"] == "fetching" and row["dispatched_at"] and not row["recorded_at"]:
                public_read = (
                    row["request_identity"].get("acquisition_provider", "direct") == "direct"
                )
                connection.execute(
                    "UPDATE knowledge.source_observations SET status=%s,error_code=%s,"
                    "lease_token=NULL,lease_until=NULL WHERE id=%s",
                    (
                        "waiting_dependency" if public_read else "blocked_unknown",
                        "source_network_unavailable" if public_read else "source_read_unknown",
                        observation_id,
                    ),
                )
                if public_read:
                    self.defer_network_read(connection, observation_id)
                return None
            sources.require(actor, row["source_id"], revision=row["source_revision"])
            lease = uuid4()
            connection.execute(
                "UPDATE knowledge.source_observations SET status=%s,lease_token=%s,"
                "lease_until=now()+interval '2 minutes',error_code=NULL WHERE id=%s",
                ("processing" if row["recorded_at"] else "fetching", lease, observation_id),
            )
            return actor, lease

    def record(self, actor, observation_id, response):
        content_digest = hashlib.sha256(response.content).hexdigest() if response.content else None
        with self.database.transaction() as connection:
            sources = MaterialSources(connection)
            seed = sources.observation_row(actor, observation_id)
            source = sources.row(actor, seed["source_id"])
            row = sources.observation_row(actor, observation_id, lock=True)
            deadline = source["specification"].get("retain_until")
            expired = deadline and datetime.fromisoformat(
                deadline.replace("Z", "+00:00")
            ) <= datetime.now(UTC)
            original_id = None
            if response.content and not (row["content_purged"] or expired):
                original_id = observation_id
                self.store.put(
                    actor.id, original_id, response.content, content_digest, len(response.content)
                )
            connection.execute(
                "UPDATE knowledge.source_observations SET response_status=%s,response_headers=%s,"
                "response_url=%s,redirects=%s,raw_digest=%s,raw_byte_size=%s,original_id=%s,"
                "recorded_at=now(),content_purged=content_purged OR %s,"
                "status=CASE WHEN status='fetching' THEN 'processing' ELSE status END WHERE id=%s",
                (
                    response.status_code,
                    Jsonb(
                        {
                            "content_type": response.content_type,
                            "etag": response.etag,
                            "last_modified": response.last_modified,
                            "extraction_provider": row["request_identity"].get(
                                "acquisition_provider", "direct",
                            ),
                        }
                    ),
                    response.url,
                    Jsonb(response.redirects),
                    content_digest,
                    len(response.content) or None,
                    original_id,
                    bool(expired),
                    observation_id,
                ),
            )
            connection.execute(
                "UPDATE knowledge.material_source_resources SET read_failures=0 WHERE id=%s",
                (row["resource_id"],),
            )

    def execute(self, observation_id, transport=None):
        lease = None
        try:
            with self.database.transaction() as connection:
                seed = connection.execute(
                    "SELECT status,published_at,session_digest FROM knowledge.source_observations "
                    "WHERE id=%s",
                    (observation_id,),
                ).fetchone()
                continuation = seed and seed["status"] == "changed" and not seed["published_at"]
                if continuation:
                    actor = Identity(
                        PgIdentityStore(connection, serialize_actor=True)
                    ).authenticate_digest(seed["session_digest"])
            if continuation:
                self.compare_current_bindings(actor, observation_id)
                return
            claimed = self.claim(observation_id)
            if not claimed:
                return
            actor, lease = claimed
            cached_response = None
            with self.database.transaction() as connection:
                row, data, resource = self.current(
                    connection, actor, observation_id, lease, before_fetch=True,
                )
                should_fetch = row["recorded_at"] is None
                if should_fetch:
                    if row["request_identity"].get("missing_topics") and (
                        row["command_key"].startswith("discovery:")
                    ):
                        previous = connection.execute(
                            "SELECT * FROM knowledge.source_observations "
                            "WHERE resource_id=%s AND source_revision=%s AND id<>%s "
                            "AND response_status=200 AND original_id IS NOT NULL "
                            "AND NOT content_purged AND document_id IS NOT NULL "
                            "ORDER BY recorded_at DESC LIMIT 1",
                            (resource["id"], row["source_revision"], observation_id),
                        ).fetchone()
                        if previous:
                            Materials(connection).require_use(
                                actor, previous["document_id"], previous["document_revision"],
                                "indexing", goal_id=data.goal_id,
                            )
                            original = self.store.read(actor.id, previous["original_id"])
                            self.store.check(
                                original, previous["raw_digest"], previous["raw_byte_size"],
                            )
                            cached_response = SourceResponse(
                                previous["response_url"], 200, original,
                                previous["response_headers"].get("content_type"),
                                previous["response_headers"].get("etag"),
                                previous["response_headers"].get("last_modified"),
                                tuple(previous["redirects"]),
                            )
                            connection.execute(
                                "UPDATE knowledge.source_observations SET request_identity="
                                "request_identity||%s WHERE id=%s",
                                (Jsonb({"reused_observation_id": str(previous["id"])}),
                                 observation_id),
                            )
                    if cached_response is None:
                        connection.execute(
                            "UPDATE knowledge.source_observations SET dispatched_at=now() "
                            "WHERE id=%s",
                            (observation_id,),
                        )
                    connection.execute(
                        "UPDATE knowledge.material_source_resources SET "
                        "next_check_at=now()+make_interval(secs=>%s) WHERE id=%s",
                        (
                            getattr(self.settings, "material_source_check_seconds", 86400),
                            resource["id"],
                        ),
                    )
            if should_fetch:
                request = row["request_identity"]
                if cached_response is not None:
                    response = cached_response
                elif request.get("acquisition_provider") == "tavily":
                    from leornian.bootstrap.material_web import MaterialWebWorkflow

                    try:
                        response = MaterialWebWorkflow(self.database, self.settings).extract(
                            actor, row, data, resource,
                            lambda connection, owner: self.current(
                                connection, owner, observation_id, lease,
                            ),
                            transport,
                        )
                    except BusinessError as error:
                        if error.code not in {
                            "tavily_original_required", "tavily_extraction_failed",
                            "tavily_invalid_response", "tavily_provider_rejected",
                        }:
                            raise
                        with self.database.transaction() as connection:
                            self.current(connection, actor, observation_id, lease)
                            connection.execute(
                                "UPDATE knowledge.material_source_resources SET "
                                "acquisition_provider='direct' WHERE id=%s", (resource["id"],),
                            )
                            connection.execute(
                                "UPDATE knowledge.source_observations SET status='cancelled',"
                                "error_code=%s,lease_token=NULL,lease_until=NULL WHERE id=%s",
                                (error.code, observation_id),
                            )
                            MaterialSources(connection).schedule(
                                actor, row["source_id"], row["session_digest"],
                                f"preserve-original:{observation_id}", resource_id=resource["id"],
                                missing_topics=row["request_identity"].get("missing_topics"),
                            )
                        return
                else:
                    response = ApprovedSourceClient(
                        timeout=getattr(self.settings, "material_source_timeout_seconds", 30),
                        max_bytes=2_000_000 if request.get("missing_topics") else 20_000_000,
                        max_redirects=getattr(self.settings, "material_source_max_redirects", 4),
                        transport=transport,
                    ).get(
                        request["url"],
                        data.allowed_prefixes,
                        etag=request["etag"],
                        last_modified=request["last_modified"],
                        deadline=row.get("example_deadline"),
                    )
                self.record(actor, observation_id, response)
            with self.database.transaction() as connection:
                row, data, resource = self.current(connection, actor, observation_id, lease)
                if row["response_status"] == 304:
                    if not resource["document_id"]:
                        raise BusinessError(
                            "source_response_invalid", "No original exists for 304."
                        )
                    Materials(connection).require_use(
                        actor, resource["document_id"], resource["document_revision"], "indexing"
                    )
                    self.finish(connection, row, resource, "unchanged")
                    return
                content = self.store.read(actor.id, row["original_id"])
                self.store.check(content, row["raw_digest"], row["raw_byte_size"])
                format = content_format(
                    content, row["response_headers"]["content_type"], data.format
                )
                seen_pages = []
                if format == "pdf" and row["raw_digest"] == resource["raw_digest"]:
                    prior_scopes = connection.execute(
                        "SELECT specification->'selected_pages' AS pages "
                        "FROM knowledge.material_uploads WHERE source_id=%s AND content_digest=%s "
                        "AND specification ? 'selected_pages'",
                        (row["source_id"], row["raw_digest"]),
                    ).fetchall()
                    seen_pages = [
                        page for scope in prior_scopes for page in scope["pages"]
                    ]
                needs_job = row["upload_id"] is None
            if needs_job:
                selected_pages = None
                if format == "pdf" and row["request_identity"].get("missing_topics"):
                    from leornian.modules.knowledge.source_candidates import selected_pdf_pages

                    selected_pages = selected_pdf_pages(
                        extract_file(content, "pdf-outline"),
                        row["request_identity"]["missing_topics"],
                        exclude_pages=seen_pages,
                    )
                parsed = (
                    extract_file(content, "html-main" if format == "html" else format)
                    if format in {"html", "markdown", "text"}
                    else {"blocks": [], "issues": ["source_parse_pending"]}
                )
                with self.database.transaction() as connection:
                    row, data, resource = self.current(connection, actor, observation_id, lease)
                    teaching_digest = teaching_identity(parsed)
                    if format == "html":
                        structure = self.source_structure_in(
                            connection, row, data, resource, content, parsed,
                        )
                        if data.discover_links and structure["role"] == "directory":
                            row["teaching_digest"] = teaching_digest
                            connection.execute(
                                "UPDATE knowledge.source_observations SET teaching_digest=%s,"
                                "published_at=now() WHERE id=%s", (teaching_digest, observation_id),
                            )
                            self.finish(connection, row, resource, "changed")
                            return

                    current_version = Materials(connection).version(
                        actor, resource["document_id"], resource["document_revision"],
                    ) if resource["document_id"] else None
                    parser_current = (
                        format != "html" or current_version is None
                        or current_version.parser_version == HTML_MAIN_PARSER_VERSION
                    )
                    raw_unchanged = (
                        resource["document_id"] is not None
                        and row["raw_digest"] == resource["raw_digest"]
                        and selected_pages is None
                    )
                    if parser_current and (raw_unchanged or (
                        resource["document_id"] is not None and not parsed["issues"]
                        and teaching_digest == resource["teaching_digest"]
                    )):
                        Materials(connection).require_use(
                            actor,
                            resource["document_id"],
                            resource["document_revision"],
                            "indexing",
                        )
                        row["teaching_digest"] = (
                            resource["teaching_digest"] if raw_unchanged else teaching_digest
                        )
                        connection.execute(
                            "UPDATE knowledge.source_observations SET teaching_digest=%s "
                            "WHERE id=%s",
                            (row["teaching_digest"], observation_id),
                        )
                        self.finish(
                            connection,
                            row,
                            resource,
                            "unchanged"
                            if row["raw_digest"] == resource["raw_digest"]
                            else "noise_only",
                        )
                        return
                    earlier = connection.execute(
                        "SELECT upload_id,job_id,teaching_digest "
                        "FROM knowledge.source_observations "
                        "WHERE resource_id=%s AND raw_digest=%s AND job_id IS NOT NULL "
                        "AND EXISTS(SELECT 1 FROM knowledge.material_jobs j "
                        "WHERE j.id=job_id AND j.state<>'cancelled') "
                        "AND (%s OR EXISTS(SELECT 1 FROM knowledge.material_jobs j "
                        "JOIN knowledge.document_versions v ON v.document_id=j.document_id "
                        "AND v.revision=j.document_revision WHERE j.id=job_id "
                        "AND v.parser_version=%s)) "
                        "AND (%s::jsonb IS NULL OR EXISTS("
                        "SELECT 1 FROM knowledge.material_uploads u WHERE u.id=upload_id "
                        "AND u.specification->'selected_pages'=%s::jsonb)) "
                        "AND id<>%s ORDER BY recorded_at DESC,id DESC LIMIT 1",
                        (resource["id"], row["raw_digest"], format != "html",
                         HTML_MAIN_PARSER_VERSION,
                         Jsonb(selected_pages) if selected_pages is not None else None,
                         Jsonb(selected_pages), observation_id),
                    ).fetchone()
                    if earlier:
                        connection.execute(
                            "UPDATE knowledge.source_observations SET upload_id=%s,job_id=%s,"
                            "teaching_digest=%s WHERE id=%s",
                            (
                                earlier["upload_id"],
                                earlier["job_id"],
                                earlier["teaching_digest"],
                                observation_id,
                            ),
                        )
                        self.release(
                            connection, observation_id, "processing", "known_source_input_reused"
                        )
                        return
                    intake = MaterialIntake(connection)
                    demand = intake.ensure_consumer_demand(
                        actor,
                        f"source-import:{resource['id']}:{observation_id}",
                        MaterialDemandInput(
                            goal_id=data.goal_id,
                            purpose="indexing",
                            language=data.language,
                            language_version=data.language_version,
                            framework=data.framework,
                            framework_version=data.framework_version,
                            scope_mode="whole_source",
                            index_mode=MaterialSources(connection).observation_index_mode(
                                observation_id,
                            ),
                            required_facets=[],
                        ),
                    )
                    material = FileMaterialInput(
                        goal_id=data.goal_id,
                        document_id=resource["document_id"],
                        expected_revision=resource["document_revision"] or 0,
                        title=resource["link_label"][:160] or data.title,
                        source_url=resource["url"],
                        format=format,
                        authorized_use=True,
                        purposes=data.purposes,
                        use_until=data.use_until,
                        retain_until=data.retain_until,
                    )
                    intake.validate_input(demand, material, demand.revision)
                    files = MaterialFiles(connection)
                    upload = files.reserve(
                        actor,
                        demand.id,
                        "source-observation:" + str(observation_id),
                        MaterialUploadInput(
                            expected_demand_revision=demand.revision,
                            material=material,
                            content_digest=row["raw_digest"],
                            byte_size=row["raw_byte_size"],
                        ),
                        extraction_policy=(
                            "task-text.v1" if row["request_identity"].get("missing_topics")
                            else "main-content.v1"
                        ) if format == "html" else None,
                        source_id=row["source_id"],
                        selected_pages=selected_pages,
                    )
                    self.store.put(actor.id, upload.id, content, row["raw_digest"], len(content))
                    connection.execute(
                        "UPDATE knowledge.material_uploads SET state='stored',stored_at=now() "
                        "WHERE id=%s",
                        (upload.id,),
                    )
                    upload_row = files.row(actor, upload.id)
                    job = intake.submit_file(
                        actor,
                        row["session_digest"],
                        demand.id,
                        "source-observation:" + str(observation_id),
                        MaterialFileJobInput(
                            expected_demand_revision=demand.revision, upload_id=upload.id
                        ),
                        upload_row,
                    )
                    connection.execute(
                        "UPDATE knowledge.source_observations SET upload_id=%s,job_id=%s,"
                        "teaching_digest=%s WHERE id=%s",
                        (upload.id, job.id, teaching_digest, observation_id),
                    )
                    self.release(
                        connection, observation_id, "processing", "source_preparation_pending"
                    )
                    return
            with self.database.transaction() as connection:
                row, data, resource = self.current(connection, actor, observation_id, lease)
                job = MaterialIntake(connection).job(actor, row["job_id"])
                if not job.document_id:
                    self.child_wait(connection, row, job)
                    return
                version = Materials(connection).require_use(
                    actor, job.document_id, job.document_revision, "indexing", goal_id=data.goal_id
                )
                indexed = connection.execute(
                    "SELECT id FROM knowledge.material_index_builds WHERE job_id=%s "
                    "AND document_revision=%s AND state='indexed'",
                    (job.id, version.revision),
                ).fetchone()
                partial_text = Materials.permits_partial_text(
                    connection.execute(
                        "SELECT * FROM knowledge.material_jobs WHERE id=%s", (job.id,),
                    ).fetchone(), version,
                )
                if not indexed or (version.processing_state != "parsed" and not partial_text):
                    self.child_wait(connection, row, job)
                    return
                blocks, after = [], -1
                while True:
                    page = Materials(connection).blocks(
                        actor,
                        version.document_id,
                        version.revision,
                        "indexing",
                        after=after,
                        limit=100,
                    )
                    blocks.extend(b.model_dump() for b in page.blocks)
                    if page.next_after is None:
                        break
                    after = page.next_after
                row["teaching_digest"] = teaching_identity({
                    "blocks": blocks,
                    "unresolved_regions": [
                        region.model_dump(mode="json") for region in version.unresolved_regions
                    ],
                })
                row["document_id"], row["document_revision"] = version.document_id, version.revision
                connection.execute(
                    "UPDATE knowledge.source_observations SET document_id=%s,document_revision=%s,"
                    "teaching_digest=%s WHERE id=%s",
                    (version.document_id, version.revision, row["teaching_digest"], observation_id),
                )
                self.finish(connection, row, resource, "changed")
            self.compare_current_bindings(actor, observation_id)
        except BusinessError as error:
            with self.database.transaction() as connection:
                status = (
                    "blocked_unknown"
                    if error.code in {"source_read_unknown", "external_result_unknown"}
                    else "waiting_config"
                    if error.code in {
                        "model_unavailable", "tavily_not_configured",
                        "tavily_configuration_changed",
                    }
                    else "cancelled"
                    if error.code
                    in {
                        "stale_version",
                        "source_not_current",
                        "unauthenticated",
                        "session_expired",
                        "source_task_cancelled",
                        "material_example_deadline",
                    }
                    else "waiting_dependency"
                )
                connection.execute(
                    "UPDATE knowledge.source_observations SET status=%s,error_code=%s,"
                    "lease_token=NULL,lease_until=NULL,next_run_at=now()+interval '30 seconds' "
                    "WHERE id=%s AND status NOT IN "
                    "('unchanged','noise_only','changed','cancelled') "
                    "AND (%s::uuid IS NULL OR lease_token=%s)",
                    (status, error.code, observation_id, lease, lease),
                )
                http_status = getattr(error, "http_status", None)
                if http_status is not None:
                    connection.execute(
                        "UPDATE knowledge.source_observations SET response_status=%s WHERE id=%s",
                        (http_status, observation_id),
                    )
                if error.code in {
                    "source_read_unknown", "source_network_unavailable",
                } or http_status in {408, 429, 502, 503, 504}:
                    self.defer_network_read(connection, observation_id)

    @staticmethod
    def defer_network_read(connection, observation_id):
        # Periodic checks use a new GET observation; automatic discovery skips failed URLs.
        connection.execute(
            "UPDATE knowledge.material_source_resources r SET "
            "read_failures=read_failures+1,next_check_at=now()+"
            "make_interval(secs=>LEAST(3600,30*power(2,LEAST(read_failures,7)))) "
            "FROM knowledge.source_observations o "
            "WHERE o.id=%s AND o.resource_id=r.id", (observation_id,),
        )

    @staticmethod
    def release(connection, observation_id, status, error_code):
        connection.execute(
            "UPDATE knowledge.source_observations SET status=%s,error_code=%s,"
            "lease_token=NULL,lease_until=NULL,next_run_at=now()+interval '2 seconds' WHERE id=%s",
            (status, error_code, observation_id),
        )

    def child_wait(self, connection, row, job):
        state = (
            job.state
            if job.state in {"waiting_config", "blocked_unknown", "cancelled"}
            else "waiting_dependency"
            if job.issues and job.reason_code != "coverage_gap"
            else "processing"
        )
        self.release(connection, row["id"], state, job.reason_code or "source_preparation_pending")

    @staticmethod
    def finish(connection, row, resource, status):
        headers = row["response_headers"]
        connection.execute(
            "UPDATE knowledge.material_source_resources SET etag=%s,last_modified=%s,"
            "raw_digest=COALESCE(%s,raw_digest),teaching_digest=COALESCE(%s,teaching_digest),"
            "document_id=COALESCE(%s,document_id),document_revision=COALESCE(%s,document_revision),"
            "last_observation_id=%s WHERE id=%s",
            (
                headers["etag"] or resource["etag"],
                headers["last_modified"] or resource["last_modified"],
                row["raw_digest"],
                row["teaching_digest"],
                row["document_id"],
                row["document_revision"],
                row["id"],
                resource["id"],
            ),
        )
        connection.execute(
            "UPDATE knowledge.source_observations SET status=%s,error_code=NULL,"
            "document_id=COALESCE(document_id,%s),document_revision=COALESCE(document_revision,%s),"
            "lease_token=NULL,lease_until=NULL WHERE id=%s",
            (status, resource["document_id"], resource["document_revision"], row["id"]),
        )
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs d SET status='queued',error_code=NULL,"
            "next_run_at=now(),published_at=NULL FROM knowledge.material_demands requested,"
            "knowledge.material_source_registrations s WHERE s.id=%s "
            "AND requested.id=d.demand_id AND requested.goal_id=s.goal_id "
            "AND requested.status<>'cancelled' "
            "AND d.actor_id=s.actor_id AND d.status IN ('queued','waiting_dependency') "
            "AND coalesce(d.error_code,'') NOT IN "
            "('material_discovery_exhausted','node_material_review_failed')",
            (row["source_id"],),
        )

    def compare_current_bindings(self, actor, observation_id):
        from leornian.bootstrap.material_changes import MaterialChangeWorkflow
        from leornian.modules.knowledge.change_contracts import MaterialChangeInput
        from leornian.modules.learning.materials import MaterialBindings

        with self.database.transaction() as connection:
            sources = MaterialSources(connection)
            row = sources.observation_row(actor, observation_id)
            Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                row["session_digest"]
            )
            _source, data = sources.require(actor, row["source_id"])
            bindings = MaterialBindings(connection).current_for_document(
                actor, data.goal_id, row["document_id"]
            )
            check_ids = []
            for binding in bindings:
                versions = {
                    ref.document_revision
                    for ref in binding.refs
                    if ref.document_id == row["document_id"]
                }
                if len(versions) != 1 or next(iter(versions)) >= row["document_revision"]:
                    continue
                try:
                    with connection.transaction():
                        report = MaterialChangeWorkflow.compare_in(
                            connection,
                            actor,
                            row["session_digest"],
                            f"source-observation:{observation_id}:{binding.id}:{binding.revision}",
                            MaterialChangeInput(
                                binding_id=binding.id,
                                expected_binding_revision=binding.revision,
                                document_id=row["document_id"],
                                candidate_revision=row["document_revision"],
                            ),
                        )
                        check_ids.append(str(report.id))
                except BusinessError as error:
                    if error.code not in {"stale_version", "source_not_current", "not_found"}:
                        raise
            connection.execute(
                "UPDATE knowledge.source_observations SET check_ids=%s,published_at=now() "
                "WHERE id=%s",
                (Jsonb(check_ids), observation_id),
            )

    def purge_retained(self, connection):
        rows = connection.execute(
            "UPDATE knowledge.source_observations o SET content_purged=true,"
            "status=CASE WHEN status IN ('unchanged','noise_only','changed') THEN status "
            "ELSE 'cancelled' END,error_code='material_retention_expired',lease_token=NULL,"
            "lease_until=NULL,original_id=NULL FROM knowledge.material_source_registrations s "
            "WHERE o.source_id=s.id AND NOT o.content_purged AND "
            "(s.specification->>'retain_until')::timestamptz<now() "
            "RETURNING o.actor_id,o.id",
        ).fetchall()
        for row in rows:
            self.store.delete(row["actor_id"], row["id"])
        connection.execute(
            "UPDATE knowledge.material_demands d SET status='cancelled',"
            "specification=jsonb_set(jsonb_set(d.specification,'{required_facets}','[]'),"
            "'{optional_facets}','[]') FROM knowledge.material_source_resources r "
            "JOIN knowledge.material_source_registrations s ON s.id=r.source_id "
            "WHERE d.consumer_ref LIKE 'source-import:'||r.id::text||':%%' "
            "AND (s.specification->>'retain_until')::timestamptz<now()",
        )


def scan_material_sources_once(database, settings, *, limit=20):
    """Register due read identities; the worker performs HTTP outside this transaction."""
    ids = []
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT r.id,r.source_id,r.next_check_at,s.session_digest,"
            "(SELECT prior.request_identity->'missing_topics' "
            "FROM knowledge.source_observations prior WHERE prior.resource_id=r.id "
            "AND prior.request_identity ? 'missing_topics' ORDER BY prior.created_at DESC LIMIT 1) "
            "AS missing_topics FROM "
            "knowledge.material_source_resources r JOIN knowledge.material_source_registrations s "
            "ON s.id=r.source_id WHERE s.admission='allowed' AND r.next_check_at<=now() "
            "AND (s.basis NOT IN ('learning_catalog','public_discovery') "
            "OR r.document_id IS NOT NULL OR EXISTS("
            "SELECT 1 FROM knowledge.material_source_check_commands selected "
            "JOIN knowledge.material_discovery_jobs d "
            "ON selected.command_key LIKE 'discovery:'||d.id::text||':shallow-v1:%%' "
            "WHERE selected.source_id=s.id AND d.status IN "
            "('queued','processing','waiting_config','waiting_dependency') "
            "AND coalesce(d.error_code,'') NOT IN "
            "('material_discovery_exhausted','node_material_review_failed'))) "
            "AND (r.document_id IS NOT NULL OR r.depth=0 OR EXISTS("
            "SELECT 1 FROM knowledge.material_source_check_commands chosen "
            "JOIN knowledge.source_observations selected ON selected.id=chosen.observation_id "
            "WHERE selected.resource_id=r.id "
            "AND chosen.command_key LIKE 'discovery:%%:shallow-v1:%%')) "
            "AND (r.depth<=%s OR (r.depth=%s AND EXISTS("
            "SELECT 1 FROM knowledge.material_source_check_commands c "
            "JOIN knowledge.source_observations o ON o.id=c.observation_id "
            "WHERE o.resource_id=r.id AND o.request_identity ? 'missing_topics' "
            "AND c.command_key LIKE 'discovery:%%'))) "
            "AND NOT EXISTS (SELECT 1 FROM knowledge.source_observations a "
            "WHERE a.source_id=s.id AND a.status IN ('queued','fetching','processing')) "
            "AND NOT EXISTS(SELECT 1 FROM knowledge.source_observations unresolved "
            "JOIN knowledge.material_jobs j ON j.id=unresolved.job_id "
            "WHERE unresolved.resource_id=r.id AND j.state='blocked_unknown') "
            "AND NOT EXISTS(SELECT 1 FROM knowledge.source_observations failed "
            "JOIN knowledge.material_source_check_commands selected ON selected.observation_id="
            "failed.id WHERE failed.resource_id=r.id AND r.document_id IS NULL "
            "AND selected.command_key LIKE 'discovery:%%' "
            "AND failed.error_code IN "
            "('source_network_unavailable','source_http_unavailable','source_read_unknown') "
            "AND COALESCE(failed.request_identity->>'acquisition_provider','direct')='direct' "
            "AND failed.recorded_at IS NULL AND failed.job_id IS NULL) "
            "ORDER BY r.next_check_at,r.id LIMIT %s FOR UPDATE OF r SKIP LOCKED",
            (DEFAULT_SOURCE_DEPTH, MAX_GAP_SOURCE_DEPTH, limit),
        ).fetchall()
        seen_sources = set()
        for row in rows:
            if row["source_id"] in seen_sources:
                continue
            try:
                with connection.transaction():
                    actor = Identity(
                        PgIdentityStore(connection, serialize_actor=True)
                    ).authenticate_digest(row["session_digest"])
                    observation = MaterialSources(connection).schedule(
                        actor,
                        row["source_id"],
                        row["session_digest"],
                        "scheduled:" + str(row["id"]) + ":" + row["next_check_at"].isoformat(),
                        resource_id=row["id"],
                        missing_topics=row["missing_topics"],
                    )
                    ids.append(observation.id)
                    seen_sources.add(row["source_id"])
            except BusinessError:
                continue
    with database.transaction() as connection:
        pending = connection.execute(
            "SELECT o.id FROM knowledge.source_observations o WHERE (status IN "
            "('queued','fetching','processing','waiting_config') "
            "OR (status='changed' AND published_at IS NULL) "
            "OR (status='waiting_dependency' AND error_code='material_storage_unavailable' "
            "AND recorded_at IS NOT NULL AND original_id IS NOT NULL AND NOT content_purged) "
            "OR (status='waiting_dependency' AND EXISTS("
            "SELECT 1 FROM knowledge.material_jobs j WHERE j.id=o.job_id AND j.state='ready'))) "
            "AND next_run_at<=now() "
            "AND (lease_until IS NULL OR lease_until<=now()) ORDER BY next_run_at,id LIMIT %s "
            "FOR UPDATE SKIP LOCKED",
            (limit,),
        ).fetchall()
        for row in pending:
            connection.execute(
                "UPDATE knowledge.source_observations SET next_run_at=now()+interval '30 seconds' "
                "WHERE id=%s", (row["id"],),
            )
        ids.extend(row["id"] for row in pending)
    return list(dict.fromkeys(ids))
