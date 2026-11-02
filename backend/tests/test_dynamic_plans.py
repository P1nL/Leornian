import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from leornian.agent_runtime.contracts import Receipt
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.contracts import AdmitSource, SourceInput
from leornian.modules.learning.contracts import GoalInput, PlanDocument
from leornian.modules.tutor.contracts import PlanningInput, TurnInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


def document(*, title="Build a file organizer", sources=()):
    return {
        "title": title,
        "summary": "Learn safe file iteration, then assemble a small file organizer.",
        "assumptions": ["Learner can run a local Python interpreter; confirm before lessons."],
        "nodes": [
            {
                "key": "paths",
                "title": "Read directory entries",
                "objective": "List a directory with pathlib without changing its files.",
                "estimated_minutes": 30,
                "prerequisite_keys": [],
                "source_refs": list(sources),
            },
            {
                "key": "organizer",
                "title": "Plan safe moves",
                "objective": "Compute and print intended destinations before any actual move.",
                "estimated_minutes": 45,
                "prerequisite_keys": ["paths"],
                "source_refs": list(sources),
            },
        ],
    }


def provider_body(content):
    return json.dumps(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": json.dumps(content)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 160},
        }
    )


@pytest.fixture
def setup_planner(database, workflow, session):
    accepted = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Python file organizer")
    )
    with database.transaction() as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id = %s",
            (accepted.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    goal = workflow.snapshot(session.token).goals[0]
    settings = Settings(
        delivery_enabled=False,  # Preserve the historical single-stage Runtime regression contract.
        database_url=database.url,
        model_enabled=True,
        model_base_url="https://owned.invalid/v1",
        model_name="offline-owned",
        model_api_key="offline-owned-secret",
    )
    tutor = TutorWorkflow(database, settings)
    return tutor, settings, tutor.conversation(session.token, goal.id)


def submit(
    setup_planner, session, revision=0, key=None, text="I know loops. Build a 2-step route."
):
    tutor, _, conversation = setup_planner
    return tutor.submit_plan(
        session.token,
        conversation.id,
        key or str(uuid4()),
        PlanningInput(text=text, expected_revision=revision),
    )


def run(setup_planner, run_id, content, seen=None):
    tutor, settings, _ = setup_planner
    sent = [] if seen is None else seen

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, content=provider_body(content), headers={"x-request-id": "owned"}
        )

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle))).run(run_id)
    return sent


def records(database, run_id):
    with database.transaction() as connection:
        return connection.execute(
            "SELECT * FROM runtime.external_calls WHERE run_id = %s ORDER BY step",
            (run_id,),
        ).fetchall()


def expire(database, run_id):
    with database.transaction() as connection:
        connection.execute(
            "UPDATE runtime.runs SET lease_until = now() - interval '1 minute' WHERE id = %s",
            (run_id,),
        )


def test_generated_plan_is_append_only_and_explicit_confirmation_selects_version(
    database,
    workflow,
    session,
    setup_planner,
):
    tutor, _, conversation = setup_planner
    first = submit(setup_planner, session)
    sent = run(setup_planner, first.run_id, document())
    assert len(sent) == 1 and sent[0]["response_format"] == {"type": "json_object"}
    assert "tools" not in sent[0] and sent[0]["max_tokens"] == 2400
    completed = tutor.get(session.token, first.run_id)
    assert (
        completed.status == "succeeded"
        and completed.purpose == "planning"
        and completed.tool_count == 0
    )
    snapshot = workflow.snapshot(session.token)
    plan = snapshot.plans[0]
    assert plan.latest.revision == 1 and plan.active is None
    assert snapshot.tracks == [] and snapshot.attempts == []
    assert "等待你确认" in snapshot.turns[0].turns[0].assistant_text
    tutor.confirm_plan(session.token, plan.id, 1)
    tutor.confirm_plan(session.token, plan.id, 1)
    second = submit(setup_planner, session, 1, text="Make the route shorter.")
    run(setup_planner, second.run_id, document(title="A shorter route"))
    plan = tutor.plan(session.token, plan.id)
    assert plan.latest.revision == 2 and plan.latest.predecessor_revision == 1
    assert plan.active.revision == 1 and plan.active.document.title == "Build a file organizer"
    with pytest.raises(BusinessError) as error:
        tutor.confirm_plan(session.token, plan.id, 1)
    assert error.value.code == "stale_version"
    tutor.confirm_plan(session.token, plan.id, 2)
    assert [item.revision for item in tutor.plan_history(session.token, plan.id)] == [2, 1]
    assert tutor.plan(session.token, plan.id).active.document.title == "A shorter route"
    assert records(database, first.run_id)[0]["applied"]
    assert all(
        event.payload.plan_id == plan.id
        for event in workflow.snapshot(session.token).events
        if event.event_type.startswith("learning.dynamic_plan_")
    )


