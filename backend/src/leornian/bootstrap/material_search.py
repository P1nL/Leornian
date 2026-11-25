import json
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_calls import consume_material_call, prepare_material_call
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_processing import MaterialProcessingWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.materials import Materials, digest
from leornian.modules.knowledge.retrieval import Retrieval
from leornian.modules.knowledge.retrieval_contracts import MaterialSearch, MaterialSearchInput
from leornian.modules.learning.materials import MaterialBindings
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


class MaterialSearchWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    @staticmethod
    def public(row):
        return MaterialSearch(**{k: row[k] for k in MaterialSearch.model_fields})

    @staticmethod
    def request(data):
        # Preserve identities of searches submitted before exact-version filtering existed.
        excluded = {"required_refs"} if data.required_refs is None else set()
        if data.source_versions is None:
            excluded.add("source_versions")
        if data.document_id is None:
            excluded.update({"document_id", "document_revision"})
        return data.model_dump(
            mode="json",
            exclude=excluded,
        )

    @staticmethod
    def scope(connection, actor, request):
        demand = MaterialIntake(connection).demand(actor, request.demand_id)
        MaterialIntakeWorkflow.require_scope(connection, actor, demand)
        if demand.revision != request.expected_demand_revision or demand.status == "cancelled":
            raise BusinessError("stale_version", "Material demand changed.")
        if demand.scope_mode == "whole_source":
            if request.document_id is None or request.mode != "lexical":
                raise BusinessError(
                    "precondition_failed", "Whole-source selection needs an exact lexical document."
                )
            prepared = connection.execute(
                "SELECT id FROM knowledge.material_jobs WHERE demand_id=%s AND demand_revision=%s "
                "AND document_id=%s AND document_revision=%s AND state='ready' "
                "AND prepared_scope IS NOT NULL",
                (
                    demand.id,
                    demand.revision,
                    request.document_id,
                    request.document_revision,
                ),
            ).fetchone()
            if not prepared:
                raise BusinessError(
                    "material_index_pending", "Whole-source preparation is incomplete."
                )
        binding = None
        if request.binding_id:
            binding = MaterialBindings(connection).get(actor, request.binding_id, lock=True)
            MaterialBindings(connection).require_scope(actor, binding)
            if binding.revision != request.expected_binding_revision or (
                binding.goal_id,
                binding.purpose,
                binding.plan_id,
                binding.plan_revision,
                binding.node_key,
            ) != (
                demand.goal_id,
                demand.purpose,
                demand.plan_id,
                demand.plan_revision,
                demand.node_key,
            ):
                raise BusinessError("stale_version", "Search needs the exact material binding.")
        builds = Retrieval(connection).scope(actor, demand, binding)
        if request.document_id:
            Materials(connection).require_use(
                actor,
                request.document_id,
                request.document_revision,
                demand.purpose,
                goal_id=demand.goal_id,
            )
            builds = [
                b
                for b in builds
                if (b["document_id"], b["document_revision"])
                == (request.document_id, request.document_revision)
            ]
        if request.required_refs:
            Materials(connection).read_refs(
                actor, demand.goal_id, demand.purpose, request.required_refs
            )
            identities = {(ref.document_id, ref.document_revision) for ref in request.required_refs}
            builds = [
                build
                for build in builds
                if (build["document_id"], build["document_revision"]) in identities
            ]
        if request.source_versions:
            versions = {
                (source.document_id, source.document_revision) for source in request.source_versions
            }
            for document_id, revision in versions:
                Materials(connection).require_use(
                    actor, document_id, revision, demand.purpose, goal_id=demand.goal_id
                )
            builds = [
                build
                for build in builds
                if (build["document_id"], build["document_revision"]) in versions
            ]
        return demand, binding, builds

    @staticmethod
    def submit_in(connection, actor, session_digest, key, data):
        request = MaterialSearchWorkflow.request(data)
        identity = digest(json.dumps(request, sort_keys=True, separators=(",", ":")))
        previous = connection.execute(
            "SELECT * FROM knowledge.material_search_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if previous["request_digest"] != identity:
                raise BusinessError("idempotency_conflict", "Material search key changed.")
            return MaterialSearchWorkflow.get_in(connection, actor, previous["search_id"])
        MaterialSearchWorkflow.scope(connection, actor, data)
        existing = connection.execute(
            "SELECT id FROM knowledge.material_searches WHERE actor_id=%s AND request_digest=%s",
            (actor.id, identity),
        ).fetchone()
        search_id = existing["id"] if existing else uuid4()
        if not existing:
            connection.execute(
                "INSERT INTO knowledge.material_searches"
                "(id,actor_id,session_digest,command_key,request,request_digest) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (search_id, actor.id, session_digest, key, Jsonb(request), identity),
            )
        connection.execute(
            "INSERT INTO knowledge.material_search_commands"
            "(actor_id,command_key,request_digest,search_id) VALUES (%s,%s,%s,%s)",
            (actor.id, key, identity, search_id),
        )
        return MaterialSearchWorkflow.get_in(connection, actor, search_id)

    def submit_digest(self, session_digest, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                session_digest
            )
            return self.submit_in(connection, actor, session_digest, key, data)

    def submit(self, token, key, data):
        with self.database.transaction() as connection:
            auth = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = auth.authenticate(token)
            return self.submit_in(connection, actor, auth.digest(token), key, data)

    @staticmethod
    def get_in(connection, actor, search_id):
        row = connection.execute(
            "SELECT * FROM knowledge.material_searches WHERE id=%s AND actor_id=%s",
            (search_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material search not found.")
        return MaterialSearchWorkflow.public(row)

    def get(self, token, search_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return self.get_in(connection, actor, search_id)

    def selection(self, token, selection_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = connection.execute(
                "SELECT scope FROM knowledge.material_selections WHERE id=%s AND actor_id=%s",
                (selection_id, actor.id),
            ).fetchone()
            if not row:
                raise BusinessError("not_found", "Material selection not found.")
            return Retrieval(connection).selection(actor, selection_id)

    def cancel(self, token, search_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            self.get_in(connection, actor, search_id)
            connection.execute(
                "UPDATE knowledge.material_searches SET status='cancelled',lease_token=NULL,"
                "lease_until=NULL WHERE id=%s",
                (search_id,),
            )
            operations = connection.execute(
                "SELECT id FROM knowledge.material_search_operations WHERE search_id=%s",
                (search_id,),
            ).fetchall()
            Runs(connection).cancel_operations([op["id"] for op in operations])
            parts = connection.execute(
                "UPDATE knowledge.material_goal_coverage_parts SET state='cancelled' "
                "WHERE search_id=%s AND state NOT IN ('reviewed','purged') RETURNING run_id",
                (search_id,),
            ).fetchall()
            for part in parts:
                if part["run_id"]:
                    Runs(connection).cancel(part["run_id"])
            return self.get_in(connection, actor, search_id)

    def current(self, connection, actor, search_id, lease):
        row = connection.execute(
            "SELECT * FROM knowledge.material_searches WHERE id=%s AND actor_id=%s FOR UPDATE",
            (search_id, actor.id),
        ).fetchone()
        if not row or (
            row["status"] != "processing"
            or row["lease_token"] != lease
            or row["lease_until"] <= datetime.now(UTC)
        ):
            raise BusinessError("lease_lost", "Material search is no longer authorized.")
        data = MaterialSearchInput(**row["request"])
        demand, binding, builds = self.scope(connection, actor, data)
        if row["scope"] is not None:
            frozen = set(row["scope"]["build_ids"])
            builds = [b for b in builds if str(b["id"]) in frozen]
            if len(builds) != len(frozen):
                raise BusinessError("source_not_current", "Material search scope changed.")
            if data.mode == "hybrid" and any(
                b["space"] != self.embedding_space(connection, actor) for b in builds
            ):
                raise BusinessError(
                    "provider_configuration_changed", "Frozen search embedding space changed."
                )
        return row, data, demand, binding, builds

    def operation(self, connection, actor, search_id, purpose, **inputs):
        row = connection.execute(
            "SELECT id FROM knowledge.material_search_operations WHERE search_id=%s "
            "AND purpose=%s AND NOT retired",
            (search_id, purpose),
        ).fetchone()
        if row:
            return row["id"]
        operation_id = uuid4()
        binding = prepare_material_call(
            connection,
            actor,
            operation_id,
            UserModels(connection, self.settings),
            purpose,
            **inputs,
        )
        connection.execute(
            "INSERT INTO knowledge.material_search_operations(id,search_id,purpose,binding) "
            "VALUES (%s,%s,%s,%s)",
            (operation_id, search_id, purpose, Jsonb(binding)),
        )
        return operation_id

    def embedding_space(self, connection, actor):
        models = UserModels(connection, self.settings)
        binding = models.binding(actor, "embedding")
        profile = models.profile(actor, binding["profile_id"])
        return {
            **{k: binding[k] for k in ("model", "protocol", "base_url", "region")},
            "dimensions": profile.embedding_dimensions,
            "preprocessing": "exact-chars.v1",
        }

    def rebuild_batch(self, actor, search_id, lease, space, transport):
        def guard(connection, owner):
            result = self.current(connection, owner, search_id, lease)
            if self.embedding_space(connection, owner) != space:
                raise BusinessError("provider_configuration_changed", "Embedding space changed.")
            return result

        with self.database.transaction() as connection:
            row, _, _, _, builds = guard(connection, actor)
            available = {b["job_id"] for b in builds if b["space"] == space}
            origin = next((b for b in builds if b["job_id"] not in available), None)
            if origin is None:
                connection.execute(
                    "UPDATE knowledge.material_searches SET status='waiting_dependency',"
                    "error_code='index_rebuild_pending',lease_token=NULL,lease_until=NULL "
                    "WHERE id=%s",
                    (search_id,),
                )
                return
            unknown = connection.execute(
                "SELECT c.status,c.dispatched_at + make_interval(secs=>"
                "COALESCE((c.policy_snapshot->>'timeout_seconds')::double precision,3600)+60)"
                ">now() AS active FROM knowledge.material_operations o "
                "JOIN runtime.external_calls c ON c.operation_ref=o.id "
                "WHERE o.job_id=%s AND o.purpose='embedding' "
                "AND c.status IN ('dispatching','unknown') "
                "ORDER BY (c.status='unknown') DESC,active LIMIT 1",
                (origin["job_id"],),
            ).fetchone()
            if unknown:
                raise BusinessError(
                    "index_rebuild_in_progress"
                    if unknown["status"] == "dispatching" and unknown["active"]
                    else "external_result_unknown",
                    "An earlier document embedding is unresolved.",
                )
            retrieval = Retrieval(connection)
            build = retrieval.build(
                actor,
                {
                    "id": origin["job_id"],
                    "document_id": origin["document_id"],
                    "document_revision": origin["document_revision"],
                },
                space,
            )
            chunks = retrieval.pending(build["id"])
            operation_id = (
                MaterialProcessingWorkflow(self.database, self.settings).operation(
                    connection,
                    actor,
                    {"id": origin["job_id"]},
                    "embedding",
                    str(build["id"]) + ":" + str(chunks[0]["id"]),
                    renew_lease=False,
                    texts=[c["text"] for c in chunks],
                )
                if chunks
                else None
            )
        if operation_id:
            vectors, call = consume_material_call(
                self.database, self.settings, operation_id, row["session_digest"], guard, transport
            )
            with self.database.transaction() as connection:
                guard(connection, actor)
                Retrieval(connection).embed(build["id"], chunks, vectors)
                Runs(connection).applied(call.id)
        with self.database.transaction() as connection:
            guard(connection, actor)
            connection.execute(
                "UPDATE knowledge.material_searches SET status='waiting_dependency',"
                "error_code='index_rebuild_pending',lease_token=NULL,lease_until=NULL "
                "WHERE id=%s",
                (search_id,),
            )

    def execute(self, search_id, transport=None):
        lease = None
        try:
            rebuild_space = None
            with self.database.transaction() as connection:
                seed = connection.execute(
                    "SELECT session_digest FROM knowledge.material_searches WHERE id=%s",
                    (search_id,),
                ).fetchone()
                if not seed:
                    return
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True)
                ).authenticate_digest(seed["session_digest"])
                row = connection.execute(
                    "SELECT * FROM knowledge.material_searches WHERE id=%s FOR UPDATE",
                    (search_id,),
                ).fetchone()
                if not row or row["status"] in {"ready", "cancelled"} or (
                    row["error_code"] == "node_material_review_failed"
                ):
                    return
                if row["status"] == "processing" and row["lease_until"] > datetime.now(UTC):
                    return
                lease = uuid4()
                connection.execute(
                    "UPDATE knowledge.material_searches SET status='processing',lease_token=%s,"
                    "lease_until=now()+interval '65 minutes' WHERE id=%s",
                    (lease, search_id),
                )
            with self.database.transaction() as connection:
                _, data, _demand, _binding, builds = self.current(
                    connection, actor, search_id, lease
                )
                if not builds:
                    raise BusinessError("material_index_pending", "No authorized material index.")
                if data.mode == "hybrid":
                    space = self.embedding_space(connection, actor)
                    compatible = [b for b in builds if b["space"] == space]
                    if {b["job_id"] for b in compatible} != {b["job_id"] for b in builds}:
                        if row["scope"] is not None:
                            raise BusinessError(
                                "index_space_mismatch", "A frozen search cannot change its space."
                            )
                        rebuild_space = space
                    builds = compatible
                else:
                    lexical = [b for b in builds if b["space"].get("mode") == "lexical"]
                    builds = lexical or builds
                if rebuild_space is None:
                    connection.execute(
                        "UPDATE knowledge.material_searches SET scope=%s "
                        "WHERE id=%s AND scope IS NULL",
                        (Jsonb({"build_ids": [str(b["id"]) for b in builds]}), search_id),
                    )
            if rebuild_space is not None:
                self.rebuild_batch(actor, search_id, lease, rebuild_space, transport)
                return
            self._retrieve(actor, row, lease, transport)
        except (BusinessError, ModelProtocolError) as error:
            with self.database.transaction() as connection:
                state = (
                    "waiting_config"
                    if error.code == "model_unavailable"
                    else "blocked_unknown"
                    if error.code == "external_result_unknown"
                    else "waiting_dependency"
                )
                connection.execute(
                    "UPDATE knowledge.material_searches SET status=%s,error_code=%s,"
                    "lease_token=NULL,"
                    "lease_until=NULL WHERE id=%s AND status<>'cancelled' "
                    "AND (lease_token=%s OR (%s::uuid IS NULL AND status<>'processing'))",
                    (state, error.code, search_id, lease, lease),
                )

    def _retrieve(self, actor, row, lease, transport):
        search_id = row["id"]

        def guard(connection, owner):
            return self.current(connection, owner, search_id, lease)

        query_vector = None
        with self.database.transaction() as connection:
            current_search, data, demand, binding, builds = guard(connection, actor)
            if demand.scope_mode == "teaching_goal":
                from leornian.bootstrap.material_goal_coverage import MaterialGoalCoverageWorkflow

                # Coverage owns the frozen evidence range, not the ranked search hits.
                MaterialGoalCoverageWorkflow.step(
                    connection,
                    actor,
                    current_search,
                    data,
                    demand,
                    binding,
                    builds,
                    self.settings,
                )
                return
            if (
                data.required_refs is not None and demand.scope_mode != "teaching_goal"
            ) or demand.scope_mode == "whole_source":
                from leornian.modules.knowledge.complete_selection import CompleteMaterialSelection

                current, data, demand, binding, builds = guard(connection, actor)
                CompleteMaterialSelection(connection).step(
                    actor, current, data, demand, binding, builds
                )
                return
            operation_id = (
                self.operation(
                    connection, actor, search_id, "embedding", texts=[data.query], text_type="query"
                )
                if data.mode == "hybrid"
                else None
            )
        if operation_id:
            vectors, call = consume_material_call(
                self.database, self.settings, operation_id, row["session_digest"], guard, transport
            )
            query_vector = vectors[0]
            with self.database.transaction() as connection:
                guard(connection, actor)
                Runs(connection).applied(call.id)
        with self.database.transaction() as connection:
            _, data, demand, binding, builds = guard(connection, actor)
            rows = Retrieval(connection).candidates(
                builds, data.query, vector=query_vector, binding=binding
            )
            rerank = (
                self.operation(
                    connection,
                    actor,
                    search_id,
                    "rerank",
                    texts=[r["text"] for r in rows],
                    query=data.query,
                )
                if rows and data.mode == "hybrid"
                else None
            )
        if rerank:
            order, call = consume_material_call(
                self.database, self.settings, rerank, row["session_digest"], guard, transport
            )
            rows = [rows[i] for i in order]
            with self.database.transaction() as connection:
                guard(connection, actor)
                Runs(connection).applied(call.id)
        with self.database.transaction() as connection:
            current, data, demand, _binding, builds = guard(connection, actor)
            selection = Retrieval(connection).select(
                actor,
                demand,
                data.query,
                data.mode,
                rows,
                {
                    "request": data.model_dump(mode="json"),
                    "build_ids": [str(b["id"]) for b in builds],
                    "semantic_recall_basis": "indexed-parent-chunk.v1"
                    if data.mode == "hybrid" and binding
                    else None,
                },
                planning=demand.consumer_ref.startswith("planning-batch:"),
            )
            connection.execute(
                "UPDATE knowledge.material_searches SET status='ready',selection_id=%s,"
                "error_code=NULL,lease_token=NULL,lease_until=NULL WHERE id=%s",
                (selection.id, search_id),
            )
            if (
                selection.coverage.missing_facets
                and data.binding_id is None
                and data.document_id is None
            ):
                from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

                MaterialDiscoveryWorkflow.ensure_in(
                    connection, actor, row["session_digest"], demand
                )
