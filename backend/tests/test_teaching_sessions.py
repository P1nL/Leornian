import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_composition_delivery import composition_provider
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import introduce, selected
from test_learning_artifacts import learning_setup as learning_setup
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_material_sources_and_goals import advance_consumer_materials
from test_teaching_delivery import body, drain, provider
from test_tutor_runtime import calls

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.agent_runtime.tools import REGISTRY
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.modules.tutor.teaching_session_contracts import (
    OpenTeachingSession,
    PauseTeaching,
    ResumeTeaching,
    ReturnToMain,
    SetTeachingMode,
    SetTeachingTopic,
)
from leornian.modules.tutor.teaching_sessions import TeachingSessions
from leornian.shared_kernel.errors import BusinessError

CAPABILITIES = {
    "versions": ["learning_composition.v2"],
    "actions": [
        "learning_practice.v2", "learning_responses.v1", "learning_code_review.v1",
        "learning_programs.v1", "learning_direct_answers.v1", "learning_hints.v1",
        "learning_demo_events.v1",
    ],
}


@pytest.fixture
def teaching_scene(database, session, consumer):
    tutor, settings, conversation, materials, _, version, binding, *_ = consumer
    materials.bind(session.token, str(uuid4()), MaterialBindingInput(
        goal_id=conversation.goal_id, purpose="teaching", expected_binding_revision=0,
        refs=binding.refs,
    ))
    legacy_key = str(uuid4())
    legacy_data = TurnInput(
        text="Show breadth-first traversal of the supplied directed graph.",
        presentation_capabilities={"versions": ["learning_composition.v2"]},
    )
    legacy = tutor.submit(session.token, conversation.id, legacy_key, legacy_data)
    advance_consumer_materials(database, session, settings, conversation.goal_id)
    gateway, sent, prepared = composition_provider(settings)
    assert drain(tutor, settings, legacy, gateway, session.token).status == "accepted"
    assert len(sent) == 3
    flow = LearningArtifactWorkflow(database)
    artifact = flow.get_v2(
        session.token, conversation.id, flow.list_v2(session.token, conversation.id)[0].id,
    )
    controls = TeachingSessionWorkflow(database)
    opened = controls.command(session.token, conversation.id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
    ))
    return SimpleNamespace(
        tutor=tutor, settings=settings, conversation=conversation, materials=materials,
        version=version, flow=flow, artifact=artifact, controls=controls, opened=opened,
        legacy=legacy, legacy_key=legacy_key, legacy_data=legacy_data, prepared=prepared,
    )


def question(scene, session, text="Why is this vertex discovered only once?"):
    state = scene.controls.get(session.token, scene.conversation.id)
    data = TurnInput(
        text=text, teaching_session_revision=state.revision,
        presentation_capabilities=CAPABILITIES,
    )
    key = str(uuid4())
    accepted = scene.tutor.submit(session.token, scene.conversation.id, key, data)
    advance_consumer_materials(
        scene.tutor.database, session, scene.settings, scene.conversation.goal_id,
    )
    return accepted, data, key


def finish_question(scene, session, accepted, text="The visited set prevents rediscovery."):
    gateway, sent, _ = provider(scene.settings, author=text)
    result = drain(
        scene.tutor, scene.settings, accepted, gateway, session.token,
    )
    assert result.status == "accepted" and len(sent) == 2
    return sent


def assert_no_assessment(workflow, session):
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.choice_results and not snapshot.attempts
    assert not snapshot.python_attempts and not snapshot.program_attempts
    assert not snapshot.node_progress and not snapshot.execution_progress


