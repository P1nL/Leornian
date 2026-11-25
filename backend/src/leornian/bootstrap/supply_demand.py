from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.model_configuration import configuration_scope, require_model_admission
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.modules.assessment.gates import Gates
from leornian.modules.assessment.transfers import Transfers
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.demands import Demands
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import PackRequest
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError


class SupplyWorkflow:
    """A missing successor starts one bounded existing pack quality pipeline."""

    def __init__(self, database, settings):
        self.database = database
        self.settings = settings

    @staticmethod
    def current(connection, actor, demand):
        origin = Transfers.origin_id(demand)
        source_id, _ = TransferWorkflow.need(connection, actor, origin, demand["kind"])
        if Transfers(connection).passed_for(actor, origin, kind=demand["kind"]):
            raise BusinessError("precondition_failed", "The original transfer need is not open.")
        source = Packs(connection).row(actor, source_id)
        if source["id"] != demand["source_pack_id"] or source["kind"] != demand["kind"]:
            raise BusinessError("precondition_failed", "Supply origin changed.")
        return ItemSupply.current(connection, actor, source)

    def _schedule(self, connection, actor, token, demand, data, feedback=None):
        plan, node, materials = self.current(connection, actor, demand)
        Gates(connection).require_no_exam(actor)
        tutor = Tutor(PgTutorStore(connection))
        conversation = tutor.conversation(actor, plan.goal_id)
        tutor.get(actor, conversation.id, lock=True)
        if Runs(connection).actor_active(actor.id):
            raise BusinessError("run_active", "Foreground work takes priority over item supply.")
        require_model_admission(self.settings)
        pack, _ = Packs(connection).request(
            actor,
            plan.id,
            "supply:" + str(demand["id"]) + ":" + str(data.predecessor_id),
            data,
            materials,
            supply_demand_id=demand["id"],
            transfer_feedback=feedback,
            session_digest=Identity.digest(token),
            material_context=ItemSupply.prepare_material_context(
                connection, actor, plan, node
            ),
        )
        ItemSupply.schedule(
            connection,
            actor,
            conversation.id,
            Identity.digest(token),
            pack,
            "author",
            configuration_scope=configuration_scope(self.settings),
        )
        ItemSupply.event(connection, actor.id, pack["id"])
        return Demands(connection).summary(actor, demand["id"])

    def request(self, token, remediation_id, key, data, *, required_kind="choice"):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            demands = Demands(connection)
            prior = demands.previous(actor, key)
            if prior:
                origin = Transfers.origin_id(prior)
                if (origin, prior["plan_revision"], prior["instruction"], prior["kind"]) != (
                    remediation_id,
                    data.expected_plan_revision,
                    data.instruction,
                    required_kind,
                ):
                    raise BusinessError("idempotency_conflict", "Supply key has different content.")
                return demands.summary(actor, prior["id"])
            source_id, failed_slots = TransferWorkflow.need(
                connection, actor, remediation_id, required_kind
            )
            transfers = Transfers(connection)
            transfers.require_available(actor, remediation_id, kind=required_kind)
            source = Packs(connection).row(actor, source_id)
            if source["kind"] != required_kind:
                raise BusinessError("precondition_failed", "Use the matching supply endpoint.")
            _, node, _ = ItemSupply.current(connection, actor, source)
            if source["plan_revision"] != data.expected_plan_revision:
                raise BusinessError("stale_version", "Supply needs the exact confirmed revision.")
            _, exposed = Exposures(connection).snapshot(actor)
            if Packs(connection).transfer_candidates(
                actor, source, failed_slots, transfers.used_keys(actor), exposed
            ):
                raise BusinessError("precondition_failed", "Select published candidates first.")
            allowed = {1, 2, 3, 4, 5}
            for item in Packs(connection).published_document(actor, source["id"]).items:
                if item.slot in failed_slots:
                    allowed &= {item.difficulty, max(1, item.difficulty - 1)}
            if not allowed or not failed_slots:
                raise BusinessError("precondition_failed", "No common permitted difficulty.")
            demand = demands.create(
                actor,
                remediation_id,
                source,
                key,
                data,
                allowed,
                {
                    "objective": node.objective,
                    "capability": required_kind,
                    "actual_exposures": exposed,
                    "teaching_context": TransferWorkflow.teaching_context(connection, actor),
                },
            )
            return self._schedule(
                connection,
                actor,
                token,
                demand,
                PackRequest(
                    expected_plan_revision=data.expected_plan_revision,
                    node_key=source["node_key"],
                    instruction=data.instruction,
                    kind=required_kind,
                    automatic=data.automatic,
                    program_environment=source.get("program_environment"),
                ),
            )

    def revise(self, token, demand_id, data):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate(token)
            demands = Demands(connection)
            demand = demands.row(actor, demand_id)
            parent = demands.latest(actor, demand_id)
            task = SupplyTasks(connection).for_pack(actor, parent["id"])
            if task:
                SupplyTasks(connection).lock(actor, task["id"])
            # This stable predecessor key makes repeated clicks return the same child.
            if parent["revision"] == data.expected_pack_revision + 1:
                if (
                    parent["instruction"] != data.instruction
                    or parent["transfer_feedback_id"] != data.transfer_feedback_id
                ):
                    raise BusinessError("idempotency_conflict", "Revision has different content.")
                return demands.summary(actor, demand_id)
            if parent["revision"] != data.expected_pack_revision:
                raise BusinessError("stale_version", "Supply head changed.")
            feedback = (
                Transfers(connection).revision_feedback(
                    actor, data.transfer_feedback_id, parent["id"]
                )
                if data.transfer_feedback_id
                else None
            )
            return self._schedule(
                connection,
                actor,
                token,
                demand,
                PackRequest(
                    expected_plan_revision=demand["plan_revision"],
                    node_key=parent["node_key"],
                    predecessor_id=parent["id"],
                    instruction=data.instruction,
                    transfer_feedback_id=data.transfer_feedback_id,
                    kind=demand["kind"],
                    automatic=parent["automatic"],
                    program_environment=parent.get("program_environment"),
                ),
                feedback,
            )

    def request_program(self, token, remediation_id, key, data):
        kind = TransferWorkflow(self.database, self.settings).program_kind(token, remediation_id)
        return self.request(token, remediation_id, key, data, required_kind=kind)

    def request_receipt(self, token, key):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            demands = Demands(connection)
            row = demands.previous(actor, key)
            if not row:
                raise BusinessError("not_found", "Supply request has not been recorded.")
            return demands.summary(actor, row["id"])

    def view(self, token, demand_id):
        with self.database.transaction() as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            return Demands(connection).summary(actor, demand_id)