def test_duplicate_planning_and_teaching_are_one_conversation_exclusion_scope(
    database,
    session,
    setup_planner,
):
    tutor, _, conversation = setup_planner
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as pool:
        accepted = list(pool.map(lambda _: submit(setup_planner, session, key=key), range(3)))
    assert len({item.run_id for item in accepted}) == 1
    with pytest.raises(BusinessError) as error:
        tutor.submit(
            session.token,
            conversation.id,
            key,
            TurnInput(text="I know loops. Build a 2-step route."),
        )
    assert error.value.code == "idempotency_conflict"
    with pytest.raises(BusinessError) as error:
        submit(setup_planner, session)
    assert error.value.code == "run_active"
    seen = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run(setup_planner, accepted[0].run_id, document(), seen), range(2)))
    assert len(seen) == 1
    # A retry after completion returns the original run even though latest revision changed.
    assert submit(setup_planner, session, key=key).run_id == accepted[0].run_id
    with pytest.raises(BusinessError) as error:
        submit(setup_planner, session, revision=0)
    assert error.value.code == "stale_version"


@pytest.mark.parametrize(
    "invalid",
    [
        "forward_dependency",
        "duplicate_key",
        "empty_nodes",
        "wrong_type",
        "injected_authority",
        "no_assumptions",
    ],
)
def test_invalid_generated_plan_preserves_receipt_but_never_creates_draft(
    database,
    workflow,
    session,
    setup_planner,
    invalid,
):
    value = document()
    if invalid == "forward_dependency":
        value["nodes"][0]["prerequisite_keys"] = ["organizer"]
    elif invalid == "duplicate_key":
        value["nodes"][1]["key"] = "paths"
    elif invalid == "empty_nodes":
        value["nodes"] = []
    elif invalid == "wrong_type":
        value["nodes"][0]["estimated_minutes"] = True
    elif invalid == "no_assumptions":
        value["assumptions"] = []
    else:
        value["actor_id"] = str(uuid4())
    accepted = submit(setup_planner, session)
    run(setup_planner, accepted.run_id, value)
    tutor, _, _ = setup_planner
    result = tutor.get(session.token, accepted.run_id)
    assert result.status == "failed" and result.error_code == "invalid_plan_output"
    assert workflow.snapshot(session.token).plans == []
    assert records(database, accepted.run_id)[0]["status"] == "result_recorded"
    assert not records(database, accepted.run_id)[0]["applied"]


def test_source_grounding_rejects_fabricated_refs_and_confirmation_requires_current_source(
    database,
    workflow,
    session,
    setup_planner,
):
    tutor, _, conversation = setup_planner
    knowledge = KnowledgeWorkflow(database)
    source = knowledge.create(
        session.token,
        conversation.goal_id,
        str(uuid4()),
        SourceInput(
            title="Owned pathlib excerpt",
            source_url="https://owned.invalid/pathlib",
            excerpt="Path.iterdir yields directory children.",
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
    bad = submit(setup_planner, session)
    run(setup_planner, bad.run_id, document(sources=[{"source_id": str(uuid4()), "revision": 1}]))
    assert tutor.get(session.token, bad.run_id).error_code == "invalid_plan_output"
    assert workflow.snapshot(session.token).plans == []
    good = submit(setup_planner, session)
    run(
        setup_planner, good.run_id, document(sources=[{"source_id": str(source.id), "revision": 1}])
    )
    plan = workflow.snapshot(session.token).plans[0]
    assert plan.latest.sources[0].excerpt == source.excerpt
    knowledge.revoke(session.token, source.id, 1)
    with pytest.raises(BusinessError) as error:
        tutor.confirm_plan(session.token, plan.id, 1)
    assert error.value.code == "source_not_current"
    assert tutor.plan(session.token, plan.id).active is None


def test_planner_unknown_and_late_result_reuse_same_native_runtime_without_resend(
    database,
    workflow,
    session,
    setup_planner,
):
    tutor, settings, _ = setup_planner
    accepted = submit(setup_planner, session)
    seen = []

    def timeout(request):
        seen.append(request)
        raise httpx.ReadTimeout("owned lost receipt")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(accepted.run_id)
    loop.run(accepted.run_id)
    assert len(seen) == 1 and tutor.get(session.token, accepted.run_id).status == "blocked_unknown"
    with pytest.raises(BusinessError) as error:
        tutor.resume(session.token, accepted.run_id)
    assert error.value.code == "unknown_unresolved"
    tutor.record(
        records(database, accepted.run_id)[0]["id"],
        Receipt(body=provider_body(document()), http_status=200),
    )
    assert tutor.get(session.token, accepted.run_id).can_resume
    tutor.resume(session.token, accepted.run_id)
    loop.run(accepted.run_id)
    assert len(seen) == 1 and tutor.get(session.token, accepted.run_id).status == "succeeded"
    assert len(workflow.snapshot(session.token).plans) == 1


def test_recorded_plan_recovers_after_worker_disappears_without_new_request(
    database,
    workflow,
    session,
    setup_planner,
):
    tutor, settings, _ = setup_planner
    accepted = submit(setup_planner, session)
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    model = ChatCompletionsGateway(settings)
    call = tutor.prepare(
        lease,
        model.endpoint,
        model.request(
            role.messages,
            require_tool=False,
            allowed_tools=(),
            json_output=True,
        ),
    )
    assert tutor.dispatch(lease, call.id)
    tutor.record(call.id, Receipt(body=provider_body(document()), http_status=200))
    expire(database, accepted.run_id)
    sent = run(setup_planner, accepted.run_id, document())
    assert sent == [] and len(workflow.snapshot(session.token).plans) == 1


def test_cancelled_planner_keeps_late_result_without_creating_plan(
    database, workflow, session, setup_planner
):
    tutor, settings, _ = setup_planner
    accepted = submit(setup_planner, session)

    def cancel(_):
        tutor.cancel(session.token, accepted.run_id)
        return httpx.Response(200, content=provider_body(document()))

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(cancel))).run(
        accepted.run_id
    )
    assert tutor.get(session.token, accepted.run_id).status == "cancelled"
    assert records(database, accepted.run_id)[0]["status"] == "result_recorded"
    assert workflow.snapshot(session.token).plans == []