def test_checked_practice_question_records_original_exposure_only_when_published(
    database, workflow, session, learning_setup,
):
    candidate = selected(session, learning_setup)
    view, _ = introduce(session, learning_setup, candidate)
    tutor, settings = learning_setup["tutor"], learning_setup["settings"]
    controls = TeachingSessionWorkflow(database)
    state = controls.command(session.token, view.conversation_id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
        focus=candidate.focus,
    ))
    data = TurnInput(
        text="Explain the concept in this displayed practice without choosing an answer.",
        focus=candidate.focus, teaching_session_revision=state.revision,
    )
    key = str(uuid4())
    accepted = tutor.submit(session.token, view.conversation_id, key, data)
    gateway, sent, _ = provider(settings, author="Inspect the condition before entering the loop.")
    AgentLoop(tutor, gateway).run(accepted.run_id)
    with database.transaction() as connection:
        before, facts = Exposures(connection).snapshot(session.actor)
        assert not any("artifact-question:" in fact["key"] for fact in facts)
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    with database.transaction() as connection:
        after, facts = Exposures(connection).snapshot(session.actor)
        question = [fact for fact in facts if "artifact-question:" in fact["key"]]
        assert after == before + 1 and len(question) == 1
        assert question[0]["feedback"]["kind"] == "artifact_question.v1"
        assert question[0]["feedback"]["turn_id"] == str(accepted.turn_id)
        assert question[0]["feedback"]["text"] == "Inspect the condition before entering the loop."
    assert len(sent) == 2
    assert tutor.submit(session.token, view.conversation_id, key, data) == accepted
    with database.transaction() as connection:
        assert Exposures(connection).revision(session.actor) == after
    assert_no_assessment(workflow, session)


def test_existing_lesson_request_replays_while_new_lesson_waits_for_mainline(
    database, workflow, session, learning_setup,
):
    from test_generated_lessons import lesson_document

    from leornian.modules.learning.contracts import LessonRequestInput

    setup = learning_setup
    candidate = selected(session, setup)
    tutor = setup["tutor"]
    key = str(uuid4())
    data = LessonRequestInput(
        expected_plan_revision=candidate.focus.expected_plan_revision,
        node_key=candidate.focus.node_key,
        instruction="Keep the original source citations.",
    )
    original = tutor.submit_lesson(session.token, candidate.focus.plan_id, key, data)
    gateway, _, _ = provider(
        setup["settings"], author=json.dumps(lesson_document(setup["source"])),
    )
    assert drain(tutor, setup["settings"], original, gateway, session.token).status == "accepted"
    view, _ = introduce(session, setup, candidate)
    controls = TeachingSessionWorkflow(database)
    opened = controls.command(session.token, view.conversation_id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
        focus=candidate.focus,
    ))
    question = tutor.submit(session.token, view.conversation_id, str(uuid4()), TurnInput(
        text="Explain this practice first.", focus=candidate.focus,
        teaching_session_revision=opened.revision,
    ))
    assert controls.get(session.token, view.conversation_id).active_branch_id
    before = workflow.snapshot(session.token)
    assert tutor.submit_lesson(session.token, candidate.focus.plan_id, key, data) == original
    with pytest.raises(BusinessError, match="Return to the teaching mainline"):
        tutor.submit_lesson(session.token, candidate.focus.plan_id, str(uuid4()), data)
    after = workflow.snapshot(session.token)
    assert after.lessons == before.lessons
    assert {run.id for run in after.runs} == {run.id for run in before.runs}
    tutor.cancel(session.token, question.run_id)


