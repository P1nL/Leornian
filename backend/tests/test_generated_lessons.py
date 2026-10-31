import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from leornian.agent_runtime.contracts import Receipt
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.contracts import AdmitSource, SourceInput
from leornian.modules.learning.contracts import GoalInput, LessonRequestInput
from leornian.modules.tutor.contracts import PlanningInput, TurnInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


def envelope(value):
    return json.dumps(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": json.dumps(value)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 180, "completion_tokens": 300},
        }
    )


def execute(tutor, settings, run_id, document):
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=envelope(document))

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle))).run(run_id)
    return seen


def lesson_document(source):
    return {
        "title": "Read paths before changing files",
        "introduction": "First inspect entries; do not modify them while learning the loop.",
        "sections": [
            {
                "heading": "Iterate over directory children",
                "explanation": "Path.iterdir yields each direct child. Inspect paths before moves.",
                "code_example": (
                    'from pathlib import Path\nfor path in Path(".").iterdir():\n    print(path)'
                ),
                "source_refs": [{"source_id": str(source.id), "revision": 1}],
            }
        ],
        "recall_prompts": ["What changes when a directory is empty?"],
    }


@pytest.fixture
def lesson_setup(database, workflow, session):
    accepted = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Python directory reader")
    )
    with database.transaction() as connection:
        event = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id = %s",
            (accepted.job_id,),
        ).fetchone()
    workflow.process_goal(event["event_id"])
    goal = workflow.snapshot(session.token).goals[0]
    settings = Settings(
        database_url=database.url,
        model_enabled=True,
        model_base_url="https://owned.invalid/v1",
        model_name="offline-owned",
        model_api_key="offline-owned-secret",
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, goal.id)
    knowledge = KnowledgeWorkflow(database)
    source = knowledge.create(
        session.token,
        goal.id,
        str(uuid4()),
        SourceInput(
            title="Owned pathlib excerpt",
            source_url="https://owned.invalid/pathlib",
            excerpt="Path.iterdir yields the direct children of a directory.",
        ),
    )
    knowledge.admit(
        session.token,
        source.id,
        AdmitSource(
            expected_revision=1,
            valid_until=datetime.now(UTC) + timedelta(days=1),
        ),
    )
    plan_doc = {
        "title": "Directory reader route",
        "summary": "Read and inspect paths safely.",
        "assumptions": ["A Python interpreter is available."],
        "nodes": [
            {
                "key": "paths",
                "title": "Inspect paths",
                "objective": "List direct directory entries.",
                "estimated_minutes": 25,
                "prerequisite_keys": [],
                "source_refs": [{"source_id": str(source.id), "revision": 1}],
            }
        ],
    }
    run = tutor.submit_plan(
        session.token,
        conversation.id,
        str(uuid4()),
        PlanningInput(
            text="Plan a short lesson",
            expected_revision=0,
        ),
    )
    execute(tutor, settings, run.run_id, plan_doc)
    plan = workflow.snapshot(session.token).plans[0]
    return tutor, settings, plan, source, conversation, plan_doc


def request_input():
    return LessonRequestInput(
        expected_plan_revision=1, node_key="paths", instruction="Use small readable examples."
    )


def records(database, run_id):
    with database.transaction() as connection:
        return connection.execute(
            "SELECT * FROM runtime.external_calls WHERE run_id = %s", (run_id,)
        ).fetchall()


def test_confirmed_node_lesson_is_persisted_cited_and_not_an_assessment(
    database, workflow, session, lesson_setup
):
    tutor, settings, plan, source, _, _ = lesson_setup
    with pytest.raises(BusinessError) as error:
        tutor.submit_lesson(session.token, plan.id, str(uuid4()), request_input())
    assert error.value.code == "stale_version"
    tutor.confirm_plan(session.token, plan.id, 1)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = list(
            pool.map(
                lambda _: tutor.submit_lesson(session.token, plan.id, key, request_input()),
                range(2),
            )
        )
    assert requests[0] == requests[1]
    seen = execute(tutor, settings, requests[0].run_id, lesson_document(source))
    assert len(seen) == 1 and "tools" not in seen[0]
    assert "confirmed_plan_revision" in json.dumps(seen[0])
    result = tutor.get(session.token, requests[0].run_id)
    assert result.status == "succeeded" and result.purpose == "lesson"
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.lessons) == 1 and snapshot.attempts == [] and snapshot.tracks == []
    assert snapshot.lessons[0].plan_id == plan.id and snapshot.lessons[0].plan_revision == 1
    assert snapshot.lessons[0].sources[0].excerpt == source.excerpt
    assert tutor.lesson_document(session.token, snapshot.lessons[0].id).document.title
    assert tutor.submit_lesson(session.token, plan.id, key, request_input()) == requests[0]
    assert records(database, requests[0].run_id)[0]["applied"]
    assert (
        sum(event.event_type == "learning.lesson_document_created" for event in snapshot.events)
        == 1
    )


