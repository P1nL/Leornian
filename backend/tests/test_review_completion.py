from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_python_execution import program
from test_python_execution import python_setup as python_setup
from test_python_practice import complete
from test_python_practice import practice_setup as practice_setup
from test_submitted_code_reviews import review_exposures, review_provider
from test_submitted_code_reviews import submitted as submitted
from test_teaching_delivery import drain
from test_tutor_runtime import calls

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.teaching_continuations import TeachingContinuationWorkflow
from leornian.bootstrap.teaching_sessions import TeachingSessionWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.python_contracts import PythonPracticeSubmission
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.evaluation_contracts import EvaluationDocument
from leornian.modules.tutor.evaluations import Evaluations
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.modules.tutor.review_contracts import CompleteReviewAction
from leornian.modules.tutor.teaching_session_contracts import (
    OpenTeachingSession,
    SetContinuationPolicy,
)
from leornian.shared_kernel.errors import BusinessError


def deliver_review(database, session, submitted, *, version=2):
    tutor = submitted["tutor"]
    flow = LearningArtifactWorkflow(database)
    key = str(uuid4())
    data = TurnInput(
        text="Review the whole original submitted program and let me confirm I read the review.",
        focus=submitted["focus"],
        presentation_capabilities={
            "versions": ["learning_composition.v2"],
            "actions": [f"learning_code_review.v{version}"],
        },
    )
    accepted = tutor.submit(session.token, submitted["conversation"].id, key, data)
    original, wires, prepared = review_provider(submitted["settings"])

    def handle(request):
        response = original.transport.handle_request(request)
        payload = response.json()
        for tool in payload["choices"][0]["message"].get("tool_calls", []):
            if tool["function"]["name"] == "prepare_learning_code_review_composition":
                tool["function"]["name"] = "prepare_learning_code_review_composition_v2"
        return httpx.Response(200, json=payload)

    gateway = (
        ChatCompletionsGateway(submitted["settings"], httpx.MockTransport(handle))
        if version == 2 else original
    )
    task = drain(tutor, submitted["settings"], accepted, gateway, session.token)
    assert task.status == "accepted" and len(wires) == 3
    assert len(prepared) == 1 and prepared[0]["status"] == "completed"
    view = flow.get_v2(
        session.token, submitted["conversation"].id,
        flow.list_v2(session.token, submitted["conversation"].id)[0].id,
        code_review_capability=f"learning_code_review.v{version}",
    )
    assert view.review_bindings[0].profile_version == f"submitted-code-review.v{version}"
    return SimpleNamespace(
        flow=flow, view=view, tutor=tutor, accepted=accepted, data=data, key=key,
        wires=wires, prepared=prepared,
    )


@pytest.fixture
def review_scene(database, session, submitted):
    with database.transaction() as connection:
        evaluations = Evaluations(connection)
        evaluations.record(
            evaluations.row(session.actor, submitted["source"]["id"]),
            EvaluationDocument(
                recorded_correct=False,
                explanation="Original immutable evaluation.",
                reflection="Why was the input ignored?",
            ),
        )
    return deliver_review(database, session, submitted)


def read_review(session, scene):
    return scene.flow.get_v2(
        session.token, scene.view.conversation_id, scene.view.id,
        code_review_capability="learning_code_review.v2",
    )


def command(scene, *, revision=None, action_id=None, component_id=None):
    return CompleteReviewAction(
        action="complete_review",
        component_id=component_id or scene.view.review_bindings[0].component_id,
        client_action_id=action_id or uuid4(),
        expected_artifact_revision=scene.view.revision if revision is None else revision,
    )


def apply(session, scene, data):
    return scene.flow.action(
        session.token, scene.view.conversation_id, scene.view.id, data,
    )


def count_completions(database, artifact_id):
    with database.transaction() as connection:
        return connection.execute(
            "SELECT count(*) AS n FROM tutor.review_completions WHERE artifact_id=%s",
            (artifact_id,),
        ).fetchone()["n"]


def artifact_events(workflow, session, artifact_id):
    return [
        event for event in workflow.snapshot(session.token).events
        if event.event_type == "tutor.learning_artifact_updated"
        and event.payload.learning_artifact_id == artifact_id
    ]


