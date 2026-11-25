from __future__ import annotations

from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.item_bank.assistance_contracts import (
    ChoiceDirectAnswer,
    ProgramDirectAnswer,
    PythonDirectAnswer,
    ResponseDirectAnswer,
)
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.generation_contracts import (
    BankPack,
    GenerationReport,
    GenerationStage,
)
from leornian.modules.item_bank.program_contracts import (
    HttpPack,
    ProjectPack,
    SqlPack,
    StdioPack,
    WebPack,
)
from leornian.modules.item_bank.python_contracts import PythonPack
from leornian.modules.item_bank.response_contracts import (
    BlindResponses,
    ResponsePack,
    ResponsePracticeSet,
    compare_response,
)
from leornian.modules.item_bank.supply_contracts import (
    REVIEW_ROLES,
    BlindSolution,
    PackDocument,
    PackMaterialContext,
    PackRequest,
    PackSummary,
    PracticeSet,
    ReviewDocument,
)
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.learning.contracts import citation_key
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

    def published_for_node(self, actor, plan_id, revision, node_key, before=None, limit=20):
        return self.connection.execute(
            "SELECT * FROM item_bank.packs WHERE actor_id=%s AND plan_id=%s "
            "AND plan_revision=%s AND node_key=%s AND status='published' "
            "AND (%s::uuid IS NULL OR id<%s) ORDER BY id DESC LIMIT %s",
            (actor.id, plan_id, revision, node_key, before, before, limit),
        ).fetchall()

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
        material_context: PackMaterialContext | None = None,
    ) -> tuple[dict, bool]:
        response_formats = (
            data.response_formats.model_dump(mode="json") if data.response_formats else None
        )
        program_environment = (
            data.program_environment.model_dump(mode="json") if data.program_environment else None
        )
        if data.predecessor_id:
            parent = self.row(actor, data.predecessor_id, lock=True)
            if program_environment != parent["program_environment"]:
                raise BusinessError(
                    "precondition_failed", "A revision must preserve its exact program environment."
                )
            if response_formats is not None and response_formats != parent["response_formats"]:
                raise BusinessError(
                    "precondition_failed", "A revision must preserve requested practice formats."
                )
            response_formats = parent["response_formats"]
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
                response_formats,
                program_environment,
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
                        "response_formats",
                        "program_environment",
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
            "transfer_feedback,kind,automatic,automation_session_digest,material_context,"
            "response_formats,program_environment) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'authoring',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                Jsonb(material_context.model_dump(mode="json")) if material_context else None,
                Jsonb(response_formats) if response_formats is not None else None,
                Jsonb(program_environment) if program_environment is not None else None,
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
            response_formats=row["response_formats"],
            program_environment=row["program_environment"],
        )

    def list(self, actor) -> list[PackSummary]:
        rows = self.connection.execute(
            "SELECT id FROM item_bank.packs WHERE actor_id = %s "
            "ORDER BY created_at DESC, id LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [self.summary(actor, row["id"]) for row in rows]

    def directory(self, actor, plan_id):
        return [BankPack(**row) for row in self.connection.execute(
            "SELECT id,plan_revision,node_key,revision,kind,status,created_at,"
            "predecessor_id,supply_task_id FROM item_bank.packs WHERE actor_id=%s AND plan_id=%s "
            "ORDER BY created_at DESC,id DESC", (actor.id, plan_id),
        ).fetchall()]

    def generation_report(self, actor, pack_id, get_run):
        pack = self.row(actor, pack_id)
        stages = []
        for stage in self.stages(pack_id):
            role, result = stage["role"], stage["result"] or {}
            run = get_run(actor.id, stage["run_id"])
            details = {}
            if result and role == "author":
                details["item_count"] = len(pack["document"]["items"])
            elif result and role == "blind":
                details["item_count"] = len(result.get("programs", result.get("answers", [])))
                details["blind_passed"] = self.blind_passed(pack, result)
            elif result and role in REVIEW_ROLES:
                review = ReviewDocument.model_validate(result)
                details["decisions"] = {item.slot: item.verdict for item in review.items}
                details["independence"] = review.assessment_independence
            stages.append(GenerationStage(
                role=role, status=run.status, started_at=run.created_at,
                completed_at=run.completed_at, public_notes=result.get("public_notes", []),
                **details,
            ))
        qualifications = {}
        if pack["kind"] not in {"choice", "response"}:
            table = ("python_qualifications" if pack["kind"] == "python_io"
                     else "program_qualifications")
            qualifications = {row["state"]: row["total"] for row in self.connection.execute(
                f"SELECT coalesce(outcome,'pending') AS state,count(*) AS total "
                f"FROM item_bank.{table} WHERE pack_id=%s GROUP BY outcome", (pack_id,),
            ).fetchall()}
        return GenerationReport(pack_id=pack_id, status=pack["status"], stages=stages,
                                qualifications=qualifications, published_at=pack["published_at"])

    def status(self, pack_id, value):
        self.connection.execute(
            "UPDATE item_bank.packs SET status = %s WHERE id = %s", (value, pack_id)
        )

    def environment_unavailable(self, pack_id):
        self.connection.execute(
            "UPDATE item_bank.packs SET automation_error='program_environment_unavailable' "
            "WHERE id=%s", (pack_id,),
        )

    def record_author(self, row, run_id, document: PackDocument):
        if not self.matches_response_formats(row, document):
            raise BusinessError(
                "invalid_item_output", "Ordinary questions must match requested response formats."
            )
        if not self.matches_program_environment(row, document):
            raise BusinessError("invalid_item_output", "The frozen program environment changed.")
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
        context = self.material_context(row)
        allowed_materials = (
            {citation_key(c) for c in context.author_citations} if context else set()
        )
        for item in document.items:
            refs = [(str(ref.source_id), ref.revision) for ref in item.source_refs]
            citations = [citation_key(c) for c in item.material_citations]
            if (
                len(refs) != len(set(refs)) or not set(refs) <= allowed
                or len(citations) != len(set(citations))
                or not set(citations) <= allowed_materials
            ):
                raise BusinessError("invalid_item_output", "Question cites an unbound source.")
        item_document = document.model_dump(mode="json", exclude={"public_notes"})
        if row["predecessor_id"]:
            parent = self.connection.execute(
                "SELECT document FROM item_bank.packs WHERE id = %s",
                (row["predecessor_id"],),
            ).fetchone()
            if item_document == parent["document"]:
                raise BusinessError("invalid_item_output", "A revision must change actual content.")
        self.connection.execute(
            "UPDATE item_bank.packs SET document = %s WHERE id = %s AND document IS NULL",
            (Jsonb(item_document), row["id"]),
        )
        notes = document.model_dump(include={"public_notes"})
        self.record_stage(run_id, {"validated": True, **notes})
        self.status(row["id"], "blind_solving")

    def record_stage(self, run_id, result):
        self.connection.execute(
            "UPDATE item_bank.stages SET result = %s WHERE run_id = %s AND result IS NULL",
            (Jsonb(result), run_id),
        )

    @staticmethod
    def material_context(row) -> PackMaterialContext | None:
        value = row.get("material_context")
        return PackMaterialContext.model_validate(value) if value is not None else None

    def bind_prepared_materials(self, actor, row, role, citations):
        """Freeze a role's node material only after its preparation has completed."""
        current = self.row(actor, row["id"])
        context = self.material_context(current)
        field = "author_citations" if role == "author" else "review_citations"
        previous = getattr(context, field)
        if not citations or previous and previous != citations:
            raise BusinessError("stale_version", "Prepared item materials changed.")
        value = PackMaterialContext.model_validate({
            **context.model_dump(), field: citations,
        }).model_dump(mode="json")
        self.connection.execute(
            "UPDATE item_bank.packs SET material_context=%s WHERE id=%s AND actor_id=%s",
            (Jsonb(value), row["id"], actor.id),
        )
        row["material_context"] = value

    @staticmethod
    def valid_review_citations(row, report):
        context = Packs.material_context(row)
        allowed = {citation_key(c) for c in context.review_citations} if context else set()
        for item in report.items:
            citations = [citation_key(c) for c in item.material_citations]
            if (
                (allowed and not citations) or len(citations) != len(set(citations))
                or not set(citations) <= allowed
            ):
                return False
        return True

    @staticmethod
    def matches_response_formats(row, document):
        formats = row.get("response_formats")
        return formats is None or (
            row["kind"] == "response"
            and all(
                item.public().response_type == formats[item.slot]
                for item in document.items if item.slot in formats
            )
        )

    @staticmethod
    def matches_program_environment(row, document):
        if row["kind"] not in {
            "sql_query", "python_project", "project_stdio", "web_project", "http_project",
        }:
            return row.get("program_environment") is None
        return bool(row.get("program_environment")) and all(
            item.environment.model_dump(mode="json") == row["program_environment"]
            for item in document.items
        )

    def record_review(self, row, run_id, report):
        if not self.valid_review_citations(row, report):
            raise BusinessError("invalid_item_output", "Review needs its exact supplied citations.")
        self.record_stage(run_id, report.model_dump(mode="json"))

    def blind_passed(self, row, result):
        if row["kind"] in {
            "sql_query", "python_project", "project_stdio", "web_project", "http_project",
        }:
            receipts = self.connection.execute(
                "SELECT slot,outcome FROM item_bank.program_qualifications WHERE pack_id=%s",
                (row["id"],),
            ).fetchall()
            if len(receipts) != 5 or any(r["outcome"] is None for r in receipts):
                return None
            return all(r["outcome"] == "passed" for r in receipts)
        if row["kind"] == "python_io":
            receipts = self.connection.execute(
                "SELECT slot,outcome FROM item_bank.python_qualifications WHERE pack_id=%s",
                (row["id"],),
            ).fetchall()
            if len(receipts) != 5 or any(r["outcome"] is None for r in receipts):
                return None
            return all(r["outcome"] == "passed" for r in receipts)
        if row["kind"] == "response":
            comparisons = self.response_blind_checks(row, result)
            return (
                False if False in comparisons
                else None if None in comparisons
                else True
            )
        document = PackDocument.model_validate(row["document"])
        solution = BlindSolution.model_validate(result)
        gold = {item.slot: item.correct_key for item in document.items}
        return all(gold[answer.slot] == answer.selected_key for answer in solution.answers)

    @staticmethod
    def response_blind_checks(row, result):
        document = ResponsePack.model_validate(row["document"])
        answers = BlindResponses.model_validate(result)
        gold = {item.slot: item for item in document.items}
        try:
            return [
                compare_response(gold[a.slot].public(), a.response, gold[a.slot].answer)
                for a in answers.answers
            ]
        except ValueError:
            return [False]

    def eligible(self, row) -> bool:
        stages = self.stages(row["id"])
        blind = next((s["result"] for s in stages if s["role"] == "blind"), None)
        reviews = {s["role"]: s["result"] for s in stages if s["role"] in REVIEW_ROLES}
        return bool(
            row["document"]
            and self.matches_response_formats(row, self.document(row))
            and self.matches_program_environment(row, self.document(row))
            and blind
            and (
                False not in self.response_blind_checks(row, blind)
                if row["kind"] == "response" and blind
                else self.blind_passed(row, blind)
            )
            and set(reviews) == set(REVIEW_ROLES)
            and all(
                value and ReviewDocument.model_validate(value).passed
                and self.valid_review_citations(row, ReviewDocument.model_validate(value))
                for value in reviews.values()
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

    def direct_answer(self, actor, pack_id, slot):
        if slot not in {"practice_1", "practice_2"}:
            raise BusinessError("precondition_failed", "Only ordinary practice allows assistance.")
        row = self.row(actor, pack_id)
        document = self.published_document(actor, pack_id)
        if not self.connection.execute(
            "SELECT 1 FROM item_bank.exposures WHERE pack_id=%s AND slot=%s", (pack_id, slot),
        ).fetchone():
            raise BusinessError(
                "precondition_failed", "The exact practice must be delivered first.",
            )
        item = next(item for item in document.items if item.slot == slot)
        if row["kind"] == "response":
            content = ResponseDirectAnswer(**item.answer.model_dump())
        elif row["kind"] in {
            "python_io", "sql_query", "python_project",
            "project_stdio", "web_project", "http_project",
        }:
            blind = next(
                stage["result"] for stage in self.stages(pack_id) if stage["role"] == "blind"
            )
            reference = next(answer for answer in blind["programs"] if answer["slot"] == slot)
            content = (
                PythonDirectAnswer(code=reference["code"], explanation=item.explanation)
                if row["kind"] == "python_io"
                else ProgramDirectAnswer(answer=reference["answer"], explanation=item.explanation)
            )
        else:
            content = ChoiceDirectAnswer(
                correct_key=item.correct_key, explanation=item.explanation,
            )
        return item, content

    @staticmethod
    def document(row):
        return Packs.document_schema(row["kind"]).model_validate(row["document"])

    @staticmethod
    def document_schema(kind):
        return {
            "python_io": PythonPack, "choice": PackDocument, "response": ResponsePack,
            "sql_query": SqlPack, "python_project": ProjectPack,
            "project_stdio": StdioPack, "web_project": WebPack, "http_project": HttpPack,
        }[kind]

    def response_practice(self, actor, pack_id):
        row = self.row(actor, pack_id)
        if row["kind"] != "response":
            raise BusinessError("precondition_failed", "Use the matching published response pack.")
        document = self.published_document(actor, pack_id)
        questions = [item.public() for item in document.items if item.slot.startswith("practice_")]
        for question in questions:
            Exposures(self.connection).record(actor, pack_id, question)
        return ResponsePracticeSet(pack_id=pack_id, questions=questions)

    def response_material(self, actor, pack_id, slot):
        row = self.row(actor, pack_id)
        if row["kind"] != "response" or slot not in {"practice_1", "practice_2"}:
            raise BusinessError("precondition_failed", "An ordinary response practice is required.")
        if not self.connection.execute(
            "SELECT 1 FROM item_bank.exposures WHERE pack_id=%s AND slot=%s", (pack_id, slot)
        ).fetchone():
            raise BusinessError("precondition_failed", "Open the exact response practice first.")
        return next(i for i in self.published_document(actor, pack_id).items if i.slot == slot)

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

    def register_program_qualification(self, pack_id, slot, attempt_id):
        self.connection.execute(
            "INSERT INTO item_bank.program_qualifications(pack_id,slot,attempt_id) "
            "VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (pack_id, slot, attempt_id),
        )

    def program_qualification_result(self, pack_id, attempt_id, status):
        changed = self.connection.execute(
            "UPDATE item_bank.program_qualifications SET outcome=%s WHERE pack_id=%s "
            "AND attempt_id=%s AND outcome IS NULL RETURNING slot",
            (status, pack_id, attempt_id),
        ).fetchone()
        if not changed:
            return False
        rows = self.connection.execute(
            "SELECT outcome FROM item_bank.program_qualifications WHERE pack_id=%s", (pack_id,),
        ).fetchall()
        return len(rows) == 5 and all(row["outcome"] is not None for row in rows)

    def opened_program_training(self, actor, pack_id, slot):
        row = self.row(actor, pack_id)
        if (
            row["kind"] not in {
                "sql_query", "python_project", "project_stdio", "web_project", "http_project",
            }
            or slot not in {"practice_1", "practice_2", "remediation_1"}
        ):
            raise BusinessError("precondition_failed", "An ordinary program practice is required.")
        if not self.connection.execute(
            "SELECT 1 FROM item_bank.exposures WHERE pack_id=%s AND slot=%s", (pack_id, slot),
        ).fetchone():
            raise BusinessError("precondition_failed", "Open the exact program practice first.")
        return next(i for i in self.published_document(actor, pack_id).items if i.slot == slot)

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
                or pack.get("program_environment") != source_pack.get("program_environment")
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
