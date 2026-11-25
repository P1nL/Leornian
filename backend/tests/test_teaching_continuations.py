import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_learning_artifacts import selected
from test_teaching_delivery import body, drain, provider
from test_tutor_runtime import calls

from leornian.agent_runtime.contracts import Receipt, TurnAccepted
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.deliveries import Deliveries
from leornian.modules.tutor.learning_artifact_contracts import RespondAction
from leornian.modules.tutor.teaching_intent_contracts import CancelTeachingIntent
from leornian.modules.tutor.teaching_intents import TeachingIntents
from leornian.modules.tutor.teaching_session_contracts import (
    OpenTeachingSession,
    PauseTeaching,
    ResumeTeaching,
    ReturnToMain,
    SetContinuationPolicy,
    SetTeachingMode,
    SetTeachingTopic,
)
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def continuation_scene(database, session, learning_setup):
    setup = learning_setup
    candidate = selected(session, setup)
    source_key = str(uuid4())
    source_data = TurnInput(
        text="Introduce the displayed practice, without answering.",
        focus=candidate.focus,
        learning_candidate_id=candidate.id,
    )
    source = setup["tutor"].submit(
        session.token, setup["conversation"].id, source_key, source_data,
    )
    gateway, _, _ = provider(setup["settings"], author="Consider how many iterations occur.")
    assert drain(
        setup["tutor"], setup["settings"], source, gateway, session.token,
    ).status == "accepted"
    artifact = setup["flow"].get(
        session.token, setup["conversation"].id,
        setup["flow"].list(session.token, setup["conversation"].id)[0].id,
    )
    controls = TeachingSessionWorkflow(database)
    opened = controls.command(
        session.token, artifact.conversation_id,
        OpenTeachingSession(
            action="open", client_action_id=uuid4(), expected_session_revision=0,
            focus=candidate.focus,
        ),
    )
    scene = SimpleNamespace(
        **setup, candidate=candidate, source_accepted=source, source_key=source_key,
        source_data=source_data, artifact=artifact, controls=controls, opened=opened,
        intents=TeachingContinuationWorkflow(database, setup["settings"]),
    )
    yield scene
    for intent in scene.intents.list(session.token, scene.conversation.id, limit=100):
        if intent.state in {"pending", "dispatched"}:
            scene.intents.cancel(
                session.token, scene.conversation.id, intent.id,
                CancelTeachingIntent(client_action_id=uuid4()),
            )
    with database.transaction(snapshot=True) as connection:
        active = connection.execute(
            "SELECT id FROM runtime.runs WHERE actor_id=%s "
            "AND status IN ('queued','running','blocked_unknown')",
            (session.actor.id,),
        ).fetchall()
    for run in active:
        scene.tutor.cancel(session.token, run["id"])


def control(scene, session, command_type, **values):
    state = scene.controls.get(session.token, scene.conversation.id)
    return scene.controls.command(
        session.token, scene.conversation.id,
        command_type(
            client_action_id=uuid4(), expected_session_revision=state.revision, **values,
        ),
    )


def enable(scene, session):
    return control(
        scene, session, SetContinuationPolicy,
        action="set_continuation_policy", policy="after_result.v1",
    )


def respond(scene, session):
    command = RespondAction(
        action="respond", client_action_id=uuid4(),
        expected_artifact_revision=scene.artifact.revision,
        payload={"selected_key": "A"},
    )
    return scene.flow.action(
        session.token, scene.conversation.id, scene.artifact.id, command,
    ), command


def current_intent(scene, session):
    rows = scene.intents.list(session.token, scene.conversation.id)
    assert len(rows) == 1
    return rows[0]


def due(database, intent):
    with database.transaction() as connection:
        connection.execute(
            "UPDATE tutor.teaching_intents SET next_check_at=now()-interval '1 second' WHERE id=%s",
            (intent.id,),
        )


def automatic(scene, session, database):
    scene.intents.reconcile_once()
    intent = current_intent(scene, session)
    assert intent.state == "dispatched" and intent.run_id
    run = scene.tutor.get(session.token, intent.run_id)
    with database.transaction(snapshot=True) as connection:
        task = Deliveries(connection).for_run(run.id)
    return intent, TurnAccepted(
        run_id=run.id, turn_id=run.turn_id, delivery_task_id=task["id"],
    )


@pytest.mark.parametrize("mode", ["guided", "free_reading"])
def test_existing_manual_and_free_reading_sessions_do_not_start_continuations(
    database, session, continuation_scene, mode,
):
    scene = continuation_scene
    assert scene.opened.continuation_policy == "manual"
    if mode == "free_reading":
        control(scene, session, SetTeachingMode, action="set_mode", mode=mode)
        enable(scene, session)
    before = scene.tutor.turn_history(session.token, scene.conversation.id)
    result, _ = respond(scene, session)
    assert result.result_id
    scene.intents.reconcile_once()
    assert not scene.intents.list(session.token, scene.conversation.id)
    assert scene.tutor.turn_history(session.token, scene.conversation.id) == before