def test_session_open_is_explicit_read_only_recoverable_and_actor_scoped(
    database, workflow, session, consumer,
):
    _, settings, conversation, *_ = consumer
    client = TestClient(create_app(settings))
    headers = {"Authorization": f"Bearer {session.token}"}
    path = f"/v2/conversations/{conversation.id}/teaching-session"
    assert client.get(path, headers=headers).json() is None
    assert not workflow.snapshot(session.token).teaching_sessions
    command = OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
    )
    response = client.post(path + "/actions", headers=headers, json=command.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    opened = response.json()
    assert opened["revision"] == opened["generation"] == 1
    assert opened["mode"] == "guided" and not opened["paused"]
    assert opened["active_branch_id"] is None
    assert client.get(path, headers=headers).json() == opened
    receipt_path = path + f"/actions/{command.client_action_id}"
    assert client.get(receipt_path, headers=headers).json() == opened
    assert client.post(
        path + "/actions", headers=headers, json=command.model_dump(mode="json"),
    ).json() == opened
    changed = {**command.model_dump(mode="json"), "mode": "free_reading"}
    assert client.post(path + "/actions", headers=headers, json=changed).status_code == 409
    assert client.get(path + f"/actions/{uuid4()}", headers=headers).status_code == 404
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.runs and not snapshot.teaching_branches
    assert len(snapshot.teaching_sessions) == 1
    assert len([
        event for event in snapshot.events
        if event.event_type == "tutor.teaching_session_updated"
    ]) == 1
    other = workflow.create_session("Other session reader")
    other_headers = {"Authorization": f"Bearer {other.token}"}
    assert client.get(path, headers=other_headers).status_code == 404
    assert client.get(receipt_path, headers=other_headers).status_code == 404
    assert client.get(
        f"/v2/conversations/{conversation.id}/teaching-branches", headers=other_headers,
    ).status_code == 404
    assert not workflow.snapshot(other.token).teaching_sessions


def test_pending_artifact_questions_share_one_server_anchor_and_independent_review(
    database, workflow, session, teaching_scene,
):
    scene = teaching_scene
    accepted, _, _ = question(scene, session)
    with database.transaction() as connection:
        frozen = Runs(connection).lock(accepted.run_id)
        assert frozen["tool_contracts"]
        assert all(REGISTRY[name].effect == "read" for name in frozen["tool_contracts"])
        assert "prepare_learning_composition" not in frozen["tool_contracts"]
        assert "request_teaching_artifact" not in frozen["tool_contracts"]
    gateway, sent, _ = provider(scene.settings, author="The visited set prevents rediscovery.")
    AgentLoop(scene.tutor, gateway).run(accepted.run_id)
    snapshot = workflow.snapshot(session.token)
    first = next(t for page in snapshot.turns for t in page.turns if t.id == accepted.turn_id)
    assert first.assistant_text is None and first.teaching_branch_id
    branch_id = first.teaching_branch_id
    assert scene.tutor.delivery_task(session.token, accepted.delivery_task_id).status == "checking"
    assert drain(
        scene.tutor, scene.settings, accepted, gateway, session.token,
    ).status == "accepted"
    assert len(sent) == 2
    context = json.loads(sent[0]["messages"][1]["content"].split(": ", 1)[1])
    anchored = context["teaching_session"]
    assert anchored["branch_id"] == str(branch_id)
    assert anchored["anchor_artifact_id"] == str(scene.artifact.id)
    assert anchored["public_anchor"]["content_ref"] == scene.artifact.content_ref.model_dump(
        mode="json"
    )
    assert "single-level question branch" in sent[0]["messages"][0]["content"]
    assert not any(message["role"] == "tool" for message in sent[0]["messages"])
    assert not any("tool_calls" in message for message in sent[0]["messages"])
    second, _, _ = question(scene, session, "Which queue entry is processed next?")
    second_sent = finish_question(scene, session, second)
    assert any(
        "Why is this vertex discovered only once?" in str(message["content"])
        for message in second_sent[0]["messages"]
    )
    branches = scene.controls.branches(session.token, scene.conversation.id)
    assert len(branches) == 1 and branches[0].id == branch_id
    assert branches[0].turn_count == 2 and branches[0].state == "active"
    current = scene.flow.get_v2(session.token, scene.conversation.id, scene.artifact.id)
    assert current.revision == scene.artifact.revision and current.state == "ready"
    assert len(scene.flow.list_v2(session.token, scene.conversation.id)) == 1
    assert_no_assessment(workflow, session)


@pytest.mark.parametrize("new_topic", [False, True], ids=["pause-keeps-anchor", "new-topic"])
def test_only_explicit_topic_change_retires_the_previous_pending_anchor(
    database, workflow, session, teaching_scene, new_topic,
):
    scene = teaching_scene
    command = (
        SetTeachingTopic(
            action="set_topic", focus=scene.opened.focus, client_action_id=uuid4(),
            expected_session_revision=scene.opened.revision,
        ) if new_topic else PauseTeaching(
            action="pause", client_action_id=uuid4(),
            expected_session_revision=scene.opened.revision,
        )
    )
    changed = scene.controls.command(session.token, scene.conversation.id, command)
    assert changed.generation > scene.opened.generation
    accepted, _, _ = question(scene, session, "Show the next independent presentation.")
    with database.transaction() as connection:
        turn = PgTutorStore(connection).get_turn(scene.conversation.id, accepted.turn_id)
        frozen = Runs(connection).lock(accepted.run_id)
    assert bool(turn.teaching_branch_id) is not new_topic
    assert ("prepare_learning_composition" in frozen["tool_contracts"]) is new_topic
    if new_topic:
        gateway, _, _ = composition_provider(scene.settings)
        assert drain(
            scene.tutor, scene.settings, accepted, gateway, session.token,
        ).status == "accepted"
        assert len(scene.flow.list_v2(session.token, scene.conversation.id)) == 2
    else:
        finish_question(scene, session, accepted)
        assert len(scene.flow.list_v2(session.token, scene.conversation.id)) == 1
    original = scene.flow.get_v2(session.token, scene.conversation.id, scene.artifact.id)
    assert original.state == "ready" and original.revision == scene.artifact.revision
    assert_no_assessment(workflow, session)


def test_return_to_main_keeps_exact_history_and_replay_without_creating_nested_branches(
    database, workflow, session, teaching_scene,
):
    scene = teaching_scene
    accepted, data, key = question(scene, session)
    finish_question(scene, session, accepted)
    active = scene.controls.get(session.token, scene.conversation.id)
    with pytest.raises(BusinessError, match="active question branch"):
        scene.controls.command(session.token, scene.conversation.id, ReturnToMain(
            action="return_to_main", client_action_id=uuid4(),
            expected_session_revision=active.revision, branch_id=uuid4(),
        ))
    command = ReturnToMain(
        action="return_to_main", client_action_id=uuid4(),
        expected_session_revision=active.revision, branch_id=active.active_branch_id,
    )
    returned = scene.controls.command(session.token, scene.conversation.id, command)
    assert returned.active_branch_id is None and returned.generation == active.generation + 1
    assert scene.controls.command(session.token, scene.conversation.id, command) == returned
    old_branch = scene.controls.branches(session.token, scene.conversation.id)[0]
    assert old_branch.state == "closed" and old_branch.closed_at and old_branch.turn_count == 1
    assert scene.tutor.submit(session.token, scene.conversation.id, key, data) == accepted
    with pytest.raises(BusinessError, match="Session-bound teaching input changed"):
        scene.tutor.submit(
            session.token, scene.conversation.id, key,
            data.model_copy(update={"teaching_session_revision": returned.revision}),
        )
    with database.transaction() as connection:
        history = PgTutorStore(connection).teaching_history(scene.conversation.id, TeachingFocus())
        old = PgTutorStore(connection).get_turn(scene.conversation.id, accepted.turn_id)
    assert accepted.turn_id not in {turn.id for turn in history}
    assert old.assistant_text == "The visited set prevents rediscovery."
    assert old.teaching_branch_id == old_branch.id
    second, _, _ = question(scene, session, "Why does the same pending main task still apply?")
    finish_question(scene, session, second)
    newest = scene.controls.branches(session.token, scene.conversation.id, limit=1)
    earlier = scene.controls.branches(
        session.token, scene.conversation.id, before=newest[0].id, limit=1,
    )
    assert newest[0].id != old_branch.id and newest[0].state == "active"
    assert newest[0].anchor_artifact_id == old_branch.anchor_artifact_id
    assert [branch.id for branch in earlier] == [old_branch.id]
    assert_no_assessment(workflow, session)


def test_session_cas_and_foreground_controls_reject_implicit_topic_changes(
    workflow, session, consumer,
):
    tutor, _, conversation, *_ = consumer
    controls = TeachingSessionWorkflow(tutor.database)
    opened = controls.command(session.token, conversation.id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
    ))
    with pytest.raises(BusinessError, match="Teaching session changed"):
        tutor.submit(
            session.token, conversation.id, str(uuid4()), TurnInput(text="Missing revision."),
        )
    with pytest.raises(BusinessError, match="Teaching session changed"):
        tutor.submit(session.token, conversation.id, str(uuid4()), TurnInput(
            text="Stale revision.", teaching_session_revision=opened.revision + 1,
        ))
    with pytest.raises(BusinessError, match="explicit control"):
        tutor.submit(session.token, conversation.id, str(uuid4()), TurnInput(
            text="Change topic without a control.", teaching_session_revision=opened.revision,
            focus=TeachingFocus(
                kind="node", plan_id=uuid4(), expected_plan_revision=1, node_key="other",
            ),
        ))
    accepted = tutor.submit(session.token, conversation.id, str(uuid4()), TurnInput(
        text="An explicit question.", teaching_session_revision=opened.revision,
    ))
    with pytest.raises(BusinessError, match="current teaching turn"):
        tutor.submit(session.token, conversation.id, str(uuid4()), TurnInput(
            text="Another foreground turn.", teaching_session_revision=opened.revision,
        ))
    with pytest.raises(BusinessError, match="foreground Turn"):
        controls.command(session.token, conversation.id, PauseTeaching(
            action="pause", client_action_id=uuid4(), expected_session_revision=opened.revision,
        ))
    assert controls.get(session.token, conversation.id) == opened
    assert tutor.cancel(session.token, accepted.run_id).status == "cancelled"
    paused = controls.command(session.token, conversation.id, PauseTeaching(
        action="pause", client_action_id=uuid4(), expected_session_revision=opened.revision,
    ))
    assert paused.paused and not workflow.snapshot(session.token).teaching_branches
    assert_no_assessment(workflow, session)


