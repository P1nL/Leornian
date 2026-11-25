import asyncio
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_dynamic_plans import document
from test_generated_lessons import lesson_setup as lesson_setup
from test_streaming_learning import frames
from test_tutor_runtime import calls, expire
from test_tutor_runtime import response as tool_response
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.contracts import Receipt, RoleSpec
from leornian.agent_runtime.gateway import ChatCompletionsGateway, DeliveryUnknown
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.policies import estimate_tokens, fit_optional_history, resolve_policy
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.contracts import AdmitSource, SourceInput, SourceRevision
from leornian.modules.learning.contracts import LessonRequestInput
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.contracts import PlanningInput, TeachingFocus, TurnInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def managed(setup_tutor):
    old, settings, conversation = setup_tutor
    settings = replace(
        settings,
        delivery_enabled=True,
        model_context_tokens=128000,
        model_max_output_tokens=32768,
        heartbeat_seconds=0.02,
    )
    return TutorWorkflow(old.database, settings), settings, conversation


def body(text, finish="stop"):
    return {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 150, "completion_tokens": 100},
    }


def report(payload, bad=False):
    return {
        "candidate_call_id": payload["candidate_call_id"],
        "verdict": "changes_required" if bad else "accepted",
        "checks": [
            {
                "code": code,
                "verdict": "changes_required" if bad else "accepted",
                "issues": [
                    {
                        "code": "missing_objective",
                        "target_ref": "candidate",
                        "evidence_ref": "request",
                        "repair_instruction": "Address the requested objective.",
                    }
                ]
                if bad
                else [],
            }
            for code in payload["required_checks"]
        ],
    }


def provider(settings, author="Use pathlib.Path.iterdir to list entries.", reject=0):
    sent = []
    reviews = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            result = report(payload, bad=len(reviews) < reject)
            reviews.append(result)
            return httpx.Response(200, json=body(json.dumps(result)))
        result = author(len(sent)) if callable(author) else author
        return httpx.Response(200, json=body(result))

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), sent, reviews


def test_provider_stream_commits_thinking_events_and_delivers_the_reply(managed, session, workflow):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    gateway, sent, _ = provider(settings)
    original_transport = gateway.transport

    def stream(request):
        result = original_transport.handle_request(request).json()
        choice = result["choices"][0]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=frames(
            {"delta": {"reasoning_content":
                       "private-provider-thinking\n先说明路径与目录的区别，再给出可复现的例子。\n"}},
            {"delta": {"content": choice["message"]["content"]}},
            {"delta": {}, "finish_reason": choice["finish_reason"]},
        ))

    gateway.transport = httpx.MockTransport(stream)
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    snapshot = workflow.snapshot(session.token)
    assert any(event.event_type == "tutor.thinking" for event in snapshot.events)
    assert snapshot.turns[0].turns[0].assistant_text.startswith("Use pathlib")
    assert snapshot.turns[0].turns[0].thinking_text.strip() == (
        "先说明路径与目录的区别，再给出可复现的例子。"
    )
    history = tutor.turn_history(session.token, conversation.id)
    assert history[0].thinking_text == snapshot.turns[0].turns[0].thinking_text
    steps = history[0].thinking_steps
    assert [step.kind for step in steps] == ["thinking", "review"]
    assert len({step.id for step in steps}) == 2
    assert all(step.status == "completed" and step.duration_ms is not None for step in steps)
    assert steps[0].detail.strip() == history[0].thinking_text.strip()
    assert "路径与目录" not in steps[1].detail
    assert snapshot.turns[0].turns[0].thinking_steps == steps
    assert any(
        event.payload.thinking_text and "路径与目录" in event.payload.thinking_text
        for event in snapshot.events
    )
    assert "private-provider-thinking" not in snapshot.model_dump_json()
    other = workflow.create_session("Different learner")
    assert "路径与目录" not in workflow.snapshot(other.token).model_dump_json()
    assert len(sent) == 2 and all(wire["stream"] for wire in sent)


