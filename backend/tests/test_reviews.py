from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_python_execution import owned_claim

from leornian.bootstrap.journey import JourneyWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.contracts import Submission
from leornian.modules.execution.contracts import CaseOutput, RunnerReport
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.learning.fsrs_schedule import schedule
from leornian.modules.learning.review_contracts import ReviewInput, ReviewStatus
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def review_setup(database, workflow, session):
    accepted = workflow.submit(session.token, str(uuid4()), GoalInput(title="Review Python loops"))
    with database.transaction() as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id = %s",
            (accepted.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    goal = workflow.snapshot(session.token).goals[0]
    service = JourneyWorkflow(database)
    track = service.draft(session.token, goal.id)
    service.confirm(session.token, track.id, 1)
    service.submit(session.token, track.id, str(uuid4()), Submission(code="owned-review-code"))
    claim = owned_claim(database, session, runner_id="test-runner")
    report = RunnerReport(
        claim_token=claim.claim_token,
        cases=[
            CaseOutput(exit_code=0, stdout=str(value), stderr="", outcome="completed")
            for value in (6, 0, 14)
        ],
    )
    service.report(claim.job_id, report)
    service.report(claim.job_id, report)
    return service, workflow.snapshot(session.token).reviews[0]


def make_due(database, card):
    with database.transaction() as connection:
        connection.execute(
            "UPDATE learning.review_cards SET next_due_at = now() - interval '1 minute' "
            "WHERE id = %s",
            (card.id,),
        )


def test_completion_schedules_exactly_once_and_early_review_is_rejected(
    database, workflow, session, review_setup
):
    service, card = review_setup
    assert len(workflow.snapshot(session.token).reviews) == 1
    assert not card.due and card.revision == 1
    with pytest.raises(BusinessError) as error:
        service.review(
            session.token, card.id, str(uuid4()), ReviewInput(expected_revision=1, rating="easy")
        )
    assert error.value.code == "precondition_failed"
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM learning.review_responses WHERE card_id = %s",
                (card.id,),
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.parametrize("rating", ["again", "good", "easy"])
def test_due_self_report_changes_schedule_not_assessment(
    database, workflow, session, review_setup, rating
):
    service, card = review_setup
    make_due(database, card)
    key = str(uuid4())
    data = ReviewInput(expected_revision=1, rating=rating)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: service.review(session.token, card.id, key, data), range(2))
        )
    assert results[0] == results[1] and results[0].revision == 2
    result = results[0]
    _, expected, _, due, _ = schedule(
        card.scheduling_state, rating, result.reviewed_at, card.id.int % (2**63),
    )
    assert result.next_due_at == due and result.scheduling_state == expected
    assert result.algorithm_version == "py-fsrs.6.3.2"
    assert not results[0].due
    with pytest.raises(BusinessError) as error:
        service.review(
            session.token,
            card.id,
            key,
            data.model_copy(update={"rating": "again" if rating != "again" else "good"}),
        )
    assert error.value.code == "idempotency_conflict"
    snapshot = workflow.snapshot(session.token)
    assert snapshot.tracks[0].status == "completed"
    assert len(snapshot.attempts) == 1 and snapshot.attempts[0].status == "passed"
    assert sum(event.event_type == "learning.review_recorded" for event in snapshot.events) == 1


def test_pause_resume_and_ownership(database, workflow, session, review_setup):
    service, card = review_setup
    make_due(database, card)
    paused = service.review_status(
        session.token, card.id, ReviewStatus(expected_revision=1, status="paused")
    )
    assert not paused.due and paused.revision == 2
    with pytest.raises(BusinessError) as error:
        service.review(
            session.token, card.id, str(uuid4()), ReviewInput(expected_revision=2, rating="good")
        )
    assert error.value.code == "precondition_failed"
    other = workflow.create_session("Not card owner")
    with pytest.raises(BusinessError) as error:
        service.review_status(
            other.token, card.id, ReviewStatus(expected_revision=2, status="scheduled")
        )
    assert error.value.code == "not_found"
    with pytest.raises(BusinessError) as error:
        service.review_status(
            session.token, card.id, ReviewStatus(expected_revision=1, status="scheduled")
        )
    assert error.value.code == "stale_version"
    resumed = service.review_status(
        session.token, card.id, ReviewStatus(expected_revision=2, status="scheduled")
    )
    assert resumed.due and resumed.revision == 3


def test_review_api_uses_current_revision_and_idempotency_key(
    database, workflow, session, review_setup
):
    _, card = review_setup
    make_due(database, card)
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
    response = client.post(
        f"/v1/reviews/{card.id}/responses",
        headers=headers,
        json={"expected_revision": 1, "rating": "good"},
    )
    assert response.status_code == 200 and response.json()["revision"] == 2
    assert (
        client.post(
            f"/v1/reviews/{card.id}/responses",
            headers=headers,
            json={"expected_revision": 1, "rating": "good"},
        ).status_code
        == 200
    )
