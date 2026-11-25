import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_dynamic_plans import document
from test_route_discussion import discuss
from test_teaching_delivery import drain, provider
from test_teaching_delivery import managed as managed
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.bootstrap.teaching_context import TeachingContext
from leornian.bootstrap.teaching_delivery import TeachingDelivery
from leornian.modules.execution.environment_contracts import EngineObservationInput
from leornian.modules.execution.environments import Environments
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.contracts import PlanningInput, TeachingFocus, TurnInput
from leornian.modules.tutor.teaching_guidance import (
    INTERACTION_SELECTION_POLICY,
    INTERACTIVE_TEACHING_POLICY,
    SANDBOX_LEARNING_POLICY,
    SANDBOX_PLANNING_POLICY,
)


def observe(connection, status):
    Environments(connection).observe_engine(EngineObservationInput(
        runner_id="owned-test-controller", status=status, detail="Actual test observation",
    ))


@pytest.fixture
def first_program(managed, session, workflow):
    tutor, settings, conversation = managed
    discuss(
        managed, session, workflow, "Learn Python. No prior programming knowledge.",
        requirements={"goal": "Learn Python", "prior_knowledge": "No prior programming knowledge"},
        ready=True,
    )
    route = document()
    route["assumptions"] = []
    route["nodes"][0].update(
        title="Environment setup and first program",
        objective="Install Python, configure PATH, then print a greeting.",
    )
    proposed = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(
            text="Give me the complete route.", expected_revision=0,
            discussion=True, start_plan=True, expected_requirements_revision=1,
        ),
    )
    gateway, sent, _ = provider(settings, author=json.dumps({
        "text": "Here is the complete proposed route.", "route": route,
    }))
    assert drain(tutor, settings, proposed, gateway, session.token).status == "accepted"
    assert SANDBOX_PLANNING_POLICY in sent[0]["messages"][0]["content"]
    assert INTERACTIVE_TEACHING_POLICY not in sent[0]["messages"][0]["content"]
    plan = workflow.snapshot(session.token).plans[0]
    assert plan.active is None
    tutor.confirm_plan(session.token, plan.id, plan.latest.revision)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=plan.latest.revision, node_key="paths",
    )
    return tutor, settings, conversation, plan, focus


@pytest.mark.parametrize("engine_status", ["stopped", "ready"])
def test_first_program_author_and_review_get_small_steps_and_actual_sandbox_state(
    database, workflow, session, first_program, engine_status,
):
    tutor, settings, conversation, plan, focus = first_program
    with database.transaction() as connection:
        observe(connection, engine_status)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()),
        TurnInput(text="I've never written a program. What do I write first?", focus=focus),
    )
    reply = (
        "This program prints a greeting.\n```python\nprint('Hello, Python')\n```\n"
        "What text do you expect it to print?"
    )
    gateway, sent, _ = provider(settings, author=reply)
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert len(sent) == 2
    author = sent[0]["messages"][0]["content"]
    assert INTERACTIVE_TEACHING_POLICY in author
    assert SANDBOX_LEARNING_POLICY in author
    context = json.loads(next(
        message["content"].removeprefix("Learning context (data): ")
        for message in sent[0]["messages"]
        if message["content"].startswith("Learning context (data): ")
    ))
    assert context["node"]["confirmed_node"]["objective"] == plan.latest.document.nodes[0].objective
    environments = context["workspace"]["execution_environments"]
    assert environments["engine"]["status"] == engine_status
    assert environments["plan_id"] == str(plan.id)
    assert environments["plan_revision"] == plan.latest.revision
    assert environments["usable_environments"] == []
    assert environments["demands"] == []
    assert any(item["recipe_id"] == "python-standard.v1" for item in environments["recipes"])
    review = json.loads(sent[1]["messages"][-1]["content"])
    assert review["teaching_turn_checks"] == INTERACTIVE_TEACHING_POLICY
    assert review["execution_environment_checks"] == SANDBOX_LEARNING_POLICY
    assert review["candidate"] == reply
    current = tutor.plan(session.token, plan.id)
    assert current.active.document == plan.latest.document
    snapshot = workflow.snapshot(session.token)
    assert snapshot.turns[0].turns[-1].assistant_text == reply
    assert not snapshot.program_attempts and not snapshot.python_attempts
    with database.transaction() as connection:
        assert Environments(connection).snapshot(session.actor).demands == []


