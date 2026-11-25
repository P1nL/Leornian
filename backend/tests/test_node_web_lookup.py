import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from test_material_consumers import consumer as consumer
from test_material_consumers import draft
from test_material_lifecycle import material_setup as material_setup
from test_streaming_learning import frames
from test_teaching_delivery import body, drain, report
from test_tutor_runtime import calls, response

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.tools import NODE_WEB_TOOL
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.node_web_lookup import available_tools
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.learning.contracts import GoalMaterialScope
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.platform.model_contracts import ModelPresetInput


@pytest.mark.parametrize("outcome", ["found", "no_sources", "provider_rejected",
                                     "not_authorized", "unknown"])
def test_public_lookup_stays_in_its_turn(database, session, consumer, outcome):
    tutor, settings, conversation, _, goal, *_ = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    settings = replace(settings, model_configuration_mode="user")
    models = ModelConfigurationWorkflow(database, settings)
    models.apply_preset(session.token, str(uuid4()), "deepseek", ModelPresetInput(
        api_key="offline-lookup", allow_private_material=True, group="teaching",
        expected_mapping_revisions={item.role: item.revision
                                    for item in models.configuration(session.token).mappings},
    ))
    with database.transaction() as connection:
        assert not available_tools(connection, settings, session.actor, goal.id)
        connection.execute(
            "UPDATE learning.goals SET material_scope=%s::jsonb WHERE id=%s",
            (GoalMaterialScope(language="Python", authorized_official_sources=True,
                               authorized_public_sources=True).model_dump_json(), goal.id),
        )
    tutor = TutorWorkflow(database, settings)
    focus = TeachingFocus(kind="node", plan_id=plan.id, expected_plan_revision=1,
                          node_key="iteration")
    question = "我叫小明。print 有个 flush 参数。它是哪一版加的？"
    parts = ["print 有个 flush 参数", "它是哪一版加的？"]
    accepted = tutor.submit(session.token, conversation.id, str(uuid4()),
                            TurnInput(text=question, focus=focus))
    native_requests, observations, reviews = [], [], []
    url = "https://docs.python.org/3/library/functions.html#print"
    statement = "Python 3.3 added flush."

    def handle(request):
        wire = json.loads(request.content)
        if wire.get("tools") == [{"type": "deepseek_web_search"}]:
            native_requests.append(wire)
            assert "response_format" not in wire and wire["thinking"] == {"type": "disabled"}
            expected_question = "\n".join(["Python", "Course documentation host: docs.python.org",
                                           *parts])
            assert wire["messages"][1:] == [{"role": "user", "content": expected_question}]
            assert "小明" not in str(wire) and "Iteration" not in str(wire)
            if outcome == "unknown":
                raise httpx.ReadTimeout("receipt lost", request=request)
            if outcome == "provider_rejected":
                return httpx.Response(400, json={"error": "Rejected by fixture"})
            delta = {"annotations": [{"type": "url_citation", "url_citation": {
                "url": url, "start_index": 0, "end_index": len(statement),
            }}], "server_tool_calls": [{
                "reasoning_content": "private lookup reasoning", "calls": [{
                    "status": "completed", "sources": [{
                        "url": url, "title": "Built-in Functions",
                        "snippet": "Changed in version 3.3: Added the flush keyword argument.",
                    }],
                }],
            }]} if outcome == "found" else {}
            stream = frames(
                {"delta": {"content": statement}}, {"delta": delta, "finish_reason": "stop"},
            )
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=stream,
            )
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            reviews.append(payload)
            assert not wire.get("tools")
            return httpx.Response(200, json=body(json.dumps(report(payload))))
        if wire["messages"][-1]["role"] == "tool":
            assert wire["messages"][-1]["tool_call_id"] == "context_1"
            observations.append(json.loads(wire["messages"][-1]["content"]))
            assert wire["thinking"] == {"type": "enabled"}
            return httpx.Response(200, json=body("核对这个参数的引入版本。"))
        assert any(tool["function"]["name"] == NODE_WEB_TOOL for tool in wire["tools"])
        request_tool = response(name=NODE_WEB_TOOL, arguments=json.dumps({
            "excerpts": parts, "symbol": "print.flush",
        }))
        request_tool["choices"][0]["message"]["reasoning_content"] = "private author reasoning"
        return httpx.Response(200, json=request_tool)

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert calls(database, accepted.run_id)[-1]["status"] == "prepared"
    if outcome == "not_authorized":
        with database.transaction() as connection:
            connection.execute(
                "UPDATE learning.goals SET material_scope=NULL WHERE id=%s", (goal.id,),
            )
    task = drain(tutor, settings, accepted, gateway, session.token)
    if outcome == "unknown":
        assert task.status == "blocked_unknown"
        AgentLoop(tutor, gateway).run(accepted.run_id)
        assert len(native_requests) == 1 and not observations and not reviews
        return
    assert task.status == "accepted" and len(native_requests) == int(outcome != "not_authorized")
    result, = observations
    assert result["outcome"] == outcome and bool(result["sources"]) == (outcome == "found")
    if outcome == "found":
        assert result["sources"][0]["url"] == url
        assert result["sources"][0]["cited_answer"] == statement
    evidence = reviews[0]["turn_evidence"]
    assert evidence["learner_messages"] == [question]
    assert evidence["tool_observations"] == [{"tool": NODE_WEB_TOOL, "result": result}]
    assert "private lookup reasoning" not in str(evidence)
    assert "private author reasoning" not in str(evidence)
