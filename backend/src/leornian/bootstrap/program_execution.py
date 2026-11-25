from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.contracts import ProgramCompletion
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.program_contracts import ProgramReceipt
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.assessment.transfers import Transfers
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import ProgramExecutionClaim
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import Actor
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.learning.progress import Progress
from leornian.modules.tutor.evaluations import Evaluations
from leornian.shared_kernel.errors import BusinessError


class ProgramWorkflow:
    """SQL/projects use the original quality chain, Assessment and execution queue."""

    def __init__(self, database):
        self.database = database

    @staticmethod
    def current(connection, actor, source):
        pack = Packs(connection).row(actor, source["pack_id"])
        if pack["kind"] not in {
            "sql_query", "python_project", "project_stdio", "web_project", "http_project",
        }:
            raise BusinessError("precondition_failed", "A program pack is required.")
        ItemSupply.current(connection, actor, pack)
        if source["purpose"] == "qualification":
            SupplyTasks(connection).require_current(actor, pack["id"])
            if pack["status"] != "qualifying":
                raise BusinessError("precondition_failed", "Qualification is no longer current.")
        elif source["purpose"] == "gate":
            gate = Gates(connection).row(actor, source["gate_id"], lock=True)
            if gate["status"] != "submitted":
                raise BusinessError("precondition_failed", "The submitted program Gate changed.")
            ConceptGate.current(connection, actor, gate)
        elif source["purpose"] == "transfer":
            from leornian.bootstrap.transfer import TransferWorkflow

            Gates(connection).require_no_exam(actor)
            transfer = Transfers(connection).row(actor, source["transfer_id"], lock=True)
            if (
                transfer["status"] != "submitted" or transfer["program_result_id"] != source["id"]
                or transfer["candidate_pack_id"] != source["pack_id"]
                or transfer["candidate_slot"] != source["slot"]
            ):
                raise BusinessError("precondition_failed", "The exact program successor changed.")
            TransferWorkflow.current(connection, actor, transfer)
        else:
            Gates(connection).require_no_exam(actor)
            Packs(connection).published_document(actor, pack["id"])
        if source["environment"] != pack["program_environment"]:
            raise BusinessError("stale_version", "The exact program environment changed.")
        return pack

    @staticmethod
    def qualify(connection, actor, pack, digest):
        stage = next(s for s in Packs(connection).stages(pack["id"]) if s["role"] == "blind")
        schema = ItemSupply.blind_schema(pack["kind"])
        answers = {
            value.slot: value.answer
            for value in schema.model_validate(stage["result"]).programs
        }
        for item in Packs.document(pack).items:
            row, _ = ProgramAssessment(connection).create(
                actor, pack["id"], item, answers[item.slot],
                "program-qualification:" + str(pack["id"]) + ":" + item.slot, "qualification",
            )
            Packs(connection).register_program_qualification(pack["id"], item.slot, row["id"])
            Execution(connection).enqueue_program(
                actor, row["id"], digest, row["environment"],
            )
        ItemSupply.event(connection, actor.id, pack["id"])

    @staticmethod
    def claim_in(connection, work):
        owner = Actor(id=work["actor_id"], display_name="")
        assessment = ProgramAssessment(connection)
        source = assessment.row(owner, work["program_input_ref"])
        try:
            with connection.transaction():
                actor = Identity(
                    PgIdentityStore(connection, lock_session=True),
                ).authenticate_digest(work["session_digest"] or "")
                if actor.id != owner.id:
                    raise BusinessError("unauthorized", "Execution owner changed.")
                if source["environment"] != work["program_environment"]:
                    raise BusinessError("stale_version", "The exact execution environment changed.")
                ProgramWorkflow.current(connection, actor, source)
        except BusinessError as error:
            Execution(connection).abandon(work["id"], error.code)
            assessment.fail(
                source["id"], "Authorization, material, version or pack changed.", error.code,
            )
            ProgramWorkflow.after_result(connection, owner, source, work["session_digest"], False)
            return None
        return ProgramExecutionClaim(
            job_id=work["id"], claim_token=work["claim_token"], program=source["execution_input"],
        )

    @staticmethod
    def report_in(connection, existing, job_id, report):
        owner = Actor(id=existing["actor_id"], display_name="")
        assessment = ProgramAssessment(connection)
        source = assessment.row(owner, existing["program_input_ref"])
        current = True
        invalid_code = None
        try:
            actor = Identity(
                PgIdentityStore(connection, serialize_actor=True),
            ).authenticate_digest(existing["session_digest"] or "")
            if actor.id != owner.id:
                raise BusinessError("unauthorized", "Execution owner changed.")
        except BusinessError as error:
            current, invalid_code = False, error.code
        if source["gate_id"]:
            Gates(connection).row(owner, source["gate_id"], lock=True)
        if source["transfer_id"]:
            Transfers(connection).row(owner, source["transfer_id"], lock=True)
        try:
            with connection.transaction():
                if current:
                    ProgramWorkflow.current(connection, actor, source)
        except BusinessError as error:
            current = False
            invalid_code = error.code
        _, first, timely = Execution(connection).report(job_id, report)
        if not first:
            return
        if current and timely:
            assessment.complete(source, report.cases, report.compilation)
        else:
            assessment.fail(
                source["id"], "Receipt kept; authorization, material or lease expired.",
                invalid_code or "runner_lease_expired",
            )
        ProgramWorkflow.after_result(connection, owner, source, existing["session_digest"],
                                     current and timely)

    @staticmethod
    def after_result(connection, actor, original, digest, applicable):
        assessment = ProgramAssessment(connection)
        source = assessment.row(actor, original["id"])
        packs = Packs(connection)
        pack = packs.row(actor, source["pack_id"], lock=True)
        if source["purpose"] == "qualification":
            all_done = packs.program_qualification_result(
                pack["id"], source["id"], source["status"],
            )
            if pack["status"] == "qualifying":
                if not applicable or source["status"] == "error":
                    packs.status(pack["id"], "failed")
                    if source["error_code"] == "runner_environment_unavailable":
                        packs.environment_unavailable(pack["id"])
                elif all_done:
                    packs.status(pack["id"], "reviewing")
                    PythonWorkflow.continue_review_in(connection, actor, pack, digest)
        elif source["purpose"] == "transfer":
            from leornian.bootstrap.transfer import TransferWorkflow

            transfers = Transfers(connection)
            transfers.complete_program(source["transfer_id"], source)
            ProgramWorkflow.feedback(connection, actor, pack, source)
            TransferWorkflow.event(
                connection, actor.id, transfers.row(actor, source["transfer_id"]),
            )
        elif source["purpose"] == "gate":
            gates = Gates(connection)
            gate = gates.row(actor, source["gate_id"], lock=True)
            rows = assessment.for_pack(actor, pack["id"], "gate")
            if (
                gate["status"] == "submitted" and len(rows) == 2
                and all(row["status"] != "queued" for row in rows)
            ):
                passed = all(row["status"] == "passed" for row in rows)
                gate = gates.complete_program(
                    actor, gate, passed,
                    error_code="program_execution_unavailable" if any(
                        row["status"] == "error" for row in rows
                    ) else None,
                )
                for row in rows:
                    ProgramWorkflow.feedback(connection, actor, pack, row)
                if passed and Progress(connection).apply_program(
                    actor, ProgramCompletion(
                        gate_id=gate["id"], plan_id=gate["plan_id"],
                        plan_revision=gate["plan_revision"], node_key=gate["node_key"],
                    ),
                ):
                    Events(connection).append(
                        actor.id, "learning.node_completed", gate["id"],
                        EventPayload(
                            gate_id=gate["id"], pack_id=pack["id"], plan_id=gate["plan_id"],
                            plan_revision=gate["plan_revision"],
                        ),
                    )
                ConceptGate.event(connection, actor.id, gate)
        else:
            ProgramWorkflow.feedback(connection, actor, pack, source)
            from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

            LearningArtifactWorkflow.owner_result(
                connection, actor, pack["id"], source["slot"], "program", source["id"], "completed",
            )
        ItemSupply.event(connection, actor.id, pack["id"])

    @staticmethod
    def feedback(connection, actor, pack, source):
        if source["purpose"] in {"training", "gate", "transfer"}:
            item = next(i for i in Packs.document(pack).items if i.slot == source["slot"])
            receipt = ProgramReceipt(
                attempt_id=source["id"], answer=source["answer"],
                correct=None if source["status"] == "error" else source["status"] == "passed",
                passed_cases=source["passed_cases"],
                explanation=source["feedback"] or "Result recorded.",
            )
            Exposures(connection).record(actor, pack["id"], item, receipt, receipt_ref=source["id"])
            if receipt.correct is not None:
                Evaluations(connection).enqueue(
                    actor, pack["id"], "program", source["id"], item.public(), receipt,
                )

    def continue_review(self, token, pack_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            pack = Packs(connection).row(actor, pack_id)
            ItemSupply.current(connection, actor, pack)
            Gates(connection).require_no_exam(actor)
            if pack["kind"] not in {
                "sql_query", "python_project", "project_stdio", "web_project", "http_project",
            } or pack["status"] != "reviewing":
                raise BusinessError(
                    "precondition_failed", "No qualified program review to continue.",
                )
            PythonWorkflow.continue_review_in(connection, actor, pack, Identity.digest(token))
            ItemSupply.event(connection, actor.id, pack_id)
            return Packs(connection).summary(actor, pack_id)

    def training(self, token, pack_id, *, remediation=False):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Gates(connection).require_no_exam(actor)
            Transfers(connection).require_regular_practice(actor, pack_id)
            pack = Packs(connection).row(actor, pack_id)
            ItemSupply.current(connection, actor, pack)
            if pack["kind"] not in {
                "sql_query", "python_project", "project_stdio", "web_project", "http_project",
            }:
                raise BusinessError("precondition_failed", "A program pack is required.")
            items = Packs(connection).published_document(actor, pack_id).items
            if remediation:
                failed = [
                    row for slot in ("practice_1", "practice_2")
                    if (row := ProgramAssessment(connection).latest(actor, pack_id, slot))
                    and row["status"] == "not_passed"
                ]
                candidate = next(i for i in items if i.slot == "remediation_1")
                difficulties = {item.slot: item.difficulty for item in items}
                if not failed or any(
                    candidate.difficulty not in {
                        difficulties[row["slot"]], max(1, difficulties[row["slot"]] - 1),
                    } for row in failed
                ):
                    raise BusinessError("precondition_failed", "No eligible program remediation.")
                items = [candidate]
            else:
                items = [i for i in items if i.slot.startswith("practice_")]
            for item in items:
                Exposures(connection).record(actor, pack_id, item)
            return [item.public() for item in items]

    def submit_practice(self, token, pack_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return self.submit_practice_in(
                connection, actor, Identity.digest(token), pack_id, key, data,
            )

    @staticmethod
    def submit_practice_in(connection, actor, digest, pack_id, key, data):
        Gates(connection).require_no_exam(actor)
        Transfers(connection).require_regular_practice(actor, pack_id, data.slot)
        pack = Packs(connection).row(actor, pack_id)
        ItemSupply.current(connection, actor, pack)
        item = Packs(connection).opened_program_training(actor, pack_id, data.slot)
        row, created = ProgramAssessment(connection).create(
            actor, pack_id, item, data.answer, key, "training", practice=data,
        )
        if created:
            Execution(connection).enqueue_program(actor, row["id"], digest, row["environment"])
            ItemSupply.event(connection, actor.id, pack_id)
        from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow

        LearningArtifactWorkflow.owner_result(
            connection, actor, pack_id, data.slot, "program", row["id"],
            "running" if row["status"] == "queued" else "completed", new_attempt=created,
        )
        return ProgramAssessment.public(row)

    def history(self, token, pack_id, slot, before=None, limit=20):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            ItemSupply.current(connection, actor, Packs(connection).row(actor, pack_id))
            return ProgramAssessment(connection).history(actor, pack_id, slot, before, limit)

    def attempt(self, token, attempt_id):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            row = ProgramAssessment(connection).row(actor, attempt_id)
            result = ProgramAssessment.public(row)
            return result

    def request(self, token, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            result = ProgramAssessment(connection).request(actor, key)
            return result

    def submit_gate(self, token, gate_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            gates = Gates(connection)
            gate = gates.row(actor, gate_id, lock=True)
            if gate["policy_version"] != "program-execution-gate.v1":
                raise BusinessError("precondition_failed", "The exact program Gate is required.")
            if gate["submission_key"]:
                previous = {
                    row["slot"]: row["answer"]
                    for row in ProgramAssessment(connection).for_pack(
                        actor, gate["pack_id"], "gate",
                    )
                }
                submitted = {
                    value.slot: value.answer.model_dump(mode="json") for value in data.programs
                }
                if gate["submission_key"] != key or previous != submitted:
                    raise BusinessError("idempotency_conflict", "Both program answers are locked.")
                return ConceptGate.project(connection, actor, gate)
            pack = ConceptGate.current(connection, actor, gate)
            if gate["status"] != "in_progress":
                raise BusinessError("precondition_failed", "Start the exact program Gate first.")
            answers = {value.slot: value.answer for value in data.programs}
            for item in Packs(connection).assessment_materials(actor, pack["id"]):
                row, _ = ProgramAssessment(connection).create(
                    actor, pack["id"], item, answers[item.slot], key + ":" + item.slot,
                    "gate", gate_id=gate["id"],
                )
                Execution(connection).enqueue_program(
                    actor, row["id"], Identity.digest(token), row["environment"],
                )
            gates.queue_program(actor, gate, key)
            ConceptGate.event(connection, actor.id, gate)
            return ConceptGate.project(connection, actor, gates.row(actor, gate_id))

    def gate_submission_receipt(self, token, gate_id, key):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            gate = Gates(connection).row(actor, gate_id)
            if (
                gate["policy_version"] != "program-execution-gate.v1"
                or gate["submission_key"] != key
            ):
                raise BusinessError("not_found", "No committed program submission for this key.")
            return ConceptGate.project(connection, actor, gate)

    def cancel(self, token, attempt_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            return self.cancel_in(connection, actor, attempt_id, Identity.digest(token))

    @staticmethod
    def cancel_in(connection, actor, attempt_id, digest):
        assessment = ProgramAssessment(connection)
        row = assessment.row(actor, attempt_id)
        ProgramAssessment.public(row)
        if row["status"] == "queued":
            Execution(connection).cancel_program(actor, attempt_id)
            assessment.fail(
                attempt_id, "Cancelled; late execution results are recorded only.",
                "learner_cancelled",
            )
            ProgramWorkflow.after_result(connection, actor, row, digest, False)
        return ProgramAssessment.public(assessment.row(actor, attempt_id))

    def expire_executions(self):
        with self.database.transaction() as connection:
            candidates = Execution(connection).expired_programs()
        count = 0
        for candidate in candidates:
            with self.database.transaction() as connection:
                reference = Execution(connection).reference(candidate["id"])
                owner = Actor(id=reference["actor_id"], display_name="")
                source = ProgramAssessment(connection).row(owner, reference["program_input_ref"])
                if source["gate_id"]:
                    Gates(connection).row(owner, source["gate_id"], lock=True)
                if source["transfer_id"]:
                    Transfers(connection).row(owner, source["transfer_id"], lock=True)
                row = Execution(connection).lock_expired_program(candidate["id"])
                if not row:
                    continue
                Execution(connection).abandon(row["id"], "runner_lease_expired")
                ProgramAssessment(connection).fail(
                    source["id"], "Runner lease expired; no automatic retry.",
                    "runner_lease_expired",
                )
                self.after_result(connection, owner, source, row["session_digest"], False)
                count += 1
        return count
