from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.file_parser import extract_file
from leornian.modules.knowledge.file_store import OriginalFileStore
from leornian.modules.knowledge.files import MaterialFiles
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.material_contracts import TextMaterialImport
from leornian.modules.knowledge.materials import Materials, parse_blocks
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.learning.application import Learning
from leornian.modules.learning.infrastructure import PgGoalStore
from leornian.modules.learning.materials import MaterialBindings
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


class MaterialIntakeWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    @staticmethod
    def require_scope(connection, actor, data):
        Learning(PgGoalStore(connection)).get_goal(actor, data.goal_id)
        MaterialBindings(connection).require_scope(actor, data)

    def create_demand(self, token, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            previous = MaterialIntake(connection).replay_demand(actor, key, data)
            if previous:
                return previous
            self.require_scope(connection, actor, data)
            demand = MaterialIntake(connection).create_demand(actor, key, data)
            from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

            MaterialDiscoveryWorkflow.ensure_in(connection, actor, Identity.digest(token), demand)
            return demand

    def demands(self, token, goal_id, before=None, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            Learning(PgGoalStore(connection)).get_goal(actor, goal_id)
            return MaterialIntake(connection).demands(actor, goal_id, before=before, limit=limit)

    def demand(self, token, demand_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return MaterialIntake(connection).demand(actor, demand_id)

    def demand_receipt(self, token, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = connection.execute(
                "SELECT demand_id FROM knowledge.material_demand_commands "
                "WHERE actor_id=%s AND command_key=%s", (actor.id, key),
            ).fetchone()
            if not row:
                raise BusinessError("not_found", "Material demand command not found.")
            return MaterialIntake(connection).demand(actor, row["demand_id"])

    def file_receipt(self, token, demand_id, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = connection.execute(
                "SELECT job_id,request FROM knowledge.material_job_commands "
                "WHERE actor_id=%s AND command_key=%s", (actor.id, key),
            ).fetchone()
            if not row or row["request"]["demand_id"] != str(demand_id):
                raise BusinessError("not_found", "Material file command not found.")
            return MaterialIntake(connection).job(actor, row["job_id"])

    def submit_text(self, token, demand_id, key, data):
        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate(token)
            intake = MaterialIntake(connection)
            previous = intake.replay_job(actor, demand_id, key, data)
            if previous:
                return previous
            demand = intake.demand(actor, demand_id)
            self.require_scope(connection, actor, demand)
            return intake.submit_text(actor, identity.digest(token), demand_id, key, data)

    def job(self, token, job_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return MaterialIntake(connection).job(actor, job_id)

    def jobs(self, token, demand_id, before=None, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return MaterialIntake(connection).jobs(actor, demand_id, before=before, limit=limit)

    def cancel(self, token, job_id):
        from leornian.bootstrap.material_files import MaterialFilesWorkflow

        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            job = MaterialIntake(connection).cancel(actor, job_id)
            from leornian.agent_runtime.repository import Runs

            operations = connection.execute(
                "SELECT o.id FROM knowledge.material_operations o "
                "JOIN knowledge.material_jobs j ON j.id=o.job_id WHERE j.root_id=%s "
                "AND j.actor_id=%s", (job.root_id, actor.id),
            ).fetchall()
            Runs(connection).cancel_operations([op["id"] for op in operations])
            if job.upload_id:
                MaterialFilesWorkflow(self.database, self.settings).discard_unconsumed(
                    connection, actor, job.upload_id
                )
            return job

    def cancel_receipt(self, token, job_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            job = MaterialIntake(connection).job(actor, job_id)
            if job.state != "cancelled":
                raise BusinessError("not_found", "Material cancellation has not occurred.")
            return job

    def _claim(self, job_id):
        from leornian.bootstrap.material_files import MaterialFilesWorkflow

        with self.database.transaction() as connection:
            seed = connection.execute(
                "SELECT session_digest FROM knowledge.material_jobs WHERE id=%s",
                (job_id,),
            ).fetchone()
            if not seed:
                return None
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate_digest(seed["session_digest"])
            row = connection.execute(
                "SELECT * FROM knowledge.material_jobs WHERE id=%s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if row["state"] not in {"queued", "parsing"} or (
                row["state"] == "parsing" and row["lease_until"] > datetime.now(UTC)
            ):
                return None
            demand = MaterialIntake(connection).demand(actor, row["demand_id"])
            self.require_scope(connection, actor, demand)
            if demand.revision != row["demand_revision"] or demand.status != "open":
                raise BusinessError("stale_version", "Material demand changed.")
            if row["retain_until"] is not None and row["retain_until"] <= datetime.now(UTC):
                raise BusinessError("source_not_current", "Material retention expired.")
            if row["upload_id"]:
                upload = MaterialFiles(connection).row(actor, row["upload_id"], lock=True)
                MaterialFilesWorkflow.require_input(connection, actor, upload)
                if upload["state"] != "stored":
                    raise BusinessError("source_not_current", "Original upload is not available.")
                row["upload"] = upload
            token = uuid4()
            MaterialIntake(connection).transition(job_id, "parsing", "parsing", lease=token)
            return actor, row, token

    def execute(self, job_id, transport=None):
        from leornian.bootstrap.material_processing import MaterialProcessingWorkflow

        with self.database.transaction() as connection:
            processing = connection.execute(
                "SELECT document_id,state FROM knowledge.material_jobs WHERE id=%s", (job_id,)
            ).fetchone()
            if processing and not MaterialSources(connection).job_selected(job_id):
                MaterialIntake(connection).defer_background(job_id)
                return
        if processing and processing["document_id"] and processing["state"] not in {
            "queued", "parsing", "cancelled", "ready"
        }:
            return MaterialProcessingWorkflow(self.database, self.settings).execute(
                job_id, transport=transport
            )
        lease = None
        try:
            claimed = self._claim(job_id)
            if not claimed:
                return
            owner, row, lease = claimed
            parsed = None
            fallback = False
            if row["upload_id"]:
                upload = row["upload"]
                store = OriginalFileStore(self.settings.material_storage_dir)
                content = store.read(owner.id, upload["id"])
                store.check(content, upload["content_digest"], upload["byte_size"])
                format = upload["specification"]["material"]["format"]
                mode = (
                    "html-main" if format == "html"
                    and upload["specification"].get("extraction_policy")
                    in {"main-content.v1", "task-text.v1"}
                    else format
                )
                if format == "pdf":
                    from leornian.bootstrap.material_parsing import parse_pdf_parts

                    parsed = parse_pdf_parts(self, owner, row, lease, content)
                    if parsed is None:
                        return
                else:
                    parsed = extract_file(content, mode)
            else:
                fields = {
                    k: v
                    for k, v in row["request_identity"]["material"].items()
                    if k != "text_digest"
                }
                material = TextMaterialImport(**fields, text=row["input_text"])
                try:
                    parse_blocks(material.text, material.format == "markdown")
                except BusinessError as error:
                    # Preserve the exact original; an incomplete fence is not corrected into code.
                    if material.format != "markdown" or error.code != "precondition_failed":
                        raise
                    fallback = True
            with self.database.transaction() as connection:
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True)
                ).authenticate_digest(row["session_digest"])
                current = connection.execute(
                    "SELECT * FROM knowledge.material_jobs WHERE id=%s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if (
                    current["state"] != "parsing"
                    or current["lease_token"] != lease
                    or current["lease_until"] <= datetime.now(UTC)
                ):
                    return
                intake = MaterialIntake(connection)
                demand = intake.demand(actor, current["demand_id"])
                self.require_scope(connection, actor, demand)
                if demand.revision != current["demand_revision"] or demand.status != "open":
                    raise BusinessError("stale_version", "Material demand changed.")
                materials = Materials(connection, check_days=self.settings.material_check_days)
                if parsed is not None:
                    self._commit_file(connection, actor, current, parsed, materials, intake)
                    return
                version = materials.import_text(
                    actor, "material-job:" + str(job_id), material, parse_as_text=fallback
                )
                intake.transition(
                    job_id,
                    "waiting_dependency",
                    "checking" if fallback else "indexing",
                    reason="material_quality_review_pending" if fallback else "indexing_pending",
                    issues=["markdown_fence_incomplete"] if fallback else [],
                    document=version,
                    discard_input=True,
                )
        except BusinessError as error:
            self._wait(job_id, error.code, lease)

    def _commit_file(self, connection, actor, current, parsed, materials, intake):
        from leornian.bootstrap.material_files import MaterialFilesWorkflow

        upload = MaterialFiles(connection).row(actor, current["upload_id"], lock=True)
        MaterialFilesWorkflow.require_input(connection, actor, upload)
        if upload["state"] != "stored":
            raise BusinessError("source_not_current", "Original upload is not available.")
        version = materials.import_file(actor, upload, parsed)
        issues = parsed["issues"]
        if (
            upload["source_id"] is not None
            and upload["specification"].get("extraction_policy") == "task-text.v1"
            and issues == ["html_nontext_content_pending"] and parsed["blocks"]
        ):
            connection.execute(
                "UPDATE knowledge.material_jobs SET prepared_scope=%s WHERE id=%s",
                (Jsonb(materials.source_text_scope(version, parsed["blocks"])), current["id"]),
            )
            issues = []
        state, phase, reason = "waiting_dependency", "indexing", "indexing_pending"
        if any(page["requires_ocr"] for page in parsed["pages"]):
            phase, reason = "ocr", "ocr_pipeline_pending"
            try:
                UserModels(connection, self.settings).binding(actor, "ocr", require_private=True)
            except BusinessError as error:
                if error.code != "model_unavailable":
                    raise
                state, reason = "waiting_config", "ocr_configuration_required"
        elif issues:
            phase, reason = "checking", "material_quality_review_pending"
        intake.transition(
            current["id"],
            state,
            phase,
            reason=reason,
            issues=issues,
            document=version,
            discard_input=True,
        )

    def _wait(self, job_id, code, lease):
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT state,phase,lease_token,lease_until "
                "FROM knowledge.material_jobs WHERE id=%s FOR UPDATE",
                (job_id,),
            ).fetchone()
            current_claim = row and (
                (lease is not None and row["lease_token"] == lease)
                or (
                    lease is None
                    and (
                        row["state"] == "queued"
                        or (
                            row["lease_until"] is not None
                            and row["lease_until"] <= datetime.now(UTC)
                        )
                    )
                )
            )
            if current_claim and row["state"] in {"queued", "parsing"}:
                MaterialIntake(connection).transition(
                    job_id,
                    "waiting_dependency",
                    row["phase"],
                    reason=code,
                    discard_input=code in {"unauthorized", "source_not_current"},
                )

    def expire_retained_inputs(self):
        from leornian.bootstrap.material_files import MaterialFilesWorkflow
        from leornian.bootstrap.material_sources import MaterialSourceWorkflow

        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT id,phase FROM knowledge.material_jobs WHERE state<>'cancelled' "
                "AND retain_until<now() ORDER BY retain_until,id LIMIT 50 FOR UPDATE SKIP LOCKED",
            ).fetchall()
            for row in rows:
                MaterialIntake(connection).transition(
                    row["id"],
                    "cancelled",
                    row["phase"],
                    reason="material_retention_expired",
                    discard_input=True,
                )
            count = len(rows)
        count += MaterialFilesWorkflow(self.database, self.settings).expire_retained()
        with self.database.transaction() as connection:
            MaterialSourceWorkflow(self.database, self.settings).purge_retained(connection)
            count += Materials(connection).purge_retained()
            from leornian.agent_runtime.repository import Runs
            from leornian.modules.knowledge.retrieval import Retrieval

            retrieval = Retrieval(connection)
            Runs(connection).forget_run_content(retrieval.purge_goal_coverage())
            Runs(connection).forget_operation_content(retrieval.purge_retained())
        return count