def test_explicit_review_confirmation_commits_receipt_event_and_exact_original_identity(
    database, workflow, session, submitted, review_scene,
):
    scene = review_scene
    initial = scene.view
    report = initial.review_reports[0]
    assert report.component_id == initial.review_bindings[0].component_id == "submitted"
    assert report.state == "ready" and report.allowed_actions == ["complete_review"]
    assert report.completion is None and initial.revision == 1
    controls = TeachingSessionWorkflow(database)
    opened = controls.command(session.token, initial.conversation_id, OpenTeachingSession(
        action="open", client_action_id=uuid4(), expected_session_revision=0,
        focus=submitted["focus"],
    ))
    controls.command(session.token, initial.conversation_id, SetContinuationPolicy(
        action="set_continuation_policy", policy="after_result.v1",
        client_action_id=uuid4(), expected_session_revision=opened.revision,
    ))
    before = workflow.snapshot(session.token)
    events_before = artifact_events(workflow, session, initial.id)
    exposures = review_exposures(database, session)
    with database.transaction() as connection:
        evaluation = Evaluations(connection).row(session.actor, submitted["source"]["id"])
    data = command(scene)
    client = TestClient(create_app(submitted["settings"]))
    path = f"/v2/conversations/{initial.conversation_id}/learning-artifacts/{initial.id}"
    headers = {"Authorization": "Bearer " + session.token}
    response = client.post(path + "/actions", headers=headers, json=data.model_dump(mode="json"))
    assert response.status_code == 200, response.json()
    receipt = scene.flow.action_receipt(
        session.token, initial.conversation_id, initial.id, data.client_action_id,
    )
    assert response.json() == receipt.model_dump(mode="json")
    assert receipt.schema_version == "learning_review_action.v1"
    assert receipt.result_owner == "tutor" and receipt.component_id == "submitted"
    assert receipt.state == "completed"
    assert receipt.artifact_revision == initial.revision + 1
    current = read_review(session, scene)
    assert current.state == "completed"
    report = current.review_reports[0]
    assert report.state == "completed" and not report.allowed_actions
    completion = report.completion
    assert completion.id == receipt.result_id
    assert completion.artifact_id == initial.id and completion.component_id == "submitted"
    assert completion.presentation_id == initial.content_ref.id
    assert completion.content_identity == initial.content_ref.public_identity
    assert completion.attempt_id == submitted["attempt"].id
    assert completion.evaluation_id == submitted["source"]["id"]
    assert completion.completed_at and completion.evidence_kind == "learner_review_report.v1"
    assert current.content_ref == initial.content_ref
    assert current.review_bindings == initial.review_bindings
    assert apply(session, scene, data) == receipt
    assert client.get(path + f"/actions/{data.client_action_id}", headers=headers).json() == (
        receipt.model_dump(mode="json")
    )
    assert client.get(path, headers=headers).status_code == 409
    assert client.get(
        path + "?code_review_capability=learning_code_review.v1", headers=headers,
    ).status_code == 409
    assert client.get(
        path + "?code_review_capability=learning_code_review.v2", headers=headers,
    ).json()["review_reports"][0]["completion"] == completion.model_dump(mode="json")
    assert len(artifact_events(workflow, session, initial.id)) == len(events_before) + 1
    assert count_completions(database, initial.id) == 1
    assert review_exposures(database, session) == exposures
    assert submitted["python"].practice_attempt(session.token, submitted["attempt"].id) == (
        submitted["attempt"]
    )
    with database.transaction() as connection:
        assert Evaluations(connection).row(session.actor, submitted["source"]["id"]) == evaluation
    after = workflow.snapshot(session.token)
    for field in (
        "attempts", "python_attempts", "program_attempts", "choice_results",
        "node_progress", "execution_progress",
    ):
        assert getattr(after, field) == getattr(before, field)
    assert not TeachingContinuationWorkflow(database, submitted["settings"]).list(
        session.token, initial.conversation_id,
    )
    assert len(calls(database, scene.accepted.run_id)) == 3


def test_review_confirmation_replay_does_not_authorize_changed_input_or_duplicate_confirmation(
    database, session, review_scene,
):
    scene = review_scene
    data = command(scene)
    receipt = apply(session, scene, data)
    with pytest.raises(BusinessError) as changed:
        apply(session, scene, data.model_copy(update={"component_id": "review"}))
    assert changed.value.code == "idempotency_conflict"
    with pytest.raises(BusinessError) as stale:
        apply(session, scene, command(scene))
    assert stale.value.code == "stale_version"
    current = read_review(session, scene)
    with pytest.raises(BusinessError):
        apply(session, scene, command(scene, revision=current.revision))
    assert apply(session, scene, data) == receipt
    assert count_completions(database, scene.view.id) == 1


