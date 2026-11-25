import heapq
import math
import re
from uuid import uuid4, uuid5

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.material_contracts import MaterialRef
from leornian.modules.knowledge.materials import Materials, digest
from leornian.modules.knowledge.retrieval_contracts import (
    MaterialCoverage,
    MaterialEvidence,
    MaterialSelection,
)
from leornian.shared_kernel.errors import BusinessError

CHUNK_CHARS = 1200
CONTEXT_CHARS = 16_000


def terms(text):
    values = re.findall(r"[a-z_][a-z_0-9]*|\d+|[\u4e00-\u9fff]+", text.casefold())
    result = set()
    for value in values:
        if "\u4e00" <= value[0] <= "\u9fff":
            result.update(value[i : i + 2] for i in range(max(1, len(value) - 1)))
        else:
            result.add(value)
    return sorted(result)


def planning_evidence_rows(rows, query):
    """Read introductions and relevant representative text before planning a curriculum."""
    documents = {}
    for row in rows:
        documents.setdefault((row["document_id"], row["document_revision"]), []).append(row)
    wanted = set(terms(query))
    selected = set()
    for parts in documents.values():
        if len(parts) <= 4:
            selected.update(row["id"] for row in parts)
            continue
        selected.add(parts[0]["id"])
        body = next(
            (row for row in parts if row.get("kind") in {"paragraph", "code", "table"}),
            parts[0],
        )
        selected.add(body["id"])
        ranked = sorted(
            parts,
            key=lambda row: (
                -len(wanted & set(terms(" ".join(row["section_path"]) + " " + row["text"]))),
                row["ordinal"], str(row["id"]),
            ),
        )
        selected.update(row["id"] for row in ranked[:2])
    return [row for row in rows if row["id"] in selected]


