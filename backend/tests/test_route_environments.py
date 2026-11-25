from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_dynamic_plans import document, run, submit
from test_dynamic_plans import setup_planner as setup_planner

from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.modules.execution.environment_contracts import (
    EngineState,
    EnvironmentDemandInput,
    ExecutionEnvironments,
)
from leornian.modules.execution.environment_recipes import RECIPES, automatic_recipe_ids, recipe
from leornian.modules.execution.environments import Environments
from leornian.modules.identity.contracts import Actor
from leornian.modules.learning.contracts import PlanDocument
from leornian.shared_kernel.errors import BusinessError


def test_base_toolchain_dependencies_do_not_become_course_consent():
    automatic = automatic_recipe_ids()
    assert "typescript-standard.v1" in automatic
    assert "html-css-browser.v1" in automatic
    assert "postgresql-query.v1" in automatic
    assert "python-flask.v1" not in automatic
    assert recipe("typescript-standard.v1").requirement.dependency_lock


def test_legacy_plan_serialization_and_recipe_deduplication():
    value = PlanDocument.model_validate(document())
    assert value.model_dump(mode="json") == {
        **document(), "nodes": [node.model_dump(mode="json") for node in value.nodes],
    }
    with pytest.raises(ValueError):
        PlanDocument.model_validate({**document(), "environment_recipes": [
            "python-flask.v1", "python-flask.v1",
        ]})


def test_route_preflight_only_reads_the_complete_list_and_separates_course_consent(monkeypatch):
    snapshot = ExecutionEnvironments(
        engine=EngineState(status="ready", detail="Offline read fixture"),
        recipes=[], demands=[], automatic_recipe_ids=automatic_recipe_ids(),
    )
    monkeypatch.setattr(Environments, "snapshot", lambda self, actor: snapshot)
    plan = SimpleNamespace(id=uuid4(), active=None, latest=SimpleNamespace(
        revision=2, document=PlanDocument.model_validate({
            **document(), "environment_recipes": ["python-standard.v1", "python-flask.v1"],
        }),
    ))
    actor = Actor(id=uuid4(), display_name="Learner")
    manifest = ExecutionEnvironmentWorkflow.route_manifest_in(None, actor, plan, 2)
    assert [r.recipe_id for r in manifest.requirements] == [
        "python-standard.v1", "python-flask.v1",
    ]
    assert [r.recipe_id for r in manifest.consent_required] == ["python-flask.v1"]
    assert not manifest.demands
    with pytest.raises(BusinessError):
        ExecutionEnvironmentWorkflow.route_manifest_in(None, actor, plan, 1)


def test_auto_base_reuses_an_already_authorized_superset_without_downgrading_it():
    existing = SimpleNamespace(
        decision="allow", requirement=recipe("python-flask.v1").requirement,
    )
    assert Environments.satisfies_base(existing, recipe("python-standard.v1").requirement)
    assert not Environments.satisfies_base(existing, recipe("python-flask.v1").requirement)
    existing.decision = "revoke"
    assert not Environments.satisfies_base(existing, recipe("python-standard.v1").requirement)


@pytest.fixture
def route_planner(setup_planner, session, workflow):
    tutor, _, _ = setup_planner
    accepted = submit(setup_planner, session)
    run(setup_planner, accepted.run_id, {
        **document(),
        "environment_recipes": ["python-standard.v1", "python-flask.v1"],
    })
    plan = workflow.snapshot(session.token).plans[0]
    try:
        yield tutor, plan, ExecutionEnvironmentWorkflow(tutor.database)
    finally:
        with tutor.database.transaction() as connection:
            connection.execute(
                "UPDATE execution.environment_preparation_jobs SET status='cancelled' "
                "WHERE actor_id=%s "
                "AND status IN ('queued','waiting_engine','preparing','verifying')",
                (session.actor.id,),
            )