@pytest.mark.parametrize("invalid", ["foreign_citation", "empty_sections", "fake_authority"])
def test_invalid_lesson_never_creates_document(database, workflow, session, lesson_setup, invalid):
    tutor, settings, plan, source, _, _ = lesson_setup
    tutor.confirm_plan(session.token, plan.id, 1)
    value = lesson_document(source)
    if invalid == "foreign_citation":
        value["sections"][0]["source_refs"][0]["source_id"] = str(uuid4())
    elif invalid == "empty_sections":
        value["sections"] = []
    else:
        value["mastery_passed"] = True
    run = tutor.submit_lesson(session.token, plan.id, str(uuid4()), request_input())
    execute(tutor, settings, run.run_id, value)
    assert tutor.get(session.token, run.run_id).error_code == "invalid_lesson_output"
    assert workflow.snapshot(session.token).lessons == []
    assert records(database, run.run_id)[0]["status"] == "result_recorded"


@pytest.mark.parametrize("invalidate", ["source", "plan"])
def test_lesson_dispatch_rechecks_source_and_confirmed_plan(
    database, workflow, session, lesson_setup, invalidate
):
    tutor, settings, plan, source, _, _ = lesson_setup
    tutor.confirm_plan(session.token, plan.id, 1)
    run = tutor.submit_lesson(session.token, plan.id, str(uuid4()), request_input())
    lease = tutor.claim(run.run_id)
    role = tutor.context(lease)
    model = ChatCompletionsGateway(settings)
    call = tutor.prepare(
        lease,
        model.endpoint,
        model.request(role.messages, require_tool=False, allowed_tools=(), json_output=True),
    )
    if invalidate == "source":
        KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    else:
        # Simulate an independently committed new active plan at the owner boundary.
        with database.transaction() as connection:
            connection.execute(
                "UPDATE learning.plans SET active_revision = NULL WHERE id = %s", (plan.id,)
            )
    assert not tutor.dispatch(lease, call.id)
    result = tutor.get(session.token, run.run_id)
    assert result.status == "failed" and result.error_code == (
        "source_not_current" if invalidate == "source" else "stale_version"
    )
    assert records(database, run.run_id)[0]["status"] == "not_sent"
    assert workflow.snapshot(session.token).lessons == []


def test_recorded_lesson_recovery_does_not_resend(database, workflow, session, lesson_setup):
    tutor, settings, plan, source, _, _ = lesson_setup
    tutor.confirm_plan(session.token, plan.id, 1)
    run = tutor.submit_lesson(session.token, plan.id, str(uuid4()), request_input())
    lease = tutor.claim(run.run_id)
    role = tutor.context(lease)
    model = ChatCompletionsGateway(settings)
    call = tutor.prepare(
        lease,
        model.endpoint,
        model.request(role.messages, require_tool=False, allowed_tools=(), json_output=True),
    )
    tutor.dispatch(lease, call.id)
    tutor.record(call.id, Receipt(body=envelope(lesson_document(source)), http_status=200))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE runtime.runs SET lease_until = now() - interval '1 minute' WHERE id = %s",
            (run.run_id,),
        )
    seen = execute(tutor, settings, run.run_id, lesson_document(source))
    assert seen == [] and len(workflow.snapshot(session.token).lessons) == 1


