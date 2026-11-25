import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import introduce
from test_python_execution import owned_claim, program, publish_python, receipt
from test_python_execution import python_setup as python_setup
from test_runner import runner as runner

from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.python_assessment import PythonAssessment
from leornian.modules.assessment.python_contracts import PythonPracticeSubmission, PythonTraining
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.tutor.learning_artifact_contracts import RunAction
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def practice_setup(database, session, python_setup, request):
    real = (
        request.getfixturevalue("runner") if os.environ.get("LEORNIAN_TEST_DOCKER") == "1" else None
    )
    publish_python(database, session, python_setup, runner=real)
    python, pack, gate = python_setup
    python.training(session.token, pack.pack_id)
    return python, pack, gate, real


def complete(database, session, attempt, real=None, *, wrong=False):
    claim = owned_claim(database, session, attempt.id)
    assert claim is not None
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, real, wrong=wrong))
    return claim


def test_immutable_revisions_use_original_runner_grades_and_latest_practice_eligibility(
    database, workflow, session, practice_setup
):
    python, pack, _, real = practice_setup
    first = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()),
        PythonPracticeSubmission(slot="practice_1", code="print(0)"),
    )
    complete(database, session, first, real, wrong=True)
    original = python.practice_attempt(session.token, first.id)
    assert original.status == "not_passed" and original.attempt_number == 1
    data = PythonPracticeSubmission(
        slot="practice_1", code=program("practice_1"), previous_attempt_id=first.id
    )
    second = python.submit_practice(session.token, pack.pack_id, str(uuid4()), data)
    assert second.previous_attempt_id == first.id and second.attempt_number == 2
    assert second.policy_version == "python-practice.v2" and not second.retry_requested
    complete(database, session, second, real)
    assert python.practice_attempt(session.token, second.id).status == "passed"
    assert python.practice_attempt(session.token, first.id) == original
    other = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()),
        PythonPracticeSubmission(slot="practice_2", code=program("practice_2")),
    )
    complete(database, session, other, real)
    with database.transaction() as connection:
        PythonAssessment(connection).require_training(session.actor, pack.pack_id)
        _, exposed = Exposures(connection).snapshot(session.actor)
        feedback = [
            item["feedback"] for item in exposed
            if item["key"].startswith(str(pack.pack_id) + ":practice_1")
            and "feedback" in item
        ]
        assert {item["attempt_id"] for item in feedback} == {str(first.id), str(second.id)}
        assert len({item["key"] for item in exposed}) == len(exposed)
    latest = python.practice_history(session.token, pack.pack_id, "practice_1", limit=1)
    assert latest.latest_attempt_id == second.id and latest.items[0].id == second.id
    assert latest.next_before == second.id
    rest = python.practice_history(
        session.token, pack.pack_id, "practice_1", before=latest.next_before, limit=1
    )
    assert [item.id for item in rest.items] == [first.id] and rest.next_before is None
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert "test_cases" not in latest.model_dump_json()
    with pytest.raises(BusinessError, match="already locked"):
        python.submit_training(
            session.token, pack.pack_id, str(uuid4()),
            PythonTraining(slot="practice_1", code=program("practice_1")),
        )


def test_replay_parent_cas_and_pending_attempt_do_not_create_parallel_execution(
    database, session, practice_setup
):
    python, pack, _, _ = practice_setup
    key = str(uuid4())
    data = PythonPracticeSubmission(slot="practice_1", code="print(0)")
    with ThreadPoolExecutor(max_workers=2) as executor:
        rows = list(executor.map(
            lambda _: python.submit_practice(session.token, pack.pack_id, key, data), range(2)
        ))
    assert rows[0].id == rows[1].id
    with pytest.raises(BusinessError) as error:
        python.submit_practice(
            session.token, pack.pack_id, key, data.model_copy(update={"retry": True})
        )
    assert error.value.code == "idempotency_conflict"
    next_data = PythonPracticeSubmission(
        slot="practice_1", code=program("practice_1"), previous_attempt_id=rows[0].id
    )
    with pytest.raises(BusinessError, match="still pending"):
        python.submit_practice(session.token, pack.pack_id, str(uuid4()), next_data)
    complete(database, session, rows[0], wrong=True)

    def submit(_):
        try:
            return python.submit_practice(
                session.token, pack.pack_id, str(uuid4()), next_data
            ).id
        except BusinessError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, range(2)))
    assert sum(item == "stale_version" for item in results) == 1
    assert len(python.practice_history(session.token, pack.pack_id, "practice_1").items) == 2


