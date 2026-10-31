from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from leornian.bootstrap.journey import JourneyWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.application import evaluate
from leornian.modules.assessment.contracts import Submission
from leornian.modules.execution.contracts import CaseOutput, RunnerReport
from leornian.modules.learning.contracts import GoalInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


def outputs(values=(6, 0, 14), **overrides):
    return [
        CaseOutput(exit_code=0, stdout=str(value), stderr="", outcome="completed").model_copy(
            update=overrides
        )
        for value in values
    ]


@pytest.fixture
def journey(database, workflow, session):
    accepted = workflow.submit(session.token, str(uuid4()), GoalInput(title="Learn Python loops"))
    with database.transaction() as connection:
        event = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id = %s", (accepted.job_id,)
        ).fetchone()
    workflow.process_goal(event["event_id"])
    goal = workflow.snapshot(session.token).goals[0]
    service = JourneyWorkflow(database)
    return service, service.draft(session.token, goal.id)


def test_plan_confirmation_versions_and_ownership(workflow, session, journey):
    service, track = journey
    assert service.draft(session.token, track.goal_id).id == track.id
    for action in (
        lambda: service.lesson(session.token, track.id),
        lambda: service.submit(session.token, track.id, str(uuid4()), Submission(code="print(0)")),
    ):
        with pytest.raises(BusinessError, match="Confirm"):
            action()
    with pytest.raises(BusinessError) as error:
        service.confirm(session.token, track.id, 2)
    assert error.value.code == "stale_version"
    other = workflow.create_session("Another learner")
    with pytest.raises(BusinessError) as error:
        service.confirm(other.token, track.id, 1)
    assert error.value.code == "not_found"
    assert service.confirm(session.token, track.id, 1).status == "confirmed"
    service.confirm(session.token, track.id, 1)
    lesson, exercise = service.lesson(session.token, track.id)
    assert lesson.title and exercise.version == "python-even-sum.v1"
    events = workflow.snapshot(session.token).events
    assert sum(event.event_type == "learning.plan_confirmed" for event in events) == 1


def test_wrong_then_correct_assessment_and_deduplication(database, workflow, session, journey):
    service, track = journey
    service.confirm(session.token, track.id, 1)
    key = str(uuid4())
    data = Submission(code="print(0)")
    with ThreadPoolExecutor(max_workers=3) as pool:
        attempts = list(
            pool.map(lambda _: service.submit(session.token, track.id, key, data), range(3))
        )
    assert len({attempt.id for attempt in attempts}) == 1
    with pytest.raises(BusinessError) as error:
        service.submit(session.token, track.id, key, Submission(code="print(6)"))
    assert error.value.code == "idempotency_conflict"
    claim = service.claim("test-runner")
    assert claim and claim.code == data.code and not hasattr(claim, "expected")
    assert service.claim("test-runner") is None
    wrong = RunnerReport(claim_token=claim.claim_token, cases=outputs((0, 0, 0)))
    service.report(claim.job_id, wrong)
    service.report(claim.job_id, wrong)
    assert service.attempt(session.token, attempts[0].id).status == "not_passed"
    assert workflow.snapshot(session.token).tracks[0].status == "confirmed"
    correct = service.submit(session.token, track.id, str(uuid4()), Submission(code="correct"))
    claim = service.claim("test-runner")
    report = RunnerReport(claim_token=claim.claim_token, cases=outputs())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: service.report(claim.job_id, report), range(2)))
    assert service.attempt(session.token, correct.id).status == "passed"
    snapshot = workflow.snapshot(session.token)
    assert snapshot.tracks[0].status == "completed"
    assert sum(event.event_type == "learning.lesson_completed" for event in snapshot.events) == 1
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM learning.assessment_inbox WHERE track_id = %s",
                (track.id,),
            ).fetchone()["n"]
            == 1
        )
    with pytest.raises(BusinessError) as error:
        service.report(
            claim.job_id, RunnerReport(claim_token=claim.claim_token, cases=outputs((1, 2, 3)))
        )
    assert error.value.code == "idempotency_conflict"


def test_expired_execution_never_reexecutes_or_applies_late_result(
    database, workflow, session, journey
):
    service, track = journey
    service.confirm(session.token, track.id, 1)
    attempt = service.submit(session.token, track.id, str(uuid4()), Submission(code="print(0)"))
    claim = service.claim("vanished-runner")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE execution.jobs SET lease_until = now() - interval '1 minute' WHERE id = %s",
            (claim.job_id,),
        )
    service.expire_executions()
    assert service.attempt(session.token, attempt.id).status == "error"
    assert service.claim("replacement-runner") is None
    report = RunnerReport(claim_token=claim.claim_token, cases=outputs())
    service.report(claim.job_id, report)
    service.report(claim.job_id, report)
    assert workflow.snapshot(session.token).tracks[0].status == "confirmed"
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM execution.jobs WHERE id = %s", (claim.job_id,)
        ).fetchone()
    assert row["status"] == "expired" and row["report"]["late_receipt"] == report.model_dump(
        mode="json"
    )
    assert (
        sum(
            event.event_type == "assessment.completed"
            for event in workflow.snapshot(session.token).events
        )
        == 1
    )