def test_mode_pause_resume_and_explicit_topic_retire_branch_without_automatic_teaching(
    workflow, session, teaching_scene,
):
    scene = teaching_scene
    accepted, _, _ = question(scene, session)
    finish_question(scene, session, accepted)
    previous_runs = {run.id for run in workflow.snapshot(session.token).runs}
    active = scene.controls.get(session.token, scene.conversation.id)
    free = scene.controls.command(session.token, scene.conversation.id, SetTeachingMode(
        action="set_mode", mode="free_reading", client_action_id=uuid4(),
        expected_session_revision=active.revision,
    ))
    paused = scene.controls.command(session.token, scene.conversation.id, PauseTeaching(
        action="pause", client_action_id=uuid4(), expected_session_revision=free.revision,
    ))
    assert free.mode == "free_reading" and paused.paused
    assert paused.active_branch_id == active.active_branch_id
    assert {run.id for run in workflow.snapshot(session.token).runs} == previous_runs
    explicit, _, _ = question(scene, session, "I explicitly ask while guidance is paused.")
    sent = finish_question(scene, session, explicit)
    after_explicit = {run.id for run in workflow.snapshot(session.token).runs}
    context = json.loads(sent[0]["messages"][1]["content"].split(": ", 1)[1])
    assert context["teaching_session"]["paused"]
    resumed = scene.controls.command(session.token, scene.conversation.id, ResumeTeaching(
        action="resume", client_action_id=uuid4(),
        expected_session_revision=scene.controls.get(
            session.token, scene.conversation.id,
        ).revision,
    ))
    assert not resumed.paused and resumed.mode == "free_reading"
    changed = scene.controls.command(session.token, scene.conversation.id, SetTeachingTopic(
        action="set_topic", focus=TeachingFocus(), client_action_id=uuid4(),
        expected_session_revision=resumed.revision,
    ))
    assert changed.active_branch_id is None
    retired = scene.controls.branches(session.token, scene.conversation.id)[0]
    assert retired.state == "superseded" and retired.turn_count == 2
    assert {run.id for run in workflow.snapshot(session.token).runs} == after_explicit
    assert_no_assessment(workflow, session)


