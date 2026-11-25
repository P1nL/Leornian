import base64
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_calls import consume_material_call, prepare_material_call
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.file_parser import extract_file
from leornian.modules.knowledge.file_store import OriginalFileStore
from leornian.modules.knowledge.files import MaterialFiles
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.retrieval import Retrieval
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


class MaterialProcessingWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def current(self, connection, actor, job_id, lease=None):
        row = connection.execute(
            "SELECT * FROM knowledge.material_jobs WHERE id=%s AND actor_id=%s FOR UPDATE",
            (job_id, actor.id),
        ).fetchone()
        if not row or row["state"] in {"ready", "cancelled"}:
            raise BusinessError("precondition_failed", "Material preparation is not active.")
        if lease and (row["lease_token"] != lease or row["lease_until"] <= datetime.now(UTC)):
            raise BusinessError("lease_lost", "Material worker lease expired.")
        demand = MaterialIntake(connection).demand(actor, row["demand_id"])
        MaterialIntakeWorkflow.require_scope(connection, actor, demand)
        if demand.revision != row["demand_revision"] or demand.status == "cancelled":
            raise BusinessError("stale_version", "Material demand changed.")
        Materials(connection).require_use(
            actor,
            row["document_id"],
            row["document_revision"],
            demand.purpose,
            goal_id=demand.goal_id,
        )
        return row, demand

    def operation(self, connection, actor, row, purpose, part, *, renew_lease=True, **inputs):
        # A part with a dispatched/unknown receipt is never replaced after a key rotation.
        previous = connection.execute(
            "SELECT id FROM knowledge.material_operations WHERE job_id=%s AND purpose=%s "
            "AND part=%s AND NOT retired ORDER BY created_at LIMIT 1",
            (row["id"], purpose, part),
        ).fetchone()
        if previous:
            operation_id = previous["id"]
        else:
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
                "INSERT INTO knowledge.material_operations(id,job_id,purpose,part,binding) "
                "VALUES (%s,%s,%s,%s,%s)",
                (operation_id, row["id"], purpose, part, Jsonb(binding)),
            )
        call = Runs(connection).operation(operation_id)
        if renew_lease:
            connection.execute(
                "UPDATE knowledge.material_jobs SET lease_until=now()+make_interval(secs=>%s) "
                "WHERE id=%s AND state='processing'",
                (call.policy_snapshot["timeout_seconds"] + 60, row["id"]),
            )
        return operation_id

    def execute(self, job_id, transport=None):
        lease = None
        try:
            with self.database.transaction() as connection:
                seed = connection.execute(
                    "SELECT session_digest FROM knowledge.material_jobs WHERE id=%s", (job_id,)
                ).fetchone()
                if not seed:
                    return
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True)
                ).authenticate_digest(seed["session_digest"])
                row, _demand = self.current(connection, actor, job_id)
                if row["state"] == "processing" and row["lease_until"] > datetime.now(UTC):
                    return
                lease = uuid4()
                MaterialIntake(connection).transition(
                    job_id,
                    "processing",
                    row["phase"],
                    issues=row["issues"],
                    lease=lease,
                )
            if row["phase"] == "ocr":
                self.ocr(actor, row, lease, transport)
            elif row["issues"]:
                from leornian.bootstrap.material_repairs import MaterialRepairWorkflow

                MaterialRepairWorkflow(self.database, self.settings).execute(actor, row, lease)
            else:
                self.index(actor, row, lease, transport)
        except (BusinessError, ModelProtocolError) as error:
            with self.database.transaction() as connection:
                row = connection.execute(
                    "SELECT state,phase,issues,lease_token FROM knowledge.material_jobs "
                    "WHERE id=%s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if not row or (lease is not None and row["lease_token"] != lease):
                    return
                if row["state"] in {"cancelled", "ready"}:
                    return
                state = (
                    "waiting_config"
                    if error.code == "model_unavailable"
                    else "blocked_unknown"
                    if error.code == "external_result_unknown"
                    else "waiting_dependency"
                )
                MaterialIntake(connection).transition(
                    job_id,
                    state,
                    row["phase"],
                    reason=error.code,
                    issues=row["issues"],
                )
                connection.execute(
                    "UPDATE knowledge.material_jobs SET next_run_at=now()+interval '30 seconds' "
                    "WHERE id=%s",
                    (job_id,),
                )

    def index(self, actor, row, lease, transport):
        def guard(connection, owner):
            return self.current(connection, owner, row["id"], lease)

        with self.database.transaction() as connection:
            current, demand = guard(connection, actor)
            retrieval = Retrieval(connection)
            lexical = retrieval.build(
                actor, current, {"mode": "lexical", "preprocessing": "exact-chars.v1"}
            )
            connection.execute(
                "UPDATE knowledge.material_index_builds SET state='indexed' WHERE id=%s",
                (lexical["id"],),
            )
        chunks = []
        build = lexical
        with self.database.transaction() as connection:
            current, demand = guard(connection, actor)
            if demand.index_mode != "lexical":
                models = UserModels(connection, self.settings)
                binding = models.binding(actor, "embedding")
                profile = models.profile(actor, binding["profile_id"])
                space = {key: binding[key] for key in ("model", "protocol", "base_url", "region")}
                space.update(
                    dimensions=profile.embedding_dimensions, preprocessing="exact-chars.v1",
                )
                retrieval = Retrieval(connection)
                build = retrieval.build(actor, current, space)
                chunks = retrieval.pending(build["id"])
            if chunks:
                operation_id = self.operation(
                    connection,
                    actor,
                    current,
                    "embedding",
                    str(build["id"]) + ":" + str(chunks[0]["id"]),
                    texts=[c["text"] for c in chunks],
                )
        if chunks:
            vectors, call = consume_material_call(
                self.database, self.settings, operation_id, row["session_digest"], guard, transport
            )
            with self.database.transaction() as connection:
                guard(connection, actor)
                Retrieval(connection).embed(build["id"], chunks, vectors)
                Runs(connection).applied(call.id)
                MaterialIntake(connection).transition(
                    row["id"], "waiting_dependency", "indexing", reason="indexing_pending"
                )
            return
        if demand.scope_mode == "teaching_goal":
            self.semantic_validation(actor, row, lease)
            return
        with self.database.transaction() as connection:
            current, demand = guard(connection, actor)
            retrieval = Retrieval(connection)
            if demand.scope_mode == "whole_source":
                version = Materials(connection).require_use(
                    actor,
                    current["document_id"],
                    current["document_revision"],
                    demand.purpose,
                    goal_id=demand.goal_id,
                )
                counts = connection.execute(
                    "SELECT count(*) AS blocks,COALESCE(sum(length(text)),0) AS characters "
                    "FROM knowledge.document_blocks WHERE document_id=%s AND document_revision=%s",
                    (version.document_id, version.revision),
                ).fetchone()
                indexed = connection.execute(
                    "SELECT COALESCE(sum(span_end-span_start),0) AS characters "
                    "FROM knowledge.material_chunks WHERE build_id=%s "
                    "AND (%s OR embedding IS NOT NULL)",
                    (build["id"], demand.index_mode == "lexical"),
                ).fetchone()
                if not counts["blocks"] or counts["characters"] != indexed["characters"]:
                    raise BusinessError(
                        "material_quality_pending", "Whole-source index is incomplete."
                    )
                frozen = {
                    "basis": (
                        "selected-source-text.v1"
                        if Materials.permits_partial_text(current, version)
                        else "whole-source-index.v1"
                    ),
                    "document_id": str(version.document_id),
                    "document_revision": version.revision,
                    "content_digest": version.content_digest,
                    "block_count": counts["blocks"],
                    "indexed_characters": counts["characters"],
                }
                if current["prepared_scope"] and current["prepared_scope"] != frozen:
                    raise BusinessError("stale_version", "Whole-source input scope changed.")
                connection.execute(
                    "UPDATE knowledge.material_jobs SET prepared_scope=%s WHERE id=%s",
                    (Jsonb(frozen), row["id"]),
                )
                MaterialIntake(connection).transition(row["id"], "ready", "validating")
                connection.execute(
                    "UPDATE knowledge.material_demands SET status='ready' WHERE id=%s",
                    (demand.id,),
                )
                return
            rows = retrieval.candidates([build], " ".join(demand.required_facets))
            selected = retrieval.select(
                actor,
                demand,
                " ".join(demand.required_facets),
                "lexical",
                rows,
                {"build_ids": [str(build["id"])], "validation": True},
            )
            ready = selected.coverage.status == "sufficient"
            MaterialIntake(connection).transition(
                row["id"],
                "ready" if ready else "waiting_dependency",
                "validating",
                reason=None if ready else "coverage_gap",
                issues=selected.coverage.missing_facets,
            )
            if ready:
                connection.execute(
                    "UPDATE knowledge.material_demands SET status='ready' WHERE id=%s",
                    (demand.id,),
                )

    def semantic_validation(self, actor, row, lease):
        from leornian.bootstrap.material_search import MaterialSearchWorkflow
        from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput

        with self.database.transaction() as connection:
            current, demand = self.current(connection, actor, row["id"], lease)
            request = MaterialSearchInput(
                demand_id=demand.id,
                expected_demand_revision=demand.revision,
                query=demand.goal_text[:4000],
                mode=demand.index_mode,
                document_id=current["document_id"],
                document_revision=current["document_revision"],
            )
        search = MaterialSearchWorkflow(self.database, self.settings).submit_digest(
            row["session_digest"], "material-job-goal:" + str(row["id"]), request
        )
        with self.database.transaction() as connection:
            current, demand = self.current(connection, actor, row["id"], lease)
            sufficient = False
            if search.status == "ready":
                selection = Retrieval(connection).selection(actor, search.selection_id)
                sufficient = selection.coverage.status == "sufficient"
            state = (
                "ready"
                if sufficient
                else search.status
                if search.status in {"waiting_config", "blocked_unknown"}
                else "waiting_dependency"
            )
            MaterialIntake(connection).transition(
                row["id"],
                state,
                "validating",
                reason=None
                if sufficient
                else "semantic_material_coverage_gap"
                if search.status == "ready"
                else search.error_code or "semantic_coverage_pending",
            )
            if sufficient:
                connection.execute(
                    "UPDATE knowledge.material_demands SET status='ready' WHERE id=%s",
                    (demand.id,),
                )

    def ocr(self, actor, row, lease, transport):
        def guard(connection, owner):
            return self.current(connection, owner, row["id"], lease)

        with self.database.transaction() as connection:
            current, _demand = guard(connection, actor)
            version = Materials(connection).require_use(
                actor, current["document_id"], current["document_revision"], "indexing"
            )
            upload = MaterialFiles(connection).row(actor, row["upload_id"])
            store = OriginalFileStore(self.settings.material_storage_dir)
            content = store.read(actor.id, upload["id"])
            store.check(content, upload["content_digest"], upload["byte_size"])
            page_numbers = [p.number for p in version.pages if p.requires_ocr]
            previous = connection.execute(
                "SELECT id,part FROM knowledge.material_operations WHERE job_id=%s "
                "AND purpose='ocr' ORDER BY part",
                (row["id"],),
            ).fetchall()
            finished = {
                int(op["part"]): Runs(connection).operation(op["id"])
                for op in previous
                if Runs(connection).operation(op["id"]).applied
            }
        page_number = next((p for p in page_numbers if p not in finished), None)
        if page_number is not None:
            page = next(p for p in version.pages if p.number == page_number)
            if version.format == "docx":
                mode = f"docx-image:{page_number}"
            elif version.format in {"png", "jpeg"}:
                mode = f"image-region:{page_number}"
                if page.region is not None:
                    mode += ":" + ":".join(map(str, page.region))
            else:
                mode = f"pdf-page:{page_number}"
            image = base64.b64decode(extract_file(content, mode)["image"])
            with self.database.transaction() as connection:
                current, _ = guard(connection, actor)
                operation_id = self.operation(
                    connection,
                    actor,
                    current,
                    "ocr",
                    str(page_number),
                    image=image,
                )
            _text, call = consume_material_call(
                self.database,
                self.settings,
                operation_id,
                row["session_digest"],
                guard,
                transport,
            )
            with self.database.transaction() as connection:
                guard(connection, actor)
                Runs(connection).applied(call.id)
                MaterialIntake(connection).transition(
                    row["id"],
                    "waiting_dependency",
                    "ocr",
                    reason="ocr_pages_pending",
                    issues=row["issues"],
                )
            return
        from leornian.platform.material_models import MaterialModelGateway
        from leornian.platform.models import MaterialProbeConfiguration

        texts = {}
        for number, call in finished.items():
            gateway = MaterialModelGateway(
                MaterialProbeConfiguration(**call.context_manifest["configuration"], api_key="")
            )
            texts[number] = gateway.result(call.response_body, call.request)
        with self.database.transaction() as connection:
            guard(connection, actor)
            derived = Materials(connection).import_ocr(actor, version, texts)
            MaterialIntake(connection).transition(
                row["id"],
                "waiting_dependency",
                "indexing",
                reason="indexing_pending",
                document=derived,
            )
