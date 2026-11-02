from __future__ import annotations

from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.python_contracts import PythonPack
from leornian.modules.item_bank.supply_contracts import (
    REVIEW_ROLES,
    BlindSolution,
    PackDocument,
    PackRequest,
    PackSummary,
    PracticeSet,
    ReviewDocument,
)
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.shared_kernel.errors import BusinessError


class Packs:
    """Owns immutable candidate documents, stage results and learner-scoped publication."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def row(self, actor: Actor, pack_id: UUID, *, lock: bool = False) -> dict:
        row = self.connection.execute(
            "SELECT * FROM item_bank.packs WHERE id = %s AND actor_id = %s"
            + (" FOR UPDATE" if lock else ""),
            (pack_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Item pack not found.")
        return row

    def request(
        self,
        actor,
        plan_id,
        key,
        data: PackRequest,
        materials,
        revision_feedback=None,
        *,
        supply_demand_id=None,
        transfer_feedback=None,
        session_digest=None,
        recovery_reason=None,
    ) -> tuple[dict, bool]:
        old = self.connection.execute(
            "SELECT * FROM item_bank.packs WHERE actor_id = %s AND idempotency_key = %s",
            (actor.id, key),
        ).fetchone()
        if old:
            expected = (
                plan_id,
                data.expected_plan_revision,
                data.node_key,
                data.instruction,
                data.predecessor_id,
                data.gate_feedback_id,
                data.transfer_feedback_id,
                data.kind,
                old["automatic"] if data.predecessor_id else data.automatic,
            )
            if (
                tuple(
                    old[k]
                    for k in (
                        "plan_id",
                        "plan_revision",
                        "node_key",
                        "instruction",
                        "predecessor_id",
                        "gate_feedback_id",
                        "transfer_feedback_id",
                        "kind",
                        "automatic",
                    )
                )
                != expected
            ):
                raise BusinessError("idempotency_conflict", "Pack key has different content.")
            return old, False
        revision = 1
        automatic = data.automatic
        if data.predecessor_id:
            parent = self.row(actor, data.predecessor_id, lock=True)
            automatic = parent["automatic"]
            session_digest = session_digest or parent["automation_session_digest"]
            eligible = (
                parent["status"] == "published"
                and data.gate_feedback_id is not None
                and revision_feedback is not None
                and revision_feedback["gate_id"] == str(data.gate_feedback_id)
                and revision_feedback["pack_id"] == str(parent["id"])
                if data.gate_feedback_id
                else parent["status"] == "changes_required"
                or (parent["automatic"] and parent["status"] == "failed")
            )
            if parent["automatic"] and parent["status"] == "published" and recovery_reason:
                eligible = True  # Coordinator-only fact: the previous binding is now stale.
            if data.transfer_feedback_id:
                eligible = (
                    parent["status"] == "published"
                    and transfer_feedback is not None
                    and transfer_feedback["transfer_id"] == str(data.transfer_feedback_id)
                    and str(parent["id"]) in transfer_feedback["candidate_pack_ids"]
                )
            if (
                not eligible
                or (parent["plan_id"], parent["plan_revision"], parent["node_key"])
                != (plan_id, data.expected_plan_revision, data.node_key)
                or parent["kind"] != data.kind
            ):
                raise BusinessError("precondition_failed", "No eligible revision predecessor.")
            child = self.connection.execute(
                "SELECT id FROM item_bank.packs WHERE predecessor_id = %s",
                (parent["id"],),
            ).fetchone()
            if child:
                raise BusinessError("precondition_failed", "This version already has a successor.")
            revision = parent["revision"] + 1
            supply_demand_id = parent["supply_demand_id"]
        if (data.gate_feedback_id is not None) != (revision_feedback is not None):
            raise BusinessError("precondition_failed", "Validated Gate feedback is required.")
        if (data.transfer_feedback_id is not None) != (transfer_feedback is not None):
            raise BusinessError("precondition_failed", "Validated transfer feedback is required.")
        pack_id = uuid4()
        if automatic and not session_digest:
            raise BusinessError("unauthorized", "Automatic supply needs current session authority.")
        self.connection.execute(
            "INSERT INTO item_bank.packs(id, actor_id, plan_id, plan_revision, node_key, "
            "idempotency_key, instruction, predecessor_id, revision, status, sources,"
            "gate_feedback_id,revision_feedback,supply_demand_id,transfer_feedback_id,"
            "transfer_feedback,kind,automatic,automation_session_digest) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'authoring',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                pack_id,
                actor.id,
                plan_id,
                data.expected_plan_revision,
                data.node_key,
                key,
                data.instruction,
                data.predecessor_id,
                revision,
                Jsonb([m.model_dump(mode="json") for m in materials]),
                data.gate_feedback_id,
                Jsonb(revision_feedback) if revision_feedback is not None else None,
                supply_demand_id,
                data.transfer_feedback_id,
                Jsonb(transfer_feedback) if transfer_feedback is not None else None,
                data.kind,
                automatic,
                session_digest if automatic else None,
            ),
        )
        if automatic:
            SupplyTasks(self.connection).attach(
                actor, pack_id, session_digest, parent if data.predecessor_id else None
            )
        return self.row(actor, pack_id), True

    def stage(self, run_id: UUID) -> dict | None:
        return self.connection.execute(
            "SELECT run_id, pack_id, role, result FROM item_bank.stages WHERE run_id = %s",
            (run_id,),
        ).fetchone()

    def add_stage(self, pack_id, run_id, role):
        self.connection.execute(
            "INSERT INTO item_bank.stages(pack_id, run_id, role) VALUES (%s,%s,%s)",
            (pack_id, run_id, role),
        )

    def stages(self, pack_id) -> list[dict]:
        return self.connection.execute(
            "SELECT run_id, role, result FROM item_bank.stages WHERE pack_id = %s "
            "ORDER BY created_at, run_id",
            (pack_id,),
        ).fetchall()

    def summary(self, actor: Actor, pack_id: UUID) -> PackSummary:
        row = self.row(actor, pack_id)
        stages = self.stages(pack_id)
        reviewed = [s for s in stages if s["role"] in REVIEW_ROLES and s["result"]]
        blind = next((s["result"] for s in stages if s["role"] == "blind"), None)
        pending = next((stage for stage in stages if stage["result"] is None), None)
        task = SupplyTasks(self.connection).for_pack(actor, pack_id)
        return PackSummary(
            **{
                key: row[key]
                for key in (
                    "id",
                    "plan_id",
                    "plan_revision",
                    "node_key",
                    "revision",
                    "predecessor_id",
                    "gate_feedback_id",
                    "transfer_feedback_id",
                    "supply_demand_id",
                    "kind",
                    "status",
                    "created_at",
                    "published_at",
                    "automatic",
                    "automation_error",
                    "supply_task_id",
                )
            },
            reviewed_roles=[s["role"] for s in reviewed],
            passed_roles=[
                s["role"] for s in reviewed if ReviewDocument.model_validate(s["result"]).passed
            ],
            blind_passed=self.blind_passed(row, blind) if blind else None,
            item_count=len(row["document"]["items"]) if row["document"] else 0,
            pending_run_id=pending["run_id"] if pending else None,
            pending_role=pending["role"] if pending else None,
            automation_status=task["status"] if task else None,
            automation_action=task["action"] if task else None,
            automation_reason=task["reason"] if task else None,
        )

    def list(self, actor) -> list[PackSummary]:
        rows = self.connection.execute(
            "SELECT id FROM item_bank.packs WHERE actor_id = %s "
            "ORDER BY created_at DESC, id LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [self.summary(actor, row["id"]) for row in rows]

    def status(self, pack_id, value):
        self.connection.execute(
            "UPDATE item_bank.packs SET status = %s WHERE id = %s", (value, pack_id)
        )

    def record_author(self, row, run_id, document: PackDocument):
        if row["supply_demand_id"]:
            demand = self.connection.execute(
                "SELECT allowed_difficulties,context_data "
                "FROM item_bank.supply_demands WHERE id=%s",
                (row["supply_demand_id"],),
            ).fetchone()
            for item in document.items:
                if not item.slot.startswith("practice_"):
                    continue
                if item.difficulty not in demand["allowed_difficulties"] or any(
                    "".join(item.prompt.split()).casefold()
                    == "".join(prior["question"]["prompt"].split()).casefold()
                    for prior in demand["context_data"]["actual_exposures"]
                ):
                    raise BusinessError(
                        "invalid_item_output", "Supply candidates violate the bound training need."
                    )
        allowed = {(ref["source_id"], ref["revision"]) for ref in row["sources"]}
        for item in document.items:
            refs = [(str(ref.source_id), ref.revision) for ref in item.source_refs]
            if len(refs) != len(set(refs)) or not set(refs) <= allowed:
                raise BusinessError("invalid_item_output", "Question cites an unbound source.")
        if row["predecessor_id"]:
            parent = self.connection.execute(
                "SELECT document FROM item_bank.packs WHERE id = %s",
                (row["predecessor_id"],),
            ).fetchone()
            if document.model_dump(mode="json") == parent["document"]:
                raise BusinessError("invalid_item_output", "A revision must change actual content.")
        self.connection.execute(
            "UPDATE item_bank.packs SET document = %s WHERE id = %s AND document IS NULL",
            (Jsonb(document.model_dump(mode="json")), row["id"]),
        )
        self.record_stage(run_id, {"validated": True})
        self.status(row["id"], "blind_solving")

    def record_stage(self, run_id, result):
        self.connection.execute(
            "UPDATE item_bank.stages SET result = %s WHERE run_id = %s AND result IS NULL",
            (Jsonb(result), run_id),
        )

    def blind_passed(self, row, result):
        if row["kind"] == "python_io":
            receipts = self.connection.execute(
                "SELECT slot,outcome FROM item_bank.python_qualifications WHERE pack_id=%s",
                (row["id"],),
            ).fetchall()
            if len(receipts) != 5 or any(r["outcome"] is None for r in receipts):
                return None
            return all(r["outcome"] == "passed" for r in receipts)
        document = PackDocument.model_validate(row["document"])
        solution = BlindSolution.model_validate(result)
        gold = {item.slot: item.correct_key for item in document.items}
        return all(gold[answer.slot] == answer.selected_key for answer in solution.answers)

    def eligible(self, row) -> bool:
        stages = self.stages(row["id"])
        blind = next((s["result"] for s in stages if s["role"] == "blind"), None)
        reviews = {s["role"]: s["result"] for s in stages if s["role"] in REVIEW_ROLES}
        return bool(
            row["document"]
            and blind
            and self.blind_passed(row, blind)
            and set(reviews) == set(REVIEW_ROLES)
            and all(
                value and ReviewDocument.model_validate(value).passed for value in reviews.values()
            )
        )

    def publish(self, actor, pack_id) -> tuple[PackSummary, bool]:
        row = self.row(actor, pack_id, lock=True)
        if row["status"] == "published":
            return self.summary(actor, pack_id), False
        if row["status"] != "ready" or not self.eligible(row):
            raise BusinessError("precondition_failed", "Complete blind and six-role review first.")
        self.connection.execute(
            "UPDATE item_bank.packs SET status = 'published', published_at = now() WHERE id = %s",
            (pack_id,),
        )
        return self.summary(actor, pack_id), True

    def practice(self, actor, pack_id) -> PracticeSet:
        row = self.row(actor, pack_id)
        self.require_choice(row)
        if row["status"] != "published":
            raise BusinessError("precondition_failed", "Only a published pack can be opened.")
        document = PackDocument.model_validate(row["document"])
        questions = [item.public() for item in document.items if item.slot.startswith("practice_")]
        for question in questions:
            Exposures(self.connection).record(actor, pack_id, question)
        return PracticeSet(pack_id=pack_id, questions=questions)

    def answer_material(self, actor, pack_id, slot):
        row = self.row(actor, pack_id)
        self.require_choice(row)
        if row["status"] != "published" or slot not in {
            "practice_1",
            "practice_2",
            "remediation_1",
        }:
            raise BusinessError("precondition_failed", "Only opened training can be answered.")
        exposed = self.connection.execute(
            "SELECT slot FROM item_bank.exposures WHERE pack_id = %s AND slot = %s",
            (pack_id, slot),
        ).fetchone()
        if not exposed:
            raise BusinessError("precondition_failed", "Open the practice before answering.")
        return next(
            item for item in PackDocument.model_validate(row["document"]).items if item.slot == slot
        )

    def published_document(self, actor, pack_id):
        row = self.row(actor, pack_id)
        if row["status"] != "published" or not self.eligible(row):
            raise BusinessError(
                "precondition_failed", "A fully reviewed published pack is required."
            )
        return self.document(row)

    @staticmethod
    def document(row):
        schema = PythonPack if row["kind"] == "python_io" else PackDocument
        return schema.model_validate(row["document"])

    @staticmethod
    def require_choice(row):
        if row["kind"] != "choice":
            raise BusinessError("precondition_failed", "Use the Python execution endpoints.")

    def register_qualification(self, pack_id, slot, attempt_id):
        self.connection.execute(
            "INSERT INTO item_bank.python_qualifications(pack_id,slot,attempt_id) VALUES(%s,%s,%s)",
            (pack_id, slot, attempt_id),
        )

    def qualification_result(self, pack_id, attempt_id, status):
        changed = self.connection.execute(
            "UPDATE item_bank.python_qualifications SET outcome=%s "
            "WHERE pack_id=%s AND attempt_id=%s AND outcome IS NULL RETURNING slot",
            (status, pack_id, attempt_id),
        ).fetchone()
        if not changed:
            return False
        rows = self.connection.execute(
            "SELECT outcome FROM item_bank.python_qualifications WHERE pack_id=%s",
            (pack_id,),
        ).fetchall()
        return len(rows) == 5 and all(row["outcome"] is not None for row in rows)

    def remediation_material(self, actor, pack_id, failed_slot):
        document = self.published_document(actor, pack_id)
        parent = next(item for item in document.items if item.slot == failed_slot)
        child = next(item for item in document.items if item.slot == "remediation_1")
        if child.difficulty > parent.difficulty:
            raise BusinessError("precondition_failed", "Remediation must not be harder.")
        return child

    def expose_remediation(self, actor, pack_id):
        document = self.published_document(actor, pack_id)
        item = next(item for item in document.items if item.slot == "remediation_1")
        Exposures(self.connection).record(actor, pack_id, item)
        return item.public()

    def assessment_materials(self, actor, pack_id):
        document = self.published_document(actor, pack_id)
        return [item for item in document.items if item.slot.startswith("assessment_")]

    def open_assessment(self, actor, pack_id):
        items = self.assessment_materials(actor, pack_id)
        for item in items:
            Exposures(self.connection).record(actor, pack_id, item)
        return [item.public() for item in items]

    def transfer_candidates(self, actor, source_pack, failed_slots, used_keys, exposures):
        original = self.published_document(actor, source_pack["id"])
        allowed_difficulties = {1, 2, 3, 4, 5}
        for item in original.items:
            if item.slot in failed_slots:
                allowed_difficulties &= {item.difficulty, max(1, item.difficulty - 1)}
        rows = self.connection.execute(
            "SELECT * FROM item_bank.packs WHERE actor_id=%s AND plan_id=%s "
            "AND plan_revision=%s AND node_key=%s AND status='published' AND id<>%s "
            "ORDER BY published_at,id",
            (
                actor.id,
                source_pack["plan_id"],
                source_pack["plan_revision"],
                source_pack["node_key"],
                source_pack["id"],
            ),
        ).fetchall()
        used = set(used_keys) | {item["key"] for item in exposures}
        source_refs = {(ref["source_id"], ref["revision"]) for ref in source_pack["sources"]}
        candidates = []
        for pack in rows:
            if (
                pack["kind"] != source_pack["kind"]
                or not self.eligible(pack)
                or {(ref["source_id"], ref["revision"]) for ref in pack["sources"]} != source_refs
            ):
                continue
            for item in self.document(pack).items:
                key = str(pack["id"]) + ":" + item.slot
                if (
                    not item.slot.startswith("practice_")
                    or key in used
                    or item.difficulty not in allowed_difficulties
                ):
                    continue
                question = item.public().model_dump(mode="json")
                if any(
                    "".join(question["prompt"].split()).casefold()
                    == "".join(prior["question"]["prompt"].split()).casefold()
                    for prior in exposures
                ):
                    continue
                candidates.append({"key": key, "pack_id": str(pack["id"]), "question": question})
                if len(candidates) == 2:
                    return candidates
        return candidates

    def transfer_material(self, actor, pack_id, slot):
        if slot not in {"practice_1", "practice_2"}:
            raise BusinessError("precondition_failed", "Transfer uses an exact practice slot.")
        return next(
            item for item in self.published_document(actor, pack_id).items if item.slot == slot
        )

    def opened_python_training(self, actor, pack_id, slot):
        row = self.row(actor, pack_id)
        if row["kind"] != "python_io" or slot not in {"practice_1", "practice_2", "remediation_1"}:
            raise BusinessError("precondition_failed", "Opened Python training is required.")
        if not self.connection.execute(
            "SELECT 1 FROM item_bank.exposures WHERE pack_id=%s AND slot=%s", (pack_id, slot)
        ).fetchone():
            raise BusinessError("precondition_failed", "Open the exact task first.")
        return next(i for i in self.published_document(actor, pack_id).items if i.slot == slot)