@pytest.mark.parametrize("invalidate", ["cancel_anchor", "revoke_material"])
def test_known_late_question_receipt_cannot_publish_after_anchor_or_material_invalidation(
    database, workflow, session, teaching_scene, invalidate,
):
    scene = teaching_scene
    accepted, _, _ = question(scene, session)
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        if invalidate == "cancel_anchor":
            scene.flow.action(session.token, scene.conversation.id, scene.artifact.id, CancelAction(
                action="cancel", client_action_id=uuid4(),
                expected_artifact_revision=scene.artifact.revision,
            ))
        else:
            scene.materials.revoke(
                session.token, scene.version.document_id, 1,
                DocumentPermissionAction(action="revoke", expected_revision=1),
            )
        return httpx.Response(200, json=body("This late response must remain unpublished."))

    gateway = ChatCompletionsGateway(scene.settings, httpx.MockTransport(handle))
    AgentLoop(scene.tutor, gateway).run(accepted.run_id)
    AgentLoop(scene.tutor, gateway).run(accepted.run_id)
    run = scene.tutor.get(session.token, accepted.run_id)
    assert run.status == "failed" and len(sent) == 1
    assert run.error_code == (
        "stale_version" if invalidate == "cancel_anchor" else "source_not_current"
    )
    records = calls(database, accepted.run_id)
    assert len(records) == 1 and records[0]["status"] == "result_recorded"
    assert not records[0]["applied"]
    turn = next(
        turn for page in workflow.snapshot(session.token).turns for turn in page.turns
        if turn.id == accepted.turn_id
    )
    assert turn.assistant_text is None
    assert len(scene.flow.list_v2(session.token, scene.conversation.id)) == 1
    assert_no_assessment(workflow, session)


