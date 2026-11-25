import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_composition_practice import owned_setup as owned_setup
from test_composition_practice import practice_provider
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import selected
from test_python_execution import owned_claim, program, receipt
from test_python_execution import python_setup as python_setup
from test_runner import runner as runner
from test_teaching_delivery import drain

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionRespondAction,
    CompositionRunAction,
)
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.demo_contracts import (
    DemoCompleteAction,
    DemoEventAction,
    DemoStartAction,
)
from leornian.modules.tutor.learning_artifact_contracts import CancelAction, LearningCandidateInput
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def mixed_scene(database, session, owned_setup):
    setup = owned_setup
    python = selected(session, setup)
    choice = setup["flow"].candidate(
        session.token, setup["conversation"].id,
        LearningCandidateInput(pack_id=setup["choice_pack"].pack_id, slot="practice_1"),
    )

    def add_step_player(args):
        editor = args["definition"]["components"][0]
        assert editor["id"] == "response" and editor["component"] == "CodeDiff"
        editor["component"] = "CodeEditor"
        editor["props"].pop("before")
        args["definition"]["states"]["step_cursor"] = {"type": "playback"}
        args["definition"]["components"].append({
            "id": "steps", "component": "StepPlayer", "props": {
                "label": "Inspect the input and output", "state": "step_cursor",
                "items": ["Read the input", "Inspect the program", "Compare the output"],
            },
        })
        args["demo_components"] = ["steps"]

    accepted = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()), TurnInput(
            text="Present the two ordinary practices and a separate explicit step demonstration.",
            focus=python.focus,
            presentation_capabilities={
                "versions": ["learning_composition.v2"],
                "actions": ["learning_practice.v2", "learning_demo_events.v1"],
            },
        ),
    )

    def before_review():
        assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
        turn = next(
            turn for turn in setup["tutor"].turn_history(
                session.token, setup["conversation"].id,
            ) if turn.id == accepted.turn_id
        )
        assert turn.assistant_text is None and turn.learning_interaction is None

    gateway, wires, prepared = practice_provider(
        setup["settings"], python.id, extra_source_id=choice.id, mutate=add_step_player,
        conflict=before_review, preparation="prepare_learning_demo_composition",
    )
    task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
    assert task.status == "accepted" and len(wires) == 4
    assert len(prepared) == 1 and prepared[0]["status"] == "completed"
    review = json.loads(wires[-1]["messages"][-1]["content"])
    assert "composition_checks" in review and "demo_interaction_checks" in review
    artifact = setup["flow"].list_v2(session.token, setup["conversation"].id)[0]
    turn = next(
        turn for turn in setup["tutor"].turn_history(session.token, setup["conversation"].id)
        if turn.id == accepted.turn_id
    )
    assert str(turn.learning_interaction.exact_handle) == prepared[0]["candidate"]["id"]
    with database.transaction() as connection:
        tools = Runs(connection).lock(accepted.run_id)["tool_contracts"]
        assert tools["prepare_learning_demo_composition"] == 1
        assert tools["prepare_learning_practice_composition"] == 1
    scene = SimpleNamespace(
        **setup, artifact_id=artifact.id, accepted=accepted, wires=wires,
        prepared=prepared[0]["candidate"], receipts=[],
    )
    initial = read(scene, session)
    assert initial.state == "ready" and initial.revision == 1
    assert set(owners(initial)) == {"response", "second_response"}
    assert owners(initial)["response"].source.kind == "code_workspace"
    assert owners(initial)["second_response"].source.kind == "knowledge_check"
    assert initial.demo_bindings[0].component_id == "steps"
    assert initial.presentation.definition.components[0].component == "CodeEditor"
    assert str(initial.content_ref.id) == scene.prepared["content_ref"]["id"]
    return scene


def read(scene, session):
    return scene.flow.get_v2(
        session.token, scene.conversation.id, scene.artifact_id,
        demo_capability="learning_demo_events.v1",
    )


def owners(view):
    return {binding.component_id: binding for binding in view.component_bindings}


def apply(scene, session, data):
    receipt = scene.flow.action(
        session.token, scene.conversation.id, scene.artifact_id, data,
    )
    scene.receipts.append((data, receipt))
    return receipt


def start_demo(scene, session):
    return apply(scene, session, DemoStartAction(
        action="start_demo", component_id="steps", client_action_id=uuid4(),
        expected_artifact_revision=read(scene, session).revision,
    ))