def test_old_accepted_thinking_is_read_only_and_does_not_invoke_the_model(
    managed, session, monkeypatch,
):
    tutor, settings, conversation = managed
    monkeypatch.setattr(tutor, "model_thinking", lambda *_args: None)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    gateway, sent, _ = provider(settings)
    original_transport = gateway.transport

    def stream(request):
        result = original_transport.handle_request(request).json()["choices"][0]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=frames(
            {"delta": {"reasoning_content": "private-provider-thinking\n先区分路径与文件。\n"}},
            {"delta": {"content": result["message"]["content"]}},
            {"delta": {}, "finish_reason": result["finish_reason"]},
        ))

    gateway.transport = httpx.MockTransport(stream)
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    history = tutor.turn_history(session.token, conversation.id)
    assert history[0].thinking_text.strip() == "先区分路径与文件。"
    again = tutor.turn_history(session.token, conversation.id)
    assert again[0].thinking_text == history[0].thinking_text
    assert len(sent) == 2


def drain(tutor, settings, accepted, gateway, token, steps=40):
    for _ in range(steps):
        AgentLoop(tutor, gateway).run(accepted.run_id)
        if tutor.get(token, accepted.run_id).status != "queued":
            return tutor.delivery_task(token, accepted.delivery_task_id)
    pytest.fail("Owned deterministic fixture did not finish")


def test_delivery_requires_independent_review_and_hides_candidate(managed, session, workflow):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    gateway, sent, _ = provider(settings)
    AgentLoop(tutor, gateway).run(accepted.run_id)
    snapshot = workflow.snapshot(session.token)
    assert snapshot.turns[0].turns[0].assistant_text is None
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "checking"
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted" and len(sent) == 2
    assert tutor.get(session.token, accepted.run_id).tool_count == 0
    assert (
        workflow.snapshot(session.token).turns[0].turns[0].assistant_text.startswith("Use pathlib")
    )
    records = calls(tutor.database, accepted.run_id)
    assert [r["policy_snapshot"]["stage"] for r in records] == ["tutor.v1", "delivery_review.v1"]
    assert records[0]["context_manifest"]["focus"]["kind"] == "goal"
    assert "owned-offline-token" not in json.dumps(records, default=str)


def test_teaching_author_and_delivery_check_both_record_thinking(managed, session):
    original, settings, conversation = managed
    settings = replace(
        settings,
        model_thinking="disabled",
        model_stage_thinking='{"tutor.v1":"enabled","delivery_review.v1":"enabled"}',
    )
    tutor = TutorWorkflow(original.database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    gateway, sent, _ = provider(settings)
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted" and len(sent) == 2
    assert all(wire["thinking"] == {"type": "enabled"} for wire in sent)
    assert sent[0]["tools"][0]["function"]["name"] == "learning_get_context"
    assert "tool_choice" not in sent[0]
    assert "tools" not in sent[1] and "tool_choice" not in sent[1]
    records = calls(tutor.database, accepted.run_id)
    assert [r["policy_snapshot"]["stage"] for r in records] == ["tutor.v1", "delivery_review.v1"]
    assert all(r["policy_snapshot"]["thinking"] == "enabled" for r in records)
    assert all(r["applied"] for r in records)


def test_managed_thinking_tool_turn_review_and_next_turn_preserve_private_protocol(
    managed, session, workflow
):
    original, settings, conversation = managed
    settings = replace(settings, model_thinking="enabled")
    tutor = TutorWorkflow(original.database, settings)
    first = tutor.submit(
        session.token,
        conversation.id,
        str(uuid4()),
        TurnInput(text="Please read my selected learning context and explain paths."),
    )
    sent = []
    author_calls = 0

    def handle(request):
        nonlocal author_calls
        wire = json.loads(request.content)
        sent.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            assert "hidden-tool-thought" not in json.dumps(wire)
            assert "hidden-final-thought" not in json.dumps(wire)
            result = body(json.dumps(report(json.loads(wire["messages"][-1]["content"]))))
            result["choices"][0]["message"]["reasoning_content"] = "hidden-review-thought"
            return httpx.Response(200, json=result)
        author_calls += 1
        assert wire["thinking"] == {"type": "enabled"} and "tool_choice" not in wire
        if author_calls == 1:
            result = tool_response()
            message = result["choices"][0]["message"]
            message["content"] = "Reading the selection."
            message["reasoning_content"] = "hidden-tool-thought"
            message["tool_calls"][0]["function"]["arguments"] = "{ \n }"
        else:
            if author_calls == 2:
                assistant, tool = wire["messages"][-2:]
                assert assistant["reasoning_content"] == "hidden-tool-thought"
                assert assistant["content"] == "Reading the selection."
                assert assistant["tool_calls"][0]["function"]["arguments"] == "{ \n }"
                assert tool["tool_call_id"] == "context_1"
                data = json.loads(tool["content"])
                assert data["goal"]["id"] == str(conversation.goal_id)
                assert data["focus"]["kind"] == "goal"
            else:
                # Include BOTH the previous tool reasoning and approved final reasoning.
                assert "hidden-tool-thought" in json.dumps(wire)
                assert "hidden-final-thought" in json.dumps(wire)
                assert "hidden-review-thought" not in json.dumps(wire)
                assert all(
                    "reasoning_content" in m for m in wire["messages"] if m["role"] == "assistant"
                )
            result = body("Use pathlib.Path to inspect the current goal's folder.")
            result["choices"][0]["message"]["reasoning_content"] = "hidden-final-thought"
        result["usage"] = {
            "prompt_tokens": 250,
            "completion_tokens": 120,
            "completion_tokens_details": {"reasoning_tokens": 100},
        }
        return httpx.Response(200, json=result)

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    assert drain(tutor, settings, first, gateway, session.token).status == "accepted"
    assert tutor.get(session.token, first.run_id).tool_count == 1
    records = calls(tutor.database, first.run_id)
    assert len(records) == 3 and all(r["status"] == "result_recorded" for r in records)
    assert records[0]["usage"]["completion_tokens_details"]["reasoning_tokens"] == 100
    steps = tutor.turn_history(session.token, conversation.id)[0].thinking_steps
    assert [step.kind for step in steps] == ["thinking", "tool", "thinking", "review"]
    assert steps[1].tool_name == "learning_get_context"
    assert steps[1].duration_ms is not None
    assert len({step.id for step in steps}) == 4
    assert all(step.status == "completed" for step in steps)
    second = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Give a brief reminder.")
    )
    assert drain(tutor, settings, second, gateway, session.token).status == "accepted"
    assert len(sent) == 5
    public = workflow.snapshot(session.token).model_dump_json()
    assert all(
        value not in public
        for value in (
            "hidden-tool-thought",
            "hidden-final-thought",
            "hidden-review-thought",
            "reasoning_content",
        )
    )