def test_question_reply_cannot_select_an_artifact_or_replace_main_anchor(
    database, workflow, session, teaching_scene,
):
    scene = teaching_scene
    accepted, _, _ = question(scene, session)
    gateway, sent, reviews = provider(scene.settings, author=json.dumps({
        "text": "Replace the main task.",
        "interaction": {
            "type": "artifact", "exact_handle": str(scene.prepared[0]["id"]),
            "intent": "introduce_only",
        },
    }))
    AgentLoop(scene.tutor, gateway).run(accepted.run_id)
    assert len(sent) == 1 and not reviews
    with database.transaction() as connection:
        task = connection.execute(
            "SELECT candidate,issues FROM tutor.delivery_tasks WHERE id=%s",
            (accepted.delivery_task_id,),
        ).fetchone()
        turn = PgTutorStore(connection).get_turn(scene.conversation.id, accepted.turn_id)
    assert task["candidate"] is None
    assert task["issues"][0]["code"] == "question_branch_cannot_replace_anchor"
    assert turn.assistant_text is None and turn.learning_interaction is None
    assert len(scene.flow.list_v2(session.token, scene.conversation.id)) == 1
    assert scene.tutor.cancel(session.token, accepted.run_id).status == "cancelled"
    assert_no_assessment(workflow, session)


