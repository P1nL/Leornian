from itertools import zip_longest
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.change_contracts import MaterialChangeVerdict
from leornian.modules.knowledge.complete_selection import require_covered
from leornian.modules.knowledge.material_contracts import MaterialRef, MaterialSpan
from leornian.modules.knowledge.materials import digest
from leornian.shared_kernel.errors import BusinessError


def partition_review_blocks(blocks, fits, *, characters=4096):
    revisions = sorted({block.ref.document_revision for block in blocks})
    groups = [
        sorted(
            (block for block in blocks if block.ref.document_revision == rev),
            key=lambda block: (block.ordinal, block.ref.span.start),
        )
        for rev in revisions
    ]
    ordered = []
    for parallel in zip_longest(*groups):
        pieces = []
        for block in (value for value in parallel if value is not None):
            values = []
            for start in range(0, len(block.text), characters):
                end = min(len(block.text), start + characters)
                text = block.text[start:end]
                ref = block.ref.model_copy(
                    update={
                        "span": MaterialSpan(
                            start=block.ref.span.start + start, end=block.ref.span.start + end
                        ),
                        "content_digest": digest(text),
                        "selection_id": None,
                    }
                )
                values.append((block.model_copy(update={"text": text, "ref": ref}), block.ref))
            pieces.append(values)
        ordered.extend(
            value
            for parallel_pieces in zip_longest(*pieces)
            for value in parallel_pieces
            if value is not None
        )
    batches, current = [], []
    while ordered:
        block, parent = ordered.pop(0)
        if fits([*current, (block, parent)]):
            current.append((block, parent))
            continue
        if current:
            batches.append(current)
            current = []
            ordered.insert(0, (block, parent))
            continue
        if len(block.text) <= 1:
            raise BusinessError(
                "model_unavailable", "Reviewer cannot fit one exact source segment."
            )
        middle = len(block.text) // 2
        children = []
        for start, end in ((0, middle), (middle, len(block.text))):
            text = block.text[start:end]
            ref = block.ref.model_copy(
                update={
                    "span": MaterialSpan(
                        start=block.ref.span.start + start, end=block.ref.span.start + end
                    ),
                    "content_digest": digest(text),
                    "selection_id": None,
                }
            )
            children.append((block.model_copy(update={"text": text, "ref": ref}), parent))
        ordered[0:0] = children
    if current:
        batches.append(current)
    return batches


class MaterialReviewParts:
    def __init__(self, connection):
        self.connection = connection

    def exists(self, review_id):
        return (
            self.connection.execute(
                "SELECT id FROM knowledge.material_change_review_parts WHERE review_id=%s LIMIT 1",
                (review_id,),
            ).fetchone()
            is not None
        )

    def save(self, review_id, batches):
        for ordinal, pairs in enumerate(batches):
            self.connection.execute(
                "INSERT INTO knowledge.material_change_review_parts"
                "(id,review_id,ordinal,refs,parent_refs) VALUES (%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    review_id,
                    ordinal,
                    Jsonb([block.ref.model_dump(mode="json") for block, _parent in pairs]),
                    Jsonb([parent.model_dump(mode="json") for _block, parent in pairs]),
                ),
            )

    def pending(self, review_id):
        return self.connection.execute(
            "SELECT * FROM knowledge.material_change_review_parts WHERE review_id=%s "
            "AND status<>'reviewed' ORDER BY ordinal LIMIT 1 FOR UPDATE",
            (review_id,),
        ).fetchone()

    def aggregate(self, review_id, required_refs):
        parts = self.connection.execute(
            "SELECT * FROM knowledge.material_change_review_parts "
            "WHERE review_id=%s ORDER BY ordinal",
            (review_id,),
        ).fetchall()
        if not parts or any(part["status"] != "reviewed" for part in parts):
            return None
        by_parent = {ref.model_dump_json(): [] for ref in required_refs}
        results = []
        for part in parts:
            result = MaterialChangeVerdict(**part["result"])
            results.append(result)
            for raw_child, raw_parent in zip(part["refs"], part["parent_refs"], strict=True):
                child = MaterialRef(**raw_child)
                parent = MaterialRef(**raw_parent)
                key = parent.model_dump_json()
                if key not in by_parent:
                    raise BusinessError(
                        "precondition_failed", "Review segment has no required parent."
                    )
                by_parent[key].append(child)
        for ref in required_refs:
            require_covered([ref], by_parent[ref.model_dump_json()])
        labels = [result.classification for result in results]
        classification = (
            "uncertain"
            if "uncertain" in labels
            else "semantic_change"
            if "semantic_change" in labels
            else "editorial_equivalent"
        )
        descriptions = [
            f"{index + 1}: {result.summary}"
            for index, result in enumerate(results)
            if result.classification == classification
        ]
        heading = f"Complete review of {len(parts)} exact source segments. "
        summary = heading + " | ".join(descriptions)
        return MaterialChangeVerdict(
            classification=classification, summary=summary[:1200], reviewed_refs=required_refs
        )
