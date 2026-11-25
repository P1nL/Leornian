from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.planning_materials import PlanningMaterials
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.goal_coverage_contracts import (
    SOURCE_DEFECTS,
    MaterialGoalFinding,
)
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.material_contracts import MaterialRef
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.retrieval import Retrieval, terms
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.knowledge.source_acquisition import (
    DEFAULT_SOURCE_DEPTH,
    MAX_GAP_SOURCE_DEPTH,
    MaterialSources,
    identity,
    ordinary_node_reading,
    teaching_reading_refs,
)
from leornian.modules.knowledge.source_candidates import gap_topics
from leornian.modules.knowledge.source_catalog import (
    framework_key,
    official_sources,
)
from leornian.modules.knowledge.stage_sections import (
    StageSections,
    chapter_location,
    guide_chapters,
    shared_readings,
)
from leornian.shared_kernel.errors import BusinessError


def subject_matches(demand, source):
    return all(
        getattr(demand, field) is None
        or (
            getattr(source, field) is not None
            and (
                framework_key(getattr(source, field)) == framework_key(getattr(demand, field))
                if field == "framework"
                else getattr(source, field).casefold() == getattr(demand, field).casefold()
            )
        )
        for field in ("language", "language_version", "framework", "framework_version")
    )


class MaterialDiscoveryWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    @staticmethod
    def public_sources_in(connection, actor, demand):
        from leornian.modules.learning.application import Learning
        from leornian.modules.learning.infrastructure import PgGoalStore

        scope = Learning(PgGoalStore(connection)).get_goal(actor, demand.goal_id).material_scope
        return bool(scope and scope.authorized_public_sources)

    @staticmethod
    def curriculum_in(connection, actor, demand, *, include_stage=False):
        from leornian.modules.learning.planning import Plans

        if not demand.plan_id or not demand.node_key:
            return None
        return Plans(connection).curriculum_snapshot(
            actor, demand.plan_id, demand.plan_revision, node_key=demand.node_key,
            include_stage=include_stage,
        )

    @staticmethod
    def preferred_urls(curriculum):
        if not curriculum:
            return set()
        current = curriculum["node_chapters"][0]["material_plan"]
        return shared_readings(curriculum.get("material_stage", {"nodes": []}), current)

    @staticmethod
    def node_frameworks(curriculum):
        from leornian.modules.knowledge.source_candidates import mentions_framework
        from leornian.modules.knowledge.source_catalog import catalog_resources

        if not curriculum:
            return set(), set()
        names = {
            name for entry in catalog_resources() for name in entry["frameworks"]
        }

        def matched(technologies):
            return {
                name for name in names if any(
                    framework_key(item["name"]) == framework_key(name)
                    or mentions_framework(item["name"], name) for item in technologies
                )
            }

        active = matched(curriculum["node_chapters"][0]["material_plan"]["technologies"])
        return active, matched(curriculum["technologies"]) - active

    @staticmethod
    def source_matches_node(scope, *, title="", url="", topics=(), framework=None):
        from leornian.modules.knowledge.source_candidates import mentions_framework

        active, deferred = scope
        labels = " ".join([title, url, *topics, framework or ""])
        explicit = {framework_key(value) for value in [*topics, framework or ""]}

        def matches(name):
            return framework_key(name) in explicit or mentions_framework(labels, name)

        return any(matches(name) for name in active) or not any(
            matches(name) for name in deferred
        )

    @staticmethod
    def curriculum_resources_in(connection, actor, demand, *, topics=None):
        """Select known chapters under existing grants before opening another source."""
        from leornian.modules.knowledge.source_network import approved_source_url

        node_stage = demand.consumer_ref.startswith("node-material:")
        curriculum = MaterialDiscoveryWorkflow.curriculum_in(
            connection, actor, demand, include_stage=node_stage,
        )
        if not curriculum:
            return {}
        chapters = curriculum["node_chapters"][0]["chapters"]
        preparation = curriculum["node_chapters"][0]["material_plan"]
        preferred = MaterialDiscoveryWorkflow.preferred_urls(curriculum)
        sources = MaterialSources(connection)
        selected = {}
        for source in sources.list(actor, demand.goal_id):
            try:
                _row, data = sources.require(actor, source.id, purpose=demand.purpose)
            except BusinessError as error:
                if error.code == "source_not_current":
                    continue
                raise
            if node_stage and source.entry_url in preferred:
                resources = connection.execute(
                    "SELECT url,link_label,depth,link_order "
                    "FROM knowledge.material_source_resources "
                    "WHERE source_id=%s AND depth=1 AND url<>%s", (source.id, source.entry_url),
                ).fetchall()
                selected.update(dict.fromkeys(guide_chapters(
                    resources, topics or preparation["topics"], preparation["technologies"],
                ), source.id))
            for chapter in chapters:
                if chapter["source_url"] is None:
                    continue
                text = next(
                    item for item in curriculum["texts"] if item["key"] == chapter["text_key"]
                )
                if source.entry_url != text["source_url"]:
                    continue
                try:
                    url = approved_source_url(chapter["source_url"], data.allowed_prefixes)
                except BusinessError:
                    continue
                sources.add_resource(source.id, url, depth=1, label=chapter["title"])
                selected[url] = source.id
            for reading in curriculum["node_chapters"][0]["material_plan"]["readings"]:
                if not reading.get("source_url"):
                    continue
                try:
                    url = approved_source_url(reading["source_url"], data.allowed_prefixes)
                except BusinessError:
                    continue
                sources.add_resource(source.id, url, depth=1, label=reading["title"])
                selected[url] = source.id
        return selected

    @staticmethod
    def catalog_in(connection, actor, demand, *, missing=()):
        from leornian.modules.learning.application import Learning
        from leornian.modules.learning.infrastructure import PgGoalStore
        from leornian.modules.learning.planning import Plans

        goal = Learning(PgGoalStore(connection)).get_goal(actor, demand.goal_id)
        if not goal.material_scope:
            return []
        topic = demand.goal_text or ""
        if goal.material_scope.language is None:
            topic = "\n".join((goal.title, goal.motivation, demand.goal_text or ""))
            if demand.plan_id:
                plan = Plans(connection).get(actor, demand.plan_id)
                document = (plan.active or plan.latest).document
                topic += "\n" + document.title + "\n" + document.summary
        from leornian.modules.knowledge.source_candidates import (
            MAX_CATALOG_CANDIDATES,
            DiscoveredSourceCatalog,
            candidate_source,
            ranked_candidates,
        )

        public = goal.material_scope.authorized_public_sources
        curriculum = MaterialDiscoveryWorkflow.curriculum_in(
            connection, actor, demand, include_stage=True,
        ) if demand.consumer_ref.startswith("node-material:") else None
        active, deferred = MaterialDiscoveryWorkflow.node_frameworks(curriculum)
        if curriculum:
            topic = demand.goal_text or ""
        preferred = MaterialDiscoveryWorkflow.preferred_urls(curriculum)
        entries = ranked_candidates(
            demand, "\n".join([topic, *missing]),
            missing=missing,
            extra=DiscoveredSourceCatalog(connection).entries(actor) if public else (),
            allowed_origins=None if public else {"official"},
            active_frameworks=active, deferred_frameworks=deferred,
            preferred_urls=preferred, node_scope=bool(curriculum),
        )
        # Frozen official registrations keep their identities and precise version URLs.
        legacy = [] if public else official_sources(demand, auto_topic=topic)
        urls = {source.entry_url for _, source in legacy}
        return (legacy + [
            (entry["id"] if entry["id"].startswith("discovered:") else "resource:" + entry["id"],
             candidate_source(demand, entry))
            for entry in entries if entry["url"] not in urls
        ])[:MAX_CATALOG_CANDIDATES]

    @staticmethod
    def ensure_in(connection, actor, session_digest, demand, *, required_refs=None,
                  resume_examples=False):
        from leornian.modules.learning.materials import MaterialBindings

        if demand.scope_mode == "whole_source":
            return None
        sources = MaterialSources(connection)
        discovery = sources.ensure_discovery(actor, session_digest, demand)
        if required_refs is None and ordinary_node_reading(demand) and (
            discovery.status == "queued" and not discovery.error_code
        ):
            bindings = MaterialBindings(connection).for_scope(
                actor, demand.goal_id, "teaching", plan_id=demand.plan_id,
                plan_revision=demand.plan_revision, node_key=demand.node_key,
            )
            if bindings and connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET status='ready',missing_facets='[]' "
                "WHERE id=%s AND status='queued' AND search_id IS NULL AND error_code IS NULL "
                "AND acquisition_state='{}'::jsonb RETURNING id", (discovery.id,),
            ).fetchone():
                from leornian.modules.tutor.deliveries import Deliveries

                connection.execute("UPDATE knowledge.material_demands SET status='ready' "
                                   "WHERE id=%s AND status='open'", (demand.id,))
                Deliveries(connection).node_material_available(demand.id)
                discovery = sources.discovery(actor, demand.id, demand.revision)
        if (resume_examples and demand.status == "open" and required_refs is None
                and demand.consumer_ref.startswith("node-material:")
                and not ordinary_node_reading(demand)
                and discovery.error_code == "material_discovery_exhausted"):
            from leornian.bootstrap.material_acquisition import MaterialAcquisition

            if MaterialAcquisition.resume_legacy_examples(
                connection, actor, discovery, session_digest,
            ):
                discovery = sources.discovery(actor, demand.id, demand.revision)
        if required_refs is not None:
            if demand.scope_mode != "teaching_goal" or not required_refs:
                raise BusinessError(
                    "precondition_failed", "Frozen material scopes need a teaching goal and refs."
                )
            request = MaterialSearchInput(
                demand_id=demand.id,
                expected_demand_revision=demand.revision,
                query=demand.goal_text[:4000],
                mode="lexical",
                required_refs=[
                    ref.model_copy(update={"selection_id": None}) for ref in required_refs
                ],
            )
            search = MaterialSearchWorkflow.submit_in(
                connection,
                actor,
                session_digest,
                f"frozen-material-discovery:{discovery.id}",
                request,
            )
            discovery = sources.attach_search(actor, discovery.id, search.id)
        return discovery

    def get(self, token, demand_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            demand = MaterialIntake(connection).demand(actor, demand_id)
            return MaterialSources(connection).discovery(actor, demand.id, demand.revision)

    def ensure(self, token, demand_id):
        with self.database.transaction() as connection:
            auth = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = auth.authenticate(token)
            demand = MaterialIntake(connection).demand(actor, demand_id)
            MaterialIntakeWorkflow.require_scope(connection, actor, demand)
            return self.ensure_in(
                connection, actor, auth.digest(token), demand, resume_examples=True,
            )

    @staticmethod
    def current(connection, discovery_id):
        seed = connection.execute(
            "SELECT * FROM knowledge.material_discovery_jobs WHERE id=%s",
            (discovery_id,),
        ).fetchone()
        if not seed:
            return None
        actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
            seed["session_digest"]
        )
        row = connection.execute(
            "SELECT * FROM knowledge.material_discovery_jobs WHERE id=%s FOR UPDATE",
            (discovery_id,),
        ).fetchone()
        demand = MaterialIntake(connection).demand(actor, row["demand_id"])
        MaterialIntakeWorkflow.require_scope(connection, actor, demand)
        if demand.revision != row["demand_revision"] or demand.status == "cancelled":
            raise BusinessError("stale_version", "Material discovery demand changed.")
        return actor, row, demand

    @staticmethod
    def transition(connection, discovery_id, status, error=None, *, missing=None, selection=None):
        row = connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET status=%s,error_code=%s,"
            "missing_facets=COALESCE(%s,missing_facets),selection_id=COALESCE(%s,selection_id),"
            "lease_token=NULL,lease_until=NULL,next_run_at=now()+interval '3 seconds' "
            "WHERE id=%s RETURNING demand_id",
            (
                status,
                error,
                Jsonb(gap_topics(missing)) if missing is not None else None,
                selection,
                discovery_id,
            ),
        ).fetchone()
        if row and (status == "ready" or error == "material_discovery_exhausted"):
            from leornian.modules.tutor.deliveries import Deliveries

            Deliveries(connection).node_material_available(row["demand_id"])
            if status == "ready":
                Deliveries(connection).material_ready(row["demand_id"])

    @staticmethod
    def evidence(connection, actor, demand):
        retrieval = Retrieval(connection)
        builds = retrieval.scope(actor, demand)
        complete = connection.execute(
            "SELECT DISTINCT job_id FROM knowledge.material_index_builds "
            "WHERE id=ANY(%s) AND EXISTS (SELECT 1 FROM knowledge.material_index_builds vector "
            "WHERE vector.job_id=material_index_builds.job_id AND vector.state='indexed' "
            "AND vector.space->>'mode' IS DISTINCT FROM 'lexical')",
            ([build["id"] for build in builds],),
        ).fetchall()
        complete_ids = {row["job_id"] for row in complete}
        builds = [
            build
            for build in builds
            if build["job_id"] in complete_ids and build["space"].get("mode") == "lexical"
        ]
        refs, missing = {}, []
        for facet in demand.required_facets:
            required = set(terms(facet))
            rows = retrieval.candidates(builds, facet)
            support = next(
                (row for row in rows if required and required <= set(terms(row["text"]))), None
            )
            if support:
                ref = retrieval.evidence(support).ref
                refs[ref.model_dump_json()] = ref
            else:
                missing.append(facet)
        return list(refs.values()), missing

    def execute(self, discovery_id):
        with self.database.transaction(snapshot=True) as connection:
            seed = connection.execute(
                "SELECT m.specification->>'scope_mode' AS scope_mode "
                "FROM knowledge.material_discovery_jobs d "
                "JOIN knowledge.material_demands m ON m.id=d.demand_id WHERE d.id=%s",
                (discovery_id,),
            ).fetchone()
            semantic = seed and seed["scope_mode"] == "teaching_goal"
        if semantic:
            return self.execute_semantic(discovery_id)
        search_input, session_digest, command_key = None, None, None
        try:
            with self.database.transaction() as connection:
                current = self.current(connection, discovery_id)
                if not current:
                    return
                actor, row, demand = current
                if row["status"] in {"ready", "cancelled"} or row["error_code"] in {
                    "node_material_review_failed", "material_discovery_exhausted",
                }:
                    return
                if row["lease_until"] and row["lease_until"] > datetime.now(UTC):
                    return
                connection.execute(
                    "UPDATE knowledge.material_discovery_jobs SET status='processing',"
                    "lease_token=%s,lease_until=now()+interval '2 minutes' WHERE id=%s",
                    (uuid4(), discovery_id),
                )
                refs, missing = self.evidence(connection, actor, demand)
                if not missing and refs:
                    if row["search_id"]:
                        search = MaterialSearchWorkflow(self.database, self.settings).get_in(
                            connection, actor, row["search_id"]
                        )
                        if search.status == "ready":
                            selected = Retrieval(connection).selection(actor, search.selection_id)
                            if selected.coverage.status == "sufficient" or (
                                PlanningMaterials.can_draft_from_partial(demand, selected)
                            ):
                                self.transition(
                                    connection,
                                    discovery_id,
                                    "ready",
                                    missing=selected.coverage.missing_facets,
                                    selection=selected.id,
                                )
                                return
                        if search.status in {"cancelled", "blocked_unknown", "waiting_config"}:
                            self.transition(
                                connection,
                                discovery_id,
                                search.status,
                                search.error_code,
                                missing=[],
                            )
                            return
                        self.transition(
                            connection,
                            discovery_id,
                            "queued",
                            "complete_selection_pending",
                            missing=[],
                        )
                        return
                    search_input = MaterialSearchInput(
                        demand_id=demand.id,
                        expected_demand_revision=demand.revision,
                        query="complete verified facet evidence",
                        mode="lexical",
                        required_refs=refs,
                    )
                    session_digest = row["session_digest"]
                    command_key = (
                        "material-discovery:"
                        + str(discovery_id)
                        + ":"
                        + identity([ref.model_dump(mode="json") for ref in refs])
                    )
                else:
                    self.acquire(connection, actor, row, demand, missing)
                    return
            search = MaterialSearchWorkflow(self.database, self.settings).submit_digest(
                session_digest, command_key, search_input
            )
            with self.database.transaction() as connection:
                actor, row, demand = self.current(connection, discovery_id)
                if row["status"] not in {"ready", "cancelled"}:
                    connection.execute(
                        "UPDATE knowledge.material_discovery_jobs SET search_id=%s WHERE id=%s",
                        (search.id, discovery_id),
                    )
                    self.transition(
                        connection, discovery_id, "queued", "complete_selection_pending"
                    )
        except BusinessError as error:
            with self.database.transaction() as connection:
                status = (
                    "cancelled"
                    if error.code
                    in {
                        "source_not_current",
                        "stale_version",
                        "unauthorized",
                        "unauthenticated",
                        "session_expired",
                    }
                    else "waiting_config"
                    if error.code == "model_unavailable"
                    else "blocked_unknown"
                    if error.code == "external_result_unknown"
                    else "waiting_dependency"
                )
                self.transition(connection, discovery_id, status, error.code)

    def execute_semantic(self, discovery_id):
        try:
            from leornian.bootstrap.material_web import MaterialWebWorkflow

            with self.database.transaction() as connection:
                current = self.current(connection, discovery_id)
                if not current:
                    return
                actor, row, demand = current
                if row["status"] in {"ready", "cancelled"} or row["error_code"] in {
                    "node_material_review_failed", "material_discovery_exhausted",
                }:
                    return
                if row["lease_until"] and row["lease_until"] > datetime.now(UTC):
                    return
                lease = uuid4()
                connection.execute(
                    "UPDATE knowledge.material_discovery_jobs SET status='processing',"
                    "lease_token=%s,lease_until=now()+interval '2 minutes' WHERE id=%s",
                    (lease, discovery_id),
                )
            MaterialWebWorkflow(self.database, self.settings).advance_search(
                discovery_id, lease=lease,
            )
            with self.database.transaction() as connection:
                current = self.current(connection, discovery_id)
                if not current:
                    return
                actor, row, demand = current
                if row["lease_token"] != lease or row["status"] != "processing":
                    return
                request = self.semantic_input(connection, actor, row, demand)
                if request is None:
                    return
                session_digest = row["session_digest"]
                command_key = (
                    "semantic-material-discovery:"
                    + str(discovery_id)
                    + ":"
                    + identity(MaterialSearchWorkflow.request(request))
                )
            search = MaterialSearchWorkflow(self.database, self.settings).submit_digest(
                session_digest, command_key, request
            )
            with self.database.transaction() as connection:
                actor, row, demand = self.current(connection, discovery_id)
                if row["status"] not in {"ready", "cancelled"}:
                    connection.execute(
                        "UPDATE knowledge.material_discovery_jobs SET search_id=%s WHERE id=%s",
                        (search.id, discovery_id),
                    )
                    self.transition(connection, discovery_id, "queued", "semantic_coverage_pending")
        except BusinessError as error:
            if error.code == "lease_lost":
                return
            with self.database.transaction() as connection:
                self.transition(
                    connection,
                    discovery_id,
                    "waiting_config"
                    if error.code in {
                        "model_unavailable", "tavily_not_configured",
                        "tavily_configuration_changed",
                    }
                    else "blocked_unknown"
                    if error.code == "external_result_unknown"
                    else "cancelled"
                    if error.code
                    in {
                        "source_not_current",
                        "stale_version",
                        "unauthenticated",
                        "session_expired",
                    }
                    else "waiting_dependency",
                    error.code,
                )

    def semantic_input(self, connection, actor, row, demand):
        from leornian.modules.learning.materials import MaterialBindings

        if row["search_id"]:
            original = connection.execute(
                "SELECT request,command_key,scope FROM knowledge.material_searches "
                "WHERE id=%s AND actor_id=%s",
                (row["search_id"], actor.id),
            ).fetchone()
            scoped_selection = bool(
                original and not original["request"].get("binding_id")
                and original["command_key"].startswith(f"semantic-material-discovery:{row['id']}:")
                and ((row.get("acquisition_state") or {}).get("excluded_findings")
                     or demand.consumer_ref.startswith("node-material:"))
            )
            if original and original["request"].get("required_refs") and not scoped_selection:
                request = MaterialSearchInput(**original["request"])
                _demand, _binding, builds = MaterialSearchWorkflow.scope(
                    connection, actor, request
                )
                search = MaterialSearchWorkflow.get_in(connection, actor, row["search_id"])
                if search.status == "ready":
                    selection = Retrieval(connection).selection(actor, search.selection_id)
                    sufficient = selection.coverage.status == "sufficient"
                    self.transition(
                        connection, row["id"], "ready" if sufficient else "waiting_dependency",
                        None if sufficient else "bound_material_coverage_gap",
                        missing=[] if sufficient else [demand.goal_text],
                        selection=selection.id if sufficient else None,
                    )
                    if sufficient:
                        connection.execute(
                            "UPDATE knowledge.material_demands SET status='ready' WHERE id=%s",
                            (demand.id,),
                        )
                elif (not builds or search.error_code == "material_index_pending") and (
                    self.prepare_existing(
                        connection, actor, row, demand, None, refs=request.required_refs
                    )
                ):
                    return None
                elif search.status in {
                    "cancelled", "waiting_config", "waiting_dependency", "blocked_unknown"
                }:
                    self.transition(connection, row["id"], search.status, search.error_code)
                else:
                    self.transition(connection, row["id"], "queued", "semantic_coverage_pending")
                return None
            search = MaterialSearchWorkflow.get_in(connection, actor, row["search_id"])
            if search.error_code == "material_goal_protocol_exhausted" and (
                search.status == "waiting_dependency"
                and original and not original["request"].get("binding_id")
            ):
                failed = connection.execute(
                    "SELECT p.refs FROM knowledge.material_goal_coverage_parts p "
                    "JOIN runtime.runs r ON r.id=p.run_id WHERE p.search_id=%s "
                    "AND p.level=0 AND p.state='waiting_dependency' AND r.status='failed' "
                    "AND r.error_code='invalid_material_goal_output' AND NOT r.cancel_requested",
                    (row["search_id"],),
                ).fetchall()
                if failed:
                    state = dict(row.get("acquisition_state") or {})
                    excluded = state.get("excluded_versions", [])
                    for part in failed:
                        for ref in part["refs"]:
                            version = [ref["document_id"], ref["document_revision"]]
                            if version not in excluded:
                                excluded.append(version)
                    state["excluded_versions"] = excluded
                    # The invalid receipts remain failed; the next selection uses another source.
                    row["acquisition_state"], row["search_id"] = state, None
                    connection.execute(
                        "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s,"
                        "search_id=NULL WHERE id=%s", (Jsonb(state), row["id"]),
                    )
                    self.acquire(
                        connection, actor, row, demand,
                        row["missing_facets"] or [demand.goal_text],
                    )
                    return None
            # A running search owns a frozen set. New documents belong to the next batch.
            if search.status != "ready":
                self.transition(
                    connection, row["id"], search.status if search.status in {
                        "cancelled", "waiting_config", "waiting_dependency", "blocked_unknown",
                    } else "queued", search.error_code or "semantic_coverage_pending",
                )
                return None
            selection = Retrieval(connection).selection(actor, search.selection_id)
            if selection.coverage.status == "sufficient" or (
                PlanningMaterials.can_draft_from_partial(demand, selection)
            ):
                self.transition(
                    connection, row["id"], "ready",
                    missing=selection.coverage.missing_facets, selection=selection.id,
                )
                connection.execute(
                    "UPDATE knowledge.material_demands SET status='ready' WHERE id=%s",
                    (demand.id,),
                )
                return None
            rejected = connection.execute(
                "SELECT refs,result FROM knowledge.material_goal_coverage_parts WHERE search_id=%s "
                "AND level=0 AND state='reviewed' AND (result->'issues' ?| "
                "ARRAY['incorrect','version_mismatch','irrelevant','access_restricted'] "
                "OR result->>'status' IN ('missing','uncertain'))",
                (row["search_id"],),
            ).fetchall()
            if rejected:
                state = dict(row.get("acquisition_state") or {})
                excluded = state.get("excluded_versions", [])
                findings = state.get("excluded_findings", [])
                for part in rejected:
                    scoped = [
                        MaterialGoalFinding(**finding)
                        for finding in part["result"].get("findings", [])
                        if finding["issue"] in SOURCE_DEFECTS
                    ]
                    unscoped = (
                        set(part["result"].get("issues", [])) & SOURCE_DEFECTS
                    ) - {finding.issue for finding in scoped}
                    whole = bool(unscoped) or (
                        not (original.get("scope") or {}).get("node_checklist")
                        and part["result"]["status"] in {"missing", "uncertain"}
                    )
                    for ref in part["refs"] if whole else []:
                        version = [ref["document_id"], ref["document_revision"]]
                        if version not in excluded:
                            excluded.append(version)
                    for finding in scoped:
                        if finding.scope == "document":
                            for ref in finding.refs:
                                version = [str(ref.document_id), ref.document_revision]
                                if version not in excluded:
                                    excluded.append(version)
                        elif finding.model_dump(mode="json") not in findings:
                            findings.append(finding.model_dump(mode="json"))
                state["excluded_versions"] = excluded
                if findings:
                    state["excluded_findings"] = findings
                row["acquisition_state"] = state
                connection.execute(
                    "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
                    (Jsonb(state), row["id"]),
                )
            if ordinary_node_reading(demand) and selection.coverage.status == "partial" and (
                teaching_reading_refs(selection.coverage, selection.id, row["acquisition_state"])
            ):
                self.transition(connection, row["id"], "ready",
                                missing=selection.coverage.missing_facets, selection=selection.id)
                connection.execute("UPDATE knowledge.material_demands SET status='ready' "
                                   "WHERE id=%s AND status='open'", (demand.id,))
                return None
        bindings = MaterialBindings(connection).for_scope(
            actor,
            demand.goal_id,
            demand.purpose,
            plan_id=demand.plan_id,
            plan_revision=demand.plan_revision,
            node_key=demand.node_key,
        )
        binding = bindings[0] if bindings and not demand.consumer_ref.startswith(
            "planning-batch:"
        ) else None
        if binding:
            MaterialBindings(connection).require_scope(actor, binding)
            supplement = (row.get("acquisition_state") or {}).get("supplement_binding")
            if supplement:
                if supplement != {"id": str(binding.id), "revision": binding.revision}:
                    raise BusinessError(
                        "stale_version", "Material supplementation binding changed.",
                    )
                binding = None
        builds = self.available_builds(connection, actor, row, demand, binding)
        if not row["search_id"]:
            reused = Retrieval(connection).reuse_goal_selection(
                actor, demand, binding, build_ids={str(build["id"]) for build in builds},
            )
            if reused:
                self.transition(
                    connection, row["id"], "ready", missing=[], selection=reused.id,
                )
                connection.execute(
                    "UPDATE knowledge.material_demands SET status='ready' WHERE id=%s",
                    (demand.id,),
                )
                return None
            if not binding and demand.consumer_ref.startswith("node-material:"):
                curriculum = self.curriculum_in(connection, actor, demand, include_stage=True)
                preferred = self.preferred_urls(curriculum)
                if preferred:
                    from leornian.bootstrap.material_acquisition import MaterialAcquisition

                    chapter_urls = [url for url in self.curriculum_resources_in(
                        connection, actor, demand,
                    ) if url not in preferred]
                    origins = MaterialSources(connection).document_origins(
                        actor, {build["document_id"] for build in builds},
                    )
                    locations = {chapter_location(origin["url"]) for origin in origins}
                    locations.update(chapter_location(build["source_url"]) for build in builds
                                     if build.get("source_url"))
                    missing_urls = [url for url in chapter_urls[:2]
                                    if chapter_location(url) not in locations]
                    if (missing_urls or not chapter_urls and not any(
                        chapter_location(url) in locations for url in preferred
                    )) and MaterialAcquisition(self).acquire(
                        connection, actor, row, demand, gap_topics([demand.goal_text]),
                        preferred_only=True,
                        **({"chapter_urls": missing_urls} if missing_urls else {}),
                    ):
                        return None
        if not binding:
            uploads = MaterialIntake(connection).pending_goal_uploads(actor, demand.goal_id)
            if uploads and demand.preparation == "complete" and (
                not builds or demand.purpose != "planning"
                and not demand.consumer_ref.startswith("node-material:")
            ):
                state = (
                    "blocked_unknown" if any(job.state == "blocked_unknown" for job in uploads)
                    else "waiting_config" if any(job.state == "waiting_config" for job in uploads)
                    else "waiting_dependency" if any(
                        job.state == "waiting_dependency" for job in uploads
                    )
                    else "queued"
                )
                self.transition(
                    connection, row["id"], state, "uploaded_material_preparation_pending",
                    missing=[demand.goal_text],
                )
                return None
        if (
            demand.preparation != "complete" and builds
            and not (row.get("acquisition_state") or {}).get("excluded_findings")
        ):
            origins = connection.execute(
                "SELECT DISTINCT o.document_id,o.document_revision,"
                "r.depth,r.link_label,r.link_order,r.url "
                "FROM knowledge.source_observations o "
                "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
                "WHERE o.actor_id=%s AND o.document_id=ANY(%s::uuid[])",
                (actor.id, list({build["document_id"] for build in builds})),
            ).fetchall()
            seen = {
                (item["document_id"], item["document_revision"])
                for item in (original or {}).get(
                    "request", {}
                ).get("source_versions", [])
            } if row["search_id"] else set()
            wanted = self.topic_terms([demand.goal_text])
            available = {
                (str(build["document_id"]), build["document_revision"]) for build in builds
            }
            choices = [item for item in origins if (
                str(item["document_id"]), item["document_revision"],
            ) in available - seen]
            choices.sort(key=lambda item: (
                -len(wanted & set(terms(item["link_label"] + " " + item["url"]))),
                -bool(set(terms(item["url"] + " " + item["link_label"])) & {
                    "introduction", "intro", "start", "started", "basics", "overview",
                }),
                item["depth"], item["link_order"], item["url"], -item["document_revision"],
            ))
            selected = {
                (choices[0]["document_id"], choices[0]["document_revision"])
            } if choices else set()
            sourced = {(item["document_id"], item["document_revision"]) for item in origins}
            uploads = sorted(
                {
                    (build["document_id"], build["document_revision"]) for build in builds
                    if (build["document_id"], build["document_revision"]) not in sourced
                },
                key=lambda item: (str(item[0]), item[1]),
            )
            if uploads:
                selected.add(uploads[0])
            builds = [build for build in builds if (
                build["document_id"], build["document_revision"],
            ) in selected]
        if not binding and demand.consumer_ref.startswith("node-material:") and not (
            (row.get("acquisition_state") or {}).get("supplement_binding")
        ):
            curriculum = self.curriculum_in(connection, actor, demand, include_stage=True)
            if curriculum and curriculum.get("material_stage"):
                return self.node_packet(
                    connection, actor, row, demand, curriculum["material_stage"], builds,
                    original if row["search_id"] else None, selection if row["search_id"] else None,
                )
        eligible_versions = {
            (build["document_id"], build["document_revision"]) for build in builds
            if demand.purpose == "planning" or build["space"].get("mode") != "lexical"
        }
        builds = [
            build for build in builds
            if (build["document_id"], build["document_revision"]) in eligible_versions
        ]
        versions = [
            {"document_id": str(document), "document_revision": revision}
            for document, revision in sorted(
                eligible_versions,
                key=lambda value: (str(value[0]), value[1]),
            )
        ]
        if not versions:
            if self.prepare_existing(connection, actor, row, demand, binding):
                return None
            self.acquire(connection, actor, row, demand, [demand.goal_text])
            return None
        same_reviewed_versions = False
        if (
            (
                demand.purpose == "planning" and demand.preparation == "complete"
                or demand.consumer_ref.startswith("node-material:")
            )
            and not binding and row["search_id"]
            and original["request"].get("required_refs")
        ):
            reviewed_versions = {
                (item["document_id"], item["document_revision"])
                for item in original["request"].get(
                    "source_versions", original["request"]["required_refs"],
                )
            }
            same_reviewed_versions = all(
                (item["document_id"], item["document_revision"]) in reviewed_versions
                for item in versions
            )
            if same_reviewed_versions and (
                not demand.consumer_ref.startswith("node-material:")
                or "stage_gap_chunks" in (row.get("acquisition_state") or {})
            ):
                # A cleaned selection was already checked. Different sampled refs in the
                # same revisions cannot keep the unresolved goal from acquiring new sources.
                self.acquire(
                    connection, actor, row, demand,
                    selection.coverage.missing_facets or [demand.goal_text],
                )
                return None
        request = MaterialSearchInput(
            demand_id=demand.id,
            expected_demand_revision=demand.revision,
            query="\n".join([demand.goal_text, *row["missing_facets"]])[:4000]
            if demand.purpose == "planning" else demand.goal_text[:4000],
            mode="lexical" if demand.purpose == "planning" else "hybrid",
            source_versions=versions,
            binding_id=binding.id if binding else None,
            expected_binding_revision=binding.revision if binding else None,
        )
        findings = (row.get("acquisition_state") or {}).get("excluded_findings", [])
        stage = None
        if not binding and demand.consumer_ref.startswith("node-material:"):
            curriculum = self.curriculum_in(connection, actor, demand, include_stage=True)
            stage = curriculum.get("material_stage") if curriculum else None
        if (findings or stage) and not binding:
            chunk_ids = (
                StageSections(connection).chunks(actor, demand, stage, builds) if stage else None
            )
            if stage:
                state = row.get("acquisition_state") or {}
                extra = state.get("stage_gap_chunks", [])
                if same_reviewed_versions:
                    lexical = [build for build in builds if build["space"].get("mode") == "lexical"]
                    extra = list(dict.fromkeys(
                        str(item["id"]) for gap in selection.coverage.missing_facets[:6]
                        for item in Retrieval(connection).candidates(lexical or builds, gap)[:3]
                        if str(item["id"]) not in chunk_ids
                    ))
                    row["acquisition_state"] = {**state, "stage_gap_chunks": extra}
                    connection.execute(
                        "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s "
                        "WHERE id=%s", (Jsonb(row["acquisition_state"]), row["id"]),
                    )
                    if not extra:
                        self.acquire(
                            connection, actor, row, demand, selection.coverage.missing_facets,
                        )
                        return None
                chunk_ids = list(dict.fromkeys([*chunk_ids, *extra]))
            refs = Retrieval(connection).unaffected_refs(
                builds, [MaterialGoalFinding(**finding) for finding in findings],
                planning_query=request.query if demand.purpose == "planning" else None,
                chunk_ids=chunk_ids,
            )
            if not refs:
                self.acquire(
                    connection, actor, row, demand, row["missing_facets"] or [demand.goal_text],
                )
                return None
            request = MaterialSearchInput(**{
                **request.model_dump(), "required_refs": refs, "mode": "lexical",
            })
        if row["search_id"]:
            original = connection.execute(
                "SELECT request FROM knowledge.material_searches WHERE id=%s AND actor_id=%s",
                (row["search_id"], actor.id),
            ).fetchone()
            search = MaterialSearchWorkflow(self.database, self.settings).get_in(
                connection, actor, row["search_id"]
            )
            if (row.get("acquisition_state") or {}).get("supplement_binding") and (
                original["request"].get("source_versions") == versions
            ):
                selected = Retrieval(connection).selection(actor, search.selection_id)
                self.acquire(
                    connection, actor, row, demand,
                    selected.coverage.missing_facets or [demand.goal_text],
                )
                return None
            if search.status == "blocked_unknown":
                self.transition(
                    connection, row["id"], "blocked_unknown", search.error_code,
                    missing=[demand.goal_text],
                )
                return None
            if original["request"] == MaterialSearchWorkflow.request(request):
                if search.status == "ready":
                    selected = Retrieval(connection).selection(actor, search.selection_id)
                    if selected.coverage.status == "sufficient" or (
                        PlanningMaterials.can_draft_from_partial(demand, selected)
                    ):
                        self.transition(
                            connection, row["id"], "ready",
                            missing=selected.coverage.missing_facets, selection=selected.id
                        )
                        connection.execute(
                            "UPDATE knowledge.material_demands SET status='ready' WHERE id=%s",
                            (demand.id,),
                        )
                    else:
                        if binding:
                            if self.public_sources_in(connection, actor, demand):
                                state = {
                                    **(row.get("acquisition_state") or {}),
                                    "supplement_binding": {
                                        "id": str(binding.id), "revision": binding.revision,
                                    },
                                }
                                connection.execute(
                                    "UPDATE knowledge.material_discovery_jobs "
                                    "SET acquisition_state=%s WHERE id=%s",
                                    (Jsonb(state), row["id"]),
                                )
                                row["acquisition_state"] = state
                                self.acquire(
                                    connection, actor, row, demand,
                                    selected.coverage.missing_facets or [demand.goal_text],
                                )
                            else:
                                self.transition(
                                    connection, row["id"], "waiting_dependency",
                                    "bound_material_coverage_gap", missing=[demand.goal_text],
                                )
                        else:
                            self.acquire(
                                connection, actor, row, demand,
                                selected.coverage.missing_facets or [demand.goal_text],
                            )
                    return None
                self.transition(
                    connection,
                    row["id"],
                    search.status
                    if search.status
                    in {"cancelled", "blocked_unknown", "waiting_config", "waiting_dependency"}
                    else "queued",
                    search.error_code or "semantic_coverage_pending",
                    missing=[demand.goal_text],
                )
                return None
        return request

    def node_packet(self, connection, actor, row, demand, stage, builds, original, selection):
        state = dict(row.get("acquisition_state") or {})
        node = next(item for item in stage["nodes"] if item["key"] == demand.node_key)
        checklist = list(dict.fromkeys(node["topics"] or [node["title"]]))
        previous = (original or {}).get("scope") or {}
        same = previous.get("node_checklist") == checklist and selection is not None
        gap = selection.coverage.missing_facets if same else None
        reviewed = set(state.get("node_reviewed_blocks", ()))
        carry = {}
        if same:
            reviewed.update(item["block_id"] for item in original["request"]["required_refs"])
            carry = {item.facet: item.evidence for item in selection.coverage.required
                     if item.status == "supported" and item.facet in checklist}
        findings = [MaterialGoalFinding(**item) for item in state.get("excluded_findings", [])]
        available = {(str(item["document_id"]), item["document_revision"]) for item in builds}

        def usable(ref):
            return ((str(ref.document_id), ref.document_revision) in available
                    and not any(finding.affects(ref) for finding in findings))

        carry = {topic: refs for topic, refs in carry.items() if refs and all(map(usable, refs))}
        missing = [topic for topic in checklist if topic not in carry]
        stalled = same and previous.get("node_parent_selection") and not (
            set(carry) - previous.get("node_carried", {}).keys()
        )
        examples = {topic: hint for topic, hint in previous.get("node_example_queries", {}).items()
                    if topic in missing}
        checked_examples = state.get("node_checked_examples", [])
        lookup = state.get("node_example_lookup")
        if same and (getattr(demand, "language", None) or getattr(demand, "framework", None)):
            for topic in missing:
                if topic in checked_examples or lookup and topic in lookup["gaps"] or (
                    stalled and "node_example_queries" not in previous
                ):
                    examples.setdefault(topic, topic)
        if stalled and not examples:
            self.transition(connection, row["id"], "waiting_dependency",
                            "material_discovery_exhausted", missing=missing)
            return None
        sample_builds = builds
        if examples and lookup:
            fresh = set(lookup["attempted"]) - set(lookup.get("reviewed", []))
            sample_builds = [build for build in builds if build.get("source_url") in fresh]
        elif examples and set(examples) <= set(checked_examples):
            sample_builds = []
        chunks = StageSections(connection).chunks(
            actor, demand, stage, sample_builds,
            topics=list(dict.fromkeys([*missing, *(gap or [])])) if same else None,
            reviewed=reviewed,
            **({"examples": examples} if examples else {}),
        ) if sample_builds else []
        refs = Retrieval(connection).unaffected_refs(sample_builds, findings, chunk_ids=chunks)
        if not refs:
            if examples:
                if not lookup or lookup.get("remaining") != missing:
                    state["node_example_lookup"] = {
                        **(lookup or {"gaps": list(examples), "attempted": [], "reviewed": []}),
                        "remaining": missing,
                    }
                    row["acquisition_state"] = state
                    connection.execute(
                        "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s "
                        "WHERE id=%s", (Jsonb(state), row["id"]),
                    )
                self.acquire(connection, actor, row, demand, list(examples), examples=True)
                return None
            if not builds and self.prepare_existing(connection, actor, row, demand, None):
                return None
            self.acquire(connection, actor, row, demand, gap or missing)
            return None
        if same:
            state["node_reviewed_blocks"] = sorted(reviewed)
            state["node_parent_selection"] = str(selection.id)
            if examples:
                prior = state.get("node_gap_context", {})
                candidates = [item.ref for item in selection.evidence
                              if selection.coverage.status == "partial"]
                if prior.get("topics") == missing:
                    candidates.extend(MaterialRef(**value) for value in prior["refs"])
                covered = {ref.model_copy(update={"selection_id": None}).model_dump_json()
                           for values in carry.values() for ref in values}
                context = {}
                for item in candidates:
                    ref = item.model_copy(update={"selection_id": None})
                    key = ref.model_dump_json()
                    if key not in covered and usable(ref):
                        context[key] = ref
                    if len(context) == 3:
                        break
                refs = [*refs, *context.values()]
                state["node_gap_context"] = {
                    "topics": missing, "refs": [ref.model_dump(mode="json")
                                                for ref in context.values()],
                }
                state["node_checked_examples"] = list(dict.fromkeys([*checked_examples, *examples]))
                if lookup:
                    lookup["remaining"] = missing
                    versions = {(ref.document_id, ref.document_revision) for ref in refs}
                    lookup["reviewed"] = sorted(set(lookup["reviewed"]) | {
                        build["source_url"] for build in sample_builds
                        if (build["document_id"], build["document_revision"]) in versions
                    })
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
                (Jsonb(state), row["id"]),
            )
        all_refs = {ref.model_dump_json(): ref for ref in refs}
        for prior in carry.values():
            for item in prior:
                ref = item.model_copy(update={"selection_id": None})
                all_refs[ref.model_dump_json()] = ref
        versions = sorted({(str(ref.document_id), ref.document_revision)
                           for ref in all_refs.values()})
        return MaterialSearchInput(
            demand_id=demand.id, expected_demand_revision=demand.revision, mode="lexical",
            query="\n".join(missing)[:4000], required_refs=list(all_refs.values()),
            source_versions=[{"document_id": document_id, "document_revision": revision}
                             for document_id, revision in versions],
        )

    def available_builds(self, connection, actor, row, demand, binding):
        builds = Retrieval(connection).scope(actor, demand, binding)
        if binding or not builds:
            return builds
        excluded = {
            (item[0], item[1])
            for item in (row.get("acquisition_state") or {}).get("excluded_versions", [])
        }
        builds = [build for build in builds if (
            str(build["document_id"]), build["document_revision"],
        ) not in excluded]
        if not builds:
            return []
        origins = MaterialSources(connection).document_origins(
            actor, {build["document_id"] for build in builds},
        )
        wanted = self.topic_terms([demand.goal_text or "", *row["missing_facets"]])
        sourced = {item["origin_document_id"] for item in origins}
        from leornian.bootstrap.material_sources import MaterialSourceWorkflow
        from leornian.modules.knowledge.file_parser import HTML_MAIN_PARSER_VERSION

        curriculum = self.curriculum_in(connection, actor, demand)
        readings = curriculum["node_chapters"][0]["material_plan"]["readings"] if curriculum else []
        preferred_urls = {
            reading["source_url"] for reading in readings if reading.get("source_url")
        }
        node_scope = self.node_frameworks(curriculum) if demand.consumer_ref.startswith(
            "node-material:"
        ) else (set(), set())
        relevant_origins = [
            item for item in origins
            if item["url"] in preferred_urls or self.source_matches_node(
                node_scope, title=item["source_title"], url=item["url"],
                topics=item["source_topics"] or (), framework=item["source_framework"],
            )
        ]
        directories = MaterialSourceWorkflow(self.database, self.settings).directory_versions_in(
            connection, actor, relevant_origins,
        )

        eligible = {
            (item["origin_document_id"], item["origin_revision"]) for item in relevant_origins
            if item["depth"] <= MAX_GAP_SOURCE_DEPTH and self.relevant_resource(item, wanted)
            and (item["format"] != "html" or item["parser_version"] == HTML_MAIN_PARSER_VERSION)
            and (item["origin_document_id"], item["origin_revision"]) not in directories
        }
        available = [
            build for build in builds
            if build["document_id"] not in sourced
            or (build["document_id"], build["document_revision"]) in eligible
        ]
        pinned = {
            (item["document_id"], item["document_revision"])
            for item in readings if item.get("document_id")
        }
        pinned_documents = {document_id for document_id, _revision in pinned}
        available = [
            build for build in available
            if str(build["document_id"]) not in pinned_documents
            or (str(build["document_id"]), build["document_revision"]) in pinned
        ]
        if curriculum and not row["search_id"]:
            chapters = curriculum["node_chapters"][0]["chapters"]
            urls = {
                item["source_url"] for item in [*chapters, *readings]
                if item.get("source_url")
            }
            if demand.consumer_ref.startswith("node-material:") and urls and not binding:
                mapped = {chapter_location(url) for url in
                          set(self.curriculum_resources_in(connection, actor, demand)) - urls}
                chapter_versions = {
                    (origin["origin_document_id"], origin["origin_revision"])
                    for origin in relevant_origins if chapter_location(origin["url"]) in mapped
                }
                targeted = [build for build in available if (
                    build["document_id"], build["document_revision"]
                ) in chapter_versions]
                if targeted:
                    return targeted
            documents = {
                item["document_id"] for item in [*chapters, *readings]
                if item.get("document_id")
            } | {
                str(origin["origin_document_id"]) for origin in origins if origin["url"] in urls
            }
            selected = [
                build for build in available if str(build["document_id"]) in documents
            ]
            if selected:
                return selected
        return available

    def prepare_existing(self, connection, actor, row, demand, binding, *, refs=None):
        from leornian.bootstrap.material_acquisition import REPLACEABLE

        if refs is not None:
            versions = {(ref.document_id, ref.document_revision) for ref in refs}
        elif binding:
            versions = {(ref.document_id, ref.document_revision) for ref in binding.refs}
        else:
            versions = {
                (item["id"], item["latest_revision"])
                for item in connection.execute(
                    "SELECT doc.id,doc.latest_revision FROM knowledge.documents doc "
                    "JOIN knowledge.document_versions v ON v.document_id=doc.id "
                    "AND v.revision=doc.latest_revision "
                    "LEFT JOIN knowledge.material_uploads u ON u.id=v.upload_id "
                    "WHERE doc.actor_id=%s AND doc.goal_id=%s AND doc.latest_revision>0 "
                    "AND (u.source_id IS NULL OR EXISTS("
                    "SELECT 1 FROM knowledge.source_observations o "
                    "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
                    "WHERE o.document_id=doc.id AND (r.depth=0 OR EXISTS("
                    "SELECT 1 FROM knowledge.material_source_check_commands c "
                    "JOIN knowledge.source_observations chosen ON chosen.id=c.observation_id "
                    "WHERE chosen.resource_id=o.resource_id AND c.command_key LIKE %s)))) "
                    "ORDER BY doc.id",
                    (actor.id, demand.goal_id, f"discovery:{row['id']}:shallow-v1:%"),
                ).fetchall()
            }
            curriculum = self.curriculum_in(connection, actor, demand)
            if curriculum and not row["search_id"]:
                readings = curriculum["node_chapters"][0]["material_plan"]["readings"]
                preferred = {
                    (UUID(reading["document_id"]), reading["document_revision"])
                    for reading in readings if reading.get("document_id")
                }
                if preferred:
                    versions = preferred
            if curriculum and demand.consumer_ref.startswith("node-material:"):
                scope = self.node_frameworks(curriculum)
                readings = curriculum["node_chapters"][0]["material_plan"]["readings"]
                preferred_urls = {
                    item["source_url"] for item in readings if item.get("source_url")
                }
                origins = MaterialSources(connection).document_origins(
                    actor, {document_id for document_id, _revision in versions},
                )
                sourced = {
                    (item["origin_document_id"], item["origin_revision"]) for item in origins
                }
                relevant = {
                    (item["origin_document_id"], item["origin_revision"]) for item in origins
                    if item["url"] in preferred_urls or self.source_matches_node(
                        scope, title=item["source_title"], url=item["url"],
                        topics=item["source_topics"] or (), framework=item["source_framework"],
                    )
                }
                versions = {
                    value for value in versions if value not in sourced or value in relevant
                }
        pending = []
        for document_id, revision in versions:
            version = Materials(connection).require_use(
                actor, document_id, revision, demand.purpose, goal_id=demand.goal_id
            )
            if refs is None and binding is None and version.format == "html":
                from leornian.modules.knowledge.file_parser import HTML_MAIN_PARSER_VERSION

                upload = connection.execute(
                    "SELECT source_id FROM knowledge.material_uploads WHERE id=%s",
                    (version.upload_id,),
                ).fetchone()
                if upload and upload["source_id"] and (
                    version.parser_version != HTML_MAIN_PARSER_VERSION
                ):
                    continue
            known = connection.execute(
                "SELECT state,reason_code,background_deferred FROM knowledge.material_jobs "
                "WHERE actor_id=%s AND document_id=%s AND document_revision=%s "
                "ORDER BY (state='ready') DESC,created_at,id LIMIT 1",
                (actor.id, document_id, revision),
            ).fetchone()
            if known:
                if known["background_deferred"]:
                    continue
                if known["state"] not in {"ready", "cancelled"} and (
                    known["reason_code"] not in REPLACEABLE
                ):
                    pending.append(known)
                    continue
                if known["state"] != "ready" or demand.purpose == "planning" or (
                    demand.consumer_ref.startswith("node-material:") and not binding and not refs
                ):
                    continue
                indexed = connection.execute(
                    "SELECT 1 FROM knowledge.material_index_builds "
                    "WHERE actor_id=%s AND document_id=%s AND document_revision=%s "
                    "AND state='indexed' AND space->>'mode' IS DISTINCT FROM 'lexical' LIMIT 1",
                    (actor.id, document_id, revision),
                ).fetchone()
                if indexed:
                    continue
                unresolved = connection.execute(
                    "SELECT j.state,j.reason_code FROM knowledge.material_jobs j "
                    "JOIN knowledge.material_demands d ON d.id=j.demand_id "
                    "WHERE j.actor_id=%s AND j.document_id=%s AND j.document_revision=%s "
                    "AND COALESCE(d.specification->>'index_mode','hybrid')='hybrid' "
                    "AND j.state NOT IN ('ready','cancelled') "
                    "ORDER BY (j.state='blocked_unknown') DESC,j.created_at,j.id LIMIT 1",
                    (actor.id, document_id, revision),
                ).fetchone()
                if unresolved:
                    pending.append(unresolved)
                    continue
            intake = MaterialIntake(connection)
            mode = "lexical" if demand.purpose == "planning" or (
                demand.consumer_ref.startswith("node-material:") and not binding and not refs
            ) else "hybrid"
            origin = intake.ensure_consumer_demand(
                actor,
                f"node-origin:{demand.plan_id}:{demand.plan_revision}:{demand.node_key}:"
                f"{document_id}:{revision}:{mode}" if demand.plan_id else
                f"discovery-origin:{row['id']}:{document_id}:{revision}",
                MaterialDemandInput(
                    goal_id=demand.goal_id,
                    purpose="indexing",
                    index_mode=mode,
                    scope_mode="whole_source",
                    language=demand.language,
                    language_version=demand.language_version,
                    framework=demand.framework,
                    framework_version=demand.framework_version,
                ),
            )
            job = intake.prepare_revision(
                actor, row["session_digest"], origin.id, document_id, revision
            )
            pending.append({"state": job.state, "reason_code": job.reason_code})
        if not pending:
            return False
        state = (
            "blocked_unknown"
            if any(item["state"] == "blocked_unknown" for item in pending)
            else "waiting_config"
            if any(item["state"] == "waiting_config" for item in pending)
            else "waiting_dependency"
            if all(item["state"] == "cancelled" for item in pending)
            else "queued"
        )
        self.transition(
            connection,
            row["id"],
            state,
            "existing_material_preparation_pending",
            missing=[demand.goal_text],
        )
        return True

    def acquire(self, connection, actor, row, demand, missing, *, examples=False):
        from leornian.bootstrap.material_acquisition import MaterialAcquisition

        missing = gap_topics(missing)
        row["missing_facets"] = missing
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET missing_facets=%s WHERE id=%s",
            (Jsonb(missing), row["id"]),
        )
        MaterialAcquisition(self).acquire(connection, actor, row, demand, missing,
                                          **({"examples": True} if examples else {}))

    @staticmethod
    def topic_terms(topics):
        from leornian.modules.knowledge.source_catalog import catalog_languages

        return set(terms(" ".join(topics))) - {
            "https", "http", "docs", "org", "com", "en", "us", "guide",
            "developer", "mozilla",
        } - catalog_languages()

    @staticmethod
    def relevant_resource(resource, wanted):
        path = urlsplit(resource["url"]).path
        targeted = bool(wanted.intersection(terms(path)))
        if resource["depth"] > DEFAULT_SOURCE_DEPTH:
            return targeted
        if not resource["catalog_id"] or resource["depth"] == 0:
            return True
        entry = urlsplit(resource["entry_url"]).path
        chapter_root = (
            entry.rsplit("/", 1)[0] + "/" if "." in entry.rsplit("/", 1)[-1]
            else entry.rstrip("/") + "/"
        )
        return path.startswith(chapter_root) or targeted


def scan_material_discovery_once(database, *, limit=20):
    with database.transaction() as connection:
        rows = connection.execute(
                "SELECT id FROM knowledge.material_discovery_jobs "
                "WHERE status IN ('queued','processing','waiting_config','waiting_dependency',"
                "'blocked_unknown') "
            "AND COALESCE(error_code,'') NOT IN "
            "('material_discovery_exhausted','node_material_review_failed') "
                "AND next_run_at<=now() "
                "AND (lease_until IS NULL OR lease_until<=now()) ORDER BY next_run_at,id LIMIT %s "
                "FOR UPDATE SKIP LOCKED",
                (limit,),
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET next_run_at=now()+"
                "interval '30 seconds' WHERE id=%s", (row["id"],),
            )
        return [row["id"] for row in rows]