def test_enabling_session_preserves_legacy_frozen_run_and_original_request_replay(
    database, workflow, session, teaching_scene,
):
    scene = teaching_scene
    with database.transaction() as connection:
        frozen = Runs(connection).lock(scene.legacy.run_id)
        before = dict(frozen["tool_contracts"])
        assert TeachingSessions(connection).binding(scene.legacy.turn_id) is None
    assert scene.tutor.submit(
        session.token, scene.conversation.id, scene.legacy_key, scene.legacy_data,
    ) == scene.legacy
    assert scene.tutor.requested_turn(
        session.token, scene.conversation.id, scene.legacy_key,
    ) == scene.legacy
    with pytest.raises(BusinessError, match="Legacy Turn has no session binding"):
        scene.tutor.submit(
            session.token, scene.conversation.id, scene.legacy_key,
            scene.legacy_data.model_copy(update={
                "teaching_session_revision": scene.opened.revision,
            }),
        )
    with database.transaction() as connection:
        assert Runs(connection).lock(scene.legacy.run_id)["tool_contracts"] == before
    current = scene.flow.get_v2(session.token, scene.conversation.id, scene.artifact.id)
    assert current.content_ref == scene.artifact.content_ref and current.revision == 1
    assert not scene.controls.branches(session.token, scene.conversation.id)
    assert_no_assessment(workflow, session)


@pytest.mark.parametrize("invalidate", [None, "cancel_anchor", "revoke_source"])
def test_v2_question_records_each_original_owner_only_after_independent_acceptance(
    database, workflow, session, learning_setup, invalidate,
):
    from test_composition_practice import current, introduce_owned

    from leornian.bootstrap.knowledge import KnowledgeWorkflow
    from leornian.modules.tutor.learning_artifact_contracts import LearningCandidateInput

    setup = learning_setup
    extra = setup["flow"].candidate(
        session.token, setup["conversation"].id,
        LearningCandidateInput(pack_id=setup["pack"].pack_id, slot="practice_2"),
    )
    task, _, prepared, _, _, introduction = introduce_owned(
        session, setup, extra_source_id=extra.id,
    )
    assert task.status == "accepted" and prepared[0]["status"] == "completed"
    anchor = current(session, setup)
    assert len(anchor.component_bindings) == 2
    controls = TeachingSessionWorkflow(database)
    state = controls.command(session.token, anchor.conversation_id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
        focus=introduction.focus,
    ))
    data = TurnInput(
        text="Explain the loop concept shared by these two displayed questions.",
        focus=introduction.focus, teaching_session_revision=state.revision,
        presentation_capabilities=CAPABILITIES,
    )
    key = str(uuid4())
    accepted = setup["tutor"].submit(session.token, anchor.conversation_id, key, data)
    text = "A loop visits each element; an empty input performs no iterations."
    with database.transaction() as connection:
        before = Exposures(connection).revision(session.actor)

    if invalidate:
        sent = []

        def handle(request):
            sent.append(json.loads(request.content))
            if invalidate == "cancel_anchor":
                setup["flow"].action(session.token, anchor.conversation_id, anchor.id, CancelAction(
                    action="cancel", client_action_id=uuid4(),
                    expected_artifact_revision=anchor.revision,
                ))
            else:
                KnowledgeWorkflow(database).revoke(session.token, setup["source"].id, 1)
            return httpx.Response(200, json=body(text))

        gateway = ChatCompletionsGateway(setup["settings"], httpx.MockTransport(handle))
    else:
        gateway, sent, _ = provider(setup["settings"], author=text)

    AgentLoop(setup["tutor"], gateway).run(accepted.run_id)
    with database.transaction() as connection:
        revision, facts = Exposures(connection).snapshot(session.actor)
        assert revision == before
        assert not any(
            fact.get("feedback", {}).get("kind") == "artifact_question.v1" for fact in facts
        )
        turn = PgTutorStore(connection).get_turn(anchor.conversation_id, accepted.turn_id)
        assert turn.assistant_text is None

    if invalidate:
        AgentLoop(setup["tutor"], gateway).run(accepted.run_id)
        run = setup["tutor"].get(session.token, accepted.run_id)
        assert run.status == "failed" and len(sent) == 1
        assert run.error_code == (
            "stale_version" if invalidate == "cancel_anchor" else "source_not_current"
        )
        receipts = calls(database, accepted.run_id)
        assert len(receipts) == 1 and receipts[0]["status"] == "result_recorded"
        assert not receipts[0]["applied"]
        with database.transaction() as connection:
            assert Exposures(connection).snapshot(session.actor) == (revision, facts)
    else:
        assert drain(
            setup["tutor"], setup["settings"], accepted, gateway, session.token,
        ).status == "accepted"
        assert len(sent) == 2
        with database.transaction() as connection:
            after, facts = Exposures(connection).snapshot(session.actor)
            question_facts = [
                fact for fact in facts
                if fact.get("feedback", {}).get("kind") == "artifact_question.v1"
            ]
        assert after == before + 2 and len(question_facts) == 2
        assert {fact["key"] for fact in question_facts} == {
            f"{setup['pack'].pack_id}:{slot}:artifact-question:{accepted.turn_id}:{component}"
            for slot, component in (
                ("practice_1", "response"), ("practice_2", "second_response"),
            )
        }
        for fact in question_facts:
            assert fact["feedback"] == {
                "kind": "artifact_question.v1", "turn_id": str(accepted.turn_id),
                "artifact_id": str(anchor.id), "text": text,
            }
            assert "correct_key" not in json.dumps(fact)
        assert setup["tutor"].submit(session.token, anchor.conversation_id, key, data) == accepted
        AgentLoop(setup["tutor"], gateway).run(accepted.run_id)
        with database.transaction() as connection:
            assert Exposures(connection).snapshot(session.actor) == (after, facts)
        assert len(sent) == 2
    assert_no_assessment(workflow, session)