def acknowledge(scene, session):
    current = read(scene, session)
    demo = current.demo_bindings[0]
    return apply(scene, session, DemoEventAction(
        action="acknowledge_demo_event", component_id="steps",
        client_action_id=uuid4(), expected_artifact_revision=current.revision,
        generation=demo.generation, nonce=demo.nonce, sequence=1,
        event="timeline_end", step_index=demo.last_step,
    ))


def complete_demo(scene, session):
    acknowledge(scene, session)
    current = read(scene, session)
    demo = current.demo_bindings[0]
    return apply(scene, session, DemoCompleteAction(
        action="complete_demo", component_id="steps",
        client_action_id=uuid4(), expected_artifact_revision=current.revision,
        generation=demo.generation, nonce=demo.nonce, sequence=2,
    ))


def run_python(scene, session, code, previous=None):
    return apply(scene, session, CompositionRunAction(
        action="run_component", component_id="response", client_action_id=uuid4(),
        expected_artifact_revision=read(scene, session).revision,
        payload={"code": code, "previous_attempt_id": previous},
    ))


def answer_choice(scene, session):
    return apply(scene, session, CompositionRespondAction(
        action="respond_component", component_id="second_response",
        client_action_id=uuid4(), expected_artifact_revision=read(scene, session).revision,
        payload={"selected_key": "A"},
    ))


def cancel(scene, session):
    return apply(scene, session, CancelAction(
        action="cancel", client_action_id=uuid4(),
        expected_artifact_revision=read(scene, session).revision,
    ))