@pytest.mark.parametrize("install", [False, True])
def test_confirmation_batches_the_route_but_plain_confirmation_does_not_consent(
    route_planner, session, install,
):
    tutor, plan, environments = route_planner
    manifest = environments.route_manifest(session.token, plan.id, 1)
    assert not environments.snapshot(session.token).demands
    assert [r.recipe_id for r in manifest.consent_required] == ["python-flask.v1"]
    tutor.confirm_plan(
        session.token, plan.id, 1,
        manifest.requirements if install else None,
    )
    snapshot = environments.snapshot(session.token)
    demands = {d.requirement.recipe_id: d for d in snapshot.demands}
    assert demands["python-standard.v1"].status == "queued"
    assert demands["python-standard.v1"].plan_id is None
    assert demands["python-flask.v1"].plan_id == plan.id
    assert demands["python-flask.v1"].status == ("queued" if install else "waiting_authorization")
    before = snapshot.demands
    tutor.confirm_plan(session.token, plan.id, 1, manifest.requirements)
    assert environments.snapshot(session.token).demands == before


def test_changed_installation_list_rolls_back_both_confirmation_and_preparation(
    route_planner, session,
):
    tutor, plan, environments = route_planner
    manifest = environments.route_manifest(session.token, plan.id, 1)
    changed = [
        requirement.model_copy(update={"dependency_lock": ["not-the-shown-lock==1"]})
        for requirement in manifest.requirements
    ]
    with pytest.raises(BusinessError) as error:
        tutor.confirm_plan(session.token, plan.id, 1, changed)
    assert error.value.code == "stale_version"
    assert tutor.plan(session.token, plan.id).active is None
    assert not environments.snapshot(session.token).demands


def test_same_route_lock_reuses_consent_but_added_dependencies_require_a_new_decision(
    setup_planner, route_planner, session, monkeypatch,
):
    tutor, plan, environments = route_planner
    manifest = environments.route_manifest(session.token, plan.id, 1)
    tutor.confirm_plan(session.token, plan.id, 1, manifest.requirements)
    accepted = submit(setup_planner, session, revision=1)
    content = {**document(), "environment_recipes": ["python-standard.v1", "python-flask.v1"]}
    run(setup_planner, accepted.run_id, content)
    next_manifest = environments.route_manifest(session.token, plan.id, 2)
    assert not next_manifest.consent_required
    tutor.confirm_plan(session.token, plan.id, 2)
    framework = next(
        d for d in environments.snapshot(session.token).demands
        if d.requirement.recipe_id == "python-flask.v1"
    )
    assert framework.plan_revision == 2 and framework.decision == "allow"
    with tutor.database.transaction() as connection:
        basis = connection.execute(
            "SELECT command FROM execution.environment_install_decisions "
            "WHERE demand_id=%s AND revision=%s",
            (framework.id, framework.decision_revision),
        ).fetchone()["command"]
        assert basis["authorization_basis"] == "reused_consent"
        assert basis["inherited_from"]
    maintained = recipe("python-flask.v1")
    monkeypatch.setitem(RECIPES, "python-flask.v1", replace(
        maintained,
        requirement=maintained.requirement.model_copy(update={
            "dependency_lock": [*maintained.requirement.dependency_lock, "new-library==1.0"],
        }),
    ))
    updated = environments.route_manifest(session.token, plan.id, 2)
    assert updated.consent_required
    assert framework in updated.demands
    changed = environments.request(
        session.token, str(uuid4()), EnvironmentDemandInput(
            recipe_id="python-flask.v1", plan_id=plan.id, plan_revision=2,
            expected_requirement_revision=framework.requirement_revision,
        ),
    )
    assert changed.id == framework.id
    assert changed.requirement_revision == framework.requirement_revision + 1
    assert changed.decision is None and changed.status == "waiting_authorization"
    assert changed.requirement == updated.consent_required[0]


def test_unknown_recipe_is_not_a_maintained_installation():
    from leornian.modules.execution.environments import Environments

    with pytest.raises(BusinessError):
        Environments.route_requirements(["invented-framework.v1"])
    assert Environments.route_requirements(["python-standard.v1"]) == [
        recipe("python-standard.v1").requirement,
    ]