def test_hint_anchor_question_never_sends_locked_hints_or_records_them_as_released(
    database, workflow, session, learning_setup,
):
    from test_composition_practice import definition_for
    from test_practice_hints import HINTS, current, introduce_hints

    from leornian.modules.assessment.assistance import PracticeAssistance

    setup = {
        **learning_setup, "pack_id": learning_setup["pack"].pack_id,
        "focus": selected(session, learning_setup).focus,
        "listing": "list_learning_artifact_candidates",
        "define": definition_for, "capability": "learning_practice.v2",
    }
    _, _, _, prepared, _ = introduce_hints(session, setup)
    assert prepared[0]["status"] == "completed"
    assert prepared[0]["hint_bindings"][0]["hints"] == HINTS
    anchor = current(session, setup)
    assert anchor.component_bindings[0].hint_receipts == []
    assert anchor.component_bindings[0].next_hint_level == 1
    controls = TeachingSessionWorkflow(database)
    state = controls.command(session.token, anchor.conversation_id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
        focus=setup["focus"],
    ))
    accepted = setup["tutor"].submit(session.token, anchor.conversation_id, str(uuid4()), TurnInput(
        text="What does this displayed loop question ask me to consider?",
        focus=setup["focus"], teaching_session_revision=state.revision,
        presentation_capabilities=CAPABILITIES,
    ))
    text = "Consider how iteration behaves for empty input."
    gateway, sent, _ = provider(setup["settings"], author=text)
    assert drain(
        setup["tutor"], setup["settings"], accepted, gateway, session.token,
    ).status == "accepted"
    assert len(sent) == 2
    for wire in sent:
        messages = json.dumps(wire["messages"])
        assert all(hint["text"] not in messages for hint in HINTS)
    shown = current(session, setup)
    assert shown.revision == anchor.revision
    assert shown.component_bindings[0].hint_receipts == []
    assert shown.component_bindings[0].next_hint_level == 1
    assert shown.component_bindings[0].assistance_receipt is None
    with database.transaction() as connection:
        assert PracticeAssistance(connection).hints(
            session.actor, setup["pack_id"], "practice_1",
        ) == []
        _, facts = Exposures(connection).snapshot(session.actor)
        feedback = [fact["feedback"] for fact in facts if "feedback" in fact]
        assert feedback == [{
            "kind": "artifact_question.v1", "turn_id": str(accepted.turn_id),
            "artifact_id": str(anchor.id), "text": text,
        }]
        assert all(hint["text"] not in json.dumps(facts) for hint in HINTS)
    assert_no_assessment(workflow, session)
