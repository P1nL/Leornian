import logging

from leornian.agent_runtime.gateway import ChatCompletionsGateway, ModelProtocolError
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.bootstrap.supply_demand import SupplyWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.transfer_contracts import TransferRequest
from leornian.modules.assessment.transfers import Transfers
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.demands import Demands
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import REVIEW_ROLES, PackRequest
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError

logger = logging.getLogger(__name__)


class AutomaticSupply:
    """Reconcile a durable goal; scheduling batches never limit total repair attempts."""

    def __init__(self, database, settings):
        self.database = database
        self.settings = settings

    def reconcile_once(self, limit=20):
        with self.database.transaction(snapshot=True) as connection:
            candidates = SupplyTasks(connection).candidates(limit)
        advanced = 0
        for candidate in candidates:
            try:
                advanced += self.advance(candidate["pack_id"])
            except Exception:
                logger.exception("Automatic supply transition failed for task %s", candidate["id"])
        return advanced

    @staticmethod
    def state(connection, task, status, action, reason=None, delay=0):
        SupplyTasks(connection).update(task["id"], status, action, reason, delay=delay)
        if (task["status"], task["action"], task["reason"]) != (status, action, reason):
            ItemSupply.event(connection, task["actor_id"], task["head_pack_id"])

    def wait(self, task, code):
        with self.database.transaction() as connection:
            self.state(connection, task, "waiting", "recover", code, delay=30)

    def consume_late_receipt(self, pack_id):
        from leornian.bootstrap.tutor import TutorWorkflow
        from leornian.modules.identity.contracts import Actor

        with self.database.transaction(snapshot=True) as connection:
            candidates = SupplyTasks(connection).candidates(1, pack_id)
            if not candidates:
                return False
            task = candidates[0]
            pending = Runs(connection).actor_pending(task["actor_id"])
            if not pending or pending["status"] != "blocked_unknown":
                return False
            ids = {s["run_id"] for s in Packs(connection).stages(task["head_pack_id"])}
            if task["transfer_id"]:
                transfer = Transfers(connection).row(
                    Actor(id=task["actor_id"], display_name=""), task["transfer_id"]
                )
                ids.add(transfer["relation_run_id"])
            call = Runs(connection).latest(pending["id"])
            if (
                pending["id"] not in ids
                or not call
                or call.status != "result_recorded"
                or call.applied
            ):
                return False
        # Revalidate authority, exact call, cancellation and bindings under the normal Run lock.
        TutorWorkflow(self.database, self.settings).resume_digest(
            task["session_digest"], pending["id"]
        )
        return True

    @staticmethod
    def findings(connection, actor, pack, gate_feedback, transfer_feedback):
        packs = Packs(connection)
        rejected = {}
        for stage in packs.stages(pack["id"]):
            report = stage["result"]
            if stage["role"] not in REVIEW_ROLES or not report:
                continue
            slots = sorted(i["slot"] for i in report["items"] if i["verdict"] != "pass")
            if slots or report["assessment_independence"] != "supported":
                rejected[stage["role"]] = {
                    "slots": slots,
                    "independence": report["assessment_independence"],
                }
        return {
            "blind_passed": packs.summary(actor, pack["id"]).blind_passed,
            "rejected_reviews": rejected,
            "failed_stages": {
                stage["role"]: Runs(connection).get(actor.id, stage["run_id"]).error_code
                for stage in packs.stages(pack["id"])
                if stage["result"] is None
            },
            "gate_pairs": [
                [p["left"], p["right"], p["verdict"]]
                for p in (
                    gate_feedback.relation_report.model_dump()["comparisons"]
                    if gate_feedback
                    else []
                )
                if p["verdict"] != "distinct_decision"
            ],
            "transfer_pairs": [
                [p["left"].split(":")[-1], p["right"].split(":")[-1], p["verdict"]]
                for p in (transfer_feedback["report"]["comparisons"] if transfer_feedback else [])
                if p["verdict"] != "distinct_decision"
            ],
        }

    def advance(self, pack_id):
        task = None
        deferred = None
        try:
            if self.consume_late_receipt(pack_id):
                return 1
            with self.database.transaction() as connection:
                tasks = SupplyTasks(connection)
                candidates = tasks.candidates(1, pack_id)
                if not candidates:
                    return 0
                initial = candidates[0]
                actor = Identity(
                    PgIdentityStore(connection, serialize_actor=True)
                ).authenticate_digest(initial["session_digest"])
                # Before plan/conversation locks; never wait on an existing Run lock here.
                task = tasks.lock(actor, initial["id"])
                if task["status"] == "cancelled":
                    return 0
                pack_id = task["head_pack_id"]
                digest = task["session_digest"]
                packs = Packs(connection)
                pack = packs.row(actor, pack_id)
                plan = Plans(connection).get(actor, pack["plan_id"])
                tutor = Tutor(PgTutorStore(connection))
                conversation = tutor.conversation(actor, plan.goal_id)
                tutor.get(actor, conversation.id, lock=True)
                _, _, materials = ItemSupply.current(connection, actor, pack)
                pack = packs.row(actor, pack_id, lock=True)
                if pack["status"] == "cancelled":
                    tasks.cancel(actor, pack_id)
                    return 0
                demand = (
                    Demands(connection).row(actor, pack["supply_demand_id"])
                    if pack["supply_demand_id"]
                    else None
                )
                if demand:
                    origin = (
                        demand["python_remediation_id"]
                        if demand["kind"] == "python_io"
                        else demand["remediation_id"]
                    )
                    if Transfers(connection).passed_for(actor, origin, kind=demand["kind"]):
                        self.state(connection, task, "completed", "deliverable")
                        return 0
                    SupplyWorkflow.current(connection, actor, demand)
                if pack["status"] == "published" and not demand:
                    if not Gates(connection).latest_pack_feedback(actor, pack_id) and not Transfers(
                        connection
                    ).latest_pack_feedback(actor, pack_id):
                        self.state(connection, task, "completed", "published", delay=30)
                        return 0
                active = Runs(connection).actor_pending(actor.id)
                if active:
                    unknown = active["status"] == "blocked_unknown"
                    own = any(s["run_id"] == active["id"] for s in packs.stages(pack_id))
                    if task["transfer_id"]:
                        own = own or (
                            Transfers(connection).row(actor, task["transfer_id"])["relation_run_id"]
                            == active["id"]
                        )
                    action = {
                        "item_review.v1": "review",
                        "transfer_relation.v1": "check_transfer",
                    }.get(active["policy_version"], "generate")
                    self.state(
                        connection,
                        task,
                        "waiting" if unknown or not own else "running",
                        "await_receipt" if unknown else (action if own else "yield_foreground"),
                        "external_result_unknown" if unknown else None,
                        delay=1,
                    )
                    return 0
                gate = Gates(connection).active(actor)
                if gate and gate["status"] in {"in_progress", "submitted"}:
                    self.state(connection, task, "waiting", "yield_exam", delay=1)
                    return 0
                if pack["status"] == "ready":
                    _, changed = packs.publish(actor, pack_id)
                    self.state(
                        connection,
                        task,
                        "running" if demand else "completed",
                        "check_transfer" if demand else "published",
                    )
                    if changed:
                        ItemSupply.event(connection, actor.id, pack_id)
                    return int(changed)
                gate_feedback, transfer_feedback = None, None
                recovery_reason = None
                if pack["status"] == "published":
                    gate_feedback = Gates(connection).latest_pack_feedback(actor, pack_id)
                    transfer_feedback = Transfers(connection).latest_pack_feedback(actor, pack_id)
                    if demand and not gate_feedback and not transfer_feedback:
                        transfer = (
                            Transfers(connection).row(actor, task["transfer_id"])
                            if task["transfer_id"]
                            else Transfers(connection).current_for_origin(
                                actor, origin, demand["kind"]
                            )
                        )
                        if transfer and transfer["status"] in {
                            "ready",
                            "opened",
                            "submitted",
                            "passed",
                            "not_passed",
                            "error",
                        }:
                            if transfer["status"] == "ready":
                                try:
                                    with connection.transaction():
                                        TransferWorkflow.current(connection, actor, transfer)
                                except BusinessError as error:
                                    if error.code == "stale_version":
                                        recovery_reason = {
                                            "code": error.code,
                                            "transfer_id": str(transfer["id"]),
                                        }
                                        Transfers(connection).invalidate_unopened(
                                            transfer["id"], error.code
                                        )
                                    else:
                                        raise
                            if not recovery_reason:
                                self.state(connection, task, "completed", "deliverable")
                                return 0
                        if transfer:
                            if recovery_reason:
                                pass
                            elif transfer["error_code"] in {"stale_version", "source_not_current"}:
                                recovery_reason = {
                                    "code": transfer["error_code"],
                                    "transfer_id": str(transfer["id"]),
                                }
                            elif (
                                transfer["status"] == "blocked" and not transfer["relation_report"]
                            ):
                                deferred = ("repair_transfer", transfer["id"], digest)
                            else:
                                self.state(
                                    connection,
                                    task,
                                    "waiting",
                                    "recover",
                                    transfer["error_code"] or "transfer_not_available",
                                    delay=30,
                                )
                                return 0
                        else:
                            deferred = ("transfer", origin, digest)
                        self.state(connection, task, "running", "check_transfer")
                    elif not gate_feedback and not transfer_feedback:
                        self.state(connection, task, "completed", "published", delay=30)
                        return 0
                pending = next((s for s in packs.stages(pack_id) if s["result"] is None), None)
                pending_error = (
                    Runs(connection).get(actor.id, pending["run_id"]).error_code
                    if pending
                    else None
                )
                revise = (
                    pack["status"] == "changes_required"
                    or (pack["status"] == "published" and (gate_feedback or transfer_feedback))
                    or (pack["status"] == "failed" and not pending)
                    or bool(recovery_reason)
                    or pending_error == "conflicting_review_verdicts"
                )
                if revise:
                    ChatCompletionsGateway(self.settings).require_ready()
                    findings = self.findings(
                        connection, actor, pack, gate_feedback, transfer_feedback
                    )
                    findings["recovery"] = recovery_reason
                    tasks.remember_failure(task, findings)
                    child, _ = packs.request(
                        actor,
                        pack["plan_id"],
                        "automatic-revision:" + str(pack_id),
                        PackRequest(
                            expected_plan_revision=pack["plan_revision"],
                            node_key=pack["node_key"],
                            instruction=pack["instruction"],
                            predecessor_id=pack_id,
                            kind=pack["kind"],
                            automatic=True,
                            gate_feedback_id=gate_feedback.gate_id if gate_feedback else None,
                            transfer_feedback_id=(
                                transfer_feedback["transfer_id"]
                                if transfer_feedback and not gate_feedback
                                else None
                            ),
                        ),
                        materials,
                        revision_feedback=(
                            gate_feedback.model_dump(mode="json") if gate_feedback else None
                        ),
                        transfer_feedback=transfer_feedback if not gate_feedback else None,
                        session_digest=digest,
                        recovery_reason=recovery_reason,
                    )
                    ItemSupply.schedule(connection, actor, conversation.id, digest, child, "author")
                    ItemSupply.event(connection, actor.id, child["id"])
                    return 1
                if pack["status"] == "reviewing" and not pending:
                    if pack["kind"] == "python_io":
                        PythonWorkflow.continue_review_in(connection, actor, pack, digest)
                        self.state(connection, task, "running", "review")
                        return 1
                if pack["status"] == "failed" and pending:
                    call = Runs(connection).latest(pending["run_id"])
                    if (
                        call
                        and call.status == "failed_known"
                        and call.http_status in {401, 403}
                        and task["action"] != "recover_authorized"
                    ):
                        self.state(
                            connection,
                            task,
                            "waiting",
                            "configure_model",
                            "provider_rejected",
                            delay=30,
                        )
                        return 0
                    deferred = ("repair", pack_id, digest)
                    self.state(
                        connection,
                        task,
                        "running",
                        "repair_output",
                        delay=min(30, 2 ** min(call.step if call else 1, 5)),
                    )
                elif not deferred:
                    self.state(
                        connection,
                        task,
                        "running",
                        "qualify" if pack["status"] == "qualifying" else "generate",
                        delay=1,
                    )
            if deferred:
                action, reference, digest = deferred
                if action == "repair":
                    ItemSupply(self.database, self.settings).repair_stage(
                        None, reference, session_digest=digest
                    )
                elif action == "repair_transfer":
                    TransferWorkflow(self.database, self.settings).repair_digest(digest, reference)
                else:
                    TransferWorkflow(self.database, self.settings).request_digest(
                        digest,
                        reference,
                        "automatic-transfer:" + str(task["head_pack_id"]),
                        TransferRequest(expected_plan_revision=pack["plan_revision"]),
                        required_kind=pack["kind"],
                        supply_task_id=task["id"],
                    )
                return 1
        except (BusinessError, ModelProtocolError) as error:
            if task is None:
                with self.database.transaction() as connection:
                    candidates = SupplyTasks(connection).candidates(1, pack_id)
                    task = candidates[0] if candidates else None
            if task and error.code != "supply_cancelled":
                self.wait(task, error.code)
        return 0
