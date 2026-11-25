import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_python_execution import owned_claim, program, publish_python, receipt
from test_python_execution import python_setup as python_setup
from test_runner import runner as runner
from test_teaching_delivery import drain, provider

from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.python_contracts import PythonTraining
from leornian.modules.item_bank.supply_contracts import ChoiceInput
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.learning_artifact_contracts import (
    LearningCandidateInput,
    RespondAction,
    RunAction,
)
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def learning_setup(database, session, gate_setup):
    _, pack, (supply, old_tutor, settings, plan, source) = gate_setup
    settings = replace(
        settings,
        delivery_enabled=True,
        model_context_tokens=128000,
        model_max_output_tokens=32768,
        heartbeat_seconds=0.02,
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, plan.goal_id)
    return {
        "tutor": tutor,
        "settings": settings,
        "conversation": conversation,
        "flow": LearningArtifactWorkflow(database),
        "pack": pack,
        "source": source,
        "supply": supply,
    }


def selected(session, setup):
    return setup["flow"].candidate(
        session.token,
        setup["conversation"].id,
        LearningCandidateInput(pack_id=setup["pack"].pack_id, slot="practice_1"),
    )


def introduce(session, setup, candidate=None):
    candidate = candidate or selected(session, setup)
    accepted = setup["tutor"].submit(
        session.token,
        setup["conversation"].id,
        str(uuid4()),
        TurnInput(
            text="Introduce this practice without answering it.",
            focus=candidate.focus,
            learning_candidate_id=candidate.id,
        ),
    )
    gateway, _sent, _reviews = provider(setup["settings"], author="Try the displayed practice.")
    task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
    assert task.status == "accepted", task
    artifacts = setup["flow"].list(session.token, setup["conversation"].id)
    assert len(artifacts) == 1
    return setup["flow"].get(session.token, setup["conversation"].id, artifacts[0].id), accepted


def test_accepted_reply_and_real_candidate_publish_together_with_safe_timeline(
    database, session, workflow, learning_setup
):
    candidate = selected(session, learning_setup)
    assert "correct_key" not in candidate.model_dump_json()
    view, accepted = introduce(session, learning_setup, candidate)
    assert view.source_turn_id == accepted.turn_id
    assert view.kind == view.presentation.type == "knowledge_check"
    assert view.allowed_actions == ["respond"]
    assert view.content_ref.public_identity == candidate.content_ref.public_identity
    assert (
        "correct_key" not in view.model_dump_json() and "explanation" not in view.model_dump_json()
    )
    snapshot = workflow.snapshot(session.token)
    assert snapshot.learning_artifacts[0].timeline_item_id == view.timeline_item_id
    assert any(e.payload.learning_artifact_id == view.id for e in snapshot.events)
    assert any(
        t.id == accepted.turn_id and t.assistant_text == "Try the displayed practice."
        for page in snapshot.turns
        for t in page.turns
    )
    assert len(snapshot.choice_results) == len(snapshot.attempts) == 0
    with database.transaction(snapshot=True) as connection:
        calls = connection.execute(
            "SELECT count(*) AS count FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["count"]
    learning_setup["flow"].get(session.token, view.conversation_id, view.id)
    with database.transaction(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM runtime.external_calls WHERE actor_id=%s",
                (session.actor.id,),
            ).fetchone()["count"]
            == calls
        )


def test_learning_action_cas_idempotency_and_old_entry_share_one_result(
    database, session, workflow, learning_setup
):
    view, _ = introduce(session, learning_setup)
    flow = learning_setup["flow"]
    data = RespondAction(
        client_action_id=uuid4(),
        expected_artifact_revision=view.revision,
        action="respond",
        payload={"selected_key": "A"},
    )
    with pytest.raises(BusinessError) as conflict:
        flow.action(
            session.token,
            view.conversation_id,
            view.id,
            data.model_copy(update={"expected_artifact_revision": 99}),
        )
    assert conflict.value.code == "stale_version"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: flow.action(session.token, view.conversation_id, view.id, data), range(2)
            )
        )
    assert results[0] == results[1] and results[0].state == "completed"
    old = learning_setup["supply"].answer(
        session.token,
        learning_setup["pack"].pack_id,
        str(data.client_action_id),
        ChoiceInput(slot="practice_1", selected_key="A"),
    )
    assert old.id == results[0].result_id
    final = flow.get(session.token, view.conversation_id, view.id)
    assert final.result.correct and final.allowed_actions == []
    with pytest.raises(BusinessError) as conflict:
        flow.action(
            session.token,
            view.conversation_id,
            view.id,
            data.model_copy(
                update={"payload": data.payload.model_copy(update={"selected_key": "B"})}
            ),
        )
    assert conflict.value.code == "idempotency_conflict"
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.choice_results) == 1
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert final.commentary_status == "pending_or_available"


def test_candidate_and_actions_do_not_open_assessment_or_foreign_scope(
    session, workflow, learning_setup
):
    flow = learning_setup["flow"]
    candidate = selected(session, learning_setup)
    other = workflow.create_session("Foreign learner")
    with pytest.raises(BusinessError):
        flow.candidate(
            other.token,
            candidate.conversation_id,
            LearningCandidateInput(pack_id=candidate.content_ref.id, slot="practice_1"),
        )
    with pytest.raises(ValidationError):
        LearningCandidateInput(pack_id=candidate.content_ref.id, slot="assessment_1")
    view, _ = introduce(session, learning_setup, candidate)
    with pytest.raises(BusinessError):
        flow.get(other.token, candidate.conversation_id, view.id)
    with pytest.raises(BusinessError):
        flow.action(
            session.token,
            candidate.conversation_id,
            view.id,
            RunAction(
                client_action_id=uuid4(),
                expected_artifact_revision=1,
                action="run",
                payload={"code": "print(1)"},
            ),
        )


