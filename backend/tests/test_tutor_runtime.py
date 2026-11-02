import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from leornian.agent_runtime.contracts import Receipt
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.contracts import AdmitSource, SourceInput, SourceRevision
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.tutor.contracts import TurnInput
from leornian.platform.config import Settings
from leornian.platform.relay import relay_runs_once
from leornian.shared_kernel.errors import BusinessError

pytestmark = pytest.mark.integration


def response(*, tool=True, name="learning_get_context", arguments="{}"):
    message = {
        "role": "assistant",
        "content": None if tool else "Learn pathlib, then list the files.",
    }
    if tool:
        message["tool_calls"] = [
            {
                "id": "context_1",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ]
    return {
        "choices": [{"message": message, "finish_reason": "tool_calls" if tool else "stop"}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 40},
    }


@pytest.fixture
def setup_tutor(database, workflow, session):
    accepted = workflow.submit(
        session.token,
        str(uuid4()),
        GoalInput(title="Python file organizer", motivation="Clean downloads"),
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
        model_base_url="https://provider.invalid/v1",
        model_name="owned-test-model",
        model_api_key="owned-offline-token",
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, goal.id)
    return tutor, settings, conversation


def submit(tutor, session, conversation, key=None):
    return tutor.submit(
        session.token,
        conversation.id,
        key or str(uuid4()),
        TurnInput(text="Where should I start?"),
    )


def calls(database, run_id):
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


def gateway(settings, sent):
    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=response(tool=len(sent) == 1),
            headers={"x-request-id": "test"},
        )

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle))


