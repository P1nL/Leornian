from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.assessment.contracts import PythonCompletion
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.assessment.python_contracts import PythonReceipt
from leornian.modules.assessment.transfers import Transfers
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import ExecutionClaim
from leornian.modules.identity.application import Identity
from leornian.modules.identity.contracts import Actor
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.learning.progress import Progress
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.evaluations import Evaluations
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError


class PythonWorkflow:
    """Uses the existing execution queue/Runner and Gate admission, never a second engine."""

    def __init__(self, database):
        self.database = database

    @staticmethod
    def event(connection, actor, pack_id):
        ItemSupply.event(connection, actor.id, pack_id)

    @staticmethod
    def current(connection, actor, source):
        pack = Packs(connection).row(actor, source["pack_id"])
        if source["purpose"] == "qualification":
            SupplyTasks(connection).require_current(actor, pack["id"])
        ItemSupply.current(connection, actor, pack)
        if pack["kind"] != "python_io":
            raise BusinessError("precondition_failed", "Python execution pack required.")
        if source["purpose"] == "qualification":
            if pack["status"] != "qualifying":
                raise BusinessError("precondition_failed", "Qualification is no longer current.")
        elif source["purpose"] == "gate":
            gate = Gates(connection).row(actor, source["gate_id"], lock=True)
            if gate["status"] != "submitted":
                raise BusinessError(
                    "precondition_failed", "The submitted Gate is no longer active."
                )
            ConceptGate.current(connection, actor, gate)
        elif source["purpose"] == "transfer":
            Gates(connection).require_no_exam(actor)
            transfer = Transfers(connection).row(actor, source["transfer_id"])
            if (
                transfer["status"] != "submitted"
                or transfer["python_result_id"] != source["id"]
                or transfer["candidate_pack_id"] != source["pack_id"]
                or transfer["candidate_slot"] != source["slot"]
            ):
                raise BusinessError(
                    "precondition_failed", "This exact successor is no longer active."
                )
            TransferWorkflow.current(connection, actor, transfer)
        else:
            Gates(connection).require_no_exam(actor)
            Packs(connection).published_document(actor, pack["id"])
        return pack

    @staticmethod
    def qualify(connection, actor, pack, digest):
        stage = next(s for s in Packs(connection).stages(pack["id"]) if s["role"] == "blind")
        programs = {item["slot"]: item["code"] for item in stage["result"]["programs"]}
        for item in Packs.document(pack).items:
            attempt, _ = PythonAssessment(connection).create(
                actor,
                pack["id"],
                item,
                programs[item.slot],
                "qualification:" + str(pack["id"]) + ":" + item.slot,
                "qualification",
            )
            Packs(connection).register_qualification(pack["id"], item.slot, attempt["id"])
            Execution(connection).enqueue_python(actor, attempt["id"], digest)
        PythonWorkflow.event(connection, actor, pack["id"])

    @staticmethod
    def claim_in(connection, work):
        owner = Actor(id=work["actor_id"], display_name="")
        assessment = PythonAssessment(connection)
        source = assessment.row(owner, work["python_input_ref"])
        try:
            with connection.transaction():
                actor = Identity(
                    PgIdentityStore(connection, lock_session=True)
                ).authenticate_digest(work["session_digest"] or "")
                if actor.id != owner.id:
                    raise BusinessError("unauthorized", "Execution owner changed.")
                PythonWorkflow.current(connection, actor, source)
        except BusinessError as error:
            Execution(connection).abandon(work["id"], error.code)
            assessment.fail(source["id"], "执行前授权、题包或 Gate 已失效。")
            PythonWorkflow.after_result(connection, owner, source, work["session_digest"], False)
            return None
        return ExecutionClaim(
            job_id=work["id"],
            claim_token=work["claim_token"],
            code=source["code"],
            inputs=[case["input"] for case in source["test_cases"]],
        )

    @staticmethod
    def report_in(connection, existing, job_id, report):
        owner = Actor(id=existing["actor_id"], display_name="")
        assessment = PythonAssessment(connection)
        source = assessment.row(owner, existing["python_input_ref"])
        current = True
        try:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
                existing["session_digest"] or ""
            )
            if actor.id != owner.id:
                raise BusinessError("unauthorized", "Execution owner changed.")
        except BusinessError:
            current = False
        # Same successor -> execution -> attempt order as expiry. Keep this lock even
        # when a later current-material check fails; late facts still need recording.
        if source["transfer_id"]:
            Transfers(connection).row(owner, source["transfer_id"], lock=True)
        try:
            with connection.transaction():
                if current:
                    PythonWorkflow.current(connection, actor, source)
        except BusinessError:
            current = False
        _, first, timely = Execution(connection).report(job_id, report)
        if not first:
            return
        if current and timely:
            assessment.complete(source, report.cases)
        else:
            assessment.fail(source["id"], "回执已保存，但当前权限、材料或执行租约已失效。")
        PythonWorkflow.after_result(
            connection, owner, source, existing["session_digest"], current and timely
        )

    @staticmethod
    def feedback(connection, actor, pack, source):
        source = PythonAssessment(connection).row(actor, source["id"])
        item = next(i for i in Packs.document(pack).items if i.slot == source["slot"])
        receipt = PythonReceipt(
            attempt_id=source["id"],
            code=source["code"],
            correct=source["status"] == "passed",
            passed_cases=source["passed_cases"],
            explanation=source["feedback"] or "执行结果已保存。",
        )
        Exposures(connection).record(actor, pack["id"], item, receipt)
        Evaluations(connection).enqueue(
            actor, pack["id"], "python", source["id"], item.public(), receipt
        )

    @staticmethod
    def after_result(connection, actor, original, digest, applicable):
        assessment = PythonAssessment(connection)
        source = assessment.row(actor, original["id"])
        packs = Packs(connection)
        pack = packs.row(actor, source["pack_id"], lock=True)
        if source["purpose"] == "qualification":
            all_done = packs.qualification_result(pack["id"], source["id"], source["status"])
            if pack["status"] == "qualifying":
                if not applicable or source["status"] == "error":
                    packs.status(pack["id"], "failed")
                elif all_done:
                    packs.status(pack["id"], "reviewing")
                    PythonWorkflow.continue_review_in(connection, actor, pack, digest)
        elif source["purpose"] == "training":
            # Only the already-locked learner attempt is exposed, never qualification or gold tests.
            PythonWorkflow.feedback(connection, actor, pack, source)
        elif source["purpose"] == "transfer":
            transfers = Transfers(connection)
            transfers.complete_python(source["transfer_id"], source)
            PythonWorkflow.feedback(connection, actor, pack, source)
            TransferWorkflow.event(
                connection, actor.id, transfers.row(actor, source["transfer_id"])
            )
        else:
            gates = Gates(connection)
            gate = gates.row(actor, source["gate_id"], lock=True)
            rows = assessment.for_pack(actor, pack["id"], "gate")
            if (
                gate["status"] == "submitted"
                and len(rows) == 2
                and all(row["status"] != "queued" for row in rows)
            ):
                passed = all(row["status"] == "passed" for row in rows)
                gate = gates.complete_python(actor, gate, passed)
                for row in rows:
                    PythonWorkflow.feedback(connection, actor, pack, row)
                if passed and Progress(connection).apply_python(
                    actor,
                    PythonCompletion(
                        gate_id=gate["id"],
                        plan_id=gate["plan_id"],
                        plan_revision=gate["plan_revision"],
                        node_key=gate["node_key"],
                    ),
                ):
                    Events(connection).append(
                        actor.id,
                        "learning.node_completed",
                        gate["id"],
                        EventPayload(
                            gate_id=gate["id"], pack_id=pack["id"], plan_id=gate["plan_id"]
                        ),
                    )
                ConceptGate.event(connection, actor.id, gate)
        PythonWorkflow.event(connection, actor, pack["id"])

    @staticmethod
    def continue_review_in(connection, actor, pack, digest):
        if any(stage["role"] == "curriculum" for stage in Packs(connection).stages(pack["id"])):
            return
        if Runs(connection).actor_active(actor.id):
            return  # A learner turn wins. The explicit continuation uses the same unique stage key.
        plan, _, _ = ItemSupply.current(connection, actor, pack)
        conversation = Tutor(PgTutorStore(connection)).conversation(actor, plan.goal_id)
        ItemSupply.schedule(connection, actor, conversation.id, digest, pack, "curriculum")

    def continue_review(self, token, pack_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            pack = Packs(connection).row(actor, pack_id)
            ItemSupply.current(connection, actor, pack)
            Gates(connection).require_no_exam(actor)
            if pack["kind"] != "python_io" or pack["status"] != "reviewing":
                raise BusinessError(
                    "precondition_failed", "No qualified execution review to continue."
                )
            self.continue_review_in(connection, actor, pack, Identity.digest(token))
            self.event(connection, actor, pack_id)
            return Packs(connection).summary(actor, pack_id)

    def training(self, token, pack_id, *, remediation=False):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Gates(connection).require_no_exam(actor)
            Transfers(connection).require_regular_practice(actor, pack_id)
            pack = Packs(connection).row(actor, pack_id)
            ItemSupply.current(connection, actor, pack)
            if pack["kind"] != "python_io":
                raise BusinessError("precondition_failed", "Execution pack required.")
            document = Packs(connection).published_document(actor, pack_id)
            if remediation:
                failed = [
                    row
                    for row in PythonAssessment(connection).for_pack(actor, pack_id, "training")
                    if row["slot"].startswith("practice_") and row["status"] == "not_passed"
                ]
                candidate = next(i for i in document.items if i.slot == "remediation_1")
                difficulties = {i.slot: i.difficulty for i in document.items}
                if not failed or any(
                    candidate.difficulty
                    not in {difficulties[r["slot"]], max(1, difficulties[r["slot"]] - 1)}
                    for r in failed
                ):
                    raise BusinessError("precondition_failed", "No eligible execution remediation.")
                items = [candidate]
            else:
                items = [i for i in document.items if i.slot.startswith("practice_")]
            for item in items:
                Exposures(connection).record(actor, pack_id, item)
            return [item.public() for item in items]

    def submit_training(self, token, pack_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            Gates(connection).require_no_exam(actor)
            Transfers(connection).require_regular_practice(actor, pack_id, data.slot)
            pack = Packs(connection).row(actor, pack_id)
            ItemSupply.current(connection, actor, pack)
            if pack["kind"] != "python_io":
                raise BusinessError("precondition_failed", "Execution pack required.")
            # Exposure is owned by item_bank, so use its Facade rather than cross-owner SQL.
            item = Packs(connection).opened_python_training(actor, pack_id, data.slot)
            row, created = PythonAssessment(connection).create(
                actor, pack_id, item, data.code, key, "training"
            )
            if created:
                Execution(connection).enqueue_python(actor, row["id"], Identity.digest(token))
                self.event(connection, actor, pack_id)
            return PythonAssessment(connection).public(row)

    def submit_gate(self, token, gate_id, key, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            gates = Gates(connection)
            gate = gates.row(actor, gate_id, lock=True)
            if gate["policy_version"] != "python-io-gate.v1":
                raise BusinessError("precondition_failed", "Execution Gate required.")
            if gate["submission_key"]:
                previous = {
                    row["slot"]: row["code"]
                    for row in PythonAssessment(connection).for_pack(actor, gate["pack_id"], "gate")
                }
                if gate["submission_key"] != key or previous != {
                    p.slot: p.code for p in data.programs
                }:
                    raise BusinessError(
                        "idempotency_conflict", "Both execution programs are locked."
                    )
                return ConceptGate.project(connection, actor, gate)
            pack = ConceptGate.current(connection, actor, gate)
            if gate["status"] != "in_progress":
                raise BusinessError("precondition_failed", "Start the execution Gate first.")
            programs = {p.slot: p.code for p in data.programs}
            for item in Packs(connection).assessment_materials(actor, pack["id"]):
                row, _ = PythonAssessment(connection).create(
                    actor,
                    pack["id"],
                    item,
                    programs[item.slot],
                    key + ":" + item.slot,
                    "gate",
                    gate_id,
                )
                Execution(connection).enqueue_python(actor, row["id"], Identity.digest(token))
            gates.queue_python(actor, gate, key)
            ConceptGate.event(connection, actor.id, gate)
            return ConceptGate.project(connection, actor, gates.row(actor, gate_id))

    def expire_executions(self):
        with self.database.transaction() as connection:
            candidates = Execution(connection).expired_python()
        count = 0
        for reference in candidates:
            # Same Gate -> execution -> attempt -> pack order as report application.
            # A transaction per job also avoids retaining an actor event-head lock across jobs.
            with self.database.transaction() as connection:
                actor = Actor(id=reference["actor_id"], display_name="")
                source = PythonAssessment(connection).row(actor, reference["python_input_ref"])
                if source["gate_id"]:
                    Gates(connection).row(actor, source["gate_id"], lock=True)
                if source["transfer_id"]:
                    Transfers(connection).row(actor, source["transfer_id"], lock=True)
                row = Execution(connection).lock_expired_python(reference["id"])
                if not row:
                    continue
                Execution(connection).abandon(row["id"], "runner_lease_expired")
                PythonAssessment(connection).fail(source["id"], "Runner 租约过期；未自动重跑。")
                self.after_result(connection, actor, source, row["session_digest"], False)
                count += 1
        return count
