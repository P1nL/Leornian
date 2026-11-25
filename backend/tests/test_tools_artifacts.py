import json
import threading
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_teaching_delivery import body, drain, report
from test_teaching_delivery import managed as managed
from test_tutor_runtime import calls, expire
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.contracts import Decision, RoleSpec, ToolCall
from leornian.agent_runtime.gateway import (
    ChatCompletionsGateway,
    ModelProtocolError,
    validate_tools,
)
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.tools import REGISTRY, TEACHING_TOOLS
from leornian.bootstrap.artifacts import ArtifactWorkflow
from leornian.bootstrap.tools import ToolRouter
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.tutor.artifact_contracts import ArtifactRequestInput
from leornian.modules.tutor.artifacts import Artifacts
from leornian.modules.tutor.contracts import TurnInput
from leornian.shared_kernel.errors import BusinessError


def tool_body(name, args, key=None):
    result = body(None, "tool_calls")
    result["choices"][0]["message"]["tool_calls"] = [
        {
            "id": key or str(uuid4()),
            "type": "function",
            "function": {
                "name": name,
                "arguments": args if isinstance(args, str) else json.dumps(args),
            },
        }
    ]
    return result


def artifact_doc(title="Loop notes", count=7):
    return {
        "title": title,
        "sections": [
            {
                "heading": f"Part {i}",
                "text": f"Explain loop step {i}.",
                "code": "print(1)",
                "language": "python",
                "source_refs": [],
            }
            for i in range(count)
        ],
    }


def artifact_provider(settings, reject=0, thinking=False):
    sent, authors, reviews = [], [], []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            result = report(payload, bad=len(reviews) < reject)
            reviews.append(result)
        else:
            assert "tools" not in wire
            result = artifact_doc(f"Loop notes version candidate {len(authors) + 1}")
            authors.append(result)
        response = body(json.dumps(result))
        if thinking:
            response["choices"][0]["message"]["reasoning_content"] = (
                "artifact-review-thought"
                if "Independently review" in wire["messages"][0]["content"]
                else "artifact-author-thought"
            )
        return httpx.Response(200, json=response)

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), sent, authors, reviews


def finish_job(tutor, settings, jobs, token, job, reject=0, thinking=False):
    jobs.reconcile_once()
    job = jobs.job(token, job.id)
    assert job.run_id
    gateway, sent, authors, reviews = artifact_provider(settings, reject, thinking)
    for _ in range(24):
        AgentLoop(tutor, gateway).run(job.run_id)
        state = tutor.get(token, job.run_id)
        if state.status != "queued":
            assert state.status == "succeeded", state
            return jobs.job(token, job.id), sent, authors, reviews
    pytest.fail("Owned artifact fixture did not complete")


def test_registry_is_single_schema_source_and_roles_default_to_no_tools():
    assert RoleSpec(messages=[]).allowed_tools == ()
    for tool in REGISTRY.values():
        assert tool.wire()["function"]["parameters"] == (
            tool.wire_arguments or tool.arguments
        ).model_json_schema()
    decision = Decision(
        tools=[
            ToolCall(
                id="x",
                name="request_teaching_artifact",
                arguments={"command_key": "owned-key", "instruction": "Make notes"},
            )
        ]
    )
    with pytest.raises(ModelProtocolError, match="tool_not_allowed"):
        validate_tools(
            decision, TEACHING_TOOLS, request={"tools": [REGISTRY["learning_get_context"].wire()]}
        )