def test_complete_native_turn_and_multiturn_history(database, workflow, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    sent = []
    loop = AgentLoop(tutor, gateway(settings, sent))
    loop.run(accepted.run_id)
    loop.run(accepted.run_id)
    run = tutor.get(session.token, accepted.run_id)
    assert run.status == "succeeded" and run.tool_count == 1
    assert len(sent) == 2
    assert "Python file organizer" in json.dumps(sent[0])
    tool_message = sent[1]["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "context_1"
    assert json.loads(tool_message["content"])["goal"]["title"] == "Python file organizer"
    snapshot = workflow.snapshot(session.token)
    assert snapshot.turns[0].turns[0].assistant_text == "Learn pathlib, then list the files."
    assert [event.event_type for event in snapshot.events][-4:] == [
        "tutor.queued",
        "tutor.running",
        "tutor.tool_completed",
        "tutor.succeeded",
    ]
    records = calls(database, run.id)
    assert all(record["status"] == "result_recorded" and record["applied"] for record in records)
    assert all(record["usage"]["completion_tokens"] == 40 for record in records)
    assert "owned-offline-token" not in json.dumps(records, default=str)
    second = submit(tutor, session, conversation)
    sent2 = []
    AgentLoop(tutor, gateway(settings, sent2)).run(second.run_id)
    assert any(
        message.get("content") == "Learn pathlib, then list the files."
        for message in sent2[0]["messages"]
    )


def test_tutor_reads_confirmed_lesson_and_versioned_material(
    database, workflow, session, setup_tutor
):
    tutor, settings, conversation = setup_tutor
    journey = JourneyWorkflow(database)
    track = journey.draft(session.token, conversation.goal_id)
    journey.confirm(session.token, track.id, 1)
    knowledge = KnowledgeWorkflow(database)
    source = knowledge.create(
        session.token,
        conversation.goal_id,
        str(uuid4()),
        SourceInput(
            title="Owned loop material",
            source_url="https://owned.invalid/loops",
            excerpt="Owned loop excerpt",
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
    accepted = submit(tutor, session, conversation)
    sent = []
    AgentLoop(tutor, gateway(settings, sent)).run(accepted.run_id)
    assert tutor.get(session.token, accepted.run_id).status == "succeeded"
    context = json.loads(sent[1]["messages"][-1]["content"])
    assert context["plan"]["status"] == "confirmed" and context["lesson"]["title"]
    assert context["materials"][0]["revision"] == 1
    assert context["materials"][0]["source_id"] == str(source.id)
    assert "execution_inputs" not in json.dumps(context) and "expected" not in context["exercise"]


@pytest.mark.parametrize("invalidate", ["revoke", "revise", "expire"])
def test_bound_source_invalidation_stops_before_external_dispatch(
    database, session, setup_tutor, invalidate
):
    tutor, settings, conversation = setup_tutor
    knowledge = KnowledgeWorkflow(database)
    source = knowledge.create(
        session.token,
        conversation.goal_id,
        str(uuid4()),
        SourceInput(
            title="Current source",
            source_url="https://owned.invalid/current",
            excerpt="Current excerpt",
        ),
    )
    knowledge.admit(
        session.token,
        source.id,
        AdmitSource(expected_revision=1, valid_until=datetime.now(UTC) + timedelta(days=1)),
    )
    accepted = submit(tutor, session, conversation)
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    model = gateway(settings, [])
    call = tutor.prepare(lease, model.endpoint, model.request(role.messages, require_tool=True))
    if invalidate == "revoke":
        knowledge.revoke(session.token, source.id, 1)
    elif invalidate == "revise":
        knowledge.revise(
            session.token,
            source.id,
            SourceRevision(
                expected_revision=1,
                title=source.title,
                source_url=source.source_url,
                excerpt="Changed excerpt",
            ),
        )
    else:
        with database.transaction() as connection:
            connection.execute(
                "UPDATE knowledge.sources SET valid_until = now() - interval '1 second' "
                "WHERE id = %s",
                (source.id,),
            )
    assert not tutor.dispatch(lease, call.id)
    run = tutor.get(session.token, accepted.run_id)
    assert run.status == "failed" and run.error_code == "source_not_current"
    assert calls(database, accepted.run_id)[0]["status"] == "not_sent"


def test_source_revoked_during_request_preserves_receipt_without_teaching_side_effects(
    database,
    session,
    setup_tutor,
):
    tutor, settings, conversation = setup_tutor
    knowledge = KnowledgeWorkflow(database)
    source = knowledge.create(
        session.token,
        conversation.goal_id,
        str(uuid4()),
        SourceInput(
            title="Bound source",
            source_url="https://owned.invalid/bound",
            excerpt="Bound excerpt",
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
    accepted = submit(tutor, session, conversation)
    sent = []

    def handle(request):
        sent.append(request)
        knowledge.revoke(session.token, source.id, 1)
        return httpx.Response(200, json=response())

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle))).run(
        accepted.run_id
    )
    run = tutor.get(session.token, accepted.run_id)
    assert run.status == "failed" and run.error_code == "source_not_current" and run.tool_count == 0
    records = calls(database, accepted.run_id)
    assert (
        len(sent) == 1 and records[0]["status"] == "result_recorded" and not records[0]["applied"]
    )


def test_parallel_duplicate_turns_and_queue_wakeups(database, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: submit(tutor, session, conversation, key), range(3)))
    assert len({result.run_id for result in results}) == 1
    with pytest.raises(BusinessError) as problem:
        tutor.submit(session.token, conversation.id, key, TurnInput(text="Different message"))
    assert problem.value.code == "idempotency_conflict"
    sent = []
    loop = AgentLoop(tutor, gateway(settings, sent))
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(lambda _: loop.run(results[0].run_id), range(3)))
    assert len(sent) == 2
    assert tutor.get(session.token, results[0].run_id).status == "succeeded"


def test_current_session_revocation_prevents_dispatch(database, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE identity.sessions SET revoked_at = now() WHERE actor_id = %s",
            (session.actor.id,),
        )
    sent = []
    AgentLoop(tutor, gateway(settings, sent)).run(accepted.run_id)
    assert sent == [] and calls(database, accepted.run_id) == []
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT status, error_code FROM runtime.runs WHERE id = %s",
            (accepted.run_id,),
        ).fetchone() == {"status": "failed", "error_code": "unauthorized"}


@pytest.mark.parametrize(
    "name,arguments,code",
    [
        ("item_bank_publish", "{}", "tool_not_allowed"),
        ("learning_get_context", '{"actor_id":"other"}', "invalid_tool_arguments"),
        ("learning_get_context", '{"goal_id":"other"}', "invalid_tool_arguments"),
    ],
)
def test_untrusted_tool_cannot_choose_owner_or_business_write(
    database,
    session,
    setup_tutor,
    name,
    arguments,
    code,
):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json=response(name=name, arguments=arguments),
        )
    )
    AgentLoop(tutor, ChatCompletionsGateway(settings, transport)).run(accepted.run_id)
    result = tutor.get(session.token, accepted.run_id)
    assert result.status == "failed" and result.error_code == code and result.tool_count == 0
    assert calls(database, accepted.run_id)[0]["status"] == "result_recorded"


