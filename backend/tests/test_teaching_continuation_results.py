import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.assessment.assistance import PracticeAssistance
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionRespondAction,
    CompositionRunAction,
)
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.modules.tutor.teaching_session_contracts import (
    OpenTeachingSession,
    SetContinuationPolicy,
)
from test_composition_practice import current, definition_for, introduce_owned
from test_composition_practice import owned_setup as owned_setup
from test_concept_gates import gate_setup as gate_setup
from test_demo_interactions import apply, completion, event, start, view_for
from test_demo_interactions import demo_scene as demo_scene
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_learning_artifacts import selected
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_practice_hints import HINTS, introduce_hints
from test_practice_hints import current as hint_current
from test_python_execution import owned_claim, program, receipt
from test_python_execution import python_setup as python_setup
from test_teaching_delivery import drain, provider


def enable(database, session, conversation_id, focus=None):
    controls = TeachingSessionWorkflow(database)
    state = controls.command(session.token, conversation_id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
        focus=focus or TeachingFocus(),
    ))
    return controls.command(session.token, conversation_id, SetContinuationPolicy(
        action="set_continuation_policy", policy="after_result.v1",
        client_action_id=uuid4(), expected_session_revision=state.revision,
    ))


def automatic(flow, tutor, session, conversation_id):
    intents = flow.list(session.token, conversation_id)
    intent = next(item for item in intents if item.state == "dispatched")
    return tutor.requested_turn(
        session.token, conversation_id, f"teaching-intent:{intent.id}",
    )


def test_demo_start_end_are_not_completion_and_one_report_continues_without_mastery(
    database, session, workflow, demo_scene,
):
    _, settings, conversation, _, _ = demo_scene
    enable(database, session, conversation.id)
    flow = TeachingContinuationWorkflow(database, settings)
    start(demo_scene, session)
    assert flow.list(session.token, conversation.id) == []
    apply(demo_scene, session, event(demo_scene, session))
    assert flow.list(session.token, conversation.id) == []
    command = completion(demo_scene, session)
    completed = apply(demo_scene, session, command)
    assert apply(demo_scene, session, command) == completed
    queued = flow.list(session.token, conversation.id)
    assert len(queued) == 1 and queued[0].trigger_ref == f"demo:{completed.result_id}"
    assert queued[0].trigger_kind == "interaction_event" and queued[0].run_id is None
    flow.reconcile_once()
    tutor = TutorWorkflow(database, settings)
    accepted = automatic(flow, tutor, session, conversation.id)
    gateway, sent, _ = provider(settings, author="Now compare the discovered queue states.")
    delivered = drain(tutor, settings, accepted, gateway, session.token)
    if delivered.status == "waiting_dependency":
        from test_material_sources_and_goals import advance_consumer_materials
        advance_consumer_materials(database, session, settings, conversation.goal_id)
        tutor.resume_delivery(session.token, delivered.id)
        delivered = drain(tutor, settings, accepted, gateway, session.token)
    assert delivered.status == "accepted"
    assert len(sent) == 2
    wire = json.dumps(sent[0]["messages"])
    assert "learner_demo_report.v1" in wire and str(completed.result_id) in wire
    assert "not learner speech" in wire
    assert len(flow.list(session.token, conversation.id)) == 1
    assert view_for(demo_scene, session).demo_bindings[0].completion_count == 1
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.choice_results and not snapshot.python_attempts
    assert not snapshot.node_progress and not snapshot.execution_progress


def test_new_demo_generation_keeps_old_report_but_retires_its_pending_continuation(
    database, session, demo_scene,
):
    _, settings, conversation, _, _ = demo_scene
    enable(database, session, conversation.id)
    flow = TeachingContinuationWorkflow(database, settings)
    start(demo_scene, session)
    apply(demo_scene, session, event(demo_scene, session))
    apply(demo_scene, session, completion(demo_scene, session))
    start(demo_scene, session)
    flow.reconcile_once()
    intent, = flow.list(session.token, conversation.id)
    assert intent.state == "superseded" and intent.run_id is None
    shown = view_for(demo_scene, session).demo_bindings[0]
    assert shown.generation == 2 and shown.completion_count == 1 and shown.state == "started"