def test_wrong_claim_and_current_learner_revocation(database, workflow, session, journey):
    service, track = journey
    service.confirm(session.token, track.id, 1)
    attempt = service.submit(session.token, track.id, str(uuid4()), Submission(code="print(0)"))
    claim = service.claim("test-runner")
    with pytest.raises(BusinessError) as error:
        service.report(claim.job_id, RunnerReport(claim_token=uuid4(), cases=outputs()))
    assert error.value.code == "stale_version"
    with database.transaction() as connection:
        connection.execute(
            "UPDATE identity.learners SET active = false WHERE id = %s", (session.actor.id,)
        )
    service.report(claim.job_id, RunnerReport(claim_token=claim.claim_token, cases=outputs()))
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM assessment.attempts WHERE id = %s", (attempt.id,)
            ).fetchone()["status"]
            == "error"
        )
        assert (
            connection.execute(
                "SELECT status FROM learning.tracks WHERE id = %s", (track.id,)
            ).fetchone()["status"]
            == "confirmed"
        )
        assert connection.execute(
            "SELECT report FROM execution.jobs WHERE id = %s", (claim.job_id,)
        ).fetchone()["report"]["cases"]


def test_inactive_queued_execution_does_not_block_queue(database, session, journey):
    service, track = journey
    service.confirm(session.token, track.id, 1)
    attempt = service.submit(session.token, track.id, str(uuid4()), Submission(code="print(0)"))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE identity.learners SET active = false WHERE id = %s", (session.actor.id,)
        )
    assert service.claim("test-runner") is None
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM execution.jobs WHERE input_ref = %s", (attempt.id,)
            ).fetchone()["status"]
            == "expired"
        )


@pytest.mark.parametrize("when", ["before_claim", "before_report"])
def test_revoked_originating_session_prevents_execution_effects(database, session, journey, when):
    service, track = journey
    service.confirm(session.token, track.id, 1)
    attempt = service.submit(session.token, track.id, str(uuid4()), Submission(code="print(0)"))
    claim = service.claim("test-runner") if when == "before_report" else None
    with database.transaction() as connection:
        connection.execute(
            "UPDATE identity.sessions SET revoked_at = now() WHERE actor_id = %s",
            (session.actor.id,),
        )
    if claim:
        service.report(claim.job_id, RunnerReport(claim_token=claim.claim_token, cases=outputs()))
    else:
        assert service.claim("test-runner") is None
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM assessment.attempts WHERE id = %s",
                (attempt.id,),
            ).fetchone()["status"]
            == "error"
        )
        assert (
            connection.execute(
                "SELECT status FROM learning.tracks WHERE id = %s",
                (track.id,),
            ).fetchone()["status"]
            == "confirmed"
        )


def test_runner_auth_and_public_projection(database, workflow, session, journey):
    service, track = journey
    client = TestClient(
        create_app(Settings(database_url=database.url, runner_token="test-runner-only"))
    )
    headers = {"Authorization": "Bearer " + session.token}
    assert (
        client.post(
            "/internal/executions/claim", headers=headers, json={"runner_id": "fake"}
        ).status_code
        == 401
    )
    assert client.get(f"/v1/tracks/{track.id}/lesson", headers=headers).status_code == 409
    assert (
        client.post(
            f"/v1/tracks/{track.id}/confirm", headers=headers, json={"expected_revision": 1}
        ).status_code
        == 200
    )
    response = client.get(f"/v1/tracks/{track.id}/lesson", headers=headers)
    assert response.status_code == 200
    assert "execution_inputs" not in response.text and "expected" not in response.text
    other = workflow.create_session("Other learner")
    assert (
        client.get(
            f"/v1/tracks/{track.id}/lesson", headers={"Authorization": "Bearer " + other.token}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"exit_code": 1},
        {"outcome": "timeout"},
        {"outcome": "output_limit"},
        {"outcome": "infrastructure_error"},
        {"stdout": "true"},
        {"stdout": "6.0"},
    ],
)
def test_exit_zero_or_invalid_output_is_not_assessment_success(overrides):
    assert not evaluate(outputs(**overrides)).passed


def test_assessment_requires_all_cases():
    assert not evaluate(outputs()[:1]).passed
    assert evaluate(outputs()).passed