def test_recorded_thinking_tool_receipt_recovers_once_and_freezes_tool_turn_policy(
    managed, session
):
    original, settings, conversation = managed
    settings = replace(settings, model_thinking="enabled")
    tutor = TutorWorkflow(original.database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    gateway = ChatCompletionsGateway(settings)
    policy = gateway.policy(role)
    request = gateway.request(role.messages, require_tool=False, policy=policy)
    prepared = tutor.prepare(lease, gateway.endpoint, request, policy, role.context_manifest)
    assert tutor.dispatch(lease, prepared.id)
    result = tool_response()
    result["choices"][0]["message"]["reasoning_content"] = "private-recovered-tool"
    raw = json.dumps(result)
    tutor.record(prepared.id, Receipt(body=raw, http_status=200))
    expire(tutor.database, accepted.run_id)
    changed = replace(settings, model_thinking="disabled", model_max_output_tokens=65536)
    recovered = TutorWorkflow(tutor.database, changed)
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            return httpx.Response(
                200, json=body(json.dumps(report(json.loads(wire["messages"][-1]["content"]))))
            )
        assert wire["thinking"] == {"type": "enabled"}
        assert wire["max_tokens"] == 32768
        assert wire["messages"][-2]["reasoning_content"] == "private-recovered-tool"
        result = body("Use pathlib.Path for the selected goal.")
        result["choices"][0]["message"]["reasoning_content"] = "private-recovered-final"
        return httpx.Response(200, json=result)

    gateway = ChatCompletionsGateway(changed, httpx.MockTransport(handle))
    assert drain(recovered, changed, accepted, gateway, session.token).status == "accepted"
    assert len(sent) == 2
    assert recovered.get(session.token, accepted.run_id).tool_count == 1
    records = calls(tutor.database, accepted.run_id)
    assert records[0]["response_body"] == raw and records[0]["request"] == request
    assert records[0]["policy_snapshot"] == policy


@pytest.mark.parametrize("outcome", ["timeout", "cancel"])
def test_thinking_tools_unknown_or_cancel_does_not_replay_or_apply_tools(managed, session, outcome):
    original, settings, conversation = managed
    settings = replace(settings, model_thinking="enabled")
    tutor = TutorWorkflow(original.database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Read the selected context.")
    )
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        if outcome == "timeout":
            raise httpx.ReadTimeout("Owned thinking transport loss")
        tutor.cancel(session.token, accepted.run_id)
        result = tool_response()
        result["choices"][0]["message"]["reasoning_content"] = "private-late-thinking"
        return httpx.Response(200, json=result)

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle)))
    loop.run(accepted.run_id)
    loop.run(accepted.run_id)
    run = tutor.get(session.token, accepted.run_id)
    assert run.status == ("blocked_unknown" if outcome == "timeout" else "cancelled")
    assert len(sent) == 1 and run.tool_count == 0
    record = calls(tutor.database, accepted.run_id)[0]
    assert not record["applied"]
    assert record["status"] == ("unknown" if outcome == "timeout" else "result_recorded")
    steps = tutor.turn_history(session.token, conversation.id)[0].thinking_steps
    assert len(steps) == 1
    assert steps[0].status == ("unknown" if outcome == "timeout" else "cancelled")
    assert not steps[0].detail


