from psycopg.types.json import Jsonb

from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.file_parser import _assemble, extract_file
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.shared_kernel.errors import BusinessError


def parse_pdf_parts(workflow, actor, job, lease, content):
    with workflow.database.transaction() as connection:
        Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
            job["session_digest"]
        )
        count = connection.execute(
            "SELECT count(*) AS count FROM knowledge.material_parse_parts WHERE upload_id=%s",
            (job["upload_id"],),
        ).fetchone()["count"]
    if not count:
        total = extract_file(content, "pdf-metadata")["page_count"]
        if not total:
            raise BusinessError("material_quality_pending", "PDF has no pages.")
        with workflow.database.transaction() as connection:
            Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                job["session_digest"]
            )
            current = connection.execute(
                "SELECT lease_token FROM knowledge.material_jobs WHERE id=%s FOR UPDATE",
                (job["id"],),
            ).fetchone()
            if current["lease_token"] != lease:
                raise BusinessError("lease_lost", "PDF parse lease changed.")
            selected = job["upload"]["specification"].get("selected_pages")
            if selected is not None and any(page > total for page in selected):
                raise BusinessError("material_page_limit", "Selected source page is out of bounds.")
            ranges = []
            for page in selected or range(1, total + 1):
                if ranges and page == ranges[-1][1] + 1 and page - ranges[-1][0] < 20:
                    ranges[-1][1] = page
                else:
                    ranges.append([page, page])
            for start, end in ranges:
                connection.execute(
                    "INSERT INTO knowledge.material_parse_parts"
                    "(upload_id,ordinal,page_start,page_end) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT(upload_id,ordinal) DO NOTHING",
                    (job["upload_id"], start, start, end),
                )
    with workflow.database.transaction(snapshot=True) as connection:
        part = connection.execute(
            "SELECT * FROM knowledge.material_parse_parts WHERE upload_id=%s "
            "AND state='queued' ORDER BY ordinal LIMIT 1", (job["upload_id"],),
        ).fetchone()
    parsed = None
    split = False
    if part:
        try:
            parsed = extract_file(content, f"pdf-range:{part['page_start']}:{part['page_end']}")
        except BusinessError as error:
            if error.code in {"material_text_limit", "material_parser_timeout"} and (
                part["page_end"] > part["page_start"]
            ):
                split = True
            else:
                raise
    with workflow.database.transaction() as connection:
        Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
            job["session_digest"]
        )
        current = connection.execute(
            "SELECT * FROM knowledge.material_jobs WHERE id=%s FOR UPDATE", (job["id"],),
        ).fetchone()
        if current["state"] != "parsing" or current["lease_token"] != lease:
            raise BusinessError("lease_lost", "PDF parse lease changed.")
        demand = MaterialIntake(connection).demand(actor, current["demand_id"])
        workflow.require_scope(connection, actor, demand)
        if demand.status == "cancelled" or demand.revision != current["demand_revision"]:
            raise BusinessError("stale_version", "PDF demand changed.")
        if part:
            if split:
                middle = (part["page_start"] + part["page_end"]) // 2
                connection.execute(
                    "UPDATE knowledge.material_parse_parts SET page_end=%s "
                    "WHERE upload_id=%s AND ordinal=%s",
                    (middle, job["upload_id"], part["ordinal"]),
                )
                connection.execute(
                    "INSERT INTO knowledge.material_parse_parts"
                    "(upload_id,ordinal,page_start,page_end) VALUES (%s,%s,%s,%s)",
                    (job["upload_id"], middle + 1, middle + 1, part["page_end"]),
                )
            else:
                connection.execute(
                    "UPDATE knowledge.material_parse_parts SET state='parsed',parsed=%s "
                    "WHERE upload_id=%s AND ordinal=%s",
                    (Jsonb(parsed), job["upload_id"], part["ordinal"]),
                )
        parts = connection.execute(
            "SELECT * FROM knowledge.material_parse_parts WHERE upload_id=%s ORDER BY ordinal",
            (job["upload_id"],),
        ).fetchall()
        if any(item["state"] != "parsed" for item in parts):
            MaterialIntake(connection).transition(
                job["id"], "queued", "parsing", reason="parse_parts_pending"
            )
            return None
        return _assemble(
            [block for item in parts for block in item["parsed"]["blocks"]],
            pages=[page for item in parts for page in item["parsed"]["pages"]],
            issues=[issue for item in parts for issue in item["parsed"]["issues"]],
            parser_version="pypdf-6.21.4.parts.v1", complete=True,
        )