@pytest.mark.parametrize("same_command", [True, False], ids=["same-command", "competing-commands"])
def test_concurrent_review_confirmations_commit_one_fact_and_one_action(
    database, workflow, session, review_scene, same_command,
):
    scene = review_scene
    first = command(scene)
    commands = [first, first if same_command else command(scene)]
    barrier = Barrier(2)
    before = len(artifact_events(workflow, session, scene.view.id))

    def submit(data):
        barrier.wait(timeout=10)
        try:
            return apply(session, scene, data)
        except BusinessError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, commands))
    errors = [result for result in results if isinstance(result, BusinessError)]
    receipts = [result for result in results if not isinstance(result, BusinessError)]
    if same_command:
        assert not errors and receipts[0] == receipts[1]
    else:
        assert len(receipts) == len(errors) == 1 and errors[0].code == "stale_version"
    assert read_review(session, scene).review_reports[0].completion.id == receipts[0].result_id
    assert count_completions(database, scene.view.id) == 1
    assert len(artifact_events(workflow, session, scene.view.id)) == before + 1
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.learning_artifact_actions WHERE artifact_id=%s",
            (scene.view.id,),
        ).fetchone()["n"] == 1


@pytest.mark.parametrize(
    "completed", [False, True], ids=["before-confirmation", "after-confirmation"],
)
def test_cancelled_review_refuses_new_confirmation_and_retains_completed_fact(
    database, session, review_scene, completed,
):
    scene = review_scene
    data = command(scene)
    receipt = apply(session, scene, data) if completed else None
    before = read_review(session, scene)
    cancel = CancelAction(
        action="cancel", client_action_id=uuid4(), expected_artifact_revision=before.revision,
    )
    if completed:
        with pytest.raises(BusinessError, match="自由练习"):
            apply(session, scene, cancel)
    else:
        assert apply(session, scene, cancel).state == "cancelled"
    current = read_review(session, scene)
    assert current.state == ("completed" if completed else "cancelled")
    assert current.review_reports[0].completion == before.review_reports[0].completion
    assert not current.review_reports[0].allowed_actions
    with pytest.raises(BusinessError):
        apply(session, scene, command(scene, revision=current.revision))
    if receipt:
        assert apply(session, scene, data) == receipt
    assert count_completions(database, scene.view.id) == int(completed)


def test_original_source_revocation_blocks_confirmation_without_changing_original_feedback(
    database, session, submitted, review_scene,
):
    scene = review_scene
    source = submitted["source"]["context_data"]["question"]["source_refs"][0]
    KnowledgeWorkflow(database).revoke(
        session.token, UUID(source["source_id"]), source["revision"],
    )
    data = command(scene)
    with pytest.raises(BusinessError):
        apply(session, scene, data)
    with pytest.raises(BusinessError):
        read_review(session, scene)
    with pytest.raises(BusinessError) as missing:
        scene.flow.action_receipt(
            session.token, scene.view.conversation_id, scene.view.id, data.client_action_id,
        )
    assert missing.value.code == "not_found"
    assert count_completions(database, scene.view.id) == 0
    assert submitted["python"].practice_attempt(session.token, submitted["attempt"].id) == (
        submitted["attempt"]
    )