def test_committed_choice_creates_one_checked_automatic_turn_without_self_triggering(
    database, workflow, session, continuation_scene, monkeypatch,
):
    scene = continuation_scene
    enable(scene, session)
    result, command = respond(scene, session)
    assert scene.flow.action(
        session.token, scene.conversation.id, scene.artifact.id, command,
    ) == result
    pending = current_intent(scene, session)
    assert pending.state == "pending" and pending.run_id is None
    assert pending.trigger_kind == "artifact_action"
    assert pending.trigger_ref == f"choice:{result.result_id}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: scene.intents.reconcile_once(), range(2)))
    intent = current_intent(scene, session)
    assert intent.state == "dispatched" and intent.run_status == "queued"
    run = scene.tutor.get(session.token, intent.run_id)
    turn = next(
        t for t in scene.tutor.turn_history(session.token, scene.conversation.id)
        if t.id == run.turn_id
    )
    assert turn.teaching_intent_id == intent.id and turn.teaching_branch_id is None
    assert turn.assistant_text is None
    with database.transaction() as connection:
        original = Runs(connection).lock(scene.source_accepted.run_id)
        generated = Runs(connection).lock(intent.run_id)
        task = Deliveries(connection).for_run(intent.run_id)
    assert generated["tool_contracts"] == original["tool_contracts"]
    assert generated["model_configuration_scope"] == original["model_configuration_scope"]
    accepted = TurnAccepted(
        run_id=run.id, turn_id=turn.id, delivery_task_id=task["id"],
    )

    def no_private_protocol(*_args, **_kwargs):
        raise AssertionError("Automatic follow-up must not read private preparation history.")

    monkeypatch.setattr(Runs, "protocol_history", no_private_protocol)
    gateway, sent, reviews = provider(
        scene.settings, author="Your recorded response identifies the iteration count.",
    )
    AgentLoop(scene.tutor, gateway).run(run.id)
    assert scene.tutor.delivery_task(session.token, task["id"]).status == "checking"
    assert next(
        t for t in scene.tutor.turn_history(session.token, scene.conversation.id)
        if t.id == turn.id
    ).assistant_text is None
    assert drain(scene.tutor, scene.settings, accepted, gateway, session.token).status == "accepted"
    assert len(sent) == 2 and len(reviews) == 1
    assert "server-issued guided continuation" in sent[0]["messages"][0]["content"]
    facts = json.loads(sent[0]["messages"][1]["content"].split("(data): ", 1)[1])
    assert str(result.result_id) in json.dumps(facts["observations"]["public_result"])
    assert facts["origin"]["trigger_ref"].endswith(str(result.result_id))
    review = json.loads(sent[-1]["messages"][-1]["content"])
    assert review["turn_evidence"]["learner_messages"] == []
    assert all(
        message.get("content") != turn.user_text
        for message in sent[0]["messages"] if message["role"] == "user"
    )
    scene.intents.reconcile_once()
    assert current_intent(scene, session).run_id == run.id
    assert len(calls(database, run.id)) == 2
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.choice_results) == 1
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert not snapshot.python_attempts and not snapshot.program_attempts


def test_pause_waits_and_resume_keeps_the_same_result_intent(
    database, session, continuation_scene,
):
    scene = continuation_scene
    enabled = enable(scene, session)
    paused = control(scene, session, PauseTeaching, action="pause")
    assert paused.continuation_generation == enabled.continuation_generation
    respond(scene, session)
    scene.intents.reconcile_once()
    pending = current_intent(scene, session)
    assert pending.state == "pending" and pending.wait_reason == "paused"
    assert pending.run_id is None
    resumed = control(scene, session, ResumeTeaching, action="resume")
    assert resumed.continuation_generation == enabled.continuation_generation
    due(database, pending)
    intent, _ = automatic(scene, session, database)
    assert intent.id == pending.id


def test_question_branch_waits_until_explicit_return_without_replacing_its_anchor(
    database, session, continuation_scene,
):
    scene = continuation_scene
    enabled = enable(scene, session)
    question = scene.tutor.submit(
        session.token, scene.conversation.id, str(uuid4()),
        TurnInput(
            text="Explain the loop condition without answering the practice.",
            focus=scene.candidate.focus, teaching_session_revision=enabled.revision,
        ),
    )
    state = scene.controls.get(session.token, scene.conversation.id)
    assert state.active_branch_id
    gateway, _, _ = provider(scene.settings, author="Inspect the condition before the body.")
    assert drain(scene.tutor, scene.settings, question, gateway, session.token).status == "accepted"
    respond(scene, session)
    scene.intents.reconcile_once()
    pending = current_intent(scene, session)
    assert pending.state == "pending" and pending.wait_reason == "question_branch"
    returned = control(
        scene, session, ReturnToMain, action="return_to_main", branch_id=state.active_branch_id,
    )
    assert returned.continuation_generation == enabled.continuation_generation
    due(database, pending)
    intent, accepted = automatic(scene, session, database)
    assert intent.id == pending.id
    assert next(
        t for t in scene.tutor.turn_history(session.token, scene.conversation.id)
        if t.id == accepted.turn_id
    ).teaching_branch_id is None