def test_reasoning_only_truncation_never_becomes_format_repair_content(managed, session):
    original, settings, conversation = managed
    settings = replace(settings, model_thinking="enabled")
    tutor = TutorWorkflow(original.database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    reviews = 0

    def handle(request):
        nonlocal reviews
        wire = json.loads(request.content)
        if "Independently review" not in wire["messages"][0]["content"]:
            return httpx.Response(200, json=body("Use pathlib.Path to represent a path."))
        reviews += 1
        if reviews == 1:
            result = body(None, "length")
            result["choices"][0]["message"]["reasoning_content"] = "private-truncated-reasoning"
            return httpx.Response(200, json=result)
        assert "private-truncated-reasoning" not in json.dumps(wire)
        assert "reasoning_content" not in json.dumps(wire)
        payload = json.loads(wire["messages"][-1]["content"])
        assert payload["format_repair"]["previous_response"] is None
        return httpx.Response(200, json=body(json.dumps(report(payload))))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    records = calls(tutor.database, accepted.run_id)
    assert reviews == 2 and len(records) == 3
    assert "private-truncated-reasoning" in records[1]["response_body"]
    assert all(r["applied"] for r in records)


def test_fifth_revision_continues_same_task_and_preserves_negative_checks(managed, session):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    gateway, sent, reviews = provider(
        settings,
        author=lambda i: f"Revised explanation {i}: use pathlib to inspect entries.",
        reject=4,
    )
    AgentLoop(tutor, gateway).run(accepted.run_id)
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert (
        tutor.delivery_task(session.token, accepted.delivery_task_id).repair_strategy
        == "diagnostic"
    )
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted" and result.revision == 5
    assert result.repair_strategy == "redesign" and len(sent) == 10
    assert [r["verdict"] for r in reviews] == ["changes_required"] * 4 + ["accepted"]
    with tutor.database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) n FROM tutor.delivery_checks WHERE task_id=%s",
                (result.id,),
            ).fetchone()["n"]
            == 5
        )


def test_complete_truncated_receipt_is_new_call_not_unknown(managed, session):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    good, _, _ = provider(settings)
    first = ChatCompletionsGateway(
        settings,
        httpx.MockTransport(lambda request: httpx.Response(200, json=body("Partial", "length"))),
    )
    AgentLoop(tutor, first).run(accepted.run_id)
    assert tutor.get(session.token, accepted.run_id).status == "queued"
    result = drain(tutor, settings, accepted, good, session.token)
    records = calls(tutor.database, accepted.run_id)
    assert result.status == "accepted" and len(records) == 3
    assert records[0]["finish_reason"] == "length" and records[0]["applied"]
    assert records[1]["policy_snapshot"]["max_output_tokens"] == 32768


def test_unknown_review_never_resends_and_late_receipt_uses_original_phase(managed, session):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    good, _, _ = provider(settings)
    AgentLoop(tutor, good).run(accepted.run_id)
    captured = []

    def lost(request):
        captured.append(json.loads(request.content))
        raise httpx.ReadTimeout("unknown", request=request)

    bad = ChatCompletionsGateway(settings, httpx.MockTransport(lost))
    AgentLoop(tutor, bad).run(accepted.run_id)
    AgentLoop(tutor, bad).run(accepted.run_id)
    assert len(captured) == 1
    with pytest.raises(BusinessError, match="No complete receipt"):
        tutor.resume_delivery(session.token, accepted.delivery_task_id)
    call = calls(tutor.database, accepted.run_id)[-1]
    payload = json.loads(captured[0]["messages"][-1]["content"])
    tutor.record(
        call["id"], Receipt(body=json.dumps(body(json.dumps(report(payload)))), http_status=200)
    )
    tutor.resume_delivery(session.token, accepted.delivery_task_id)
    result = drain(tutor, settings, accepted, bad, session.token)
    assert result.status == "accepted" and len(captured) == 1