def test_tools_recover_bad_arguments_dedupe_commands_and_deliver_after_parent(
    managed,
    session,
    workflow,
):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Make loop notes.")
    )
    sent, tool_results = [], []
    sequence = [
        (
            "request_teaching_artifact",
            {"command_key": "loop-notes", "instruction": "Make notes", "actor_id": str(uuid4())},
        ),
        ("request_teaching_artifact", "{"),
        ("request_teaching_artifact", {"command_key": "loop-notes", "instruction": "Make notes"}),
        ("request_teaching_artifact", {"command_key": "loop-notes", "instruction": "Make notes"}),
    ]

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            return httpx.Response(
                200, json=body(json.dumps(report(json.loads(wire["messages"][-1]["content"]))))
            )
        if wire["messages"][-1]["role"] == "tool":
            tool_results.append(json.loads(wire["messages"][-1]["content"]))
        if len(tool_results) < len(sequence):
            name, args = sequence[len(tool_results)]
            return httpx.Response(200, json=tool_body(name, args))
        return httpx.Response(
            200, json=body("Notes are queued for checked delivery, not ready yet.")
        )

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted"
    assert [r["status"] for r in tool_results] == ["rejected", "rejected", "accepted", "accepted"]
    assert tool_results[2]["job_id"] == tool_results[3]["job_id"]
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.artifact_jobs) == 1 and snapshot.artifacts == []
    assert len(snapshot.tool_activities) == 4
    jobs = ArtifactWorkflow(tutor.database, settings)
    job, _, _, _ = finish_job(tutor, settings, jobs, session.token, snapshot.artifact_jobs[0])
    artifact = jobs.get(session.token, job.artifact_id, 1)
    assert len(artifact.document.sections) == 7
    assert workflow.snapshot(session.token).node_progress == []
    assert any(
        turn.assistant_text == artifact.document.model_dump_json()
        for page in workflow.snapshot(session.token).turns
        for turn in page.turns
    )
    public = json.dumps(snapshot.model_dump(mode="json"))
    assert "arguments" not in public and "response_body" not in public


def test_artifacts_checked_repeatedly_append_versions_and_keep_old_content(managed, session):
    tutor, settings, conversation = managed
    jobs = ArtifactWorkflow(tutor.database, settings)
    data = ArtifactRequestInput(instruction="Make loop notes")
    job = jobs.request(session.token, conversation.id, "artifact-create", data)
    assert jobs.request(session.token, conversation.id, "artifact-create", data).id == job.id
    job, sent, _, reviews = finish_job(tutor, settings, jobs, session.token, job, reject=3)
    assert job.status == "accepted" and len(reviews) == 4 and len(sent) == 8
    first = jobs.get(session.token, job.artifact_id, 1)
    revision = ArtifactRequestInput(
        instruction="Improve the examples without dropping any section",
        artifact_id=job.artifact_id,
        expected_revision=1,
    )
    second = jobs.request(session.token, conversation.id, "artifact-revise", revision)
    second, _, _, _ = finish_job(tutor, settings, jobs, session.token, second)
    assert jobs.get(session.token, job.artifact_id, None).revision == 2
    assert jobs.get(session.token, job.artifact_id, 1) == first
    assert jobs.request(session.token, conversation.id, "artifact-revise", revision).id == second.id
    with pytest.raises(BusinessError, match="Read the current artifact"):
        jobs.request(session.token, conversation.id, "stale-revise", revision)
    with tutor.database.transaction() as connection:
        assert len(Artifacts(connection).jobs(workflow_actor(connection, session))) == 2


def workflow_actor(connection, session):
    from leornian.modules.identity.application import Identity
    from leornian.modules.identity.infrastructure import PgIdentityStore

    return Identity(PgIdentityStore(connection)).authenticate(session.token)


def test_http_ownership_immutable_read_and_cancel_queued_job(managed, session, workflow):
    tutor, settings, conversation = managed
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": "http-artifact"}
    result = client.post(
        f"/v1/conversations/{conversation.id}/artifact-requests",
        headers=headers,
        json={"instruction": "Make notes"},
    )
    assert result.status_code == 202
    job = result.json()
    assert client.get(f"/v1/artifacts/{job['artifact_id']}", headers=headers).status_code == 404
    stranger = workflow.create_session("Other learner")
    other = {"Authorization": "Bearer " + stranger.token}
    assert client.get(f"/v1/artifact-jobs/{job['id']}", headers=other).status_code == 404
    cancelled = client.post(f"/v1/artifact-jobs/{job['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    jobs = ArtifactWorkflow(tutor.database, settings)
    jobs.reconcile_once()
    assert jobs.job(session.token, UUID(job["id"])).run_id is None


def test_old_runs_do_not_gain_new_tool_permissions(managed, session):
    original, settings, conversation = managed
    settings = replace(settings, delivery_enabled=False)
    tutor = TutorWorkflow(original.database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Make notes")
    )
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        assert [t["function"]["name"] for t in wire["tools"]] == ["learning_get_context"]
        return httpx.Response(
            200,
            json=tool_body(
                "request_teaching_artifact",
                {"command_key": "not-allowed", "instruction": "Make notes"},
            ),
        )

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle))).run(
        accepted.run_id
    )
    assert tutor.get(session.token, accepted.run_id).error_code == "tool_not_allowed"
    with tutor.database.transaction() as connection:
        assert Artifacts(connection).jobs(workflow_actor(connection, session)) == []