def test_context_refresh_reads_engine_state_without_preparing_or_authorizing_environments(
    database, managed, session,
):
    _, _, conversation = managed
    with database.transaction() as connection:
        observe(connection, "stopped")
        first, _ = TeachingContext.build(
            connection, session.actor, conversation, TeachingFocus(),
        )
        observe(connection, "ready")
        second, _ = TeachingContext.build(
            connection, session.actor, conversation, TeachingFocus(),
        )
    assert first["execution_environments"]["engine"]["status"] == "stopped"
    assert second["execution_environments"]["engine"]["status"] == "ready"
    assert first["execution_environments"]["demands"] == second["execution_environments"]["demands"]
    assert not second["execution_environments"]["usable_environments"]


@pytest.mark.parametrize("kind", ["teaching", "planning", "lesson"])
def test_review_pacing_is_specific_to_conversation_not_complete_routes_or_lessons(kind):
    role = TeachingDelivery.review_role({
        "kind": kind, "candidate_call_id": uuid4(),
        "candidate": json.dumps(document()) if kind == "planning" else "Candidate",
        "candidate_input": [], "context_manifest": {}, "issues": [], "output_multiplier": 1,
    })
    payload = json.loads(role.messages[-1]["content"])
    assert ("teaching_turn_checks" in payload) == (kind == "teaching")
    assert payload["execution_environment_checks"] == (
        SANDBOX_PLANNING_POLICY if kind == "planning" else SANDBOX_LEARNING_POLICY
    )


@pytest.mark.parametrize("kind", ["teaching", "planning", "lesson"])
def test_original_roles_share_sandbox_rules_without_truncating_complete_documents(kind):
    tutor = Tutor(None)
    turn = SimpleNamespace(id=uuid4(), user_text="Explain this.", completed_at=None)
    if kind == "teaching":
        role = tutor.role({}, [turn], turn.id)
    else:
        role = getattr(tutor, kind + "_role")({}, turn)
    system = role.messages[0]["content"]
    assert (INTERACTIVE_TEACHING_POLICY in system) == (kind == "teaching")
    assert (SANDBOX_PLANNING_POLICY if kind == "planning" else SANDBOX_LEARNING_POLICY) in system


def test_local_inert_preview_is_distinct_from_assessed_web_execution():
    assert "An IsolatedPreview is local presentation, not Runner execution" in (
        SANDBOX_LEARNING_POLICY
    )
    assert "requires no execution-environment release" in SANDBOX_LEARNING_POLICY
    assert "executable workspaces still require their original execution owner" in (
        SANDBOX_LEARNING_POLICY
    )
    role = TeachingDelivery.review_role({
        "kind": "teaching", "candidate_call_id": uuid4(), "candidate": "Candidate",
        "candidate_input": [], "context_manifest": {"learning_composition_contract": 2},
        "issues": [], "output_multiplier": 1,
    })
    checks = json.loads(role.messages[-1]["content"])["execution_environment_checks"]
    assert checks == SANDBOX_LEARNING_POLICY


@pytest.mark.parametrize("kind", ["teaching", "planning", "lesson"])
@pytest.mark.parametrize("interactive", [False, True])
def test_activity_based_interaction_checks_only_apply_to_capable_teaching(kind, interactive):
    role = TeachingDelivery.review_role({
        "kind": kind, "candidate_call_id": uuid4(),
        "candidate": json.dumps(document()) if kind == "planning" else "Candidate",
        "candidate_input": [],
        "context_manifest": {"learning_interaction_contract": 1} if interactive else {},
        "issues": [], "output_multiplier": 1,
    })
    payload = json.loads(role.messages[-1]["content"])
    expected = kind == "teaching" and interactive
    assert ("interaction_selection_checks" in payload) == expected
    if expected:
        assert payload["interaction_selection_checks"] == INTERACTION_SELECTION_POLICY


def test_legacy_qualified_workspaces_follow_their_original_environment_contract():
    assert "exact environment admission checks" in SANDBOX_LEARNING_POLICY
    assert "no release binding" in SANDBOX_LEARNING_POLICY
    assert "unrelated environment demand" in SANDBOX_LEARNING_POLICY
