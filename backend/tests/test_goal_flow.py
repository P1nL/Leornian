from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from leornian.entrypoints.api import create_app
from leornian.modules.learning.contracts import GoalInput
from leornian.platform.config import Settings
from leornian.platform.relay import relay_once
from leornian.shared_kernel.errors import BusinessError

pytestmark = pytest.mark.integration


def submit(workflow, session, key=None):
    return workflow.submit(
        session.token,
        key or str(uuid4()),
        GoalInput(title="Learn Python", motivation="Build a tool"),
    )


def event_id(database, job_id):
    with database.transaction() as connection:
        return connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id = %s", (job_id,)
        ).fetchone()["event_id"]


def test_durable_request_and_idempotent_execution(database, workflow, session):
    key = str(uuid4())
    accepted = submit(workflow, session, key)
    assert workflow.job(session.token, accepted.job_id).status == "queued"
    assert not workflow.snapshot(session.token).goals
    assert submit(workflow, session, key) == accepted
    event = event_id(database, accepted.job_id)
    workflow.process_goal(event)
    workflow.process_goal(event)
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.goals) == 1
    assert snapshot.jobs[0].status == "succeeded"
    assert snapshot.jobs[0].result_ref == snapshot.goals[0].id
    assert snapshot.cursor == 3
    events = workflow.events(session.token, 0)
    assert [event.event_type for event in events] == ["job.queued", "goal.created", "job.succeeded"]
    assert [event.sequence for event in workflow.events(session.token, 1)] == [2, 3]
    assert workflow.events(session.token, snapshot.cursor) == []
    with pytest.raises(BusinessError, match="reset"):
        workflow.events(session.token, 999)


def test_changed_payload_is_not_accepted_under_the_same_key(workflow, session):
    key = str(uuid4())
    submit(workflow, session, key)
    with pytest.raises(BusinessError) as problem:
        workflow.submit(session.token, key, GoalInput(title="Different goal"))
    assert problem.value.code == "idempotency_conflict"
    assert len(workflow.snapshot(session.token).jobs) == 1


def test_concurrent_duplicate_requests_and_messages(database, workflow, session):
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as executor:
        accepted = list(executor.map(lambda _: submit(workflow, session, key), range(4)))
    assert len({item.job_id for item in accepted}) == 1
    event = event_id(database, accepted[0].job_id)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: workflow.process_goal(event), range(4)))
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.goals) == 1
    assert snapshot.cursor == 3


def test_failed_transaction_leaves_no_partial_business_result(
    database,
    workflow,
    session,
    monkeypatch,
):
    from leornian.delivery.events import Events

    accepted = submit(workflow, session)
    event = event_id(database, accepted.job_id)
    original = Events.append

    def crash(*_args, **_kwargs):
        raise RuntimeError("simulated crash before commit")

    monkeypatch.setattr(Events, "append", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        workflow.process_goal(event)
    assert workflow.job(session.token, accepted.job_id).status == "queued"
    assert not workflow.snapshot(session.token).goals
    monkeypatch.setattr(Events, "append", original)
    workflow.process_goal(event)
    assert len(workflow.snapshot(session.token).goals) == 1


def test_current_identity_is_checked_again_before_worker_writes(database, workflow, session):
    accepted = submit(workflow, session)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE identity.learners SET active = false WHERE id = %s", (session.actor.id,)
        )
    workflow.process_goal(event_id(database, accepted.job_id))
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status, error_code FROM platform.jobs WHERE id = %s", (accepted.job_id,)
        ).fetchone()
        assert row == {"status": "failed", "error_code": "unauthorized"}
        assert not connection.execute(
            "SELECT id FROM learning.goals WHERE actor_id = %s", (session.actor.id,)
        ).fetchall()


def test_broker_failure_keeps_outbox_eligible_and_lost_wakeup_is_redispatched(
    database,
    workflow,
    session,
):
    accepted = submit(workflow, session)
    event = event_id(database, accepted.job_id)

    def unavailable(_event):
        raise ConnectionError("broker unavailable")

    with pytest.raises(ConnectionError):
        relay_once(database, unavailable)
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT published_at FROM platform.outbox WHERE event_id = %s", (event,)
            ).fetchone()["published_at"]
            is None
        )

    published = []
    relay_once(database, published.append)
    assert event in published
    with database.transaction() as connection:
        connection.execute(
            "UPDATE platform.outbox SET published_at = now() - interval '1 minute' "
            "WHERE event_id = %s",
            (event,),
        )
    redispatched = []
    relay_once(database, redispatched.append)
    assert event in redispatched
    workflow.process_goal(event)
    assert len(workflow.snapshot(session.token).goals) == 1


def test_http_auth_ownership_conflicts_and_validation(database, workflow, session):
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": f"Bearer {session.token}", "Idempotency-Key": str(uuid4())}
    assert client.get("/v1/snapshot").status_code == 401
    assert client.get("/v1/events").status_code == 401
    response = client.post("/v1/goals", headers=headers, json={"title": "Learn Rust"})
    assert response.status_code == 202
    job = response.json()["job_id"]
    other = workflow.create_session("Other learner")
    other_headers = {"Authorization": f"Bearer {other.token}"}
    assert client.get(f"/v1/jobs/{job}", headers=other_headers).status_code == 404
    assert client.get("/v1/snapshot", headers=other_headers).json()["jobs"] == []
    assert client.get("/v1/events?after=1", headers=other_headers).status_code == 409
    assert client.post("/v1/goals", headers=headers, json={"title": "Changed"}).status_code == 409
    assert client.post("/v1/goals", headers=headers, json={"title": "  "}).status_code == 422
    assert (
        client.post(
            "/v1/goals",
            headers=headers,
            json={"title": "Another goal", "actor_id": str(other.actor.id)},
        ).status_code
        == 422
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE identity.sessions SET revoked_at = now() WHERE actor_id = %s",
            (session.actor.id,),
        )
    assert client.get("/v1/snapshot", headers=headers).status_code == 401