def test_review_confirmation_rejects_other_actor_conversation_and_unbound_component(
    database, workflow, session, submitted, review_scene,
):
    scene = review_scene
    other = workflow.create_session("Another review reader")
    goal_job = workflow.submit(
        session.token, str(uuid4()),
        GoalInput(title="Separate review conversation", motivation="Keep confirmations scoped."),
    )
    with database.transaction() as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (goal_job.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    goal = next(
        goal for goal in workflow.snapshot(session.token).goals
        if goal.title == "Separate review conversation"
    )
    conversation = submitted["tutor"].conversation(session.token, goal.id)
    for token, conversation_id in (
        (other.token, scene.view.conversation_id), (session.token, conversation.id),
    ):
        with pytest.raises(BusinessError) as denied:
            scene.flow.action(token, conversation_id, scene.view.id, command(scene))
        assert denied.value.code == "not_found"
    with pytest.raises(BusinessError):
        apply(session, scene, command(scene, component_id="review"))
    assert count_completions(database, scene.view.id) == 0
    assert read_review(session, scene).revision == scene.view.revision
    receipt = apply(session, scene, command(scene))
    for token, conversation_id in (
        (other.token, scene.view.conversation_id), (session.token, conversation.id),
    ):
        with pytest.raises(BusinessError) as denied:
            scene.flow.action_receipt(
                token, conversation_id, scene.view.id, receipt.client_action_id,
            )
        assert denied.value.code == "not_found"


def test_new_attempt_does_not_rebase_completed_review(
    database, session, submitted, review_scene,
):
    scene = review_scene
    receipt = apply(session, scene, command(scene))
    original = read_review(session, scene)
    second = submitted["python"].submit_practice(
        session.token, submitted["pack"].pack_id, str(uuid4()),
        PythonPracticeSubmission(
            slot="practice_1", code=program("practice_1"),
            previous_attempt_id=submitted["attempt"].id,
        ),
    )
    complete(database, session, second, submitted["real"])
    current = read_review(session, scene)
    assert current.content_ref == original.content_ref
    assert current.review_bindings == original.review_bindings
    assert current.review_reports == original.review_reports
    assert current.review_reports[0].completion.id == receipt.result_id
    assert current.review_reports[0].completion.attempt_id != second.id
    assert count_completions(database, scene.view.id) == 1


def test_failed_commit_rolls_back_confirmation_revision_receipt_and_event(
    database, workflow, session, review_scene, monkeypatch,
):
    scene = review_scene
    data = command(scene)
    before = artifact_events(workflow, session, scene.view.id)

    def fail(*args):
        raise BusinessError("precondition_failed", "Injected review commit-path failure.")

    with monkeypatch.context() as patch:
        patch.setattr(LearningArtifactWorkflow, "event", staticmethod(fail))
        with pytest.raises(BusinessError, match="Injected review"):
            apply(session, scene, data)
    assert read_review(session, scene) == scene.view
    assert count_completions(database, scene.view.id) == 0
    assert artifact_events(workflow, session, scene.view.id) == before
    with pytest.raises(BusinessError) as missing:
        scene.flow.action_receipt(
            session.token, scene.view.conversation_id, scene.view.id, data.client_action_id,
        )
    assert missing.value.code == "not_found"
    receipt = apply(session, scene, data)
    assert read_review(session, scene).review_reports[0].completion.id == receipt.result_id
    assert count_completions(database, scene.view.id) == 1


def test_v1_reader_and_frozen_run_do_not_gain_confirmation_and_v2_replay_cannot_change_support(
    database, session, submitted,
):
    legacy = deliver_review(database, session, submitted, version=1)
    assert not legacy.view.review_reports
    assert "review_reports" not in legacy.view.model_dump(mode="json")
    with database.transaction() as connection:
        tools = Runs(connection).lock(legacy.accepted.run_id)["tool_contracts"]
        assert tools["prepare_learning_code_review_composition"] == 1
        assert "prepare_learning_code_review_composition_v2" not in tools
    upgraded_reader = read_review(session, legacy)
    assert upgraded_reader.review_bindings == legacy.view.review_bindings
    assert not upgraded_reader.review_reports
    assert "review_reports" not in upgraded_reader.model_dump(mode="json")
    with pytest.raises(BusinessError):
        apply(session, legacy, command(legacy))
    upgraded_data = legacy.data.model_copy(update={
        "presentation_capabilities": legacy.data.presentation_capabilities.model_copy(update={
            "actions": ["learning_code_review.v2"],
        }),
    })
    with pytest.raises(BusinessError):
        legacy.tutor.submit(
            session.token, legacy.view.conversation_id, legacy.key, upgraded_data,
        )
    assert legacy.tutor.submit(
        session.token, legacy.view.conversation_id, legacy.key, legacy.data,
    ) == legacy.accepted
    current = deliver_review(database, session, submitted)
    with database.transaction() as connection:
        tools = Runs(connection).lock(current.accepted.run_id)["tool_contracts"]
        assert tools["prepare_learning_code_review_composition_v2"] == 1
        assert "prepare_learning_code_review_composition" not in tools
    assert current.tutor.submit(
        session.token, current.view.conversation_id, current.key, current.data,
    ) == current.accepted
    downgraded_data = current.data.model_copy(update={
        "presentation_capabilities": current.data.presentation_capabilities.model_copy(update={
            "actions": ["learning_code_review.v1"],
        }),
    })
    with pytest.raises(BusinessError):
        current.tutor.submit(
            session.token, current.view.conversation_id, current.key, downgraded_data,
        )
    assert count_completions(database, legacy.view.id) == 0
    assert count_completions(database, current.view.id) == 0
    assert len(calls(database, legacy.accepted.run_id)) == 3
    assert len(calls(database, current.accepted.run_id)) == 3
    with pytest.raises(ValueError):
        TurnInput(
            text="Conflicting review capabilities.",
            presentation_capabilities={
                "versions": ["learning_composition.v2"],
                "actions": ["learning_code_review.v1", "learning_code_review.v2"],
            },
        )
