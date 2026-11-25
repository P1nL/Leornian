from typing import get_args
from uuid import uuid4

from fastapi.testclient import TestClient
from test_goal_flow import event_id, submit

from leornian.agent_runtime.repository import Runs
from leornian.delivery.contracts import EventPayload, PublicEvent
from leornian.delivery.events import Events
from leornian.entrypoints.api import create_app
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.platform.config import Settings


def test_every_public_event_type_can_be_committed_after_migration(database, session):
    with database.transaction() as connection:
        for kind in get_args(PublicEvent.model_fields["event_type"].annotation):
            Events(connection).append(
                session.actor.id, kind, uuid4(), EventPayload(goal_id=uuid4()),
            )
    with database.transaction() as connection:
        assert any(event.event_type == "tutor.thinking" for event in
                   Events(connection).list(session.actor, 0))


def test_goal_rename_delete_are_owner_scoped_and_keep_original_history(database, workflow, session):
    accepted = submit(workflow, session)
    workflow.process_goal(event_id(database, accepted.job_id))
    goal = workflow.snapshot(session.token).goals[0]
    with database.transaction() as connection:
        conversation = PgTutorStore(connection).conversation(session.actor, goal.id)
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": f"Bearer {session.token}"}
    path = f"/v1/goals/{goal.id}"
    other = workflow.create_session("Other owner")
    other_headers = {"Authorization": f"Bearer {other.token}"}
    assert client.patch(path, headers=other_headers, json={"title": "Other"}).status_code == 404
    assert client.delete(path, headers=other_headers).status_code == 404
    assert client.patch(path, headers=headers, json={"title": "  "}).status_code == 422
    renamed = client.patch(path, headers=headers, json={"title": " Python 基础 "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Python 基础"
    assert workflow.snapshot(session.token).goals[0].title == "Python 基础"
    assert client.delete(path, headers=headers).status_code == 200
    assert client.delete(path, headers=headers).status_code == 200
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.goals
    assert any(item.id == conversation.id for item in snapshot.conversations)
    assert snapshot.jobs[0].status == "succeeded"


def test_recent_conversation_delete_is_owner_scoped_idempotent_and_keeps_learning(
    database, workflow, session,
):
    accepted = submit(workflow, session)
    workflow.process_goal(event_id(database, accepted.job_id))
    goal = workflow.snapshot(session.token).goals[0]
    with database.transaction() as connection:
        store = PgTutorStore(connection)
        conversation = store.conversation(session.actor, goal.id)
        turn, _ = store.request_turn(conversation.id, str(uuid4()), "Continue my route")
        run = Runs(connection).create(
            session.actor.id, conversation.id, turn.id, "isolated-navigation-test",
        )
    before = workflow.snapshot(session.token)
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": f"Bearer {session.token}"}
    path = f"/v1/conversations/{conversation.id}/recent-entry"
    other = workflow.create_session("Other owner")
    assert client.delete(path).status_code == 401
    other_headers = {"Authorization": f"Bearer {other.token}"}
    assert client.delete(path, headers=other_headers).status_code == 404
    missing = f"/v1/conversations/{uuid4()}/recent-entry"
    assert client.delete(missing, headers=headers).status_code == 404
    assert not workflow.snapshot(session.token).conversations[0].hidden_from_recents
    response = client.delete(path, headers=headers)
    assert response.status_code == 200 and response.json()["hidden_from_recents"]
    after = workflow.snapshot(session.token)
    assert after.goals == before.goals
    assert after.turns == before.turns
    assert after.runs == before.runs and after.runs[0].id == run.id
    assert after.conversations[0].hidden_from_recents
    assert after.events[-1].event_type == "tutor.conversation_hidden"
    assert after.events[-1].payload.conversation_id == conversation.id
    assert client.delete(path, headers=headers).json() == response.json()
    assert workflow.snapshot(session.token).cursor == after.cursor
    history = client.get(f"/v1/conversations/{conversation.id}/history", headers=headers)
    assert history.status_code == 200 and history.json()[0]["id"] == str(turn.id)