def test_tool_write_and_receipt_application_rollback_and_recover_once(
    managed,
    session,
    monkeypatch,
):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Make notes")
    )
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=tool_body(
                "request_teaching_artifact",
                {"command_key": "atomic-note", "instruction": "Make notes"},
            ),
        )

    original = ArtifactWorkflow.event
    monkeypatch.setattr(
        ArtifactWorkflow,
        "event",
        staticmethod(
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected event rollback"))
        ),
    )
    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    with pytest.raises(RuntimeError, match="event rollback"):
        AgentLoop(tutor, gateway).run(accepted.run_id)
    with tutor.database.transaction() as connection:
        assert Artifacts(connection).jobs(workflow_actor(connection, session)) == []
    assert calls(tutor.database, accepted.run_id)[0]["applied"] is False
    monkeypatch.setattr(ArtifactWorkflow, "event", staticmethod(original))
    expire(tutor.database, accepted.run_id)
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert len(sent) == 1
    with tutor.database.transaction() as connection:
        jobs = Artifacts(connection).jobs(workflow_actor(connection, session))
        assert len(jobs) == 1
    tutor.cancel(session.token, accepted.run_id)
    assert (
        ArtifactWorkflow(tutor.database, settings).job(session.token, jobs[0].id).status
        == "cancelled"
    )


def test_independent_artifact_pages_parallel_reuse_and_private_protocol(
    managed,
    session,
    monkeypatch,
):
    tutor, settings, conversation = managed
    jobs = ArtifactWorkflow(tutor.database, settings)
    job = jobs.request(
        session.token,
        conversation.id,
        "pages-fixture",
        ArtifactRequestInput(instruction="Make loop notes"),
    )
    job, _, _, _ = finish_job(tutor, settings, jobs, session.token, job)
    accepted = tutor.submit(
        session.token,
        conversation.id,
        str(uuid4()),
        TurnInput(text="Compare the first four sections"),
    )
    barrier = threading.Barrier(2)
    dispatches = []
    original = ToolRouter._dispatch

    def dispatch(self, connection, name, args):
        if name == "read_artifact":
            dispatches.append(args.offset)
            barrier.wait(timeout=5)
        return original(self, connection, name, args)

    monkeypatch.setattr(ToolRouter, "_dispatch", dispatch)
    author_calls = 0
    results = []

    def handle(request):
        nonlocal author_calls
        wire = json.loads(request.content)
        if "Independently review" in wire["messages"][0]["content"]:
            return httpx.Response(
                200, json=body(json.dumps(report(json.loads(wire["messages"][-1]["content"]))))
            )
        author_calls += 1
        if author_calls == 1:
            response = body(None, "tool_calls")
            response["choices"][0]["message"]["tool_calls"] = [
                tool_body(
                    "read_artifact",
                    {
                        "artifact_id": str(job.artifact_id),
                        "revision": 1,
                        "offset": offset,
                        "limit": 2,
                    },
                    str(index),
                )["choices"][0]["message"]["tool_calls"][0]
                for index, offset in enumerate([0, 2, 0])
            ]
            return httpx.Response(200, json=response)
        results.extend([json.loads(m["content"]) for m in wire["messages"][-3:]])
        assert all(m["role"] == "tool" for m in wire["messages"][-3:])
        return httpx.Response(200, json=body("The first four sections explain four loop steps."))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert sorted(dispatches) == [0, 2]  # third identical read reuses this batch, not stale cache.
    assert [r["offset"] for r in results] == [0, 2, 0]
    assert [r["next_offset"] for r in results] == [2, 4, 2]
    assert all(r["section_count"] == 7 and r["code_is_inert"] for r in results)
    assert tutor.get(session.token, accepted.run_id).tool_count == 3


