"""Teaching reads and demand registration; installation consent stays with the learner."""

from leornian.modules.execution.environment_contracts import (
    EnvironmentDemandInput,
    EnvironmentDemandToolReceipt,
    ExecutionEnvironmentSnapshot,
)
from leornian.modules.execution.environments import Environments
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError


class ExecutionEnvironmentTools:
    @staticmethod
    def _scope(connection, actor, focus):
        if focus is None or focus.kind == "goal":
            return None, None
        plan = Plans(connection).get(actor, focus.plan_id)
        if not plan.active or plan.active.revision != focus.expected_plan_revision:
            raise BusinessError("stale_version", "Environment scope needs the confirmed plan.")
        if not any(node.key == focus.node_key for node in plan.active.document.nodes):
            raise BusinessError("not_found", "Environment scope node is outside this route.")
        return plan.id, plan.active.revision

    @staticmethod
    def snapshot_in(connection, actor, focus=None):
        plan_id, revision = ExecutionEnvironmentTools._scope(connection, actor, focus)
        environments = Environments(connection)
        snapshot = environments.snapshot(actor)
        demands = [
            demand
            for demand in snapshot.demands
            if demand.plan_id is None
            or (demand.plan_id == plan_id and demand.plan_revision == revision)
        ]
        usable = []
        if snapshot.engine.status == "ready":
            for demand in demands:
                if demand.release is None:
                    continue
                release = demand.release
                try:
                    current = environments.require_release(
                        actor,
                        release.id,
                        profile=release.profile,
                        language=release.language,
                        dialect=release.dialect or None,
                        runtime_version=release.runtime_version,
                        plan_id=plan_id,
                        plan_revision=revision,
                    )
                except BusinessError:
                    continue
                usable.append(current.environment())
        return ExecutionEnvironmentSnapshot(
            plan_id=plan_id,
            plan_revision=revision,
            engine=snapshot.engine,
            recipes=snapshot.recipes,
            demands=demands,
            usable_environments=usable,
            automatic_recipe_ids=snapshot.automatic_recipe_ids,
        )

    @staticmethod
    def request_in(connection, actor, row, command_key, data: EnvironmentDemandInput, focus=None):
        if row["tool_contracts"].get("request_execution_environment") != 1:
            raise BusinessError(
                "precondition_failed", "This Run cannot register local environment demands."
            )
        current = Identity(PgIdentityStore(connection, serialize_actor=True)).authenticate_digest(
            row["session_digest"]
        )
        if current.id != actor.id:
            raise BusinessError("unauthorized", "Environment request session owner changed.")
        key = f"teaching-environment:{row['input_ref']}:{command_key}"
        environments = Environments(connection)
        previous = environments.recorded_request(actor, key, data)
        if previous is None:
            plan_id, revision = ExecutionEnvironmentTools._scope(connection, actor, focus)
            if (data.plan_id, data.plan_revision) != (plan_id, revision):
                raise BusinessError(
                    "precondition_failed", "Environment demand must use this teaching scope."
                )
            demand = environments.request(actor, key, data)
        else:
            demand = previous
        return EnvironmentDemandToolReceipt(
            demand=demand,
            requires_user_decision=demand.decision != "allow",
            command_receipt_key=key,
        )
