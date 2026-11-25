import json
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.file_contracts import MaterialUpload
from leornian.modules.knowledge.materials import digest
from leornian.shared_kernel.errors import BusinessError


class MaterialFiles:
    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, upload_id, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM knowledge.material_uploads WHERE id=%s AND actor_id=%s"
            + (" FOR UPDATE" if lock else ""),
            (upload_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material upload not found.")
        return row

    @staticmethod
    def view(row):
        return MaterialUpload(
            **{key: row[key] for key in MaterialUpload.model_fields if key != "format"},
            format=row["specification"]["material"]["format"],
        )

    def require_use(self, actor, row, purpose=None):
        if row.get("source_id"):
            from leornian.modules.knowledge.source_acquisition import MaterialSources

            MaterialSources(self.connection).require(actor, row["source_id"], purpose=purpose)
        material = row["specification"]["material"]
        now = datetime.now(UTC)
        if row["state"] == "purged" or (
            row["retain_until"] is not None and row["retain_until"] <= now
        ):
            raise BusinessError("source_not_current", "Original material is no longer available.")
        use_until = material.get("use_until")
        if use_until and datetime.fromisoformat(use_until.replace("Z", "+00:00")) <= now:
            raise BusinessError("source_not_current", "Original material use has expired.")
        if purpose is not None and purpose not in material["purposes"]:
            raise BusinessError("source_not_current", "This material purpose was not authorized.")

    def replay(self, actor, demand_id, key, data):
        request = {"demand_id": str(demand_id), **data.model_dump(mode="json")}
        previous = self.connection.execute(
            "SELECT * FROM knowledge.material_upload_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if previous["request"] != request:
                raise BusinessError("idempotency_conflict", "Material upload key changed.")
            return self.view(self.row(actor, previous["upload_id"]))
        return None

    def reserve(
        self, actor, demand_id, key, data, *, extraction_policy=None, source_id=None,
        selected_pages=None,
    ):
        request = data.model_dump(mode="json")
        if extraction_policy:
            request["extraction_policy"] = extraction_policy
        if source_id:
            request["source_id"] = str(source_id)
        if selected_pages is not None:
            if not selected_pages or len(selected_pages) > 20 or any(
                type(page) is not int or page < 1 for page in selected_pages
            ):
                raise BusinessError("precondition_failed", "Invalid automatic PDF selection.")
            request["selected_pages"] = sorted(set(selected_pages))
        request_digest = digest(json.dumps(request, sort_keys=True, separators=(",", ":")))
        existing = self.connection.execute(
            "SELECT * FROM knowledge.material_uploads "
            "WHERE actor_id=%s AND demand_id=%s AND request_digest=%s",
            (actor.id, demand_id, request_digest),
        ).fetchone()
        if existing:
            upload = self.view(existing)
        else:
            upload_id = uuid4()
            row = self.connection.execute(
                "INSERT INTO knowledge.material_uploads"
                "(id,actor_id,demand_id,demand_revision,specification,request_digest,"
                    "content_digest,byte_size,retain_until,source_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "RETURNING *",
                (
                    upload_id,
                    actor.id,
                    demand_id,
                    data.expected_demand_revision,
                    Jsonb(request),
                    request_digest,
                    data.content_digest,
                    data.byte_size,
                    data.material.retain_until,
                    source_id,
                ),
            ).fetchone()
            upload = self.view(row)
        self.connection.execute(
            "INSERT INTO knowledge.material_upload_commands"
            "(actor_id,command_key,request,upload_id) VALUES (%s,%s,%s,%s)",
            (actor.id, key, Jsonb({"demand_id": str(demand_id), **request}), upload.id),
        )
        return upload
