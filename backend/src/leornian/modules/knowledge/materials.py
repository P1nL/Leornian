from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.knowledge.material_contracts import (
    DocumentBlock,
    DocumentBlockPage,
    DocumentPermission,
    DocumentVersion,
    MaterialRef,
    TextMaterialImport,
)
from leornian.shared_kernel.errors import BusinessError

PARSER_VERSION = "exact-text.v1"
MAX_BLOCKS = 10_000


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_blocks(text: str, markdown: bool) -> list[dict]:
    """Keep exact source spans, including whitespace and fenced code."""
    lines = text.splitlines(keepends=True)
    result, path, pending = [], [], []
    start = offset = 0
    fence = None
    kind = "paragraph"

    def flush():
        nonlocal pending
        if pending:
            value = "".join(pending)
            result.append(
                dict(kind=kind, section_path=list(path), start=start, end=offset, text=value)
            )
            if len(result) > MAX_BLOCKS:
                raise BusinessError("material_block_limit", "Split material into fewer blocks.")
            pending = []

    for line in lines:
        heading = re.match(r"^(#{1,6})[ \t]+(.+?)[\r\n]*$", line) if markdown else None
        marker = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line) if markdown else None
        if fence:
            pending.append(line)
            offset += len(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
                flush()
            continue
        if heading or marker or not line.strip():
            flush()
        if heading:
            depth = len(heading[1])
            path = path[: depth - 1] + [heading[2]]
            kind = "heading"
        elif marker:
            kind, fence = "code", marker[1]
        elif not line.strip():
            offset += len(line)
            continue
        elif not pending:
            kind = "table" if markdown and "|" in line else "paragraph"
        if not pending:
            start = offset
        pending.append(line)
        offset += len(line)
        if heading:
            flush()
    if fence:
        raise BusinessError("precondition_failed", "Markdown has an unclosed code fence.")
    flush()
    return result


class Materials:
    def __init__(self, connection: Connection, *, check_days=30):
        self.connection = connection
        self.check_days = check_days

    def version(self, actor: Actor, document_id: UUID, revision: int) -> DocumentVersion:
        row = self.connection.execute(
            "SELECT d.goal_id,d.next_check_at,v.* FROM knowledge.documents d "
            "JOIN knowledge.document_versions v ON v.document_id=d.id "
            "WHERE d.id=%s AND d.actor_id=%s AND v.revision=%s",
            (document_id, actor.id, revision),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Document version not found.")
        permission = self.connection.execute(
            "SELECT revision,status,purposes,use_until,retain_until,basis "
            "FROM knowledge.document_permissions WHERE document_id=%s AND document_revision=%s",
            (document_id, revision),
        ).fetchone()
        return DocumentVersion(
            **{key: value for key, value in row.items() if key in DocumentVersion.model_fields},
            permission=DocumentPermission(**permission),
        )

    def require_use(self, actor, document_id, revision, purpose, *, goal_id=None):
        # Permission changes serialize with reads/acceptance; review/check dates are not permits.
        self.connection.execute(
            "SELECT p.document_id FROM knowledge.document_permissions p "
            "JOIN knowledge.documents d ON d.id=p.document_id "
            "WHERE d.id=%s AND d.actor_id=%s AND p.document_revision=%s FOR SHARE OF p",
            (document_id, actor.id, revision),
        )
        version = self.version(actor, document_id, revision)
        permission, now = version.permission, datetime.now(UTC)
        if goal_id is not None and goal_id != version.goal_id:
            raise BusinessError("not_found", "Material does not belong to this goal.")
        if (
            permission.status != "allowed"
            or version.content_state != "retained"
            or purpose not in permission.purposes
            or (permission.use_until is not None and permission.use_until <= now)
            or (permission.retain_until is not None and permission.retain_until <= now)
        ):
            raise BusinessError("source_not_current", "Material use or retention is not allowed.")
        if version.provenance == "legacy_excerpt":
            Knowledge(self.connection).current(
                actor,
                version.goal_id,
                [
                    SourceRef(
                        source_id=version.legacy_source_id,
                        revision=version.legacy_source_revision,
                    )
                ],
            )
        return version

    def import_text(self, actor: Actor, key: str, data: TextMaterialImport, *, parse_as_text=False):
        request = {
            **data.model_dump(mode="json", exclude={"text"}),
            "text_digest": digest(data.text),
        }
        previous = self.connection.execute(
            "SELECT * FROM knowledge.document_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if previous["request"] != request:
                raise BusinessError("idempotency_conflict", "Import key has different content.")
            return self.version(actor, previous["document_id"], previous["document_revision"])
        now = datetime.now(UTC)
        if any(value is not None and value <= now for value in (data.use_until, data.retain_until)):
            raise BusinessError(
                "source_not_current", "A supplied real deadline has already passed."
            )
        blocks = parse_blocks(data.text, data.format == "markdown" and not parse_as_text)
        document_id = self._document_identity(actor, data)
        revision = data.expected_revision + 1
        self._record(
            actor,
            document_id,
            revision,
            data,
            blocks,
            parser_version="exact-text.markdown-fallback.v1" if parse_as_text else PARSER_VERSION,
        )
        self.connection.execute(
            "INSERT INTO knowledge.document_commands"
            "(actor_id,command_key,request,document_id,document_revision) VALUES (%s,%s,%s,%s,%s)",
            (actor.id, key, Jsonb(request), document_id, revision),
        )
        return self.version(actor, document_id, revision)

    def _document_identity(self, actor, data):
        document_id = data.document_id or uuid4()
        if data.document_id:
            head = self.connection.execute(
                "SELECT latest_revision,goal_id FROM knowledge.documents "
                "WHERE id=%s AND actor_id=%s FOR UPDATE",
                (document_id, actor.id),
            ).fetchone()
            if not head or head["goal_id"] != data.goal_id:
                raise BusinessError("not_found", "Document not found in this goal.")
            if head["latest_revision"] != data.expected_revision:
                raise BusinessError("stale_version", "Document revision changed.")
        else:
            self.connection.execute(
                "INSERT INTO knowledge.documents(id,actor_id,goal_id,next_check_at) "
                "VALUES (%s,%s,%s,now()+make_interval(days=>%s))",
                (document_id, actor.id, data.goal_id, self.check_days),
            )
        return document_id

    def import_file(self, actor, upload, parsed):
        from leornian.modules.knowledge.file_contracts import FileMaterialInput

        previous = self.connection.execute(
            "SELECT document_id,revision FROM knowledge.document_versions WHERE upload_id=%s "
            "ORDER BY revision LIMIT 1",
            (upload["id"],),
        ).fetchone()
        if previous:
            return self.version(actor, previous["document_id"], previous["revision"])
        data = FileMaterialInput(**upload["specification"]["material"])
        document_id = self._document_identity(actor, data)
        revision = data.expected_revision + 1
        self._record(
            actor,
            document_id,
            revision,
            data,
            parsed["blocks"],
            parser_version=parsed["parser_version"],
            text=parsed["text"],
            upload_id=upload["id"],
            pages=parsed["pages"],
            text_basis=parsed["text_basis"],
            partial=bool(parsed["issues"]),
            unresolved_regions=parsed.get("unresolved_regions", []),
        )
        return self.version(actor, document_id, revision)

    @staticmethod
    def source_text_scope(version, blocks):
        return {
            "basis": "selected-source-text.v1", "document_id": str(version.document_id),
            "document_revision": version.revision, "content_digest": version.content_digest,
            "block_count": len(blocks),
            "indexed_characters": sum(len(block["text"]) for block in blocks),
        }

    @staticmethod
    def permits_partial_text(job, version):
        scope = job.get("prepared_scope") or {}
        return (
            version.format == "html" and bool(version.unresolved_regions)
            and scope.get("basis") == "selected-source-text.v1"
            and scope.get("document_id") == str(version.document_id)
            and scope.get("document_revision") == version.revision
            and scope.get("content_digest") == version.content_digest
            and not job.get("issues")
        )

    def import_ocr(self, actor, original, page_texts):
        from leornian.modules.knowledge.file_contracts import FileMaterialInput
        from leornian.modules.knowledge.file_parser import _assemble

        self.require_use(actor, original.document_id, original.revision, "indexing")
        blocks, pages = [], []
        for page in original.pages:
            if page.requires_ocr:
                text = page_texts[page.number]
                if not text.strip() or "\ufffd" in text or text.count("?") > max(3, len(text)//100):
                    raise BusinessError("material_quality_pending", "OCR has unreadable regions.")
                parsed = parse_blocks(text, True)
                pages.append({**page.model_dump(), "method": "ocr",
                              "requires_ocr": False, "reason_code": None})
            else:
                parsed = self.connection.execute(
                    "SELECT kind,section_path,text FROM knowledge.document_blocks "
                    "WHERE document_id=%s AND document_revision=%s AND source_page=%s "
                    "ORDER BY ordinal",
                    (original.document_id, original.revision, page.number),
                ).fetchall()
                pages.append(page.model_dump())
            blocks.extend({**block, "source_page": page.number} for block in parsed)
        extracted = _assemble(
            blocks, pages=pages,
            parser_version="pdf.page-ocr.v1" if original.format == "pdf" else "image.region-ocr.v1",
            complete=True,
        )
        data = FileMaterialInput(
            goal_id=original.goal_id, document_id=original.document_id,
            expected_revision=original.revision, title=original.title,
            source_url=original.source_url if original.source_url.startswith("https://") else None,
            format=original.format, authorized_use=True,
            purposes=original.permission.purposes,
            use_until=original.permission.use_until, retain_until=original.permission.retain_until,
        )
        document_id = self._document_identity(actor, data)
        self._record(
            actor, document_id, original.revision + 1, data, extracted["blocks"],
            parser_version=extracted["parser_version"], text=extracted["text"],
            pages=pages, upload_id=original.upload_id, text_basis="extracted_text",
        )
        return self.version(actor, document_id, original.revision + 1)

    def derive_extraction(self, actor, original, parsed):
        from leornian.modules.knowledge.file_contracts import FileMaterialInput

        self.require_use(actor, original.document_id, original.revision, "indexing")
        data = FileMaterialInput(
            goal_id=original.goal_id, document_id=original.document_id,
            expected_revision=original.revision, title=original.title,
            source_url=original.source_url if original.source_url.startswith("https://") else None,
            format=original.format, authorized_use=True, purposes=original.permission.purposes,
            use_until=original.permission.use_until, retain_until=original.permission.retain_until,
        )
        document_id = self._document_identity(actor, data)
        self._record(
            actor, document_id, original.revision + 1, data, parsed["blocks"],
            parser_version=parsed["parser_version"], text=parsed["text"],
            pages=parsed["pages"], upload_id=original.upload_id, text_basis=parsed["text_basis"],
            partial=bool(parsed["issues"]),
            unresolved_regions=parsed.get("unresolved_regions", []),
        )
        return self.version(actor, document_id, original.revision + 1)

    def _record(
        self,
        actor,
        document_id,
        revision,
        data,
        blocks,
        *,
        legacy=None,
        parser_version=PARSER_VERSION,
        text=None,
        upload_id=None,
        pages=(),
        text_basis="source_text",
        partial=False,
        unresolved_regions=(),
    ):
        text = data.text if text is None else text
        self.connection.execute(
            "INSERT INTO knowledge.document_versions"
            "(document_id,revision,title,source_url,format,original_text,content_digest,"
            "parser_version,provenance,legacy_source_id,legacy_source_revision,"
            "upload_id,text_basis,pages,processing_state,unresolved_regions) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                document_id,
                revision,
                data.title,
                data.source_url or "leornian-upload:" + str(upload_id),
                data.format,
                text,
                digest(text),
                parser_version,
                "legacy_excerpt" if legacy else "learner_supplied",
                legacy.source_id if legacy else None,
                legacy.revision if legacy else None,
                upload_id,
                text_basis,
                Jsonb(list(pages)),
                "partial" if partial else "parsed",
                Jsonb(list(unresolved_regions)),
            ),
        )
        for ordinal, block in enumerate(blocks):
            self.connection.execute(
                "INSERT INTO knowledge.document_blocks"
                "(id,document_id,document_revision,ordinal,kind,section_path,span_start,"
                "span_end,text,content_digest,source_page) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    uuid5(document_id, f"{revision}:{ordinal}"),
                    document_id,
                    revision,
                    ordinal,
                    block["kind"],
                    Jsonb(block["section_path"]),
                    block["start"],
                    block["end"],
                    block["text"],
                    digest(block["text"]),
                    block.get("source_page"),
                ),
            )
        self.connection.execute(
            "INSERT INTO knowledge.document_permissions"
            "(document_id,document_revision,purposes,use_until,retain_until,basis) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                document_id,
                revision,
                Jsonb(data.purposes),
                data.use_until,
                data.retain_until,
                "legacy_admission" if legacy else "learner_authorized",
            ),
        )
        self.connection.execute(
            "UPDATE knowledge.documents SET latest_revision=%s WHERE id=%s", (revision, document_id)
        )

    def import_legacy(self, actor, source_id, revision):
        source = Knowledge(self.connection).get(actor, source_id, lock=True)
        if source.revision != revision:
            raise BusinessError("stale_version", "Legacy source revision changed.")
        material = Knowledge(self.connection).current(
            actor, source.goal_id, [SourceRef(source_id=source_id, revision=revision)]
        )[0]
        previous = self.connection.execute(
            "SELECT document_id,revision FROM knowledge.document_versions "
            "WHERE legacy_source_id=%s AND legacy_source_revision=%s",
            (source_id, revision),
        ).fetchone()
        if previous:
            return self.version(actor, previous["document_id"], previous["revision"])
        data = TextMaterialImport(
            goal_id=source.goal_id,
            title=source.title,
            source_url=source.source_url,
            text=source.excerpt,
            authorized_use=True,
            purposes=["reference", "planning", "lesson", "teaching", "item_author", "item_review"],
            use_until=material.valid_until,
        )
        document_id = uuid4()
        self.connection.execute(
            "INSERT INTO knowledge.documents(id,actor_id,goal_id,next_check_at) "
            "VALUES (%s,%s,%s,now()+make_interval(days=>%s))",
            (document_id, actor.id, source.goal_id, self.check_days),
        )
        self._record(actor, document_id, 1, data, parse_blocks(data.text, False), legacy=material)
        return self.version(actor, document_id, 1)

    @staticmethod
    def _block(row):
        return DocumentBlock(
            id=row["id"],
            ordinal=row["ordinal"],
            kind=row["kind"],
            section_path=row["section_path"],
            text=row["text"],
            source_page=row["source_page"],
            span_basis=row["text_basis"],
            ref=MaterialRef(
                document_id=row["document_id"],
                document_revision=row["document_revision"],
                block_id=row["id"],
                span={"start": row["span_start"], "end": row["span_end"]},
                content_digest=row["content_digest"],
            ),
        )

    def blocks(self, actor, document_id, revision, purpose, *, after=-1, limit=20):
        version = self.require_use(actor, document_id, revision, purpose)
        rows = self.connection.execute(
            "SELECT b.*,v.text_basis FROM knowledge.document_blocks b "
            "JOIN knowledge.document_versions v ON v.document_id=b.document_id "
            "AND v.revision=b.document_revision WHERE b.document_id=%s "
            "AND b.document_revision=%s AND b.ordinal>%s ORDER BY b.ordinal LIMIT %s",
            (document_id, revision, after, limit + 1),
        ).fetchall()
        return DocumentBlockPage(
            document=version,
            blocks=[self._block(row) for row in rows[:limit]],
            next_after=rows[limit - 1]["ordinal"] if len(rows) > limit else None,
        )

    def read_refs(self, actor, goal_id, purpose, refs: list[MaterialRef]):
        identities = sorted({(ref.document_id, ref.document_revision) for ref in refs})
        for document_id, revision in identities:
            self.require_use(actor, document_id, revision, purpose, goal_id=goal_id)
        result = []
        for ref in refs:
            row = self.connection.execute(
                "SELECT b.*,v.text_basis FROM knowledge.document_blocks b "
                "JOIN knowledge.document_versions v ON v.document_id=b.document_id "
                "AND v.revision=b.document_revision WHERE b.id=%s AND b.document_id=%s "
                "AND b.document_revision=%s",
                (ref.block_id, ref.document_id, ref.document_revision),
            ).fetchone()
            if (
                not row or row["text"] is None
                or not row["span_start"] <= ref.span.start < ref.span.end <= row["span_end"]
            ):
                raise BusinessError(
                    "stale_version", "Material locator does not match its original."
                )
            excerpt = row["text"][
                ref.span.start - row["span_start"]:ref.span.end - row["span_start"]
            ]
            if digest(excerpt) != ref.content_digest:
                raise BusinessError("stale_version", "Material content identity changed.")
            if ref.selection_id is not None:
                selection = self.connection.execute(
                    "SELECT refs FROM knowledge.material_selections WHERE id=%s AND actor_id=%s "
                    "AND goal_id=%s AND purpose=%s",
                    (ref.selection_id, actor.id, goal_id, purpose),
                ).fetchone()
                if not selection or ref.model_dump(mode="json") not in selection["refs"]:
                    raise BusinessError(
                        "not_found", "Material selection does not grant this range."
                    )
            block = self._block({
                **row, "text": excerpt, "span_start": ref.span.start, "span_end": ref.span.end,
                "content_digest": ref.content_digest,
            })
            result.append(block.model_copy(update={"ref": ref}))
        return result

    def revoke(self, actor, document_id, revision, expected_permission_revision):
        self.version(actor, document_id, revision)
        row = self.connection.execute(
            "SELECT revision,status FROM knowledge.document_permissions "
            "WHERE document_id=%s AND document_revision=%s FOR UPDATE",
            (document_id, revision),
        ).fetchone()
        if row["revision"] != expected_permission_revision:
            raise BusinessError("stale_version", "Material permission changed.")
        if row["status"] != "revoked":
            self.connection.execute(
                "UPDATE knowledge.document_permissions SET status='revoked',revision=revision+1,"
                "updated_at=now() WHERE document_id=%s AND document_revision=%s",
                (document_id, revision),
            )
        return self.version(actor, document_id, revision)

    def purge_retained(self, *, limit=50):
        rows = self.connection.execute(
            "SELECT v.document_id,v.revision FROM knowledge.document_versions v "
            "JOIN knowledge.document_permissions p ON p.document_id=v.document_id "
            "AND p.document_revision=v.revision WHERE v.content_state='retained' "
            "AND p.retain_until<now() ORDER BY p.retain_until,v.document_id,v.revision "
            "LIMIT %s FOR UPDATE OF v,p SKIP LOCKED",
            (limit,),
        ).fetchall()
        for row in rows:
            params = (row["document_id"], row["revision"])
            self.connection.execute(
                "UPDATE knowledge.document_versions SET original_text=NULL,unresolved_regions='[]',"
                "content_state='purged',"
                "purged_at=now() WHERE document_id=%s AND revision=%s",
                params,
            )
            self.connection.execute(
                "UPDATE knowledge.document_blocks SET text=NULL,section_path='[]' "
                "WHERE document_id=%s AND document_revision=%s",
                params,
            )
        return len(rows)