@pytest.mark.parametrize("change", ["policy", "topic"])
def test_explicit_policy_or_topic_change_supersedes_queued_intent(
    database, session, continuation_scene, change,
):
    scene = continuation_scene
    enabled = enable(scene, session)
    respond(scene, session)
    if change == "policy":
        changed = control(
            scene, session, SetContinuationPolicy,
            action="set_continuation_policy", policy="manual",
        )
    else:
        changed = control(
            scene, session, SetTeachingTopic, action="set_topic", focus=TeachingFocus(),
        )
    assert changed.continuation_generation == enabled.continuation_generation + 1
    scene.intents.reconcile_once()
    intent = current_intent(scene, session)
    assert intent.state == "superseded" and intent.run_id is None


def test_old_request_replay_does_not_preempt_but_new_user_message_does(
    database, session, continuation_scene,
):
    scene = continuation_scene
    enable(scene, session)
    respond(scene, session)
    intent, _ = automatic(scene, session, database)
    assert scene.tutor.submit(
        session.token, scene.conversation.id, scene.source_key, scene.source_data,
    ) == scene.source_accepted
    assert scene.tutor.get(session.token, intent.run_id).status == "queued"
    state = scene.controls.get(session.token, scene.conversation.id)
    key = str(uuid4())
    data = TurnInput(
        text="Wait, explain the empty-input case first.",
        focus=scene.candidate.focus, teaching_session_revision=state.revision,
    )
    explicit = scene.tutor.submit(session.token, scene.conversation.id, key, data)
    assert current_intent(scene, session).state == "superseded"
    assert scene.tutor.get(session.token, intent.run_id).status == "cancelled"
    assert scene.tutor.submit(session.token, scene.conversation.id, key, data) == explicit
    with pytest.raises(BusinessError) as problem:
        scene.tutor.submit(session.token, scene.conversation.id, str(uuid4()), data)
    assert problem.value.code == "run_active"
    assert scene.tutor.get(session.token, explicit.run_id).status == "queued"
    scene.intents.reconcile_once()
    assert current_intent(scene, session).run_id == intent.run_id


def test_rejected_stale_user_message_rolls_back_automatic_preemption(
    database, session, continuation_scene,
):
    scene = continuation_scene
    enable(scene, session)
    respond(scene, session)
    intent, _ = automatic(scene, session, database)
    before = scene.tutor.turn_history(session.token, scene.conversation.id)
    with pytest.raises(BusinessError) as problem:
        scene.tutor.submit(
            session.token, scene.conversation.id, str(uuid4()),
            TurnInput(
                text="Use a stale session.", focus=scene.candidate.focus,
                teaching_session_revision=1,
            ),
        )
    assert problem.value.code == "stale_version"
    assert current_intent(scene, session).state == "dispatched"
    assert scene.tutor.get(session.token, intent.run_id).status == "queued"
    assert scene.tutor.turn_history(session.token, scene.conversation.id) == before


@pytest.mark.parametrize("dispatch", [False, True])
def test_cancel_keeps_exact_receipt_and_never_creates_a_replacement(
    database, session, continuation_scene, dispatch,
):
    scene = continuation_scene
    enable(scene, session)
    respond(scene, session)
    intent = automatic(scene, session, database)[0] if dispatch else current_intent(scene, session)
    command = CancelTeachingIntent(client_action_id=uuid4())
    with pytest.raises(BusinessError) as missing:
        scene.intents.cancel_receipt(
            session.token, scene.conversation.id, intent.id, command.client_action_id,
        )
    assert missing.value.code == "not_found"
    cancelled = scene.intents.cancel(session.token, scene.conversation.id, intent.id, command)
    assert cancelled.state == "cancelled"
    if dispatch:
        assert cancelled.run_status == "cancelled"
    assert scene.intents.cancel(
        session.token, scene.conversation.id, intent.id, command,
    ) == cancelled
    assert scene.intents.cancel_receipt(
        session.token, scene.conversation.id, intent.id, command.client_action_id,
    ) == cancelled
    scene.intents.reconcile_once()
    assert current_intent(scene, session).run_id == intent.run_id


