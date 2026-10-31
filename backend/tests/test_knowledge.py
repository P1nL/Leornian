from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.knowledge.contracts import (
    AdmitSource,
    SourceInput,
    SourceRef,
    SourceRevision,
)
from leornian.modules.learning.contracts import GoalInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError

CONTENT = SourceInput(
    title="Local supplied Python notes",
    source_url="https://docs.python.org/3/tutorial/controlflow.html",
    excerpt="A for statement iterates over the items of a sequence.",
)


@pytest.fixture
def source_setup(database, workflow, session):
    accepted = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Learn Python iteration")
    )
    with database.transaction() as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id = %s",
            (accepted.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    goal = workflow.snapshot(session.token).goals[0]
    return KnowledgeWorkflow(database), goal


def test_source_idempotence_ownership_and_revision_admission(
    database, workflow, session, source_setup
):
    service, goal = source_setup
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        sources = list(
            pool.map(lambda _: service.create(session.token, goal.id, key, CONTENT), range(2))
        )
    source = sources[0]
    assert all(item.id == source.id for item in sources) and not source.usable
    with pytest.raises(BusinessError) as error:
        service.create(
            session.token, goal.id, key, CONTENT.model_copy(update={"excerpt": "Changed"})
        )
    assert error.value.code == "idempotency_conflict"
    other = workflow.create_session("Other learner")
    with pytest.raises(BusinessError) as error:
        service.revoke(other.token, source.id, 1)
    assert error.value.code == "not_found"
    expiry = datetime.now(UTC) + timedelta(days=7)
    assert service.admit(
        session.token, source.id, AdmitSource(expected_revision=1, valid_until=expiry)
    ).usable
    revision = SourceRevision(**CONTENT.model_dump(), expected_revision=1).model_copy(
        update={"excerpt": "Revised note"}
    )
    revised = service.revise(session.token, source.id, revision)
    assert revised.revision == 2 and not revised.usable and revised.admission == "pending"
    assert service.revise(session.token, source.id, revision).revision == 2
    assert service.create(session.token, goal.id, key, CONTENT).revision == 2
    with pytest.raises(BusinessError) as error:
        service.admit(
            session.token, source.id, AdmitSource(expected_revision=1, valid_until=expiry)
        )
    assert error.value.code == "stale_version"
    service.admit(session.token, source.id, AdmitSource(expected_revision=2, valid_until=expiry))
    assert not service.revoke(session.token, source.id, 2).usable
    service.revoke(session.token, source.id, 2)
    with database.transaction() as connection:
        versions = connection.execute(
            "SELECT excerpt FROM knowledge.source_versions WHERE source_id = %s ORDER BY revision",
            (source.id,),
        ).fetchall()
    assert versions == [{"excerpt": CONTENT.excerpt}, {"excerpt": "Revised note"}]
    snapshot = workflow.snapshot(session.token)
    assert snapshot.sources[0].revision == 2
    assert sum(event.event_type == "knowledge.revoked" for event in snapshot.events) == 1


def test_only_current_admitted_bound_versions_are_retrievable(database, session, source_setup):
    service, goal = source_setup
    source = service.create(session.token, goal.id, str(uuid4()), CONTENT)
    with database.transaction() as connection:
        assert Knowledge(connection).materials(session.actor, goal.id) == []
    expiry = datetime.now(UTC) + timedelta(hours=1)
    service.admit(session.token, source.id, AdmitSource(expected_revision=1, valid_until=expiry))
    with database.transaction() as connection:
        materials = Knowledge(connection).materials(session.actor, goal.id)
        assert materials[0].source_id == source.id and materials[0].revision == 1
        connection.execute(
            "UPDATE knowledge.sources SET valid_until = now() - interval '1 second' WHERE id = %s",
            (source.id,),
        )
    with database.transaction() as connection:
        assert Knowledge(connection).materials(session.actor, goal.id) == []
        with pytest.raises(BusinessError) as error:
            Knowledge(connection).current(
                session.actor, goal.id, [SourceRef(source_id=source.id, revision=1)]
            )
        assert error.value.code == "source_not_current"
    with pytest.raises(BusinessError):
        service.admit(
            session.token,
            source.id,
            AdmitSource(expected_revision=1, valid_until=datetime.now(UTC) - timedelta(seconds=1)),
        )


def test_source_http_commands_do_not_fetch_supplied_url(database, session, source_setup):
    _, goal = source_setup
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
    body = CONTENT.model_copy(
        update={"source_url": "https://offline.invalid/not-fetched"}
    ).model_dump()
    response = client.post(f"/v1/goals/{goal.id}/sources", headers=headers, json=body)
    assert response.status_code == 201 and response.json()["admission"] == "pending"
    assert response.json()["origin"] == "learner_supplied"
    assert (
        client.post(
            f"/v1/goals/{goal.id}/sources", headers=headers, json={**body, "actor_id": str(uuid4())}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://example.org",
        "https://user:pass@example.org",
    ],
)
def test_source_links_are_not_executable_or_credentialed(url):
    with pytest.raises(ValidationError):
        SourceInput(**{**CONTENT.model_dump(), "source_url": url})