def test_lesson_api_has_owner_boundary_and_no_model_fallback(
    database, workflow, session, lesson_setup
):
    tutor, settings, plan, source, _, _ = lesson_setup
    tutor.confirm_plan(session.token, plan.id, 1)
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
    assert (
        client.post(
            f"/v1/plans/{plan.id}/lesson-requests",
            headers=headers,
            json=request_input().model_dump(),
        ).status_code
        == 503
    )
    run = tutor.submit_lesson(session.token, plan.id, str(uuid4()), request_input())
    execute(tutor, settings, run.run_id, lesson_document(source))
    lesson = workflow.snapshot(session.token).lessons[0]
    other = workflow.create_session("Other lesson reader")
    assert (
        client.get(
            f"/v1/lessons/{lesson.id}", headers={"Authorization": "Bearer " + other.token}
        ).status_code
        == 404
    )
    response = client.get(f"/v1/lessons/{lesson.id}", headers=headers)
    assert response.status_code == 200 and response.json()["sources"][0]["revision"] == 1
    assert "produced_by_run" not in response.text and "model_api_key" not in response.text


def test_confirming_new_route_inflight_preserves_receipt_not_old_version_lesson(
    database,
    workflow,
    session,
    lesson_setup,
):
    tutor, settings, plan, source, conversation, plan_doc = lesson_setup
    tutor.confirm_plan(session.token, plan.id, 1)
    planned = tutor.submit_plan(
        session.token,
        conversation.id,
        str(uuid4()),
        PlanningInput(
            text="Use a shorter route",
            expected_revision=1,
        ),
    )
    execute(tutor, settings, planned.run_id, {**plan_doc, "title": "A shorter confirmed route"})
    requested = tutor.submit_lesson(session.token, plan.id, str(uuid4()), request_input())

    def switch_plan(_):
        tutor.confirm_plan(session.token, plan.id, 2)
        return httpx.Response(200, content=envelope(lesson_document(source)))

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(switch_plan))).run(
        requested.run_id
    )
    result = tutor.get(session.token, requested.run_id)
    assert result.status == "failed" and result.error_code == "stale_version"
    assert records(database, requested.run_id)[0]["status"] == "result_recorded"
    assert workflow.snapshot(session.token).lessons == []


def test_tutor_reads_generated_body_only_with_active_plan_and_current_bound_sources(
    database,
    workflow,
    session,
    lesson_setup,
):
    tutor, settings, plan, source, conversation, _ = lesson_setup
    tutor.confirm_plan(session.token, plan.id, 1)
    requested = tutor.submit_lesson(session.token, plan.id, str(uuid4()), request_input())
    execute(tutor, settings, requested.run_id, lesson_document(source))
    observed = []

    def teach(request):
        sent = json.loads(request.content)
        tool_result = sent["messages"][-1]
        if tool_result["role"] == "tool":
            observed.append(json.loads(tool_result["content"]))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Use the saved lesson to inspect paths first.",
                            },
                            "finish_reason": "stop",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "context",
                                    "type": "function",
                                    "function": {"name": "learning_get_context", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    for revoked in (False, True):
        if revoked:
            KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
        accepted = tutor.submit(
            session.token,
            conversation.id,
            str(uuid4()),
            TurnInput(text="Explain the saved lesson."),
        )
        AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(teach))).run(
            accepted.run_id
        )
        assert tutor.get(session.token, accepted.run_id).status == "succeeded"
        assert ("latest_generated_lesson" in observed[-1]) is not revoked
    assert (
        observed[0]["latest_generated_lesson"]["document"]["title"]
        == lesson_document(source)["title"]
    )


def test_nodes_without_grounding_cannot_generate_lessons(database, workflow, session, lesson_setup):
    tutor, settings, plan, _, conversation, plan_doc = lesson_setup
    KnowledgeWorkflow(database).revoke(
        session.token, workflow.snapshot(session.token).sources[0].id, 1
    )
    plan_doc["nodes"][0]["source_refs"] = []
    run = tutor.submit_plan(
        session.token,
        conversation.id,
        str(uuid4()),
        PlanningInput(text="Ungrounded route", expected_revision=1),
    )
    execute(tutor, settings, run.run_id, plan_doc)
    tutor.confirm_plan(session.token, plan.id, 2)
    with pytest.raises(BusinessError) as error:
        tutor.submit_lesson(
            session.token,
            plan.id,
            str(uuid4()),
            request_input().model_copy(update={"expected_plan_revision": 2}),
        )
    assert error.value.code == "source_not_current"
