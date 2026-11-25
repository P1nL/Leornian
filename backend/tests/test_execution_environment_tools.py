from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from leornian.bootstrap import execution_environment_tools as tools
from leornian.modules.execution.environment_contracts import (
    EngineState,
    EnvironmentDemand,
    EnvironmentDemandInput,
    EnvironmentRelease,
    ExecutionEnvironments,
)
from leornian.modules.execution.environment_recipes import recipe
from leornian.modules.identity.contracts import Actor
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def bridge(monkeypatch):
    actor = Actor(id=uuid4(), display_name="Learner")
    plan_id = uuid4()
    focus = TeachingFocus(kind="node", plan_id=plan_id, expected_plan_revision=4, node_key="loops")
    active = SimpleNamespace(
        revision=4, document=SimpleNamespace(nodes=[SimpleNamespace(key="loops")])
    )
    plan = SimpleNamespace(id=plan_id, active=active)
    requirement = recipe("javascript-standard.v1").requirement
    now = datetime.now(UTC)

    def demand(plan=None, revision=None, decision="allow"):
        demand_id = uuid4()
        release = EnvironmentRelease(
            id=uuid4(),
            demand_id=demand_id,
            requirement_revision=1,
            recipe_id=requirement.recipe_id,
            recipe_revision=1,
            profile=requirement.profile,
            language="javascript",
            dialect="",
            runtime_version="22.16.0",
            image_id="sha256:" + "a" * 64,
            image_ids={"runtime": "sha256:" + "a" * 64},
            toolchains={"node": "22.16.0"},
            verification={"isolated": True, "smoke": True},
            created_at=now,
        )
        return EnvironmentDemand(
            id=demand_id,
            local_scope="this-device.v1",
            plan_id=plan,
            plan_revision=revision,
            requirement_revision=1,
            requirement=requirement,
            decision_revision=1,
            decision=decision,
            status="ready" if decision == "allow" else "revoked",
            release=release,
            created_at=now,
            updated_at=now,
        )

    basic, scoped = demand(), demand(plan_id, 4)
    revoked = demand(plan_id, 4, "revoke")
    foreign, stale = demand(uuid4(), 4), demand(plan_id, 3)
    snapshot = ExecutionEnvironments(
        engine=EngineState(status="ready", detail="Actual controller observation"),
        recipes=[requirement],
        demands=[basic, scoped, revoked, foreign, stale],
    )
    records, requests, gates = {}, [], []

    def require_release(owner, release_id, **scope):
        assert owner.id == actor.id
        gates.append((release_id, scope))
        value = next(item for item in snapshot.demands if item.release.id == release_id)
        if value.decision != "allow":
            raise BusinessError("precondition_failed", "Revoked release.")
        return value.release

    def request(owner, key, data):
        requests.append((owner.id, key, data))
        value = demand(data.plan_id, data.plan_revision)
        value = value.model_copy(
            update={"status": "waiting_authorization", "decision": None, "release": None}
        )
        records[key] = value
        return value

    environments = SimpleNamespace(
        snapshot=lambda owner: snapshot,
        require_release=require_release,
        recorded_request=lambda owner, key, data: records.get(key),
        request=request,
    )
    monkeypatch.setattr(tools, "Environments", lambda connection: environments)
    monkeypatch.setattr(
        tools, "Plans", lambda connection: SimpleNamespace(get=lambda owner, identity: plan)
    )
    monkeypatch.setattr(tools, "PgIdentityStore", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tools,
        "Identity",
        lambda store: SimpleNamespace(authenticate_digest=lambda digest: actor),
    )
    row = {
        "session_digest": "only-the-original-session",
        "input_ref": "original-turn",
        "tool_contracts": {"request_execution_environment": 1},
    }
    return SimpleNamespace(
        actor=actor,
        plan=plan,
        focus=focus,
        row=row,
        snapshot=snapshot,
        environments=environments,
        basic=basic,
        scoped=scoped,
        revoked=revoked,
        requests=requests,
        gates=gates,
    )


def test_teaching_snapshot_is_own_exact_scope_and_revalidates_usable_releases(bridge):
    result = tools.ExecutionEnvironmentTools.snapshot_in(None, bridge.actor, bridge.focus)
    assert [item.id for item in result.demands] == [
        bridge.basic.id,
        bridge.scoped.id,
        bridge.revoked.id,
    ]
    assert [item.environment_release_id for item in result.usable_environments] == [
        bridge.basic.release.id,
        bridge.scoped.release.id,
    ]
    assert all(call[1]["plan_revision"] == 4 for call in bridge.gates)


def test_stopped_engine_keeps_demand_history_but_advertises_no_usable_runtime(bridge):
    bridge.environments.snapshot = lambda actor: bridge.snapshot.model_copy(
        update={"engine": bridge.snapshot.engine.model_copy(update={"status": "stopped"})}
    )
    result = tools.ExecutionEnvironmentTools.snapshot_in(None, bridge.actor, bridge.focus)
    assert result.demands
    assert result.usable_environments == []
    assert bridge.gates == []


def test_teaching_request_only_registers_demand_and_original_read_receipt(bridge):
    data = EnvironmentDemandInput(
        recipe_id="javascript-standard.v1",
        plan_id=bridge.plan.id,
        plan_revision=4,
    )
    result = tools.ExecutionEnvironmentTools.request_in(
        None, bridge.actor, bridge.row, "original-key", data, bridge.focus
    )
    assert result.demand.status == "waiting_authorization"
    assert result.demand.decision is None and result.requires_user_decision
    assert result.command_receipt_key == "teaching-environment:original-turn:original-key"
    assert len(bridge.requests) == 1
    bridge.plan.active.revision = 5
    previous = tools.ExecutionEnvironmentTools.request_in(
        None, bridge.actor, bridge.row, "original-key", data, bridge.focus
    )
    assert previous == result and len(bridge.requests) == 1


@pytest.mark.parametrize("failure", ["missing_capability", "different_plan_scope"])
def test_teaching_request_cannot_bypass_run_capability_or_expand_its_scope(bridge, failure):
    if failure == "missing_capability":
        bridge.row["tool_contracts"] = {}
    data = EnvironmentDemandInput(recipe_id="javascript-standard.v1")
    with pytest.raises(BusinessError) as error:
        tools.ExecutionEnvironmentTools.request_in(
            None, bridge.actor, bridge.row, "original-key", data, bridge.focus
        )
    assert error.value.code == "precondition_failed"
    assert bridge.requests == []
