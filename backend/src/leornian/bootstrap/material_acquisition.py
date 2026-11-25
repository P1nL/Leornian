from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.file_parser import HTML_MAIN_PARSER_VERSION
from leornian.modules.knowledge.goal_coverage_contracts import SOURCE_DEFECTS
from leornian.modules.knowledge.source_acquisition import (
    MAX_GAP_SOURCE_DEPTH,
    MaterialSources,
    identity,
)
from leornian.modules.knowledge.source_candidates import (
    CATALOG_RESOURCE_READS,
    MAX_RENEWED_RESOURCE_READS,
    MAX_RENEWED_SEARCH_ROUNDS,
    MAX_RESOURCE_READS,
    MAX_SEARCH_ROUNDS,
    MAX_SOURCE_READS,
    material_matches_gaps,
)
from leornian.modules.knowledge.source_catalog import CATALOG_VERSION
from leornian.shared_kernel.errors import BusinessError

MAX_EXAMPLE_PAGES = 2
EXAMPLE_LOOKUP_WINDOW = timedelta(seconds=90)

# Known bad source content can be replaced. Unknown calls and configuration waits cannot.
REPLACEABLE = {
    "automatic_repair_exhausted", "material_quality_pending", "material_quality_review_pending",
    "material_replacement_source_required", "material_nontext_processing_required",
    "source_http_unavailable", "source_response_invalid", "source_format_unsupported",
    "source_redirect_limit", "source_not_current", "source_access_restricted",
    "source_network_unavailable", "source_encoding_invalid", "source_encoding_unsupported",
    "material_file_limit", "source_automatic_scope_limit", "source_depth_not_selected",
    "material_pdf_invalid", "material_pdf_limit", "material_encrypted",
    "material_parser_timeout", "material_text_limit", "material_parser_failed",
    "tavily_provider_rejected", "tavily_extraction_failed", "tavily_invalid_response",
    "source_body_missing",
}


def renew_budget(budget, used, supports, *, new_candidate, search_exhausted=False):
    """A checked coverage gain, or one bounded exploration, can fund the next batch."""
    read_limit = budget.get("read_limit", MAX_RESOURCE_READS)
    search_limit = budget.get("search_limit", MAX_SEARCH_ROUNDS)
    progress = bool(set(supports) - set(budget.get("supports", [])))
    explore = new_candidate and not budget.get("exploration_used")
    if not progress and not explore:
        return None
    next_reads = min(read_limit + (4 if used >= read_limit else 0), MAX_RENEWED_RESOURCE_READS)
    next_searches = min(search_limit + 1, MAX_RENEWED_SEARCH_ROUNDS)
    if next_reads == read_limit and (not search_exhausted or next_searches == search_limit):
        return None
    return {
        **budget, "read_limit": next_reads, "search_limit": next_searches,
        "supports": sorted(supports),
        "exploration_used": budget.get("exploration_used", False) or not progress,
        "grants": [
            *budget.get("grants", []),
            {"read_limit": next_reads, "search_limit": next_searches,
             "selected_resources": used,
             "basis": "coverage_progress" if progress else "new_gap_candidate"},
        ],
    }