@pytest.mark.parametrize("claimed", [False, True], ids=["queued", "running"])
def test_cancel_and_explicit_retry_keep_late_receipt_without_applying_it_to_new_attempt(
    database, session, practice_setup, claimed
):
    python, pack, _, _ = practice_setup
    code = program("practice_1")
    first = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()),
        PythonPracticeSubmission(slot="practice_1", code=code),
    )
    claim = owned_claim(database, session, first.id) if claimed else None
    cancelled = python.cancel_practice(session.token, first.id)
    assert cancelled.status == "error"
    assert python.cancel_practice(session.token, first.id) == cancelled
    retry = PythonPracticeSubmission(
        slot="practice_1", code=code, previous_attempt_id=first.id,
    )
    with pytest.raises(BusinessError, match="explicitly retry"):
        python.submit_practice(session.token, pack.pack_id, str(uuid4()), retry)
    second = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()), retry.model_copy(update={"retry": True})
    )
    assert second.retry_requested and second.attempt_number == 2
    if claim:
        report = receipt(database, claim)
        JourneyWorkflow(database).report(claim.job_id, report)
        JourneyWorkflow(database).report(claim.job_id, report)
        with database.transaction() as connection:
            fact = connection.execute(
                "SELECT status,report FROM execution.jobs WHERE id=%s", (claim.job_id,)
            ).fetchone()
            assert fact["status"] == "expired" and "late_receipt" in fact["report"]
    assert python.practice_attempt(session.token, first.id) == cancelled
    assert python.practice_attempt(session.token, second.id).status == "queued"
    complete(database, session, second)
    assert python.practice_attempt(session.token, second.id).status == "passed"


def test_public_api_recovers_committed_request_without_dispatch_and_hides_qualification(
    database, workflow, session, practice_setup
):
    python, pack, gate, _ = practice_setup
    client = TestClient(create_app(gate[2][2]))
    headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
    path = f"/v2/packs/{pack.pack_id}/execution-submissions"
    response = client.post(
        path, headers=headers, json={"slot": "practice_1", "code": "print(0)"}
    )
    assert response.status_code == 202
    attempt = response.json()
    recovery = client.get(
        "/v2/python-practice-requests/" + headers["Idempotency-Key"], headers=headers
    )
    assert recovery.status_code == 200 and recovery.json()["id"] == attempt["id"]
    other = workflow.create_session("Other practice owner")
    assert client.get(
        "/v2/python-practice-attempts/" + attempt["id"],
        headers={"Authorization": "Bearer " + other.token},
    ).status_code == 404
    with database.transaction() as connection:
        qualification = connection.execute(
            "SELECT id FROM assessment.python_attempts WHERE pack_id=%s AND purpose='qualification'"
            " LIMIT 1", (pack.pack_id,),
        ).fetchone()["id"]
        assert connection.execute(
            "SELECT count(*) AS n FROM execution.jobs WHERE python_input_ref=%s",
            (attempt["id"],),
        ).fetchone()["n"] == 1
    assert client.get(
        f"/v2/python-practice-attempts/{qualification}", headers=headers
    ).status_code == 404
    assert client.get(
        f"/v2/packs/{pack.pack_id}/execution-practice-attempts?slot=assessment_1", headers=headers
    ).status_code == 422
    assert "test_cases" not in response.text and '"tests"' not in response.text
    python.cancel_practice(session.token, attempt["id"])


def test_explicit_new_practice_never_retargets_a_completed_v1_artifact(
    database, session, practice_setup
):
    python, pack, gate, _ = practice_setup
    settings = replace(
        gate[2][2], delivery_enabled=True,
        model_context_tokens=128000, model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    setup = {
        "flow": LearningArtifactWorkflow(database), "tutor": tutor, "settings": settings,
        "conversation": tutor.conversation(session.token, gate[2][3].goal_id), "pack": pack,
    }
    view, _ = introduce(session, setup)
    action = RunAction(
        action="run", client_action_id=uuid4(), expected_artifact_revision=view.revision,
        payload={"code": "print(0)"},
    )
    accepted = setup["flow"].action(session.token, view.conversation_id, view.id, action)
    first = python.practice_attempt(session.token, accepted.result_id)
    complete(database, session, first, wrong=True)
    before = setup["flow"].get(session.token, view.conversation_id, view.id)
    second = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()), PythonPracticeSubmission(
            slot="practice_1", code=program("practice_1"), previous_attempt_id=first.id,
        ),
    )
    complete(database, session, second)
    after = setup["flow"].get(session.token, view.conversation_id, view.id)
    assert after == before and after.result.id == first.id
    assert after.result.status == "not_passed" and after.allowed_actions == []