def test_cancel_during_review_records_receipt_without_publishing(managed, session, workflow):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    good, _, _ = provider(settings)
    AgentLoop(tutor, good).run(accepted.run_id)

    def cancel(request):
        tutor.cancel_delivery(session.token, accepted.delivery_task_id)
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        return httpx.Response(200, json=body(json.dumps(report(payload))))

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(cancel))).run(
        accepted.run_id
    )
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "cancelled"
    assert calls(tutor.database, accepted.run_id)[-1]["response_body"]
    assert workflow.snapshot(session.token).turns[0].turns[0].assistant_text is None


def test_long_request_heartbeat_keeps_lease_and_fences_old_worker(managed, session):
    tutor, settings, conversation = managed
    settings = replace(settings, run_lease_seconds=1)
    tutor = TutorWorkflow(tutor.database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )

    def slow(request):
        time.sleep(1.1)
        assert tutor.claim(accepted.run_id) is None
        return httpx.Response(200, json=body("A complete explanation."))

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(slow))).run(
        accepted.run_id
    )
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "checking"
    with tutor.database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT heartbeat_at FROM runtime.runs WHERE id=%s", (accepted.run_id,)
            ).fetchone()["heartbeat_at"]
            is not None
        )


def test_plan_fragments_assemble_more_than_eight_nodes_before_review(managed, session, workflow):
    tutor, settings, conversation = managed
    accepted = tutor.submit_plan(
        session.token,
        conversation.id,
        str(uuid4()),
        PlanningInput(text="Give a twelve-step route.", expected_revision=0),
    )
    pieces = []
    for part in range(2):
        doc = document()
        doc["nodes"] = [
            {
                **document()["nodes"][0],
                "key": f"step_{i}",
                "prerequisite_keys": [f"step_{i - 1}"] if i else [],
            }
            for i in range(part * 6, (part + 1) * 6)
        ]
        pieces.append(json.dumps({"fragment": doc, "complete": part == 1}))
    gateway, _, _ = provider(settings, author=lambda _: pieces.pop(0))
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted"
    plan = workflow.snapshot(session.token).plans[0]
    assert len(plan.latest.document.nodes) == 12 and plan.active is None


def test_node_context_and_more_than_five_lesson_sections(database, workflow, session, lesson_setup):
    old, settings, plan, source, conversation, _ = lesson_setup
    old.confirm_plan(session.token, plan.id, 1)
    settings = replace(
        settings, delivery_enabled=True, model_context_tokens=128000, model_max_output_tokens=32768
    )
    tutor = TutorWorkflow(database, settings)
    accepted = tutor.submit_lesson(
        session.token,
        plan.id,
        str(uuid4()),
        LessonRequestInput(
            expected_plan_revision=1,
            node_key="paths",
            instruction="Cover the objective fully.",
        ),
    )
    lesson = {
        "title": "Inspect paths",
        "introduction": "Read directory entries.",
        "sections": [
            {
                "heading": f"Part {i}",
                "explanation": "Path.iterdir lists direct children.",
                "code_example": "from pathlib import Path\nprint(list(Path('.').iterdir()))",
                "source_refs": [{"source_id": str(source.id), "revision": 1}],
            }
            for i in range(6)
        ],
        "recall_prompts": ["What does iterdir return?"],
    }
    gateway, _, _ = provider(settings, author=json.dumps(lesson))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    saved = workflow.snapshot(session.token).lessons[0]
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="paths", lesson_id=saved.id
    )
    turn = tutor.submit(
        session.token,
        conversation.id,
        str(uuid4()),
        TurnInput(text="Explain this node.", focus=focus),
    )
    model, sent, _ = provider(settings)
    drain(tutor, settings, turn, model, session.token)
    context = json.loads(sent[0]["messages"][1]["content"].split("(data): ", 1)[1])
    assert context["node"]["selected_lesson"]["id"] == str(saved.id)
    assert len(context["node"]["selected_lesson"]["document"]["sections"]) == 6
    with pytest.raises(BusinessError):
        tutor.submit(
            session.token,
            conversation.id,
            str(uuid4()),
            TurnInput(
                text="Wrong binding",
                focus=focus.model_copy(update={"node_key": "other"}),
            ),
        )