def test_result_continuation_excludes_previous_private_hint_preparation(
    database, session, workflow, learning_setup,
):
    setup = {
        **learning_setup, "pack_id": learning_setup["pack"].pack_id,
        "focus": selected(session, learning_setup).focus,
        "listing": "list_learning_artifact_candidates",
        "define": definition_for, "capability": "learning_practice.v2",
    }
    introduce_hints(session, setup)
    anchor = hint_current(session, setup)
    enable(database, session, anchor.conversation_id, setup["focus"])
    setup["flow"].action(session.token, anchor.conversation_id, anchor.id, CompositionRespondAction(
        action="respond_component", component_id="response", payload={"selected_key": "B"},
        client_action_id=uuid4(), expected_artifact_revision=anchor.revision,
    ))
    flow = TeachingContinuationWorkflow(database, setup["settings"])
    flow.reconcile_once()
    accepted = automatic(flow, setup["tutor"], session, anchor.conversation_id)
    gateway, sent, _ = provider(
        setup["settings"], author="Compare your trace with the recorded result.",
    )
    assert drain(
        setup["tutor"], setup["settings"], accepted, gateway, session.token,
    ).status == "accepted"
    for call in sent:
        assert all(hint["text"] not in json.dumps(call["messages"]) for hint in HINTS)
    shown = hint_current(session, setup).component_bindings[0]
    assert shown.result.selected_key == "B" and not shown.result.correct
    assert shown.hint_receipts == [] and shown.assistance_receipt is None
    with database.transaction() as connection:
        assert not PracticeAssistance(connection).hints(
            session.actor, setup["pack_id"], "practice_1",
        )
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.node_progress and not snapshot.execution_progress


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
def test_execution_only_captures_committed_result_and_new_attempt_retires_old_trigger(
    database, session, workflow, owned_setup,
):
    setup = owned_setup
    introduce_owned(session, setup)
    shown = current(session, setup)
    enable(database, session, shown.conversation_id, shown.focus)
    flow = TeachingContinuationWorkflow(database, setup["settings"])

    def run(code, previous=None):
        view = current(session, setup)
        return setup["flow"].action(
            session.token, view.conversation_id, view.id, CompositionRunAction(
                action="run_component", component_id="response", client_action_id=uuid4(),
                expected_artifact_revision=view.revision,
                payload={"code": code, "previous_attempt_id": previous},
            ),
        )

    first = run("print(0)")
    assert flow.list(session.token, shown.conversation_id) == []
    claim = owned_claim(database, session, first.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, None, wrong=True))
    intent, = flow.list(session.token, shown.conversation_id)
    assert intent.trigger_kind == "expected_result"
    assert intent.trigger_ref == f"python:{first.result_id}" and intent.run_id is None
    second = run(program("practice_1"), first.result_id)
    flow.reconcile_once()
    assert flow.list(session.token, shown.conversation_id)[0].state == "superseded"
    claim = owned_claim(database, session, second.result_id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, None))
    flow.reconcile_once()
    accepted = automatic(flow, setup["tutor"], session, shown.conversation_id)
    gateway, sent, _ = provider(setup["settings"], author="The second submitted trace passed.")
    assert drain(
        setup["tutor"], setup["settings"], accepted, gateway, session.token,
    ).status == "accepted"
    assert len(sent) == 2
    assert str(second.result_id) in json.dumps(sent[0]["messages"])
    final = current(session, setup).component_bindings[0]
    assert final.result.id == second.result_id and final.result.status == "passed"
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.python_attempts) >= 2
    assert not snapshot.node_progress and not snapshot.execution_progress


def test_user_admission_waits_for_original_acceptance_without_conversation_lock_inversion(
    database, session, learning_setup, monkeypatch,
):
    from leornian.modules.tutor.learning_artifact_contracts import RespondAction
    from test_learning_artifacts import introduce

    setup = learning_setup
    candidate = selected(session, setup)
    view, _ = introduce(session, setup, candidate)
    state = enable(database, session, view.conversation_id, view.focus)
    setup["flow"].action(session.token, view.conversation_id, view.id, RespondAction(
        action="respond", client_action_id=uuid4(), expected_artifact_revision=view.revision,
        payload={"selected_key": "A"},
    ))
    flow = TeachingContinuationWorkflow(database, setup["settings"])
    flow.reconcile_once()
    accepted = automatic(flow, setup["tutor"], session, view.conversation_id)
    at_publication, at_cancellation = threading.Event(), threading.Event()
    original_advance, original_cancel = LearningArtifacts.advance, TutorWorkflow.cancel_in

    def pause_at_publication(store, actor, conversation_id, expected):
        if conversation_id == view.conversation_id:
            at_publication.set()
            assert at_cancellation.wait(10)
        return original_advance(store, actor, conversation_id, expected)

    def notify_cancel(cls, connection, actor, run_id):
        if run_id == accepted.run_id:
            at_cancellation.set()
        return original_cancel(connection, actor, run_id)

    monkeypatch.setattr(LearningArtifacts, "advance", pause_at_publication)
    monkeypatch.setattr(TutorWorkflow, "cancel_in", classmethod(notify_cancel))
    gateway, _, _ = provider(setup["settings"], author="The recorded trace is consistent.")
    with ThreadPoolExecutor(max_workers=2) as pool:
        publishing = pool.submit(
            drain, setup["tutor"], setup["settings"], accepted, gateway, session.token,
        )
        assert at_publication.wait(15)
        user = pool.submit(
            setup["tutor"].submit, session.token, view.conversation_id, str(uuid4()),
            TurnInput(
                text="Explain the next case, without submitting it.",
                focus=view.focus, teaching_session_revision=state.revision,
            ),
        )
        assert publishing.result(timeout=20).status == "accepted"
        explicit = user.result(timeout=20)
    assert explicit.run_id != accepted.run_id
    assert setup["tutor"].cancel(session.token, explicit.run_id).status == "cancelled"
