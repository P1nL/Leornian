from datetime import UTC, datetime
from difflib import SequenceMatcher
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.change_contracts import MaterialChangeReport
from leornian.modules.knowledge.material_contracts import MaterialSpan
from leornian.modules.knowledge.materials import Materials
from leornian.shared_kernel.errors import BusinessError


def compare_blocks(baseline, candidate, refs):
    def identity(block):
        return block.kind, tuple(block.section_path), block.text

    matcher = SequenceMatcher(
        a=[identity(b) for b in baseline], b=[identity(b) for b in candidate], autojunk=False
    )
    unchanged, removed, added, relocated = [], [], [], []
    matches = {}
    for tag, start, end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            for old, new in zip(baseline[start:end], candidate[new_start:new_end], strict=True):
                unchanged.append({"baseline": old.ref, "candidate": new.ref})
                matches[old.id] = new
        else:
            removed.extend(baseline[start:end])
            added.extend(candidate[new_start:new_end])
    changed_paths = [tuple(b.section_path) for b in removed + added]
    old_blocks = {b.id: b for b in baseline}
    affected, context = [], []
    for ref in refs:
        old = old_blocks[ref.block_id]
        if ref.block_id not in matches:
            affected.append(ref)
            continue
        new = matches[ref.block_id]
        shift = new.ref.span.start - old.ref.span.start
        relocated.append(
            {
                "baseline": ref,
                "candidate": ref.model_copy(
                    update={
                        "document_revision": new.ref.document_revision,
                        "block_id": new.id,
                        "span": MaterialSpan(
                            start=ref.span.start + shift, end=ref.span.end + shift
                        ),
                        "selection_id": None,
                    }
                ),
            }
        )
        path = tuple(old.section_path)
        if any(path[: len(p)] == p or p[: len(path)] == path for p in changed_paths):
            context.append(ref)
    return {
        "unchanged_blocks": unchanged,
        "removed_or_changed_blocks": [b.ref for b in removed],
        "added_or_changed_blocks": [b.ref for b in added],
        "affected_refs": affected,
        "affected_context_refs": context,
        "relocated_refs": relocated,
    }


class MaterialChanges:
    def __init__(self, connection):
        self.connection = connection

    def get(self, actor, check_id):
        row = self.connection.execute(
            "SELECT report FROM knowledge.material_change_checks WHERE id=%s AND actor_id=%s",
            (check_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material change check not found.")
        report = MaterialChangeReport(**row["report"])
        for revision in (report.baseline_revision, report.candidate_revision):
            Materials(self.connection).require_use(
                actor, report.document_id, revision, report.purpose, goal_id=report.goal_id
            )
        return report

    def replay(self, actor, key, data):
        row = self.connection.execute(
            "SELECT request,check_id FROM knowledge.material_change_commands "
            "WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if not row:
            return None
        if row["request"] != data.model_dump(mode="json"):
            raise BusinessError("idempotency_conflict", "Change check key has different content.")
        return self.get(actor, row["check_id"])

    def compare(self, actor, key, data, *, goal_id, purpose, refs):
        old_revisions = {r.document_revision for r in refs if r.document_id == data.document_id}
        if len(old_revisions) != 1 or data.candidate_revision <= next(iter(old_revisions)):
            raise BusinessError(
                "precondition_failed", "Compare a later version of one exact bound document."
            )
        baseline_revision = next(iter(old_revisions))
        materials = Materials(self.connection)
        versions, pages = [], []
        for revision in (baseline_revision, data.candidate_revision):
            versions.append(
                materials.require_use(actor, data.document_id, revision, purpose, goal_id=goal_id)
            )
            blocks, after = [], -1
            while True:
                page = materials.blocks(
                    actor, data.document_id, revision, purpose, after=after, limit=100
                )
                blocks.extend(page.blocks)
                if page.next_after is None:
                    break
                after = page.next_after
            pages.append(blocks)
        row = self.connection.execute(
            "SELECT id FROM knowledge.material_change_checks WHERE actor_id=%s "
            "AND binding_id=%s AND binding_revision=%s "
            "AND document_id=%s AND candidate_revision=%s",
            (
                actor.id,
                data.binding_id,
                data.expected_binding_revision,
                data.document_id,
                data.candidate_revision,
            ),
        ).fetchone()
        if row:
            report = self.get(actor, row["id"])
        else:
            unchanged = versions[0].content_digest == versions[1].content_digest
            report = MaterialChangeReport(
                id=uuid4(),
                binding_id=data.binding_id,
                binding_revision=data.expected_binding_revision,
                goal_id=goal_id,
                purpose=purpose,
                document_id=data.document_id,
                baseline_revision=baseline_revision,
                candidate_revision=data.candidate_revision,
                classification="unchanged" if unchanged else "uncertain",
                state="no_content_change" if unchanged else "waiting_dependency",
                reason_code=None if unchanged else "change_review_required",
                created_at=datetime.now(UTC),
                **compare_blocks(*pages, [r for r in refs if r.document_id == data.document_id]),
            )
            self.connection.execute(
                "INSERT INTO knowledge.material_change_checks"
                "(id,actor_id,binding_id,binding_revision,document_id,baseline_revision,"
                "candidate_revision,report) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    report.id,
                    actor.id,
                    report.binding_id,
                    report.binding_revision,
                    report.document_id,
                    baseline_revision,
                    report.candidate_revision,
                    Jsonb(report.model_dump(mode="json")),
                ),
            )
        self.connection.execute(
            "INSERT INTO knowledge.material_change_commands(actor_id,command_key,request,check_id) "
            "VALUES (%s,%s,%s,%s)",
            (actor.id, key, Jsonb(data.model_dump(mode="json")), report.id),
        )
        return report