def test_http_tasks_and_history_are_owned_and_pageable(managed, session, workflow):
    tutor, settings, conversation = managed
    first = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    model, _, _ = provider(settings)
    drain(tutor, settings, first, model, session.token)
    second = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Next question.")
    )
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {session.token}"}
        page = client.get("/v1/delivery-tasks?limit=1", headers=headers).json()
        assert page[0]["id"] == str(second.delivery_task_id)
        older = client.get(f"/v1/delivery-tasks?before={page[0]['id']}", headers=headers).json()
        assert older[0]["id"] == str(first.delivery_task_id)
        turns = client.get(
            f"/v1/conversations/{conversation.id}/history?limit=1", headers=headers
        ).json()
        assert turns[0]["id"] == str(second.turn_id)
        other = workflow.create_session("Another learner")
        denied = client.get(
            f"/v1/delivery-tasks/{first.delivery_task_id}",
            headers={"Authorization": f"Bearer {other.token}"},
        )
        assert denied.status_code == 404


def test_context_budget_reserves_actual_stage_output_and_preserves_history_order():
    settings = Settings(
        model_name="owned", model_context_tokens=128000, model_max_output_tokens=32768
    )
    policy = resolve_policy(
        settings,
        RoleSpec(messages=[]),
        {
            "context_window": 128000,
            "max_output_tokens": 32768,
        },
    )
    assert policy["input_limit"] == 128000 - 16384 - policy["estimate_margin"]
    request = {
        "messages": [{"role": "system", "content": "Rules"}, {"role": "user", "content": "Now"}]
    }
    history = [
        [
            {"role": "user", "content": f"Question {i}"},
            {"role": "assistant", "content": f"Answer {i}"},
        ]
        for i in range(10)
    ]
    fitted = fit_optional_history(request, history, policy)
    assert fitted["messages"][1]["content"] == "Question 0"
    assert fitted["messages"][-2]["content"] == "Answer 9"
    assert estimate_tokens(fitted) < policy["input_limit"]
    repair = {"role": "user", "content": "Repair the rejected candidate."}
    repaired = fit_optional_history(
        {**request, "messages": request["messages"] + [repair]}, history, policy
    )
    assert repaired["messages"][-2:] == [request["messages"][-1], repair]


def test_real_total_deadline_includes_waiting_for_response_headers():
    settings = Settings(
        model_enabled=True,
        model_base_url="https://owned.invalid",
        model_name="owned",
        model_api_key="offline",
    )

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=body("late"))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(slow))
    started = time.monotonic()
    with pytest.raises(DeliveryUnknown):
        gateway.send(
            gateway.endpoint,
            {"model": "owned"},
            policy={
                "timeout_seconds": 0.03,
                "connect_timeout_seconds": 0.01,
                "response_bytes": 1000,
            },
        )
    assert time.monotonic() - started < 0.5


def test_review_format_repair_preserves_negative_and_identical_candidate_cannot_reroll(
    managed, session
):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    author_count = 0
    review_count = 0

    def handle(request):
        nonlocal author_count, review_count
        wire = json.loads(request.content)
        if "Independently review" in wire["messages"][0]["content"]:
            review_count += 1
            payload = json.loads(wire["messages"][-1]["content"])
            result = report(payload, bad=review_count in {1, 2})
            if review_count == 1:
                result["verdict"] = "bad-format"
            return httpx.Response(200, json=body(json.dumps(result)))
        author_count += 1
        return httpx.Response(
            200,
            json=body(
                "First explanation." if author_count < 3 else "Substantively revised explanation."
            ),
        )

    result = drain(
        tutor,
        settings,
        accepted,
        ChatCompletionsGateway(settings, httpx.MockTransport(handle)),
        session.token,
    )
    assert result.status == "accepted" and result.revision == 2
    assert author_count == 3 and review_count == 3
    assert len(calls(tutor.database, accepted.run_id)) == 6


