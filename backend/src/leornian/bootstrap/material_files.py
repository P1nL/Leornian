from datetime import UTC, datetime
from uuid import UUID

from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.file_contracts import FileMaterialInput
from leornian.modules.knowledge.file_store import OriginalFileStore
from leornian.modules.knowledge.files import MaterialFiles
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.materials import Materials
from leornian.shared_kernel.errors import BusinessError


class MaterialFilesWorkflow:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings
        self.store = OriginalFileStore(settings.material_storage_dir)

    @staticmethod
    def require_input(connection, actor, row):
        MaterialFiles(connection).require_use(actor, row)
        demand = MaterialIntake(connection).demand(actor, row["demand_id"])
        MaterialIntakeWorkflow.require_scope(connection, actor, demand)
        MaterialIntake.validate_input(
            demand, FileMaterialInput(**row["specification"]["material"]), row["demand_revision"]
        )
        return demand

    def reserve(self, token, demand_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            files = MaterialFiles(connection)
            previous = files.replay(actor, demand_id, key, data)
            if previous:
                return previous
            demand = MaterialIntake(connection).demand(actor, demand_id)
            MaterialIntakeWorkflow.require_scope(connection, actor, demand)
            MaterialIntake.validate_input(demand, data.material, data.expected_demand_revision)
            return files.reserve(actor, demand_id, key, data)

    def upload(self, token, upload_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            files = MaterialFiles(connection)
            return files.view(files.row(actor, upload_id))

    def upload_receipt(self, token, demand_id, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = connection.execute(
                "SELECT upload_id,request FROM knowledge.material_upload_commands "
                "WHERE actor_id=%s AND command_key=%s", (actor.id, key),
            ).fetchone()
            if not row or row["request"]["demand_id"] != str(demand_id):
                raise BusinessError("not_found", "Material upload command not found.")
            files = MaterialFiles(connection)
            return files.view(files.row(actor, row["upload_id"]))

    def preflight(self, token, upload_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            files = MaterialFiles(connection)
            row = files.row(actor, upload_id)
            self.require_input(connection, actor, row)
            if row["state"] == "pending" and row["expires_at"] <= datetime.now(UTC):
                raise BusinessError("source_not_current", "Upload reservation expired.")
            return files.view(row)

    def store_content(self, token, upload_id, content):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            files = MaterialFiles(connection)
            row = files.row(actor, upload_id, lock=True)
            self.require_input(connection, actor, row)
            if row["state"] == "pending" and row["expires_at"] <= datetime.now(UTC):
                raise BusinessError("source_not_current", "Upload reservation expired.")
            self.store.put(actor.id, upload_id, content, row["content_digest"], row["byte_size"])
            if row["state"] == "pending":
                connection.execute(
                    "UPDATE knowledge.material_uploads SET state='stored',stored_at=now() "
                    "WHERE id=%s",
                    (upload_id,),
                )
            return files.view(files.row(actor, upload_id))

    def submit(self, token, demand_id, key, data):
        with self.database.transaction() as connection:
            identity = Identity(PgIdentityStore(connection, serialize_actor=True))
            actor = identity.authenticate(token)
            intake = MaterialIntake(connection)
            previous = intake.replay_job(actor, demand_id, key, data)
            if previous:
                return previous
            files = MaterialFiles(connection)
            row = files.row(actor, data.upload_id, lock=True)
            if row["demand_id"] != demand_id:
                raise BusinessError("not_found", "Upload belongs to another material demand.")
            demand = self.require_input(connection, actor, row)
            if data.expected_demand_revision != demand.revision:
                raise BusinessError("stale_version", "Material demand changed.")
            if row["state"] != "stored":
                raise BusinessError("precondition_failed", "Complete the original upload first.")
            return intake.submit_file(actor, identity.digest(token), demand_id, key, data, row)

    def original(self, token, upload_id, purpose):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, lock_session=True)).authenticate(token)
            files = MaterialFiles(connection)
            row = files.row(actor, upload_id, lock=True)
            files.require_use(actor, row, purpose)
            if row["state"] != "stored":
                raise BusinessError("precondition_failed", "Original upload is not available.")
            document = connection.execute(
                "SELECT document_id,revision FROM knowledge.document_versions WHERE upload_id=%s",
                (upload_id,),
            ).fetchone()
            if document:
                Materials(connection).require_use(
                    actor,
                    document["document_id"],
                    document["revision"],
                    purpose,
                    goal_id=UUID(row["specification"]["material"]["goal_id"]),
                )
            else:
                self.require_input(connection, actor, row)
            content = self.store.read(actor.id, upload_id)
            self.store.check(content, row["content_digest"], row["byte_size"])
            return content

    def discard_unconsumed(self, connection, actor, upload_id):
        MaterialFiles(connection).row(actor, upload_id, lock=True)
        if connection.execute(
            "SELECT 1 FROM knowledge.document_versions WHERE upload_id=%s", (upload_id,)
        ).fetchone():
            return
        self.store.delete(actor.id, upload_id)
        connection.execute(
            "UPDATE knowledge.material_uploads SET state='purged',"
            "purged_at=COALESCE(purged_at,now()) "
            "WHERE id=%s",
            (upload_id,),
        )

    def expire_retained(self):
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT u.id,u.actor_id FROM knowledge.material_uploads u "
                "WHERE u.state<>'purged' AND (u.retain_until<now() OR EXISTS ("
                "SELECT 1 FROM knowledge.document_versions v "
                "JOIN knowledge.document_permissions p ON p.document_id=v.document_id "
                "AND p.document_revision=v.revision WHERE v.upload_id=u.id "
                "AND p.retain_until<now()) OR "
                "(u.expires_at<now() AND NOT EXISTS (SELECT 1 FROM knowledge.document_versions v "
                "WHERE v.upload_id=u.id) AND NOT EXISTS (SELECT 1 FROM knowledge.material_jobs j "
                "WHERE j.upload_id=u.id AND j.state IN ('queued','parsing')))) "
                "ORDER BY u.expires_at,u.id LIMIT 50 FOR UPDATE OF u SKIP LOCKED",
            ).fetchall()
            for row in rows:
                self.store.delete(row["actor_id"], row["id"])
                connection.execute(
                    "UPDATE knowledge.material_uploads SET state='purged',purged_at=now() "
                    "WHERE id=%s",
                    (row["id"],),
                )
            return len(rows)