def test_response_timeout_stays_unknown_without_automatic_retry(database, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    sent = []

    def timeout(request):
        sent.append(request)
        raise httpx.ReadTimeout("upstream receipt lost")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(accepted.run_id)
    loop.run(accepted.run_id)
    assert len(sent) == 1
    assert tutor.get(session.token, accepted.run_id).status == "blocked_unknown"
    assert calls(database, accepted.run_id)[0]["status"] == "unknown"
    with pytest.raises(BusinessError) as problem:
        tutor.resume(session.token, accepted.run_id)
    assert problem.value.code == "unknown_unresolved"
    with pytest.raises(BusinessError) as problem:
        submit(tutor, session, conversation)
    assert problem.value.code == "run_active"


def test_lost_worker_after_dispatch_and_late_receipt_require_explicit_resume(
    database,
    session,
    setup_tutor,
):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    model = ChatCompletionsGateway(settings)
    prepared = tutor.prepare(lease, model.endpoint, model.request(role.messages, require_tool=True))
    assert tutor.dispatch(lease, prepared.id)
    expire(database, accepted.run_id)
    sent = []
    loop = AgentLoop(tutor, gateway(settings, sent))
    loop.run(accepted.run_id)
    assert tutor.get(session.token, accepted.run_id).status == "blocked_unknown" and not sent
    tutor.record(prepared.id, Receipt(body=json.dumps(response()), http_status=200))
    assert tutor.get(session.token, accepted.run_id).can_resume
    loop.run(accepted.run_id)
    assert not sent
    tutor.resume(session.token, accepted.run_id)
    final_transport = httpx.MockTransport(
        lambda request: (
            sent.append(json.loads(request.content))
            or httpx.Response(200, json=response(tool=False))
        )
    )
    AgentLoop(tutor, ChatCompletionsGateway(settings, final_transport)).run(accepted.run_id)
    assert len(sent) == 1 and tutor.get(session.token, accepted.run_id).status == "succeeded"
    assert len(calls(database, accepted.run_id)) == 2


def test_recorded_result_recovery_does_not_repeat_the_same_call(database, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    model = ChatCompletionsGateway(settings)
    prepared = tutor.prepare(lease, model.endpoint, model.request(role.messages, require_tool=True))
    tutor.dispatch(lease, prepared.id)
    tutor.record(prepared.id, Receipt(body=json.dumps(response()), http_status=200))
    expire(database, accepted.run_id)
    sent = []
    transport = httpx.MockTransport(
        lambda request: (
            sent.append(json.loads(request.content))
            or httpx.Response(200, json=response(tool=False))
        )
    )
    AgentLoop(tutor, ChatCompletionsGateway(settings, transport)).run(accepted.run_id)
    assert len(sent) == 1 and sent[0]["messages"][-1]["role"] == "tool"
    assert tutor.get(session.token, accepted.run_id).status == "succeeded"


def test_cancel_during_request_records_late_result_without_running_tools(
    database,
    workflow,
    session,
    setup_tutor,
):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)

    def cancel_inflight(_request):
        assert tutor.cancel(session.token, accepted.run_id).status == "cancelled"
        return httpx.Response(200, json=response())

    AgentLoop(
        tutor,
        ChatCompletionsGateway(
            settings,
            httpx.MockTransport(cancel_inflight),
        ),
    ).run(accepted.run_id)
    record = calls(database, accepted.run_id)[0]
    assert record["status"] == "result_recorded" and not record["applied"]
    run = tutor.get(session.token, accepted.run_id)
    assert run.status == "cancelled" and run.tool_count == 0 and not run.can_resume
    assert workflow.snapshot(session.token).turns[0].turns[0].assistant_text is None


def test_lease_loss_fences_old_worker_and_current_session_blocks_tools(
    database,
    session,
    setup_tutor,
):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    sent = []

    def revoke_before_tool(request):
        sent.append(request)
        with database.transaction() as connection:
            connection.execute(
                "UPDATE identity.sessions SET revoked_at = now() WHERE actor_id = %s",
                (session.actor.id,),
            )
        return httpx.Response(200, json=response())

    AgentLoop(
        tutor,
        ChatCompletionsGateway(
            settings,
            httpx.MockTransport(revoke_before_tool),
        ),
    ).run(accepted.run_id)
    assert len(sent) == 1
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM runtime.tool_invocations WHERE run_id = %s",
                (accepted.run_id,),
            ).fetchone()["count"]
            == 0
        )
    assert calls(database, accepted.run_id)[0]["status"] == "result_recorded"


