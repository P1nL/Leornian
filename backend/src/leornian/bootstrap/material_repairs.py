from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.file_parser import HTML_MAIN_PARSER_VERSION, extract_file
from leornian.modules.knowledge.file_store import OriginalFileStore
from leornian.modules.knowledge.files import MaterialFiles
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.materials import Materials
from leornian.shared_kernel.errors import BusinessError


class MaterialRepairWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    def execute(self, actor, job, lease):
        from leornian.bootstrap.material_processing import MaterialProcessingWorkflow

        processing = MaterialProcessingWorkflow(self.database, self.settings)
        with self.database.transaction() as connection:
            current, demand = processing.current(connection, actor, job["id"], lease)
            version = Materials(connection).version(
                actor, current["document_id"], current["document_revision"]
            )
            strategy = (
                HTML_MAIN_PARSER_VERSION
                if version.format == "html"
                and version.parser_version != HTML_MAIN_PARSER_VERSION
                and current["upload_id"]
                else "approved-source-replacement.v1"
            )
            identity = f"{version.document_id}:{version.revision}:{version.content_digest}"
            attempt = connection.execute(
                "SELECT * FROM knowledge.material_repair_attempts "
                "WHERE job_id=%s AND input_identity=%s AND strategy=%s",
                (job["id"], identity, strategy),
            ).fetchone()
            if attempt and attempt["state"] in {"waiting", "applied", "superseded"}:
                if not attempt["replacement_discovery_id"] and strategy != HTML_MAIN_PARSER_VERSION:
                    self.replacement(connection, actor, current, demand, attempt["id"])
                    return
                raise BusinessError(
                    "material_quality_pending",
                    "The recorded extraction strategy needs another source.",
                )
            if not attempt:
                attempt_id = uuid4()
                connection.execute(
                    "INSERT INTO knowledge.material_repair_attempts"
                    "(id,job_id,input_identity,strategy,state,issues) "
                    "VALUES (%s,%s,%s,%s,'prepared',%s)",
                    (attempt_id, job["id"], identity, strategy, Jsonb(current["issues"])),
                )
            else:
                attempt_id = attempt["id"]
            if strategy == HTML_MAIN_PARSER_VERSION:
                upload = MaterialFiles(connection).row(actor, current["upload_id"])
                MaterialFiles(connection).require_use(actor, upload, "indexing")
                content = OriginalFileStore(self.settings.material_storage_dir).read(
                    actor.id, upload["id"]
                )
                OriginalFileStore.check(content, upload["content_digest"], upload["byte_size"])
            else:
                self.replacement(connection, actor, current, demand, attempt_id)
                return
        parsed = extract_file(content, "html-main")
        with self.database.transaction() as connection:
            current, demand = processing.current(connection, actor, job["id"], lease)
            automatic_text = connection.execute(
                "SELECT 1 FROM knowledge.source_observations WHERE job_id=%s "
                "AND command_key LIKE 'discovery:%%' "
                "AND request_identity ? 'missing_topics' LIMIT 1",
                (job["id"],),
            ).fetchone()
            partial_text = bool(
                automatic_text and parsed["issues"] == ["html_nontext_content_pending"]
                and parsed["blocks"]
            )
            if parsed["issues"] and not partial_text:
                self.replacement(connection, actor, current, demand, attempt_id)
                return
            derived = Materials(connection).derive_extraction(actor, version, parsed)
            if partial_text:
                connection.execute(
                    "UPDATE knowledge.material_jobs SET prepared_scope=%s WHERE id=%s",
                    (Jsonb(Materials.source_text_scope(derived, parsed["blocks"])), job["id"]),
                )
            connection.execute(
                "UPDATE knowledge.material_repair_attempts SET state='applied',"
                "result_revision=%s WHERE id=%s",
                (derived.revision, attempt_id),
            )
            MaterialIntake(connection).transition(
                job["id"],
                "waiting_dependency",
                "indexing",
                reason="indexing_pending",
                document=derived,
            )

    @staticmethod
    def replacement(connection, actor, row, demand, attempt_id):
        from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow

        discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, actor, row["session_digest"], demand
        )
        if discovery is None:
            parents = connection.execute(
                "SELECT DISTINCT d.id FROM knowledge.source_observations o "
                "JOIN knowledge.material_source_check_commands c ON c.observation_id=o.id "
                "JOIN knowledge.material_discovery_jobs d "
                "ON c.command_key LIKE 'discovery:'||d.id::text||':shallow-v1:%%' "
                "JOIN knowledge.material_demands m ON m.id=d.demand_id "
                "WHERE o.job_id=%s AND d.actor_id=%s AND m.goal_id=%s "
                "AND m.status<>'cancelled' AND d.demand_revision=m.revision "
                "AND d.status NOT IN ('ready','cancelled','blocked_unknown') "
                "AND coalesce(d.error_code,'') NOT IN "
                "('material_discovery_exhausted','node_material_review_failed') ORDER BY d.id",
                (row["id"], actor.id, demand.goal_id),
            ).fetchall()
            connection.execute(
                "UPDATE knowledge.material_repair_attempts SET state='superseded',"
                "replacement_discovery_id=%s WHERE id=%s",
                (parents[0]["id"] if parents else None, attempt_id),
            )
            MaterialIntake(connection).transition(
                row["id"], "waiting_dependency" if parents else "waiting_config", "checking",
                reason="material_nontext_processing_required"
                if "html_nontext_content_pending" in row["issues"]
                else "material_replacement_source_required",
                issues=row["issues"],
            )
            if parents:
                connection.execute(
                    "UPDATE knowledge.material_discovery_jobs SET status='queued',"
                    "error_code='material_replacement_source_required',next_run_at=now(),"
                    "published_at=NULL,lease_token=NULL,lease_until=NULL WHERE id=ANY(%s::uuid[])",
                    ([item["id"] for item in parents],),
                )
            return
        connection.execute(
            "UPDATE knowledge.material_repair_attempts SET state='waiting',"
            "replacement_discovery_id=%s WHERE id=%s",
            (discovery.id if discovery else None, attempt_id),
        )
        MaterialIntake(connection).transition(
            row["id"],
            "waiting_dependency",
            "checking",
            reason="automatic_repair_exhausted",
            issues=row["issues"],
        )