def test_additional_checks_are_allowed_and_their_negative_findings_reach_the_author(
    managed, session,
):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    authors, reviews = [], []

    def handle(request):
        wire = json.loads(request.content)
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            assert "execution_environment_checks" in payload["required_checks"]
            result = report(payload)
            extra = report({"candidate_call_id": payload["candidate_call_id"],
                            "required_checks": ["supplemental_environment_claim"]},
                           bad=not reviews)["checks"][0]
            result["checks"].append(extra)
            result["verdict"] = extra["verdict"]
            reviews.append(result)
            return httpx.Response(200, json=body(json.dumps(result)))
        authors.append(wire)
        return httpx.Response(200, json=body(
            "Revised sandbox explanation." if len(authors) > 1 else "First explanation."
        ))

    result = drain(tutor, settings, accepted,
                   ChatCompletionsGateway(settings, httpx.MockTransport(handle)), session.token)
    assert result.status == "accepted" and result.revision == 2
    assert len(authors) == len(reviews) == 2
    assert "Address the requested objective" in json.dumps(authors[1])


@pytest.mark.parametrize("omit_negative", [False, True])
def test_no_progress_review_repair_pauses_across_restart_without_reissuing_calls(
    managed, session, workflow, omit_negative,
):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        if "Independently review" not in wire["messages"][0]["content"]:
            return httpx.Response(200, json=body("A complete explanation."))
        payload = json.loads(wire["messages"][-1]["content"])
        result = report(payload)
        if omit_negative:
            if not payload.get("format_repair"):
                extra = report({"candidate_call_id": payload["candidate_call_id"],
                                "required_checks": ["supplemental_environment_claim"]},
                               bad=True)["checks"][0]
                result["checks"].append(extra)
                result["verdict"] = "malformed"
        else:
            result["checks"].pop(0)
        return httpx.Response(200, json=body(json.dumps(result)))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    for _ in range(3):
        tutor = TutorWorkflow(tutor.database, settings)
        AgentLoop(tutor, gateway).run(accepted.run_id)
    task = tutor.delivery_task(session.token, accepted.delivery_task_id)
    assert task.status == "blocked_protocol" and task.can_resume
    assert task.reason_code == "delivery_protocol_stalled" and task.last_progress_at
    assert tutor.get(session.token, accepted.run_id).status == "failed"
    assert workflow.snapshot(session.token).turns[0].turns[0].assistant_text is None
    history = tutor.turn_history(session.token, conversation.id)
    assert history[0].thinking_steps[-1].status == "failed"
    AgentLoop(TutorWorkflow(tutor.database, settings), gateway).run(accepted.run_id)
    assert len(sent) == 3
    if omit_negative:
        with tutor.database.transaction(snapshot=True) as connection:
            issue = connection.execute(
                "SELECT issues FROM tutor.delivery_tasks WHERE id=%s",
                (task.id,),
            ).fetchone()["issues"][0]
        assert issue["frozen_checks"]["supplemental_environment_claim"]["verdict"] == (
            "changes_required"
        )
    else:
        tutor.resume_delivery(session.token, task.id)
        fixed, _, _ = provider(settings)
        assert drain(tutor, settings, accepted, fixed, session.token).status == "accepted"


def test_prepared_call_keeps_frozen_policy_after_configuration_change(managed, session):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    gateway, _, _ = provider(settings)
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    policy = gateway.policy(role)
    request = gateway.request(role.messages, require_tool=False, allowed_tools=(), policy=policy)
    prepared = tutor.prepare(lease, gateway.endpoint, request, policy, role.context_manifest)
    with tutor.database.transaction() as connection:
        connection.execute(
            "UPDATE runtime.runs SET lease_until=now()-interval '1 second' WHERE id=%s",
            (accepted.run_id,),
        )
    changed = replace(settings, model_timeout=0.001, model_context_tokens=256000)
    restarted = TutorWorkflow(tutor.database, changed)
    replay, sent, _ = provider(changed)
    AgentLoop(restarted, replay).run(accepted.run_id)
    current = calls(tutor.database, accepted.run_id)[0]
    assert current["id"] == prepared.id
    assert current["request"] == request and current["policy_snapshot"] == policy
    assert current["policy_snapshot"]["context_window"] == 128000
    assert len(sent) == 1