def test_publication_failure_does_not_leave_reply_artifact_event_or_cas_half_committed(
    database, session, learning_setup, monkeypatch
):
    candidate = selected(session, learning_setup)
    tutor, conversation = learning_setup["tutor"], learning_setup["conversation"]
    accepted = tutor.submit(
        session.token,
        conversation.id,
        str(uuid4()),
        TurnInput(
            text="Introduce this.", focus=candidate.focus, learning_candidate_id=candidate.id
        ),
    )
    original = LearningArtifacts.publish

    def fail_after_insert(self, *args):
        original(self, *args)
        raise BusinessError("stale_version", "Forced publication transaction conflict")

    monkeypatch.setattr(LearningArtifacts, "publish", fail_after_insert)
    gateway, _, _ = provider(learning_setup["settings"], author="Uncommitted introduction.")
    for _ in range(6):
        AgentLoop(tutor, gateway).run(accepted.run_id)
        if tutor.get(session.token, accepted.run_id).status != "queued":
            break
    assert tutor.get(session.token, accepted.run_id).status == "failed"
    assert learning_setup["flow"].list(session.token, conversation.id) == []
    with database.transaction(snapshot=True) as connection:
        row = connection.execute(
            "SELECT t.assistant_text,c.teaching_revision FROM tutor.turns t "
            "JOIN tutor.conversations c ON c.id=t.conversation_id WHERE t.id=%s",
            (accepted.turn_id,),
        ).fetchone()
    assert row == {"assistant_text": None, "teaching_revision": 0}


def test_source_revocation_blocks_new_actions(session, learning_setup):
    view, _ = introduce(session, learning_setup)
    KnowledgeWorkflow(learning_setup["tutor"].database).revoke(
        session.token, learning_setup["source"].id, 1
    )
    current = learning_setup["flow"].get(session.token, view.conversation_id, view.id)
    assert "respond" not in current.allowed_actions
    with pytest.raises(BusinessError):
        learning_setup["flow"].action(
            session.token,
            view.conversation_id,
            view.id,
            RespondAction(
                client_action_id=uuid4(),
                expected_artifact_revision=1,
                action="respond",
                payload={"selected_key": "A"},
            ),
        )


def test_code_artifact_run_uses_original_execution_and_result_without_tutor_grading(
    database, session, python_setup, request
):
    real_runner = (
        request.getfixturevalue("runner") if os.environ.get("LEORNIAN_TEST_DOCKER") == "1" else None
    )
    python, pack, gate = python_setup
    publish_python(database, session, python_setup, runner=real_runner)
    supply, _, settings, plan, _ = gate[2]
    settings = replace(
        settings,
        delivery_enabled=True,
        model_context_tokens=128000,
        model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    setup = {
        "flow": LearningArtifactWorkflow(database),
        "tutor": tutor,
        "settings": settings,
        "conversation": tutor.conversation(session.token, plan.goal_id),
        "pack": pack,
    }
    view, _ = introduce(session, setup)
    assert view.kind == "code_workspace" and view.allowed_actions == ["run"]
    assert "tests" not in view.model_dump_json()
    action = RunAction(
        client_action_id=uuid4(),
        expected_artifact_revision=1,
        action="run",
        payload={"code": program("practice_1")},
    )
    accepted = setup["flow"].action(session.token, view.conversation_id, view.id, action)
    assert accepted.state == "running"
    assert setup["flow"].action(session.token, view.conversation_id, view.id, action) == accepted
    old = python.submit_training(
        session.token,
        pack.pack_id,
        str(action.client_action_id),
        PythonTraining(slot="practice_1", code=program("practice_1")),
    )
    assert old.id == accepted.result_id
    claim = owned_claim(database, session, accepted.result_id)
    assert claim is not None and "expected" not in claim.model_dump_json()
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, real_runner))
    final = setup["flow"].get(session.token, view.conversation_id, view.id)
    assert final.state == "completed" and final.result.status == "passed"
    assert final.result.passed_cases == 3 and final.allowed_actions == []


def test_learning_artifact_http_is_scoped_and_rejects_untyped_action_payload(
    session, learning_setup
):
    view, _ = introduce(session, learning_setup)
    client = TestClient(create_app(learning_setup["settings"]))
    headers = {"Authorization": "Bearer " + session.token}
    path = f"/v1/conversations/{view.conversation_id}/learning-artifacts/{view.id}"
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["schema_version"] == "learning_artifact.v1"
    action = {
        "client_action_id": str(uuid4()),
        "expected_artifact_revision": 1,
        "action": "respond",
        "payload": {"selected_key": "A", "correct": True},
    }
    rejected = client.post(path + "/actions", headers=headers, json=action)
    assert rejected.status_code == 422
    del action["payload"]["correct"]
    accepted = client.post(path + "/actions", headers=headers, json=action)
    assert accepted.status_code == 200 and accepted.json()["state"] == "completed"