def test_prepared_but_unsent_work_can_be_recovered(database, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    old = tutor.claim(accepted.run_id)
    role = tutor.context(old)
    model = ChatCompletionsGateway(settings)
    prepared = tutor.prepare(old, model.endpoint, model.request(role.messages, require_tool=True))
    expire(database, accepted.run_id)
    new = tutor.claim(accepted.run_id)
    assert new.token != old.token and not tutor.dispatch(old, prepared.id)
    expire(database, accepted.run_id)
    sent = []
    AgentLoop(tutor, gateway(settings, sent)).run(accepted.run_id)
    assert len(sent) == 2 and tutor.get(session.token, accepted.run_id).status == "succeeded"


@pytest.mark.parametrize(
    "status,body,expected,code",
    [
        (401, {"error": "rejected"}, "failed", "provider_rejected"),
        (503, {"error": "upstream unavailable"}, "blocked_unknown", "external_result_unknown"),
        (200, {"bad": "not a valid model response"}, "failed", "invalid_model_response"),
        (200, response(tool=False), "failed", "required_tool_missing"),
    ],
)
def test_provider_receipts_are_separate_from_business_success(
    session,
    setup_tutor,
    status,
    body,
    expected,
    code,
):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    AgentLoop(tutor, ChatCompletionsGateway(settings, transport)).run(accepted.run_id)
    result = tutor.get(session.token, accepted.run_id)
    assert result.status == expected and result.error_code == code


def test_http_availability_ownership_and_no_fake_reply(database, workflow, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    unavailable = TestClient(create_app(replace(settings, model_enabled=False)))
    headers = {"Authorization": f"Bearer {session.token}", "Idempotency-Key": str(uuid4())}
    assert unavailable.get("/v1/tutor/availability", headers=headers).json()["ready"] is False
    refused = unavailable.post(
        f"/v1/conversations/{conversation.id}/turns",
        headers=headers,
        json={"text": "Teach me"},
    )
    assert refused.status_code == 503 and refused.json()["code"] == "model_unavailable"
    assert workflow.snapshot(session.token).turns[0].turns == []
    client = TestClient(create_app(settings))
    accepted = client.post(
        f"/v1/conversations/{conversation.id}/turns",
        headers=headers,
        json={"text": "Teach me"},
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    other = workflow.create_session("Other learner")
    other_headers = {"Authorization": f"Bearer {other.token}"}
    assert client.get(f"/v1/runs/{run_id}", headers=other_headers).status_code == 404
    assert client.post(f"/v1/runs/{run_id}/cancel", headers=other_headers).status_code == 404
    assert client.post(f"/v1/runs/{run_id}/resume", headers=other_headers).status_code == 404
    assert client.get("/v1/snapshot", headers=other_headers).json()["runs"] == []
    assert (
        client.post(
            "/v1/conversations",
            headers=other_headers,
            json={
                "goal_id": str(conversation.goal_id),
            },
        ).status_code
        == 404
    )
    assert client.post(f"/v1/runs/{run_id}/cancel", headers=headers).json()["status"] == "cancelled"


def test_relay_only_coordinates_queued_or_expired_runs(database, session, setup_tutor):
    tutor, settings, conversation = setup_tutor
    accepted = submit(tutor, session, conversation)
    # This persistent test DB may have >50 old queued fixtures. Age only our owned
    # run into the bounded relay batch; do not drain/cancel/rewrite historical runs.
    with database.transaction() as connection:
        connection.execute(
            "UPDATE runtime.runs SET created_at=(SELECT min(created_at) FROM runtime.runs) "
            "- interval '1 second' WHERE id=%s",
            (accepted.run_id,),
        )
    published = []
    relay_runs_once(database, published.append)
    assert accepted.run_id in published
    lease = tutor.claim(accepted.run_id)
    assert lease is not None
    published.clear()
    relay_runs_once(database, published.append, seconds=0)
    assert accepted.run_id not in published
    expire(database, accepted.run_id)
    relay_runs_once(database, published.append, seconds=0)
    assert accepted.run_id in published