def test_optional_history_is_not_six_turns_and_audit_does_not_displace_it(managed, session):
    tutor, settings, conversation = managed
    with tutor.database.transaction() as connection:
        for index in range(12):
            connection.execute(
                "INSERT INTO tutor.turns(id,conversation_id,idempotency_key,user_text,"
                "assistant_text,purpose,completed_at) VALUES(%s,%s,%s,%s,%s,%s,now())",
                (
                    uuid4(),
                    conversation.id,
                    str(uuid4()),
                    f"History {index}",
                    f"Explanation {index}",
                    "teaching" if index < 9 else "item_supply",
                ),
            )
    accepted = tutor.submit(
        session.token,
        conversation.id,
        str(uuid4()),
        TurnInput(text="Explain the earlier discussion."),
    )
    gateway, sent, _ = provider(settings)
    drain(tutor, settings, accepted, gateway, session.token)
    text = json.dumps(sent[0]["messages"])
    assert all(f"History {i}" in text for i in range(9))
    assert "History 10" not in text and "History 11" not in text


def test_waiting_input_resumes_same_task_without_replacing_initial_request(managed, session):
    tutor, settings, conversation = managed
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain paths.")
    )
    review_calls = 0

    def handle(request):
        nonlocal review_calls
        wire = json.loads(request.content)
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            result = report(payload, bad=review_calls == 0)
            if review_calls == 0:
                result["verdict"] = "needs_input"
                for check in result["checks"]:
                    check["verdict"] = "needs_input"
            review_calls += 1
            return httpx.Response(200, json=body(json.dumps(result)))
        return httpx.Response(200, json=body("A grounded explanation."))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    waiting = drain(tutor, settings, accepted, gateway, session.token)
    assert waiting.status == "waiting_input" and waiting.required_input
    with pytest.raises(BusinessError):
        tutor.resume_delivery(session.token, waiting.id)
    tutor.resume_delivery(session.token, waiting.id, "I already know Python lists.")
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert tutor.turn_history(session.token, conversation.id)[0].user_text == "Explain paths."


def test_quality_acceptance_and_business_save_are_atomic_and_recover_without_resending(
    managed, session, workflow, monkeypatch
):
    tutor, settings, conversation = managed
    accepted = tutor.submit_plan(
        session.token,
        conversation.id,
        str(uuid4()),
        PlanningInput(text="Plan this goal.", expected_revision=0),
    )
    gateway, sent, _ = provider(settings, author=json.dumps(document()))
    AgentLoop(tutor, gateway).run(accepted.run_id)

    def fail(*args, **kwargs):
        raise RuntimeError("Owned transactional failure")

    with monkeypatch.context() as patch:
        patch.setattr(Plans, "record", fail)
        with pytest.raises(RuntimeError, match="Owned transactional"):
            AgentLoop(tutor, gateway).run(accepted.run_id)
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "checking"
    assert not workflow.snapshot(session.token).plans
    with tutor.database.transaction() as connection:
        connection.execute(
            "UPDATE runtime.runs SET lease_until=now()-interval '1 second' WHERE id=%s",
            (accepted.run_id,),
        )
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert len(sent) == 2 and len(workflow.snapshot(session.token).plans) == 1


def test_goal_sources_are_not_truncated_to_three_and_revision_change_supersedes_delivery(
    managed, session, workflow
):
    tutor, settings, conversation = managed
    knowledge = KnowledgeWorkflow(tutor.database)
    sources = []
    for i in range(4):
        source = knowledge.create(
            session.token,
            conversation.goal_id,
            str(uuid4()),
            SourceInput(
                title=f"Owned material {i}",
                source_url=f"https://owned.invalid/material/{i}",
                excerpt=f"Owned relevant context fact {i}.",
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
        sources.append(source)
    accepted = tutor.submit(
        session.token,
        conversation.id,
        str(uuid4()),
        TurnInput(text="Explain the provided materials."),
    )
    gateway, sent, _ = provider(settings)
    AgentLoop(tutor, gateway).run(accepted.run_id)
    context = json.loads(sent[0]["messages"][1]["content"].split("(data): ", 1)[1])
    assert {m["source_id"] for m in context["materials"]} == {str(s.id) for s in sources}
    knowledge.revise(
        session.token,
        sources[0].id,
        SourceRevision(
            expected_revision=1,
            title="New version",
            source_url="https://owned.invalid/material/0",
            excerpt="The material was explicitly revised.",
        ),
    )
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "superseded"
    assert len(sent) == 1
    assert workflow.snapshot(session.token).turns[0].turns[0].assistant_text is None