def test_cancel_during_artifact_model_request_keeps_receipt_without_new_version(managed, session):
    tutor, settings, conversation = managed
    jobs = ArtifactWorkflow(tutor.database, settings)
    job = jobs.request(
        session.token,
        conversation.id,
        "cancel-artifact",
        ArtifactRequestInput(instruction="Make notes"),
    )
    jobs.reconcile_once()
    job = jobs.job(session.token, job.id)
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        jobs.action(session.token, job.id, "cancel")
        return httpx.Response(200, json=body(json.dumps(artifact_doc())))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    AgentLoop(tutor, gateway).run(job.run_id)
    assert jobs.job(session.token, job.id).status == "cancelled"
    assert len(sent) == 1
    assert calls(tutor.database, job.run_id)[0]["response_body"]
    with pytest.raises(BusinessError, match="Accepted artifact revision not found"):
        jobs.get(session.token, job.artifact_id, 1)
    AgentLoop(tutor, gateway).run(job.run_id)
    assert len(sent) == 1


def test_artifact_tool_cannot_read_another_goal_even_for_the_same_actor(
    managed,
    session,
    workflow,
):
    tutor, settings, conversation = managed
    jobs = ArtifactWorkflow(tutor.database, settings)
    job = jobs.request(
        session.token,
        conversation.id,
        "bound-artifact",
        ArtifactRequestInput(instruction="Make notes"),
    )
    job, _, _, _ = finish_job(tutor, settings, jobs, session.token, job)
    accepted_goal = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Other goal", motivation="")
    )
    with tutor.database.transaction() as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s",
            (accepted_goal.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    other_goal = next(g for g in workflow.snapshot(session.token).goals if g.title == "Other goal")
    other = tutor.conversation(session.token, other_goal.id)
    accepted = tutor.submit(
        session.token, other.id, str(uuid4()), TurnInput(text="Read the other goal's artifact")
    )
    results = []

    def handle(request):
        wire = json.loads(request.content)
        if "Independently review" in wire["messages"][0]["content"]:
            return httpx.Response(
                200, json=body(json.dumps(report(json.loads(wire["messages"][-1]["content"]))))
            )
        if wire["messages"][-1]["role"] != "tool":
            return httpx.Response(
                200,
                json=tool_body(
                    "read_artifact",
                    {"artifact_id": str(job.artifact_id), "revision": 1},
                ),
            )
        results.append(json.loads(wire["messages"][-1]["content"]))
        return httpx.Response(200, json=body("That artifact is outside the selected goal."))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert results[0]["status"] == "rejected" and results[0]["code"] == "not_found"
    assert "sections" not in results[0]


def test_artifact_history_replays_only_author_thought_not_review_or_public_data(
    managed,
    session,
    workflow,
):
    original, settings, conversation = managed
    settings = replace(settings, model_thinking="enabled")
    tutor = TutorWorkflow(original.database, settings)
    jobs = ArtifactWorkflow(tutor.database, settings)
    job = jobs.request(
        session.token,
        conversation.id,
        "thinking-artifact",
        ArtifactRequestInput(instruction="Make notes"),
    )
    job, _, _, _ = finish_job(tutor, settings, jobs, session.token, job, thinking=True)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain the note")
    )
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    private = json.dumps(role.model_dump(mode="json"))
    assert "artifact-author-thought" in private
    assert "artifact-review-thought" not in private
    public = json.dumps(workflow.snapshot(session.token).model_dump(mode="json"))
    assert "artifact-author-thought" not in public and "artifact-review-thought" not in public
    tutor.cancel(session.token, accepted.run_id)


def test_queued_artifacts_behind_active_foreground_do_not_starve_other_conversations(
    managed,
    session,
    workflow,
):
    tutor, settings, conversation = managed
    jobs = ArtifactWorkflow(tutor.database, settings)
    foreground = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Foreground request")
    )
    blocked = [
        jobs.request(
            session.token,
            conversation.id,
            f"blocked-artifact-{i}",
            ArtifactRequestInput(instruction=f"Make note {i}"),
        )
        for i in range(21)
    ]
    accepted_goal = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Ready artifact goal", motivation="")
    )
    with tutor.database.transaction() as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s",
            (accepted_goal.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    goal = next(
        g for g in workflow.snapshot(session.token).goals if g.title == "Ready artifact goal"
    )
    other = tutor.conversation(session.token, goal.id)
    ready = jobs.request(
        session.token, other.id, "ready-artifact", ArtifactRequestInput(instruction="Make notes")
    )
    try:
        jobs.reconcile_once()
        assert jobs.job(session.token, ready.id).run_id is not None
        assert all(jobs.job(session.token, job.id).run_id is None for job in blocked)
    finally:
        tutor.cancel(session.token, foreground.run_id)
        for job in [*blocked, ready]:
            jobs.action(session.token, job.id, "cancel")