def test_intent_reads_cursors_and_cancellations_do_not_cross_actor_or_conversation(
    database, workflow, session, continuation_scene,
):
    scene = continuation_scene
    enable(scene, session)
    respond(scene, session)
    intent = current_intent(scene, session)
    foreign = workflow.create_session("Foreign continuation reader")
    command = CancelTeachingIntent(client_action_id=uuid4())
    with pytest.raises(BusinessError):
        scene.intents.list(foreign.token, scene.conversation.id)
    with pytest.raises(BusinessError):
        scene.intents.cancel(foreign.token, scene.conversation.id, intent.id, command)
    created = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Separate continuation scope"),
    )
    with database.transaction(snapshot=True) as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (created.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    other_goal = next(
        g for g in workflow.snapshot(session.token).goals if g.id != scene.conversation.goal_id
    )
    other = scene.tutor.conversation(session.token, other_goal.id)
    with pytest.raises(BusinessError) as bad_cursor:
        scene.intents.list(session.token, other.id, before=intent.id)
    assert bad_cursor.value.code == "not_found"
    with pytest.raises(BusinessError):
        scene.intents.cancel(session.token, other.id, intent.id, command)
    with pytest.raises(BusinessError):
        scene.intents.cancel_receipt(
            foreign.token, scene.conversation.id, intent.id, command.client_action_id,
        )
    assert current_intent(scene, session).state == "pending"


def test_owner_result_and_intent_capture_roll_back_together(
    database, workflow, session, continuation_scene, monkeypatch,
):
    scene = continuation_scene
    enable(scene, session)
    original = TeachingIntents.create

    def reject_after_insert(self, *args, **kwargs):
        assert original(self, *args, **kwargs)
        raise RuntimeError("Abort original owner transaction after intent insertion.")

    with monkeypatch.context() as scoped:
        scoped.setattr(TeachingIntents, "create", reject_after_insert)
        with pytest.raises(RuntimeError):
            respond(scene, session)
    assert not scene.intents.list(session.token, scene.conversation.id)
    assert not workflow.snapshot(session.token).choice_results
    original_view = scene.flow.get(session.token, scene.conversation.id, scene.artifact.id)
    assert original_view.revision == scene.artifact.revision and original_view.result is None
    respond(scene, session)
    assert current_intent(scene, session).state == "pending"


def test_revoked_source_prevents_admission_without_leaving_a_partial_turn(
    database, session, continuation_scene,
):
    scene = continuation_scene
    enable(scene, session)
    respond(scene, session)
    before = scene.tutor.turn_history(session.token, scene.conversation.id)
    KnowledgeWorkflow(database).revoke(
        session.token, scene.source.id, 1,
    )
    scene.intents.reconcile_once()
    intent = current_intent(scene, session)
    assert intent.state == "superseded" and intent.run_id is None
    assert scene.tutor.turn_history(session.token, scene.conversation.id) == before


def test_unknown_automatic_call_and_late_receipt_never_authorize_another_send(
    database, session, continuation_scene,
):
    scene = continuation_scene
    enable(scene, session)
    respond(scene, session)
    intent, accepted = automatic(scene, session, database)
    sent = []

    def timeout(request):
        sent.append(request)
        raise httpx.ReadTimeout("Owned offline automatic result is unknown.")

    loop = AgentLoop(
        scene.tutor, ChatCompletionsGateway(scene.settings, httpx.MockTransport(timeout)),
    )
    loop.run(accepted.run_id)
    loop.run(accepted.run_id)
    assert len(sent) == 1
    assert scene.tutor.get(session.token, accepted.run_id).status == "blocked_unknown"
    recorded = calls(database, accepted.run_id)
    assert len(recorded) == 1 and recorded[0]["status"] == "unknown"
    scene.intents.reconcile_once()
    assert current_intent(scene, session).run_id == accepted.run_id
    state = scene.controls.get(session.token, scene.conversation.id)
    explicit = scene.tutor.submit(
        session.token, scene.conversation.id, str(uuid4()),
        TurnInput(
            text="Stop the follow-up; answer my explicit question.",
            focus=scene.candidate.focus, teaching_session_revision=state.revision,
        ),
    )
    assert scene.tutor.get(session.token, accepted.run_id).status == "cancelled"
    scene.tutor.record(
        recorded[0]["id"],
        Receipt(body=json.dumps(body("Late automatic text must not publish.")), http_status=200),
    )
    loop.run(accepted.run_id)
    final_call = calls(database, accepted.run_id)[0]
    assert final_call["status"] == "result_recorded" and not final_call["applied"]
    assert len(sent) == 1 and current_intent(scene, session).id == intent.id
    assert next(
        t for t in scene.tutor.turn_history(session.token, scene.conversation.id)
        if t.id == accepted.turn_id
    ).assistant_text is None
    assert scene.tutor.get(session.token, explicit.run_id).status == "queued"
