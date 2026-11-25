from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.material_contracts import MaterialRef
from leornian.modules.knowledge.materials import Materials
from leornian.modules.knowledge.retrieval import CONTEXT_CHARS, Retrieval, coverage
from leornian.shared_kernel.errors import BusinessError


def ref_parts(refs, limit=CONTEXT_CHARS):
    parts, batch, size = [], [], 0
    for ref in refs:
        length = ref.span.end - ref.span.start
        if batch and size + length > limit:
            parts.append(batch)
            batch, size = [], 0
        batch.append(ref)
        size += length
    if batch:
        parts.append(batch)
    return parts


def require_covered(targets, slices):
    for target in targets:
        positions = sorted(
            (ref.span.start, ref.span.end)
            for ref in slices
            if (ref.document_id, ref.document_revision, ref.block_id)
            == (target.document_id, target.document_revision, target.block_id)
        )
        cursor = target.span.start
        for start, end in positions:
            if end <= cursor:
                continue
            if start > cursor:
                break
            cursor = end
            if cursor >= target.span.end:
                break
        if cursor < target.span.end:
            raise BusinessError(
                "material_index_pending", "An exact source range is not fully indexed."
            )


class CompleteMaterialSelection:
    """Explicit full ranges are verified in durable pages, independently of query top-k."""

    def __init__(self, connection):
        self.connection = connection

    def ensure(self, actor, search, data, demand, binding, builds):
        existing = self.connection.execute(
            "SELECT ordinal FROM knowledge.material_selection_parts WHERE search_id=%s LIMIT 1",
            (search["id"],),
        ).fetchone()
        if existing:
            return
        materials = Materials(self.connection)
        targets = data.required_refs
        if targets is None:
            targets, after = [], -1
            while True:
                page = materials.blocks(
                    actor,
                    data.document_id,
                    data.document_revision,
                    demand.purpose,
                    after=after,
                    limit=100,
                )
                targets.extend(block.ref for block in page.blocks)
                if page.next_after is None:
                    break
                after = page.next_after
        if not targets:
            raise BusinessError(
                "material_quality_pending", "Complete selection has no source text."
            )
        materials.read_refs(actor, demand.goal_id, demand.purpose, targets)
        if binding:
            require_covered(targets, binding.refs)
        rows = self.connection.execute(
            "SELECT c.*,b.document_id,b.document_revision,v.title,v.source_url,"
            "db.source_page,db.section_path FROM knowledge.material_chunks c "
            "JOIN knowledge.material_index_builds b ON b.id=c.build_id "
            "JOIN knowledge.document_versions v ON v.document_id=b.document_id "
            "AND v.revision=b.document_revision "
            "JOIN knowledge.document_blocks db ON db.id=c.block_id "
            "WHERE c.build_id=ANY(%s) AND c.text IS NOT NULL ORDER BY c.ordinal,c.id",
            ([build["id"] for build in builds],),
        ).fetchall()
        slices = Retrieval.bound_ranges(rows, targets)
        refs = list(
            {
                item.ref.model_dump_json(): item.ref
                for item in (Retrieval.evidence(row) for row in slices)
            }.values()
        )
        require_covered(targets, refs)
        for ordinal, part in enumerate(ref_parts(refs)):
            self.connection.execute(
                "INSERT INTO knowledge.material_selection_parts(search_id,ordinal,refs) "
                "VALUES (%s,%s,%s)",
                (search["id"], ordinal, Jsonb([ref.model_dump(mode="json") for ref in part])),
            )
        scope = {
            **search["scope"],
            "selection_basis": "complete-indexed-ranges.v1",
            "complete_refs": [ref.model_dump(mode="json") for ref in targets],
        }
        self.connection.execute(
            "UPDATE knowledge.material_searches SET scope=%s WHERE id=%s",
            (Jsonb(scope), search["id"]),
        )

    def step(self, actor, search, data, demand, binding, builds):
        self.ensure(actor, search, data, demand, binding, builds)
        pending = self.connection.execute(
            "SELECT * FROM knowledge.material_selection_parts WHERE search_id=%s "
            "AND status='queued' ORDER BY ordinal LIMIT 1 FOR UPDATE",
            (search["id"],),
        ).fetchone()
        if pending:
            refs = [MaterialRef(**ref) for ref in pending["refs"]]
            Materials(self.connection).read_refs(actor, demand.goal_id, demand.purpose, refs)
            self.connection.execute(
                "UPDATE knowledge.material_selection_parts SET status='verified' "
                "WHERE search_id=%s AND ordinal=%s",
                (search["id"], pending["ordinal"]),
            )
        incomplete = self.connection.execute(
            "SELECT ordinal FROM knowledge.material_selection_parts "
            "WHERE search_id=%s AND status<>'verified' LIMIT 1",
            (search["id"],),
        ).fetchone()
        if incomplete:
            self.connection.execute(
                "UPDATE knowledge.material_searches SET status='queued',error_code="
                "'complete_selection_pending',lease_token=NULL,lease_until=NULL WHERE id=%s",
                (search["id"],),
            )
            return None
        scope = self.connection.execute(
            "SELECT scope FROM knowledge.material_searches WHERE id=%s",
            (search["id"],),
        ).fetchone()["scope"]
        targets = [MaterialRef(**ref) for ref in scope["complete_refs"]]
        blocks = Materials(self.connection).read_refs(
            actor, demand.goal_id, demand.purpose, targets
        )
        selection_id = uuid4()
        refs = [
            ref.model_copy(update={"selection_id": selection_id}).model_dump(mode="json")
            for ref in targets
        ]
        evidence = [
            block.model_copy(update={"ref": MaterialRef(**ref)})
            for ref, block in zip(refs, blocks, strict=True)
        ]
        report = coverage(demand.required_facets, evidence)
        self.connection.execute(
            "INSERT INTO knowledge.material_selections"
            "(id,actor_id,goal_id,demand_id,purpose,query,facets,mode,refs,coverage,scope) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'lexical',%s,%s,%s)",
            (
                selection_id,
                actor.id,
                demand.goal_id,
                demand.id,
                demand.purpose,
                data.query,
                Jsonb(demand.required_facets),
                Jsonb(refs),
                Jsonb(report.model_dump(mode="json")),
                Jsonb(scope),
            ),
        )
        self.connection.execute(
            "UPDATE knowledge.material_searches SET status='ready',selection_id=%s,"
            "error_code=NULL,lease_token=NULL,lease_until=NULL WHERE id=%s",
            (selection_id, search["id"]),
        )
        return selection_id