def test_planning_http_ownership_no_model_fallback_and_schema(
    database, workflow, session, setup_planner
):
    tutor, settings, conversation = setup_planner
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
    body = {"text": "Propose a route", "expected_revision": 0}
    assert (
        client.post(
            f"/v1/conversations/{conversation.id}/plan-requests", headers=headers, json=body
        ).status_code
        == 503
    )
    assert workflow.snapshot(session.token).plans == []
    accepted = submit(setup_planner, session)
    run(setup_planner, accepted.run_id, document())
    plan = workflow.snapshot(session.token).plans[0]
    other = workflow.create_session("Other planner")
    assert (
        client.get(
            f"/v1/plans/{plan.id}", headers={"Authorization": "Bearer " + other.token}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/plans/{plan.id}/confirm", headers=headers, json={"expected_revision": 1}
        ).json()["active"]["revision"]
        == 1
    )
    assert len(client.get(f"/v1/plans/{plan.id}/revisions", headers=headers).json()) == 1


def test_plan_json_contract_does_not_accept_cycles_or_blank_objectives():
    value = document()
    value["nodes"][0]["objective"] = "   "
    with pytest.raises(ValidationError):
        PlanDocument.model_validate_json(json.dumps(value), strict=True)


def test_planner_cannot_invoke_even_the_teaching_read_tool(
    database, workflow, session, setup_planner
):
    tutor, settings, _ = setup_planner
    accepted = submit(setup_planner, session)
    content = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "injected",
                            "type": "function",
                            "function": {"name": "learning_get_context", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    AgentLoop(
        tutor,
        ChatCompletionsGateway(
            settings,
            httpx.MockTransport(lambda _: httpx.Response(200, json=content)),
        ),
    ).run(accepted.run_id)
    assert tutor.get(session.token, accepted.run_id).error_code == "tool_not_allowed"
    assert workflow.snapshot(session.token).plans == []
    assert records(database, accepted.run_id)[0]["status"] == "result_recorded"


@pytest.mark.parametrize("revoke", ["session", "source"])
def test_planning_receipt_survives_revocation_but_no_route_is_saved(
    database,
    workflow,
    session,
    setup_planner,
    revoke,
):
    tutor, settings, conversation = setup_planner
    knowledge = KnowledgeWorkflow(database)
    source = knowledge.create(
        session.token,
        conversation.goal_id,
        str(uuid4()),
        SourceInput(
            title="Owned reference",
            source_url="https://owned.invalid/reference",
            excerpt="Owned excerpt",
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
    accepted = submit(setup_planner, session)

    def handle(_):
        if revoke == "session":
            with database.transaction() as connection:
                connection.execute(
                    "UPDATE identity.sessions SET revoked_at = now() WHERE actor_id = %s",
                    (session.actor.id,),
                )
        else:
            knowledge.revoke(session.token, source.id, 1)
        return httpx.Response(
            200,
            content=provider_body(
                document(
                    sources=[
                        {
                            "source_id": str(source.id),
                            "revision": 1,
                        }
                    ]
                )
            ),
        )

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle))).run(
        accepted.run_id
    )
    assert records(database, accepted.run_id)[0]["status"] == "result_recorded"
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status, error_code FROM runtime.runs WHERE id = %s",
            (accepted.run_id,),
        ).fetchone()
        assert row == {
            "status": "failed",
            "error_code": "unauthorized" if revoke == "session" else "source_not_current",
        }
        assert not connection.execute(
            "SELECT id FROM learning.plans WHERE actor_id = %s",
            (session.actor.id,),
        ).fetchall()
