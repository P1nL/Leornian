from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_goal_flow import event_id

from leornian.bootstrap.material_consumers import (
    consumer_material_required_in,
    register_node_demand_in,
)
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.identity.application import Identity
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.source_catalog import official_sources
from leornian.modules.learning.contracts import GoalInput, GoalMaterialScope
from leornian.modules.tutor.contracts import PlanningInput, TeachingFocus
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


@pytest.mark.parametrize("scope", [
    {"language": "Python", "authorized_official_sources": False},
    {"language": "Python", "authorized_official_sources": 1},
    {"language": "Python", "authorized_official_sources": "true"},
    {"language": " ", "authorized_official_sources": True},
    {"language": "Python", "language_version": " ", "authorized_official_sources": True},
    {"language": "Python", "framework_version": "3", "authorized_official_sources": True},
    {"language_version": "3.12", "authorized_official_sources": True},
    {"framework": "React", "authorized_official_sources": True},
])
def test_course_scope_requires_explicit_structured_authorization(scope):
    with pytest.raises(ValidationError):
        GoalMaterialScope(**scope)


def test_automatic_scope_discovers_only_supported_official_topics_and_exact_versions():
    scope = GoalMaterialScope(authorized_official_sources=True)
    assert scope.language is None
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="planning", scope_mode="teaching_goal",
        goal_text="Build a learning route",
    )
    sources = official_sources(demand, auto_topic="零基础学习 Python 3.12 和 JS")
    assert {key for key, _source in sources} == {"python-3.12-tutorial", "mdn-javascript"}
    assert sources[0][1].entry_url.startswith("https://docs.python.org/3.12/")
    assert [key for key, _source in official_sources(demand, auto_topic="学习 React")] == [
        "react-learn",
    ]
    for text in ("我想学点东西", "Java 8", "C# 12", "React v99"):
        assert official_sources(demand, auto_topic=text) == []


@pytest.mark.integration
def test_scoped_goal_preserves_receipt_and_enters_normal_official_discovery(
    database, workflow, session,
):
    scope = GoalMaterialScope(
        language="Python", language_version="3.12", authorized_official_sources=True,
    )
    # The title intentionally names another language: only confirmed metadata is authoritative.
    data = GoalInput(title="Compare with JavaScript text statistics", material_scope=scope)
    key = str(uuid4())
    accepted = workflow.submit(session.token, key, data)
    assert workflow.submit(session.token, key, data) == accepted
    with pytest.raises(BusinessError) as failure:
        workflow.submit(session.token, key, data.model_copy(update={
            "material_scope": scope.model_copy(update={"language_version": "3.11"}),
        }))
    assert failure.value.code == "idempotency_conflict"
    workflow.process_goal(event_id(database, accepted.job_id))
    goal = workflow.snapshot(session.token).goals[0]
    assert goal.material_scope == scope
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": f"Bearer {session.token}"}
    assert client.get(f"/v1/goal-requests/{key}", headers=headers).json()["job_id"] == str(
        accepted.job_id,
    )
    assert client.get("/v1/snapshot", headers=headers).json()["goals"][0]["material_scope"] == (
        scope.model_dump(mode="json")
    )
    settings = Settings(
        database_url=database.url, delivery_enabled=True, model_configuration_mode="user",
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, goal.id)
    turn = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Teach text statistics.", expected_revision=0),
    )
    with database.transaction() as connection:
        demand = register_node_demand_in(
            connection, session.actor, goal.id, TeachingFocus(kind="goal"),
            "planning", f"tutor-turn:{turn.turn_id}:planning", goal.title,
        )
        assert (demand.language, demand.language_version) == ("Python", "3.12")
        assert consumer_material_required_in(connection, session.actor, demand)
        discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
    MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    with database.transaction(snapshot=True) as connection:
        registered = connection.execute(
            "SELECT specification FROM knowledge.material_source_registrations "
            "WHERE actor_id=%s AND goal_id=%s",
            (session.actor.id, goal.id),
        ).fetchall()
        assert registered
        assert all(
            row["specification"]["language"] == "Python"
            and row["specification"]["language_version"] == "3.12"
            and row["specification"]["entry_url"].startswith("https://docs.python.org/3.12/")
            for row in registered
        )
        assert not connection.execute(
            "SELECT 1 FROM runtime.external_calls WHERE run_id=%s", (turn.run_id,),
        ).fetchone()


@pytest.mark.integration
def test_legacy_free_goal_does_not_infer_subject_or_authorize_catalog_fetch(
    database, workflow, session,
):
    data = GoalInput(title="Learn Python 3.12 and Flask")
    assert "material_scope" not in data.model_dump(mode="json")
    accepted = workflow.submit(session.token, str(uuid4()), data)
    workflow.process_goal(event_id(database, accepted.job_id))
    goal = workflow.snapshot(session.token).goals[0]
    assert goal.material_scope is None
    assert "material_scope" not in goal.model_dump(mode="json")
    with database.transaction() as connection:
        demand = register_node_demand_in(
            connection, session.actor, goal.id, TeachingFocus(kind="goal"),
            "planning", "legacy-scope-check:" + str(uuid4()), goal.title,
        )
        assert (demand.language, demand.language_version, demand.framework) == (None, None, None)
        assert not consumer_material_required_in(connection, session.actor, demand)
        assert not connection.execute(
            "SELECT 1 FROM knowledge.material_source_registrations WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()
