from uuid import uuid4

import pytest
from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.modules.execution.environment_contracts import (
    CourseEnvironment,
    EnvironmentDecisionInput,
    EnvironmentDemandInput,
)
from leornian.modules.execution.environment_recipes import (
    automatic_recipe_ids,
    course_recipe,
    recipe,
)
from leornian.modules.execution.environments import Environments
from leornian.shared_kernel.errors import BusinessError
from pydantic import ValidationError
from test_dynamic_plans import document, run, submit
from test_dynamic_plans import setup_planner as setup_planner

PACKAGES = [
    ("python", "humanize", "4.11.0"),
    ("javascript", "dayjs", "1.11.13"),
    ("typescript", "dayjs", "1.11.13"),
    ("java", "org.apache.commons:commons-lang3", "3.17.0"),
    ("go", "github.com/google/uuid", "v1.6.0"),
    ("csharp", "Newtonsoft.Json", "13.0.3"),
]


def course(language="typescript", name="dayjs", version="1.11.13"):
    return CourseEnvironment(
        language=language, title="Course dependency integration",
        dependencies=[{"name": name, "version": version}],
    )


@pytest.mark.parametrize(("language", "name", "version"), PACKAGES)
def test_new_course_package_set_has_an_exact_nonautomatic_requirement(language, name, version):
    spec = course(language, name, version)
    maintained = course_recipe(spec)
    request = EnvironmentDemandInput(
        recipe_id=maintained.requirement.recipe_id, course_environment=spec,
    )
    assert recipe(request.recipe_id, request.course_environment) == maintained
    assert maintained.requires_consent
    assert request.recipe_id not in automatic_recipe_ids()
    assert maintained.requirement.course_environment == spec
    changed = course(language, name, version + ".1")
    assert course_recipe(changed).requirement.recipe_id != request.recipe_id
    with pytest.raises(BusinessError):
        recipe(request.recipe_id, changed)


def test_course_request_cannot_replace_the_installer_with_commands_or_registry_urls():
    with pytest.raises(ValidationError):
        course("javascript", "https://example.org/package.tgz", "1.0.0")
    with pytest.raises(ValidationError):
        EnvironmentDemandInput(
            recipe_id="javascript-standard.v1", course_environment=course(),
            command="npm install anything",
        )

def test_display_title_does_not_change_the_course_dependency_identity():
    original = course_recipe(course())
    renamed = course_recipe(course().model_copy(update={"title": "A clearer display title"}))
    assert original.requirement.recipe_id == renamed.requirement.recipe_id
    assert original.requirement.installation_scope() == renamed.requirement.installation_scope()

def test_course_declaration_always_keeps_its_base_available_without_framework_consent():
    requirements = Environments.route_requirements([], [course()])
    assert requirements[0].recipe_id == "typescript-standard.v1"
    assert requirements[0].recipe_id in automatic_recipe_ids()
    assert requirements[1].course_environment == course()


@pytest.fixture
def course_plan(setup_planner, session, workflow):
    tutor, _, _ = setup_planner
    accepted = submit(setup_planner, session)
    run(setup_planner, accepted.run_id, {
        **document(), "environment_recipes": ["typescript-standard.v1"],
        "environment_dependencies": [course().model_dump(mode="json")],
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
def test_route_declared_dependencies_use_the_existing_explicit_install_decision(
    course_plan, session, install,
):
    tutor, plan, environments = course_plan
    manifest = environments.route_manifest(session.token, plan.id, 1)
    assert len(manifest.consent_required) == 1
    extra = manifest.consent_required[0]
    assert extra.course_environment == course()
    assert not environments.snapshot(session.token).demands
    tutor.confirm_plan(
        session.token, plan.id, 1, manifest.requirements if install else None,
    )
    demand = next(
        item for item in environments.snapshot(session.token).demands
        if item.requirement.course_environment
    )
    assert demand.plan_id == plan.id and demand.plan_revision == 1
    assert demand.decision == ("allow" if install else None)
    assert demand.status == ("queued" if install else "waiting_authorization")
    if not install:
        environments.decide(session.token, demand.id, str(uuid4()), EnvironmentDecisionInput(
            decision="allow", expected_requirement_revision=demand.requirement_revision,
            expected_decision_revision=demand.decision_revision,
        ))
        updated = next(
            item for item in environments.snapshot(session.token).demands if item.id == demand.id
        )
        assert updated.status == "queued"


def test_route_package_change_requires_a_new_installation_decision(
    course_plan, session, setup_planner,
):
    tutor, plan, environments = course_plan
    manifest = environments.route_manifest(session.token, plan.id, 1)
    tutor.confirm_plan(session.token, plan.id, 1, manifest.requirements)
    accepted = submit(setup_planner, session, revision=1)
    updated = course(version="1.11.12")
    run(setup_planner, accepted.run_id, {
        **document(), "environment_recipes": ["typescript-standard.v1"],
        "environment_dependencies": [updated.model_dump(mode="json")],
    })
    manifest = environments.route_manifest(session.token, plan.id, 2)
    assert manifest.consent_required[0].course_environment == updated
    tutor.confirm_plan(session.token, plan.id, 2)
    demand = next(
        item for item in environments.snapshot(session.token).demands
        if item.requirement.course_environment
    )
    assert demand.plan_revision == 2
    assert demand.requirement_revision == 2
    assert demand.decision is None and demand.status == "waiting_authorization"


def test_same_course_packages_reuse_consent_after_a_route_and_display_title_update(
    course_plan, session, setup_planner,
):
    tutor, plan, environments = course_plan
    manifest = environments.route_manifest(session.token, plan.id, 1)
    tutor.confirm_plan(session.token, plan.id, 1, manifest.requirements)
    accepted = submit(setup_planner, session, revision=1)
    renamed = course().model_copy(update={"title": "Same packages in the next route"})
    run(setup_planner, accepted.run_id, {
        **document(), "environment_recipes": ["typescript-standard.v1"],
        "environment_dependencies": [renamed.model_dump(mode="json")],
    })
    manifest = environments.route_manifest(session.token, plan.id, 2)
    assert not manifest.consent_required
    tutor.confirm_plan(session.token, plan.id, 2)
    demand = next(
        item for item in environments.snapshot(session.token).demands
        if item.requirement.course_environment
    )
    assert demand.plan_revision == 2 and demand.decision == "allow"