def ranges(text):
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            newline = text.rfind("\n", start + CHUNK_CHARS // 2, end)
            if newline > start:
                end = newline + 1
        yield start, end
        start = end


def coverage(facets, evidence, *, excluded=0):
    facts = []
    for facet in facets:
        required = set(terms(facet))
        support = [item.ref for item in evidence if required and required <= set(terms(item.text))]
        facts.append(
            {
                "facet": facet,
                "status": "text_supported" if support else "missing",
                "evidence": support,
            }
        )
    missing = [f["facet"] for f in facts if not f["evidence"]]
    return MaterialCoverage(
        status="unavailable"
        if not evidence
        else "sufficient"
        if not missing
        else "partial"
        if len(missing) < len(facets)
        else "insufficient",
        required=facts,
        missing_facets=missing,
        excluded_for_capacity=excluded,
    )


class Retrieval:
    def __init__(self, connection):
        self.connection = connection

    def require_bound_selection(self, actor, goal_id, purpose, ref, binding_id, revision):
        row = self.connection.execute(
            "SELECT scope FROM knowledge.material_selections WHERE id=%s AND actor_id=%s "
            "AND goal_id=%s AND purpose=%s",
            (ref.selection_id, actor.id, goal_id, purpose),
        ).fetchone()
        request = row["scope"].get("request", {}) if row else {}
        if (
            request.get("binding_id") != str(binding_id)
            or request.get("expected_binding_revision") != revision
        ):
            raise BusinessError("source_not_current", "Selected slice has another binding origin.")
        Materials(self.connection).read_refs(actor, goal_id, purpose, [ref])
        return ref

    def require_frozen_selection(self, actor, goal_id, purpose, ref, required_refs):
        row = self.connection.execute(
            "SELECT scope FROM knowledge.material_selections WHERE id=%s AND actor_id=%s "
            "AND goal_id=%s AND purpose=%s",
            (ref.selection_id, actor.id, goal_id, purpose),
        ).fetchone()
        request = row["scope"].get("request", {}) if row else {}

        def key(value):
            return value.model_copy(update={"selection_id": None}).model_dump_json()

        frozen = request.get("required_refs") or []
        if {key(MaterialRef(**value)) for value in frozen} != {
            key(value) for value in required_refs
        } or not frozen:
            raise BusinessError("source_not_current", "Selection has another frozen source scope.")
        Materials(self.connection).read_refs(actor, goal_id, purpose, [ref])
        return ref

    def purge_goal_coverage(self):
        searches = self.connection.execute(
            "UPDATE knowledge.material_searches s SET status='cancelled',"
            "error_code='material_retention_expired',lease_token=NULL,lease_until=NULL "
            "WHERE s.error_code IS DISTINCT FROM 'material_retention_expired' "
            "AND EXISTS (SELECT 1 FROM knowledge.material_goal_coverage_parts part "
            "WHERE part.search_id=s.id) AND EXISTS ("
            "SELECT 1 FROM knowledge.material_index_builds b "
            "JOIN knowledge.document_permissions p ON p.document_id=b.document_id "
            "AND p.document_revision=b.document_revision "
            "WHERE s.scope->'build_ids' @> jsonb_build_array(b.id::text) "
            "AND p.retain_until<now()) RETURNING s.id",
        ).fetchall()
        ids = [search["id"] for search in searches]
        if not ids:
            return []
        runs = self.connection.execute(
            "UPDATE knowledge.material_goal_coverage_parts SET state='purged',result=NULL "
            "WHERE search_id=ANY(%s) RETURNING run_id", (ids,),
        ).fetchall()
        self.connection.execute(
            "UPDATE knowledge.material_selections SET query=NULL,facets='[]',coverage=%s "
            "WHERE scope->'request'->>'demand_id' IN (SELECT request->>'demand_id' "
            "FROM knowledge.material_searches WHERE id=ANY(%s))",
            (
                Jsonb({
                    "status": "unavailable", "basis": "semantic-goal-evidence.v1",
                    "required": [], "missing_facets": [], "semantic_quality": "not_certified",
                    "excluded_for_capacity": 0,
                }),
                ids,
            ),
        )
        return [run["run_id"] for run in runs if run["run_id"]]

    def purge_retained(self):
        from leornian.modules.knowledge.updates import MaterialUpdates

        update_operations = MaterialUpdates(self.connection).purge_retained()
        review_operations = self.connection.execute(
            "UPDATE knowledge.material_change_reviews r SET result=NULL,"
            "status='cancelled',error_code='material_retention_expired',"
            "lease_token=NULL,lease_until=NULL FROM knowledge.material_change_checks c "
            "WHERE r.check_id=c.id AND r.error_code IS DISTINCT FROM "
            "'material_retention_expired' AND EXISTS ("
            "SELECT 1 FROM knowledge.document_permissions p WHERE p.document_id=c.document_id "
            "AND p.document_revision IN (c.baseline_revision,c.candidate_revision) "
            "AND p.retain_until<now()) RETURNING r.operation_id",
        ).fetchall()
        part_operations = self.connection.execute(
            "UPDATE knowledge.material_change_review_parts p SET result=NULL,status='purged' "
            "FROM knowledge.material_change_reviews r WHERE p.review_id=r.id "
            "AND r.error_code='material_retention_expired' AND p.status<>'purged' "
            "RETURNING p.operation_id",
        ).fetchall()
        self.connection.execute(
            "UPDATE knowledge.material_parse_parts p SET parsed=NULL,state='purged' "
            "FROM knowledge.material_uploads u WHERE p.upload_id=u.id "
            "AND u.retain_until<now() AND p.state<>'purged'",
        )
        self.connection.execute(
            "UPDATE knowledge.material_repair_attempts a SET issues='[]' "
            "FROM knowledge.material_jobs j WHERE a.job_id=j.id AND j.retain_until<now()",
        )
        self.connection.execute(
            "UPDATE knowledge.material_selection_parts p SET refs='[]',status='purged' "
            "FROM knowledge.material_searches s WHERE p.search_id=s.id AND s.status='cancelled' "
            "AND s.error_code='material_retention_expired'",
        )
        builds = self.connection.execute(
            "SELECT b.id FROM knowledge.material_index_builds b "
            "JOIN knowledge.document_permissions p ON p.document_id=b.document_id "
            "AND p.document_revision=b.document_revision "
            "WHERE p.retain_until<now() AND b.state<>'purged' FOR UPDATE OF b",
        ).fetchall()
        operations = self.connection.execute(
            "SELECT o.id FROM knowledge.material_operations o "
            "JOIN knowledge.material_jobs j ON j.id=o.job_id WHERE j.retain_until<now()",
        ).fetchall()
        for build in builds:
            self.connection.execute(
                "UPDATE knowledge.material_chunks SET text=NULL,lexemes=NULL,embedding=NULL "
                "WHERE build_id=%s",
                (build["id"],),
            )
            self.connection.execute(
                "UPDATE knowledge.material_index_builds SET state='purged' WHERE id=%s",
                (build["id"],),
            )
            operations.extend(
                self.connection.execute(
                    "SELECT o.id FROM knowledge.material_search_operations o "
                    "JOIN knowledge.material_searches s ON s.id=o.search_id "
                    "WHERE s.scope->'build_ids' @> jsonb_build_array(%s::text)",
                    (str(build["id"]),),
                ).fetchall()
            )
            self.connection.execute(
                "UPDATE knowledge.material_selections SET query=NULL "
                "WHERE scope->'build_ids' @> jsonb_build_array(%s::text)",
                (str(build["id"]),),
            )
        return update_operations + [op["id"] for op in operations] + [
            op["operation_id"] for op in review_operations if op["operation_id"]
        ] + [op["operation_id"] for op in part_operations if op["operation_id"]]

    def build(self, actor, job, space):
        materials = Materials(self.connection)
        version = materials.require_use(
            actor, job["document_id"], job["document_revision"], "indexing"
        )
        if version.processing_state != "parsed" and not materials.permits_partial_text(
            job, version,
        ):
            raise BusinessError("material_quality_pending", "The extracted text needs repair.")
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_index_builds WHERE job_id=%s AND document_id=%s "
            "AND document_revision=%s AND space=%s FOR UPDATE",
            (job["id"], version.document_id, version.revision, Jsonb(space)),
        ).fetchone()
        if row:
            return row
        build_id = uuid4()
        inserted = self.connection.execute(
            "INSERT INTO knowledge.material_index_builds"
            "(id,actor_id,job_id,document_id,document_revision,space) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (job_id,document_id,document_revision,space) DO NOTHING RETURNING id",
            (build_id, actor.id, job["id"], version.document_id, version.revision, Jsonb(space)),
        ).fetchone()
        if not inserted:
            return self.connection.execute(
                "SELECT * FROM knowledge.material_index_builds WHERE job_id=%s AND document_id=%s "
                "AND document_revision=%s AND space=%s FOR UPDATE",
                (job["id"], version.document_id, version.revision, Jsonb(space)),
            ).fetchone()
        after, ordinal = -1, 0
        while True:
            page = materials.blocks(
                actor, version.document_id, version.revision, "indexing", after=after, limit=100
            )
            for block in page.blocks:
                for start, end in ranges(block.text):
                    text = block.text[start:end]
                    self.connection.execute(
                        "INSERT INTO knowledge.material_chunks"
                        "(id,build_id,ordinal,block_id,span_start,span_end,"
                        "content_digest,text,lexemes) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,to_tsvector('simple',%s))",
                        (
                            uuid5(build_id, str(ordinal)),
                            build_id,
                            ordinal,
                            block.id,
                            block.ref.span.start + start,
                            block.ref.span.start + end,
                            digest(text),
                            text,
                            " ".join(terms(text)),
                        ),
                    )
                    ordinal += 1
            if page.next_after is None:
                break
            after = page.next_after
        if ordinal == 0:
            raise BusinessError("material_quality_pending", "No usable text was extracted.")
        if space.get("mode") != "lexical":
            self.reuse_embeddings(actor, build_id, version, space)
        return self.connection.execute(
            "SELECT * FROM knowledge.material_index_builds WHERE id=%s", (build_id,)
        ).fetchone()

    def reuse_embeddings(self, actor, build_id, version, space):
        sources = self.connection.execute(
            "SELECT b.id,b.document_revision FROM knowledge.material_index_builds b "
            "JOIN knowledge.material_jobs j ON j.id=b.job_id "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "WHERE b.actor_id=%s AND b.document_id=%s AND b.document_revision<=%s "
            "AND b.space=%s AND b.state='indexed' AND b.id<>%s "
            "AND j.state<>'cancelled' AND d.status<>'cancelled' "
            "AND j.demand_revision=d.revision ORDER BY b.document_revision DESC,b.id",
            (actor.id, version.document_id, version.revision, Jsonb(space), build_id),
        ).fetchall()
        for source in sources:
            try:
                Materials(self.connection).require_use(
                    actor, version.document_id, source["document_revision"], "indexing",
                    goal_id=version.goal_id,
                )
            except BusinessError as error:
                if error.code != "source_not_current":
                    raise
                continue
            # Copy only exact inputs in the same space; the new chunk keeps its own locator.
            self.connection.execute(
                "UPDATE knowledge.material_chunks target SET embedding=source.embedding,"
                "reused_from_chunk_id=source.id FROM ("
                "SELECT DISTINCT ON (content_digest,text) id,content_digest,text,embedding "
                "FROM knowledge.material_chunks WHERE build_id=%s AND embedding IS NOT NULL "
                "AND text IS NOT NULL ORDER BY content_digest,text,ordinal) source "
                "WHERE target.build_id=%s AND target.embedding IS NULL "
                "AND target.content_digest=source.content_digest AND target.text=source.text",
                (source["id"], build_id),
            )
        if not self.pending(build_id):
            self.connection.execute(
                "UPDATE knowledge.material_index_builds SET state='indexed' WHERE id=%s",
                (build_id,),
            )

    def pending(self, build_id):
        return self.connection.execute(
            "SELECT id,text FROM knowledge.material_chunks WHERE build_id=%s "
            "AND embedding IS NULL ORDER BY ordinal LIMIT 10",
            (build_id,),
        ).fetchall()

    def unaffected_refs(self, builds, findings, *, planning_query=None, chunk_ids=None):
        if chunk_ids == []:
            return []
        rows = self.connection.execute(
            "SELECT c.*,b.document_id,b.document_revision,db.section_path,db.kind "
            "FROM knowledge.material_chunks c "
            "JOIN knowledge.material_index_builds b ON b.id=c.build_id "
            "JOIN knowledge.document_blocks db ON db.id=c.block_id "
            "WHERE b.id=ANY(%s) AND c.text IS NOT NULL "
            + ("AND c.id=ANY(%s::uuid[]) " if chunk_ids is not None else "")
            + "ORDER BY b.document_id,b.document_revision,c.ordinal,c.id",
            ([build["id"] for build in builds], *([chunk_ids] if chunk_ids is not None else [])),
        ).fetchall()
        refs, clean_rows = {}, []
        for row in rows:
            ref = MaterialRef(
                document_id=row["document_id"], document_revision=row["document_revision"],
                block_id=row["block_id"],
                span={"start": row["span_start"], "end": row["span_end"]},
                content_digest=row["content_digest"],
            )
            if not any(finding.affects(ref) for finding in findings):
                refs[row["id"]] = ref
                clean_rows.append(row)
        if planning_query is not None:
            clean_rows = planning_evidence_rows(clean_rows, planning_query)
        return list({
            refs[row["id"]].model_dump_json(): refs[row["id"]] for row in clean_rows
        }.values())

    def embed(self, build_id, chunks, vectors):
        for chunk, vector in zip(chunks, vectors, strict=True):
            norm = math.hypot(*vector)
            self.connection.execute(
                "UPDATE knowledge.material_chunks SET embedding=%s WHERE id=%s AND build_id=%s "
                "AND embedding IS NULL",
                ([v / norm for v in vector], chunk["id"], build_id),
            )
        if not self.pending(build_id):
            self.connection.execute(
                "UPDATE knowledge.material_index_builds SET state='indexed' WHERE id=%s",
                (build_id,),
            )

    def scope(self, actor, demand, binding=None):
        candidates = self.connection.execute(
            "SELECT b.*,v.source_url FROM knowledge.material_index_builds b "
            "JOIN knowledge.material_jobs j ON j.id=b.job_id "
            "JOIN knowledge.material_demands origin ON origin.id=j.demand_id "
            "JOIN knowledge.documents d ON d.id=b.document_id "
            "JOIN knowledge.document_versions v ON v.document_id=b.document_id "
            "AND v.revision=b.document_revision "
            "WHERE b.actor_id=%s AND d.goal_id=%s AND b.state='indexed' "
            "AND j.state<>'cancelled' AND origin.status<>'cancelled' "
            "AND j.demand_revision=origin.revision "
            "ORDER BY b.created_at,b.id",
            (actor.id, demand.goal_id),
        ).fetchall()
        result = []
        for build in candidates:
            if binding and not any(
                (r.document_id, r.document_revision)
                == (build["document_id"], build["document_revision"])
                for r in binding.refs
            ):
                continue
            try:
                Materials(self.connection).require_use(
                    actor,
                    build["document_id"],
                    build["document_revision"],
                    demand.purpose,
                    goal_id=demand.goal_id,
                )
            except BusinessError as error:
                if error.code != "source_not_current":
                    raise
                continue
            result.append(build)
        return result

    def candidates(self, builds, query, *, vector=None, binding=None):
        if not builds:
            return []
        ids = [b["id"] for b in builds]
        query_terms = terms(query)
        tsquery = " | ".join("'" + term + "'" for term in query_terms) or "'__empty__'"
        rows = self.connection.execute(
            "SELECT c.*,b.document_id,b.document_revision,v.title,v.source_url,"
            "db.source_page,db.section_path FROM knowledge.material_chunks c "
            "JOIN knowledge.material_index_builds b ON b.id=c.build_id "
            "JOIN knowledge.document_versions v ON v.document_id=b.document_id "
            "AND v.revision=b.document_revision "
            "JOIN knowledge.document_blocks db ON db.id=c.block_id "
            "WHERE c.build_id=ANY(%s) AND c.text IS NOT NULL "
            "ORDER BY ts_rank(c.lexemes,to_tsquery('simple',%s)) DESC,c.id",
            (ids, tsquery),
        )
        if binding:
            rows = self.bound_ranges(rows, binding.refs)
            if rows:
                ranks = self.connection.execute(
                    "SELECT ordinal,ts_rank(to_tsvector('simple',text),"
                    "to_tsquery('simple',%s)) AS rank FROM unnest(%s::text[]) "
                    "WITH ORDINALITY AS fragments(text,ordinal)",
                    (tsquery, [" ".join(terms(r["text"])) for r in rows]),
                ).fetchall()
                scores = {r["ordinal"] - 1: r["rank"] for r in ranks}
                rows = [
                    row for _, row in sorted(
                        enumerate(rows), key=lambda item: (-scores[item[0]], str(item[1]["id"]))
                    )
                ]
        lexical, semantic, visited = [], [], set()
        if vector:
            norm = math.hypot(*vector)
            vector = [v / norm for v in vector]
        # All authorized rows are visited; top-k limits output, not corpus coverage.
        for row in rows:
            identity = (
                row["document_id"], row["document_revision"], row["block_id"],
                row["span_start"], row["span_end"], row["content_digest"],
            )
            if identity in visited:
                continue
            visited.add(identity)
            if len(lexical) < 40 and set(query_terms) & set(terms(row["text"])):
                lexical.append(row)
            if vector is not None:
                # Semantic recall uses the indexed parent, never a fictitious slice vector.
                value = row["embedding"]
                if value is None or len(value) != len(vector):
                    raise BusinessError("index_space_mismatch", "Embedding space changed.")
                denominator = math.hypot(*value)
                score = sum(a * b for a, b in zip(value, vector, strict=True)) / denominator
                item = (score, str(row["id"]), row)
                if len(semantic) < 40:
                    heapq.heappush(semantic, item)
                elif item[:2] > semantic[0][:2]:
                    heapq.heapreplace(semantic, item)
        semantic = [item[2] for item in sorted(semantic, reverse=True)]
        fused, values = {}, {}
        for sequence in (lexical, semantic):
            for rank, row in enumerate(sequence, 1):
                key = row["id"]
                fused[key] = fused.get(key, 0) + 1 / (60 + rank)
                values[key] = row
        return [values[key] for key in sorted(fused, key=lambda k: (-fused[k], str(k)))]

    @staticmethod
    def bound_ranges(rows, refs):
        by_block = {}
        for ref in refs:
            key = (ref.document_id, ref.document_revision, ref.block_id)
            by_block.setdefault(key, []).append(ref)
        selected = []
        for row in rows:
            key = (row["document_id"], row["document_revision"], row["block_id"])
            for ref in by_block.get(key, []):
                start = max(ref.span.start, row["span_start"])
                end = min(ref.span.end, row["span_end"])
                if start >= end:
                    continue
                text = row["text"][start - row["span_start"]:end - row["span_start"]]
                selected.append({
                    **row,
                    "id": row["id"] if (start, end) == (row["span_start"], row["span_end"])
                    else uuid5(row["id"], f"{start}:{end}"),
                    "span_start": start,
                    "span_end": end,
                    "text": text,
                    "content_digest": digest(text),
                })
        return selected

    @staticmethod
    def evidence(row, selection_id=None):
        return MaterialEvidence(
            ref=MaterialRef(
                document_id=row["document_id"],
                document_revision=row["document_revision"],
                block_id=row["block_id"],
                span={"start": row["span_start"], "end": row["span_end"]},
                content_digest=row["content_digest"],
                selection_id=selection_id,
            ),
            text=row["text"],
            title=row["title"],
            source_url=row["source_url"],
            source_page=row["source_page"],
            section_path=row["section_path"],
        )

    def select(self, actor, demand, query, mode, rows, scope, selection_id=None, *, planning=False):
        selection_id = selection_id or uuid4()
        evidence, remaining, excluded = [], CONTEXT_CHARS, 0
        for row in rows:
            if len(row["text"]) > remaining:
                excluded += 1
                continue
            evidence.append(self.evidence(row, selection_id))
            remaining -= len(row["text"])
        report = coverage(demand.required_facets, evidence, excluded=excluded)
        if planning:
            # This certifies a retrieved batch, not whole-route teaching coverage.
            report = report.model_copy(update={
                "basis": "planning-batch-evidence.v1",
                "status": "sufficient" if evidence else "unavailable",
                "lexical_coverage": report.required,
                "missing_facets": [],
                "synopsis": "\n\n".join(item.text for item in evidence)[:4000] or None,
            })
        self.connection.execute(
            "INSERT INTO knowledge.material_selections"
            "(id,actor_id,goal_id,demand_id,purpose,query,facets,mode,refs,coverage,scope) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                selection_id,
                actor.id,
                demand.goal_id,
                demand.id,
                demand.purpose,
                query,
                Jsonb(demand.required_facets),
                mode,
                Jsonb([item.ref.model_dump(mode="json") for item in evidence]),
                Jsonb(report.model_dump(mode="json")),
                Jsonb(scope),
            ),
        )
        return self.selection(actor, selection_id)

    def reuse_goal_selection(self, actor, demand, binding=None, *, build_ids=None):
        """Reuse an identical checked task, retaining its receipt and exact live source scope."""
        rows = self.connection.execute(
            "SELECT s.*,d.specification AS demand_spec FROM knowledge.material_selections s "
            "JOIN knowledge.material_demands d ON d.id=s.demand_id "
            "WHERE s.actor_id=%s AND s.goal_id=%s AND s.purpose=%s "
            "AND s.coverage->>'status'='sufficient' "
            "AND s.coverage->>'basis' IN "
            "('semantic-goal-evidence.v1','planning-batch-evidence.v1',"
            "'route-planning-evidence.v1') "
            "AND s.scope ? 'coverage_root_id' "
            "AND s.demand_id<>%s ORDER BY s.created_at DESC,s.id LIMIT 20",
            (actor.id, demand.goal_id, demand.purpose, demand.id),
        ).fetchall()
        fields = (
            "goal_text", "language", "language_version", "framework",
            "framework_version", "plan_id", "plan_revision", "node_key",
        )
        target = demand.model_dump(mode="json")
        for row in rows:
            if (
                row["demand_spec"].get("preparation", "complete") == "complete"
            ) != (demand.preparation == "complete"):
                continue
            if any(row["demand_spec"].get(key) != target.get(key) for key in fields):
                continue
            if binding and (
                row["scope"].get("request", {}).get("binding_id") != str(binding.id)
                or row["scope"].get("request", {}).get(
                    "expected_binding_revision",
                ) != binding.revision
            ):
                continue
            try:
                selected = self.selection(actor, row["id"])
            except BusinessError as error:
                if error.code in {"source_not_current", "not_found", "stale_version"}:
                    continue
                raise
            if not selected.evidence:
                continue
            builds = build_ids if build_ids is not None else {
                str(item["id"]) for item in self.scope(actor, demand, binding)
            }
            if not set(row["scope"].get("build_ids", ())) <= builds:
                continue
            selection_id = uuid4()

            def retarget(value, target_id=selection_id):
                if isinstance(value, list):
                    return [retarget(item) for item in value]
                if isinstance(value, dict):
                    return {
                        key: str(target_id) if key == "selection_id" and item else retarget(item)
                        for key, item in value.items()
                    }
                return value

            scope = {
                **row["scope"], "reused_selection_id": str(row["id"]),
                "request": {
                    **row["scope"]["request"], "demand_id": str(demand.id),
                    "expected_demand_revision": demand.revision,
                },
            }
            self.connection.execute(
                "INSERT INTO knowledge.material_selections"
                "(id,actor_id,goal_id,demand_id,purpose,query,facets,mode,refs,coverage,scope) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (selection_id, actor.id, demand.goal_id, demand.id, demand.purpose,
                 row["query"], Jsonb(row["facets"]), row["mode"], Jsonb(retarget(row["refs"])),
                 Jsonb(retarget(row["coverage"])), Jsonb(scope)),
            )
            return self.selection(actor, selection_id)
        return None

    def selection(self, actor, selection_id):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_selections WHERE id=%s AND actor_id=%s",
            (selection_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material selection not found.")
        refs = [MaterialRef(**r) for r in row["refs"]]
        blocks = Materials(self.connection).read_refs(actor, row["goal_id"], row["purpose"], refs)
        evidence = []
        for block in blocks:
            version = Materials(self.connection).version(
                actor, block.ref.document_id, block.ref.document_revision
            )
            evidence.append(
                MaterialEvidence(
                    ref=block.ref,
                    text=block.text,
                    title=version.title,
                    source_url=version.source_url,
                    source_page=block.source_page,
                    section_path=block.section_path,
                )
            )
        return MaterialSelection(
            id=row["id"],
            demand_id=row["demand_id"],
            mode=row["mode"],
            coverage=row["coverage"],
            evidence=evidence,
            created_at=row["created_at"],
        )