class MaterialAcquisition:
    """Advance one bounded acquisition choice after checked local reuse was exhausted."""

    def __init__(self, workflow):
        self.workflow = workflow

    @staticmethod
    def resume_legacy_examples(connection, actor, discovery, session_digest):
        row = connection.execute(
            "SELECT acquisition_state FROM knowledge.material_discovery_jobs WHERE id=%s "
            "AND actor_id=%s AND status='waiting_dependency' "
            "AND error_code='material_discovery_exhausted' FOR UPDATE", (discovery.id, actor.id),
        ).fetchone()
        state = row["acquisition_state"] if row else {}
        lookup = state.get("node_example_lookup") or {}
        attempted = set(lookup.get("attempted", ()))
        if ("deadline_at" in lookup or len(attempted) != MAX_EXAMPLE_PAGES
                or len(lookup.get("reviewed", ())) >= MAX_EXAMPLE_PAGES
                or not set(lookup.get("hits", ())) - attempted):
            return False
        lookup["deadline_at"] = (datetime.now(UTC) + EXAMPLE_LOOKUP_WINDOW).isoformat()
        state.pop("exhausted", None)
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s,status='queued',"
            "error_code=NULL,session_digest=%s,next_run_at=now(),published_at=NULL WHERE id=%s",
            (Jsonb(state), session_digest, discovery.id),
        )
        return True

    def budget(self, connection, actor, row):
        root_id = UUID(str((row.get("acquisition_state") or {}).get("budget_root", row["id"])))
        root = connection.execute(
            "SELECT * FROM knowledge.material_discovery_jobs "
            "WHERE id=%s AND actor_id=%s FOR UPDATE",
            (root_id, actor.id),
        ).fetchone()
        if not root:
            raise BusinessError("source_not_current", "Material acquisition budget is unavailable.")
        family = connection.execute(
            "SELECT id,acquisition_state FROM knowledge.material_discovery_jobs "
            "WHERE actor_id=%s AND (id=%s OR acquisition_state->>'budget_root'=%s)",
            (actor.id, root_id, str(root_id)),
        ).fetchall()
        return root, (root.get("acquisition_state") or {}).get("budget", {}), family

    def extend(self, connection, actor, row, used, *, new_candidate, search_exhausted=False):
        root, budget, family = self.budget(connection, actor, row)
        parts = connection.execute(
            "SELECT p.refs,p.result,s.scope FROM knowledge.material_goal_coverage_parts p "
            "JOIN knowledge.material_searches s ON s.id=p.search_id "
            "JOIN knowledge.material_discovery_jobs d ON s.request->>'demand_id'=d.demand_id::text "
            "WHERE d.id=ANY(%s) AND p.level=0 AND p.state='reviewed' "
            "AND p.result->>'status' IN ('supported','partial')",
            ([item["id"] for item in family],),
        ).fetchall()
        supports = set()
        for part in parts:
            result = part["result"]
            scoped = {finding["issue"] for finding in result.get("findings", [])}
            if (set(result.get("issues", [])) & SOURCE_DEFECTS) - scoped:
                continue
            if not result.get("evidence_refs"):
                continue
            if (part["scope"] or {}).get("coverage_contract"):
                supports.update(
                    "topic:" + " ".join(topic.casefold().split())
                    for topic in result.get("supported_topics", [])
                )
            else:
                supports.update(
                    f"{ref['document_id']}:{ref['document_revision']}" for ref in part["refs"]
                )
        renewed = renew_budget(
            budget, used, supports,
            new_candidate=new_candidate, search_exhausted=search_exhausted,
        )
        if renewed is None:
            return None
        state = {**(root.get("acquisition_state") or {}), "budget": renewed}
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
            (Jsonb(state), root["id"]),
        )
        if root["id"] == row["id"]:
            row["acquisition_state"] = state
        return renewed

    def search(self, connection, actor, row, demand, eligible, missing, used, *, examples=False):
        from leornian.bootstrap.material_web import MaterialWebWorkflow

        _root, budget, family = self.budget(connection, actor, row)
        rounds = sum(item["acquisition_state"].get("search_rounds", 0) for item in family)
        limit = budget.get("search_limit", MAX_SEARCH_ROUNDS)
        if rounds >= limit:
            budget = self.extend(
                connection, actor, row, used, new_candidate=False, search_exhausted=True,
            )
            if budget is None:
                return False
            limit = budget["search_limit"]
        own_rounds = (row.get("acquisition_state") or {}).get("search_rounds", 0)
        return MaterialWebWorkflow(self.workflow.database, self.workflow.settings).ensure_search(
            connection, actor, row, demand, eligible, missing,
            discover_public=self.workflow.public_sources_in(connection, actor, demand),
            max_rounds=own_rounds + limit - rounds,
            **({"examples": True} if examples else {}),
        )

    def acquire(self, connection, actor, row, demand, missing, *, preferred_only=False,
                chapter_urls=(), examples=False):
        from leornian.bootstrap.material_discovery import subject_matches

        workflow = self.workflow
        sources = MaterialSources(connection)
        curriculum_urls = workflow.curriculum_resources_in(
            connection, actor, demand, topics=missing,
        ) if demand.consumer_ref.startswith("node-material:") and row.get("search_id") else (
            workflow.curriculum_resources_in(connection, actor, demand)
        )
        catalog = workflow.catalog_in(connection, actor, demand, missing=missing)
        curriculum = workflow.curriculum_in(
            connection, actor, demand,
            include_stage=demand.consumer_ref.startswith("node-material:"),
        )
        preferred = workflow.preferred_urls(curriculum)
        if preferred_only:
            if not preferred and not curriculum_urls:
                return False
            catalog = [item for item in catalog if item[1].entry_url in preferred]
        node_scope = workflow.node_frameworks(curriculum) if demand.consumer_ref.startswith(
            "node-material:"
        ) else (set(), set())
        catalog.sort(key=lambda item: item[1].entry_url not in preferred)
        registered = sources.list(actor, demand.goal_id)
        catalog_ids = {item[0] for item in catalog}
        eligible = []
        for source in registered:
            if preferred_only and (
                source.entry_url not in preferred and source.id not in curriculum_urls.values()
            ):
                continue
            if (
                source.entry_url not in preferred and source.id not in curriculum_urls.values()
                and not workflow.source_matches_node(
                    node_scope, title=source.title, url=source.entry_url,
                    topics=source.topics, framework=source.framework,
                )
            ):
                continue
            if (
                source.catalog_id not in catalog_ids
                and source.id not in curriculum_urls.values()
                and not subject_matches(demand, source)
            ):
                # An admitted public candidate remains usable for its exact teaching goal;
                # version fitness is checked against its body, not copied into metadata.
                if source.basis not in {"learning_catalog", "public_discovery"}:
                    continue
                if source.language and demand.language and (
                    source.language.casefold() != demand.language.casefold()
                ):
                    continue
            try:
                sources.require(actor, source.id, purpose=demand.purpose)
            except BusinessError as error:
                if error.code != "source_not_current":
                    raise
                continue
            eligible.append(source.id)
        if preferred_only and not eligible and not catalog:
            return False
        if not (preferred_only or examples) and workflow.public_sources_in(
            connection, actor, demand,
        ):
            from leornian.modules.knowledge.retrieval import terms
            from leornian.modules.knowledge.source_candidates import (
                DiscoveredSourceCatalog,
                candidate_url,
            )

            wanted = workflow.topic_terms(missing)
            structures = connection.execute(
                "SELECT o.request_identity->'source_structure' AS structure "
                "FROM knowledge.material_source_resources r JOIN knowledge.source_observations o "
                "ON o.id=r.last_observation_id WHERE r.source_id=ANY(%s::uuid[])", (eligible,),
            ).fetchall()
            chapters = [
                item for origin in structures for item in (origin["structure"] or {}).get(
                    "chapter_candidates", [],
                ) if (origin["structure"] or {}).get("role") == "directory"
                and wanted & set(terms(item["title"]))
            ]
            chapters.sort(key=lambda item: -len(
                wanted & set(terms(item["title"] + " " + item["url"])),
            ))
            for item in chapters[:4]:
                try:
                    candidate_url(item["url"])
                except BusinessError:
                    continue
                # Outside-prefix links are only candidates: their own grant precedes any GET.
                DiscoveredSourceCatalog(connection).remember(actor, row["id"], item, demand)
            if chapters:
                catalog = workflow.catalog_in(connection, actor, demand, missing=missing)
        _root, budget, family = self.budget(connection, actor, row)
        observations = connection.execute(
            "SELECT DISTINCT o.*,j.state AS job_state,j.reason_code AS job_reason,j.issues "
            "FROM knowledge.material_source_check_commands c "
            "JOIN knowledge.source_observations chosen ON chosen.id=c.observation_id "
            "JOIN knowledge.source_observations o ON o.resource_id=chosen.resource_id "
            "LEFT JOIN knowledge.material_jobs j ON j.id=o.job_id "
            "WHERE c.command_key LIKE ANY(%s) "
            "AND NOT EXISTS(SELECT 1 FROM knowledge.source_observations newer "
            "WHERE newer.resource_id=o.resource_id AND newer.created_at>o.created_at)",
            ([f"discovery:{item['id']}:shallow-v1:%" for item in family],),
        ).fetchall()
        for item in observations:
            # Historical direct GET failures can be skipped without rewriting their receipts.
            failed_public_read = (
                item["error_code"] == "source_read_unknown"
                and item["request_identity"].get("acquisition_provider", "direct") == "direct"
                and item["recorded_at"] is None and item["job_id"] is None
            )
            if item["job_state"] == "blocked_unknown" or (
                item["status"] == "blocked_unknown" and not failed_public_read
            ):
                workflow.transition(
                    connection, row["id"], "blocked_unknown",
                    item["job_reason"] or item["error_code"] or "external_result_unknown",
                    missing=missing,
                )
                return True
        pending = [
            item for item in observations
            if item["status"] in {
                "queued", "fetching", "processing", "waiting_config", "waiting_dependency",
            }
            and item["error_code"] not in REPLACEABLE and item["job_reason"] not in REPLACEABLE
        ]
        if pending:
            blocked = next((item for item in pending if (
                item["status"] == "waiting_config" or item["job_state"] == "waiting_config"
            )), None)
            workflow.transition(
                connection, row["id"], "waiting_config" if blocked else "queued",
                (blocked["job_reason"] or blocked["error_code"]) if blocked
                else "source_preparation_pending", missing=missing,
            )
            return True
        reads = {item["resource_id"]: item for item in observations}
        patterns = [f"discovery:{item['id']}:shallow-v1:%" for item in family]
        usage = connection.execute(
            "SELECT count(DISTINCT o.id) FILTER (WHERE o.dispatched_at IS NOT NULL "
            "AND o.command_key LIKE ANY(%s)) AS fetched_observations,"
            "count(DISTINCT o.id) FILTER (WHERE o.request_identity ? 'reused_observation_id' "
            "OR NOT o.command_key LIKE ANY(%s)) AS reused_observations "
            "FROM knowledge.material_source_check_commands c "
            "JOIN knowledge.source_observations o ON o.id=c.observation_id "
            "WHERE c.command_key LIKE ANY(%s)",
            (patterns, patterns, patterns),
        ).fetchone()
        state = {
            **(row.get("acquisition_state") or {}),
            "usage": {"selected_resources": len(reads), **usage},
        }
        row["acquisition_state"] = state
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
            (Jsonb(state), row["id"]),
        )
        wanted = workflow.topic_terms(missing)
        source_reads = Counter(item["source_id"] for item in reads.values())
        resources = connection.execute(
            "SELECT r.*,s.catalog_id,s.specification->>'entry_url' AS entry_url "
            "FROM knowledge.material_source_resources r "
            "JOIN knowledge.material_source_registrations s ON s.id=r.source_id "
            "WHERE r.source_id=ANY(%s::uuid[]) AND r.depth<=%s AND (NOT EXISTS("
            "SELECT 1 FROM knowledge.source_observations o WHERE o.resource_id=r.id "
            "AND (o.status<>'cancelled' OR "
            "o.error_code IS DISTINCT FROM 'source_depth_not_selected')) OR EXISTS("
            "SELECT 1 FROM knowledge.source_observations o "
            "JOIN knowledge.material_jobs j ON j.id=o.job_id "
            "WHERE o.resource_id=r.id AND j.background_deferred "
            "AND j.state NOT IN ('ready','cancelled','blocked_unknown')) OR (EXISTS("
            "SELECT 1 FROM knowledge.document_versions v WHERE v.document_id=r.document_id "
            "AND v.revision=r.document_revision AND v.format='pdf') AND NOT EXISTS("
            "SELECT 1 FROM knowledge.material_source_check_commands c "
            "JOIN knowledge.source_observations o ON o.id=c.observation_id "
            "WHERE o.resource_id=r.id AND c.command_key LIKE %s)) OR EXISTS("
            "SELECT 1 FROM knowledge.document_versions v WHERE v.document_id=r.document_id "
            "AND v.revision=r.document_revision AND v.format='html' AND v.parser_version<>%s))",
            (eligible, MAX_GAP_SOURCE_DEPTH, f"discovery:{row['id']}:shallow-v1:%",
             HTML_MAIN_PARSER_VERSION),
        ).fetchall()
        from leornian.modules.knowledge.retrieval import terms

        example_hits = set(state.get("node_example_lookup", {}).get("hits", [])) if examples else ()
        resources = [
            item for item in resources
            if (item["url"] in example_hits or workflow.relevant_resource(item, wanted))
            and source_reads[item["source_id"]] < MAX_SOURCE_READS
            and (item["url"] in example_hits or item["url"] in curriculum_urls or item["depth"] == 0
                 or wanted & set(terms(item["url"] + " " + item["link_label"])))
        ]
        if examples:
            readable = {
                item["request_identity"]["url"] for item in observations
                if item["status"] in {"changed", "unchanged", "noise_only"} and item["document_id"]
            }
            self.example_source(connection, actor, row, demand, eligible, missing, resources,
                                curriculum_urls, registered, len(reads), budget, readable)
            return
        resources = [
            item for item in resources if item["url"] in curriculum_urls or material_matches_gaps(
                item["url"] + " " + item["link_label"], missing,
                goal_text=demand.goal_text or "",
            )
        ]
        catalog = [
            item for item in catalog if item[1].entry_url in preferred or material_matches_gaps(
                " ".join([item[1].title, item[1].entry_url, *item[1].topics]), missing,
                goal_text=demand.goal_text or "",
            )
        ]
        resources.sort(key=lambda item: (
                item["url"] not in curriculum_urls, item["depth"] == 0 and item["url"] in preferred,
                -len(set(terms(item["url"] + " " + item["link_label"])) & wanted),
                item["depth"], item["link_order"], item["url"],
        ))
        known_urls = {source.entry_url for source in registered}
        # Register only the chosen entry: the background source scanner must not fetch a shortlist.
        candidate = next((
            item for item in catalog if item[1].entry_url not in known_urls
        ), None)
        if preferred_only:
            if len(reads) >= min(MAX_SOURCE_READS, budget.get("read_limit", MAX_RESOURCE_READS)):
                return False
            resource = next((
                item for item in resources if (not chapter_urls or item["url"] in chapter_urls)
                and (item["url"] in preferred or item["url"] in curriculum_urls)
            ), None)
            if resource:
                self.schedule(connection, actor, row, demand, resource, missing)
                return True
            return False if chapter_urls else self.schedule_candidate(
                connection, actor, row, demand, candidate, missing,
            )
        discovered = next((
            item for item in catalog if item[0].startswith("discovered:")
            and item[1].entry_url not in known_urls
        ), None)
        if len(reads) >= budget.get("read_limit", MAX_RESOURCE_READS):
            renewed = self.extend(
                connection, actor, row, len(reads),
                new_candidate=bool(candidate or resources),
            )
            if renewed is None:
                self.exhausted(connection, row, missing)
                return
        if resources and resources[0]["url"] in curriculum_urls:
            self.schedule(connection, actor, row, demand, resources[0], missing)
            return
        state = row.get("acquisition_state") or {}
        if len(reads) >= CATALOG_RESOURCE_READS:
            public_resources = [
                item for item in resources if (item["catalog_id"] or "").startswith("discovered:")
            ]
            # Retained discoveries must not suppress the first search for a new gap.
            if (
                not state.get("search_rounds") or not (discovered or public_resources)
            ) and self.search(connection, actor, row, demand, eligible, missing, len(reads)):
                return
            if discovered:
                candidate, resources = discovered, public_resources
            elif public_resources:
                resources, candidate = public_resources, None
        resource = resources[0] if resources else None
        candidate_score = (
            len(wanted & set(terms(" ".join([
                candidate[1].title, candidate[1].entry_url, *candidate[1].topics,
            ])))) if candidate else -1
        )
        resource_score = (
            len(wanted & set(terms(resource["url"] + " " + resource["link_label"])))
            if resource else -1
        )
        if resource and resource_score >= candidate_score:
            self.schedule(connection, actor, row, demand, resource, missing)
            return
        if candidate:
            if not self.schedule_candidate(connection, actor, row, demand, candidate, missing):
                self.exhausted(connection, row, missing)
            return
        if resource:
            self.schedule(connection, actor, row, demand, resource, missing)
            return
        if self.search(connection, actor, row, demand, eligible, missing, len(reads)):
            return
        self.exhausted(connection, row, missing)

    def example_source(self, connection, actor, row, demand, eligible, missing, resources,
                       curriculum_urls, registered, used, budget, readable_urls):
        from leornian.modules.knowledge.source_candidates import candidate_source
        from leornian.modules.knowledge.stage_sections import topic_words

        state = row["acquisition_state"]
        lookup = state["node_example_lookup"]
        attempted = lookup["attempted"]
        remaining = lookup.get("remaining", missing)

        def save():
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
                (Jsonb(state), row["id"]),
            )

        now = datetime.now(UTC)
        readable = sorted(set(lookup.get("readable", ())) | set(lookup.get("reviewed", ()))
                          | (set(attempted) & readable_urls))
        if "deadline_at" not in lookup or lookup.get("readable") != readable:
            lookup.setdefault("deadline_at", (now + EXAMPLE_LOOKUP_WINDOW).isoformat())
            lookup["readable"] = readable
            save()
        if (len(readable) >= MAX_EXAMPLE_PAGES
                or used >= budget.get("read_limit", MAX_RESOURCE_READS)
                or now >= datetime.fromisoformat(lookup["deadline_at"])):
            self.exhausted(connection, row, remaining)
            return
        choices = {item["url"]: item for item in resources if item["url"] not in attempted}
        if not attempted:
            wanted = topic_words(" ".join(missing))
            chapters = [(len(wanted & topic_words(item["link_label"])), item)
                        for url, item in choices.items()
                        if url in curriculum_urls and item["depth"]]
            chapter = max(chapters, key=lambda pair: (pair[0], -pair[1]["link_order"]),
                          default=None)
            if chapter and chapter[0]:
                attempted.append(chapter[1]["url"])
                save()
                self.schedule(connection, actor, row, demand, chapter[1], missing)
                return
        if not lookup.get("searched"):
            lookup["searched"] = True
            save()
            if self.search(connection, actor, row, demand, eligible, missing, used, examples=True):
                return
        known = {source.entry_url for source in registered}
        hits = [url for url in lookup.get("hits", []) if url not in attempted]
        public = {}
        if hits and self.workflow.public_sources_in(connection, actor, demand):
            public = {item["url"]: item["metadata"] for item in connection.execute(
                "SELECT url,metadata FROM knowledge.discovered_source_catalog "
                "WHERE actor_id=%s AND discovery_id=%s AND url=ANY(%s)",
                (actor.id, row["id"], hits),
            ).fetchall()}
        for url in hits:
            if url in choices:
                attempted.append(url)
                save()
                self.schedule(connection, actor, row, demand, choices[url], missing)
                return
            if url in public and url not in known:
                entry = public[url]
                attempted.append(url)
                save()
                if self.schedule_candidate(connection, actor, row, demand, (
                    entry["id"], candidate_source(demand, entry),
                ), missing):
                    return
        self.exhausted(connection, row, remaining)

    def schedule_candidate(self, connection, actor, row, demand, candidate, missing):
        if candidate is None:
            return False
        catalog_id, data = candidate
        basis = (
            "public_discovery" if catalog_id.startswith("discovered:")
            else "learning_catalog" if catalog_id.startswith("resource:") else None
        )
        key = (
            f"learning-catalog:{demand.id}:{catalog_id}:" + identity(data.model_dump(mode="json"))
            if basis else f"{CATALOG_VERSION}:{demand.id}:{catalog_id}"
        )
        source = MaterialSources(connection).register(
            actor, row["session_digest"], key, data, catalog_id=catalog_id, basis=basis,
        )
        if source.admission != "allowed":
            return False
        resource = connection.execute(
            "SELECT * FROM knowledge.material_source_resources WHERE source_id=%s AND url=%s",
            (source.id, source.entry_url),
        ).fetchone()
        self.schedule(connection, actor, row, demand, resource, missing)
        return True

    def schedule(self, connection, actor, row, demand, resource, missing):
        MaterialSources(connection).schedule(
            actor, resource["source_id"], row["session_digest"],
            f"discovery:{row['id']}:shallow-v1:{resource['id']}",
            resource_id=resource["id"],
            # Freeze the selection scope for all automatic reads, including first-hop chapters.
            missing_topics=missing,
        )
        self.workflow.transition(
            connection, row["id"], "queued", "approved_source_fetch_pending", missing=missing,
        )

    def exhausted(self, connection, row, missing):
        state = {**(row.get("acquisition_state") or {}), "exhausted": True}
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
            (Jsonb(state), row["id"]),
        )
        self.workflow.transition(
            connection, row["id"], "waiting_dependency", "material_discovery_exhausted",
            missing=missing,
        )