def assert_replays(scene, session):
    for data, expected_receipt in scene.receipts:
        assert scene.flow.action(
            session.token, scene.conversation.id, scene.artifact_id, data,
        ) == expected_receipt
        assert scene.flow.action_receipt(
            session.token, scene.conversation.id, scene.artifact_id, data.client_action_id,
        ) == expected_receipt


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_three_owners_keep_failure_new_attempt_demo_generations_and_cancelled_receipts_independent(
    database, workflow, session, mixed_scene,
):
    scene = mixed_scene
    initial = read(scene, session)
    started = start_demo(scene, session)
    first = run_python(scene, session, "print(0)")
    claim = owned_claim(database, session, first.result_id)
    assert claim is not None
    pending = read(scene, session)
    assert pending.state == "running"
    assert owners(pending)["response"].result.code == "print(0)"
    demo = pending.demo_bindings[0]
    assert demo.state == "started" and demo.generation == 1 and demo.sequence == 0
    assert demo.nonce == started.nonce and not demo.allowed_actions
    blocked = DemoEventAction(
        action="acknowledge_demo_event", component_id="steps", client_action_id=uuid4(),
        expected_artifact_revision=pending.revision, generation=demo.generation,
        nonce=demo.nonce, sequence=1, event="timeline_end", step_index=demo.last_step,
    )
    with pytest.raises(BusinessError, match="No ready demonstration"):
        apply(scene, session, blocked)
    assert read(scene, session) == pending
    with pytest.raises(BusinessError, match="No committed"):
        scene.flow.action_receipt(
            session.token, scene.conversation.id, scene.artifact_id, blocked.client_action_id,
        )
    choice = answer_choice(scene, session)
    assert choice.result_owner == "assessment" and choice.state == "running"
    answered = read(scene, session)
    choice_binding = owners(answered)["second_response"]
    assert choice_binding.result.correct and not choice_binding.allowed_actions
    assert owners(answered)["response"].result.id == first.result_id
    assert answered.demo_bindings == pending.demo_bindings
    JourneyWorkflow(database).report(
        claim.job_id, receipt(database, claim, scene.runner, wrong=True),
    )
    failed = read(scene, session)
    assert failed.state == "ready"
    first_attempt = owners(failed)["response"].result
    assert first_attempt.status == "not_passed"
    assert first_attempt.policy_version == "python-practice.v2"
    assert owners(failed)["response"].allowed_actions == ["run"]
    assert owners(failed)["second_response"] == choice_binding
    assert failed.demo_bindings[0].nonce == started.nonce
    first_report = complete_demo(scene, session)
    before_revision = read(scene, session)
    assert first_report.state == before_revision.state == "completed"
    first_demo = before_revision.demo_bindings[0].completions[0]
    assert first_demo.id == first_report.result_id
    assert first_demo.evidence_kind == "learner_demo_report.v1"
    restarted = start_demo(scene, session)
    assert restarted.generation == 2 and restarted.nonce != started.nonce
    assert read(scene, session).demo_bindings[0].completions == [first_demo]
    second_report = complete_demo(scene, session)
    before_revision = read(scene, session)
    with pytest.raises(BusinessError) as stale:
        run_python(scene, session, program("practice_1"))
    assert stale.value.code == "stale_version"
    assert read(scene, session) == before_revision
    second = run_python(scene, session, program("practice_1"), first.result_id)
    running_again = read(scene, session)
    assert running_again.state == "running"
    assert owners(running_again)["second_response"] == choice_binding
    assert (running_again.demo_bindings[0].completions
            == before_revision.demo_bindings[0].completions)
    assert not running_again.demo_bindings[0].allowed_actions
    claim = owned_claim(database, session, second.result_id)
    assert claim is not None
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, scene.runner))
    passed = read(scene, session)
    python_binding = owners(passed)["response"]
    assert passed.state == "completed" and python_binding.result.status == "passed"
    assert python_binding.result.previous_attempt_id == first.result_id
    assert [attempt.id for attempt in python_binding.attempts.items] == [
        second.result_id, first.result_id,
    ]
    assert python_binding.attempts.items[1] == first_attempt
    assert owners(passed)["second_response"] == choice_binding
    reports = passed.demo_bindings[0].completions
    assert [report.id for report in reports] == [second_report.result_id, first_report.result_id]
    with pytest.raises(BusinessError, match="自由练习"):
        cancel(scene, session)
    final = read(scene, session)
    assert final == passed and final.practice_only and not final.allowed_actions
    assert final.content_ref == initial.content_ref
    assert owners(final)["response"].result == python_binding.result
    assert owners(final)["response"].attempts == python_binding.attempts
    assert owners(final)["second_response"].result == choice_binding.result
    assert not any(binding.allowed_actions for binding in final.component_bindings)
    assert final.demo_bindings[0].completions == reports
    assert not final.demo_bindings[0].allowed_actions
    assert scene.flow.demo_history(
        session.token, scene.conversation.id, scene.artifact_id, "steps", None, 20,
    ).items == reports
    assert_replays(scene, session)
    for forbidden in (
        lambda: start_demo(scene, session),
        lambda: answer_choice(scene, session),
        lambda: run_python(scene, session, program("practice_1"), second.result_id),
    ):
        with pytest.raises(BusinessError):
            forbidden()
    assert read(scene, session) == final
    snapshot = workflow.snapshot(session.token)
    assert {attempt.id for attempt in snapshot.python_attempts} == {
        first.result_id, second.result_id,
    }
    assert [result.id for result in snapshot.choice_results] == [choice.result_id]
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert len(scene.wires) == 4


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_running_cancel_keeps_choice_demo_and_original_receipts_when_python_report_arrives_late(
    database, workflow, session, mixed_scene,
):
    scene = mixed_scene
    start_demo(scene, session)
    demo_receipt = complete_demo(scene, session)
    answer_choice(scene, session)
    before_run = read(scene, session)
    choice = owners(before_run)["second_response"]
    reports = before_run.demo_bindings[0].completions
    assert before_run.state == "ready" and reports[0].id == demo_receipt.result_id
    running = run_python(scene, session, program("practice_1"))
    late = owned_claim(database, session, running.result_id)
    assert late is not None
    assert read(scene, session).state == "running"
    cancel(scene, session)
    cancelled = read(scene, session)
    assert cancelled.state == "cancelled" and not cancelled.allowed_actions
    assert owners(cancelled)["response"].result.status == "error"
    assert owners(cancelled)["response"].result.code == program("practice_1")
    assert owners(cancelled)["second_response"].result == choice.result
    assert cancelled.demo_bindings[0].completions == reports
    report = receipt(database, late, scene.runner)
    JourneyWorkflow(database).report(late.job_id, report)
    assert read(scene, session) == cancelled
    assert_replays(scene, session)
    with database.transaction() as connection:
        recorded = connection.execute(
            "SELECT status,report FROM execution.jobs WHERE id=%s AND actor_id=%s",
            (late.job_id, session.actor.id),
        ).fetchone()
        assert recorded["status"] == "expired"
        assert recorded["report"]["late_receipt"] == report.model_dump(mode="json")
        assert recorded["report"]["error_code"] == "learner_cancelled"
    assert scene.flow.demo_history(
        session.token, scene.conversation.id, scene.artifact_id, "steps", None, 20,
    ).items == reports
    snapshot = workflow.snapshot(session.token)
    assert [attempt.id for attempt in snapshot.python_attempts] == [running.result_id]
    assert [result.id for result in snapshot.choice_results] == [choice.result.id]
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert len(scene.wires) == 4
