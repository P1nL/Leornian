import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_composition_delivery import composition_provider
from test_item_supply import run_model
from test_teaching_delivery import drain, provider
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.contracts import TurnAccepted
from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.tutor.contracts import PlanningInput
from leornian.modules.tutor.interaction_contracts import PacedLearningReply


@pytest.fixture
def node_scene(database, session, workflow, setup_tutor, request):
    original, settings, conversation = setup_tutor
    route = original.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Plan", expected_revision=0),
    )
    run_model(original, settings, route.run_id, {
        "title": "Two lessons", "summary": "First print, then parameterize.",
        "assumptions": ["The learner is new to strings."],
        **({"environment_recipes": [request.param]} if hasattr(request, "param") else {}),
        "nodes": [{"key": key, "title": key, "objective": objective, "estimated_minutes": 5}
                  for key, objective in [("text", "Print a greeting"), ("name", "Use a variable")]],
    })
    plan = workflow.snapshot(session.token).plans[0]
    original.confirm_plan(session.token, plan.id, plan.latest.revision)
    settings = replace(settings, delivery_enabled=True, heartbeat_seconds=0.02,
                       model_context_tokens=128000, model_max_output_tokens=32768)
    client = TestClient(create_app(settings))
    client.headers["Authorization"] = f"Bearer {session.token}"
    root = f"/v2/conversations/{conversation.id}/teaching-session"
    focus = {"kind": "node", "plan_id": str(plan.id),
             "expected_plan_revision": 1, "node_key": "text"}
    opened = client.post(root + "/actions", json={
        "action": "open", "expected_session_revision": 0, "client_action_id": str(uuid4()),
        "focus": focus, "mode": "guided",
    })
    assert opened.status_code == 200, opened.text
    return client, root, focus, conversation, TutorWorkflow(database, settings), settings


def window(revision, focus, after=None):
    return {"expected_session_revision": revision, "focus": focus, "after_turn_id": after}


def greeting_editor():
    return {
        "schema_version": "learning_composition.v2", "title": "我的问候",
        "states": {"greeting": {"type": "code", "value": "print('你好')"}},
        "components": [{"id": "greeting_editor", "component": "CodeEditor",
                        "props": {"state": "greeting", "label": "问候语"}}],
    }


def deliver(scene, session, accepted, text, next_step, resume_at="", check_topic=None, choice=None):
    *_, tutor, settings = scene
    reply = {"text": text, "interaction": {"type": "none"}, "pacing": {
        "next_step": next_step, "resume_at": resume_at, "check_topic": check_topic,
        **({"practice_choice": choice} if choice else {}),
    }}
    gateway, sent, _ = provider(settings, author=json.dumps(reply))
    result = drain(tutor, settings, TurnAccepted(**accepted), gateway, session.token)
    assert result.status == "accepted", result
    assert "pacing_checks" in json.loads(sent[-1]["messages"][-1]["content"])
    return sent[0]["messages"]


def test_listening_window_is_single_use_and_only_explicit_finish_unlocks(
    node_scene, session, workflow,
):
    client, root, focus, conversation, tutor, _ = node_scene
    command = window(1, focus)
    assert client.get(root).json()["node_window"] == {"next_step": "opening", "after_turn_id": None}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda _: client.post(root + "/continue", json=command), range(2),
        ))
    assert [r.status_code for r in responses] == [202, 202]
    accepted = responses[0].json()
    assert accepted == responses[1].json()
    messages = deliver(node_scene, session, accepted, "Print one greeting.", "can_continue",
                       "format")
    assert not any(m["role"] == "user" and "Open this node" in m["content"] for m in messages)
    next_window = window(1, focus, accepted["turn_id"])
    assert client.get(root).json()["node_window"]["next_step"] == "can_continue"
    second = client.post(root + "/continue", json=next_window).json()
    messages = deliver(node_scene, session, second, "That is the whole greeting.", "wrap_up")
    assert all(message["role"] != "assistant" for message in messages)
    assert any("Print one greeting." in message["content"] for message in messages)
    assert "format" in next(m["content"] for m in messages if "node_continuity" in m["content"]
                            and m["content"].startswith("Learning context"))
    refused = client.post(root + "/continue", json=window(1, focus, second["turn_id"]))
    assert refused.status_code == 409
    before = workflow.snapshot(session.token)
    assert not before.conversations[0].studied_nodes and not before.conversations[0].ended_nodes
    next_focus = {**focus, "node_key": "name"}
    assert client.post(root + "/actions", json={
        "action": "set_topic", "focus": next_focus, "client_action_id": str(uuid4()),
        "expected_session_revision": 1,
    }).status_code == 409
    end = {"action": "finish_node", "focus": focus, "after_turn_id": second["turn_id"],
           "client_action_id": str(uuid4()), "expected_session_revision": 1}
    result = client.post(root + "/actions", json=end)
    assert result.status_code == 200 and result.json()["focus"]["node_key"] == "name"
    assert client.post(root + "/actions", json=end).json() == result.json()
    after = workflow.snapshot(session.token)
    assert after.conversations[0].ended_nodes[0].node_key == "text"
    assert not after.conversations[0].studied_nodes and not after.node_progress
    assert len(tutor.turn_history(session.token, conversation.id)) == len(before.turns[0].turns)


def test_learner_asks_about_visible_example_then_listens(node_scene, session):
    client, root, focus, conversation, tutor, _ = node_scene
    capabilities = {"presentation_capabilities": {"versions": ["learning_composition.v2"]}}
    opening = client.post(root + "/continue", json={**window(1, focus), **capabilities}).json()
    deliver(node_scene, session, opening, "要显示一句问候，可以写 `print('你好')`。",
            "can_continue", "更换问候语")

    question = "引号也会显示出来吗？"
    asked = client.post(f"/v1/conversations/{conversation.id}/turns",
                        headers={"Idempotency-Key": str(uuid4())}, json={
                            "text": question, "focus": focus, "teaching_session_revision": 1,
                            "node_pacing": True, **capabilities,
                        })
    assert asked.status_code == 202
    deliver(node_scene, session, asked.json(), "不会。引号标出哪几个字是文字，显示的只有「你好」。",
            "can_continue", "更换问候语")
    continued = client.post(root + "/continue", json={
        **window(1, focus, asked.json()["turn_id"]), **capabilities,
    })
    assert continued.status_code == 202
    deliver(node_scene, session, continued.json(), "同样，`print('早上好')` 显示的是「早上好」。",
            "wrap_up")

    history = tutor.turn_history(session.token, conversation.id)
    assert [turn.user_text for turn in history
            if turn.purpose == "teaching" and not turn.teaching_intent_id] == [question]


def test_learner_preempts_opening_then_explicitly_skips_offered_question(node_scene, session):
    client, root, focus, conversation, tutor, _ = node_scene
    explicit = f"/v1/conversations/{conversation.id}/turns"
    auto = client.post(root + "/continue", json=window(1, focus)).json()
    data = {"text": "怎么让程序显示一句你好？", "focus": focus, "teaching_session_revision": 1,
            "node_pacing": True}
    user = client.post(explicit, headers={"Idempotency-Key": str(uuid4())}, json=data).json()
    assert tutor.get(session.token, auto["run_id"]).status == "cancelled"
    deliver(node_scene, session, user,
            "`print('你好')` 会显示「你好」。猜猜看，`print('晚安')` 会显示什么？",
            "wait_for_reply", "更换问候语", "显示的文字")
    refused = client.post(root + "/continue", json=window(1, focus, user["turn_id"]))
    assert refused.status_code == 409
    skip = "这题先跳过吧。"
    user = client.post(explicit, headers={"Idempotency-Key": str(uuid4())},
                       json={**data, "text": skip}).json()
    choice = {"choice": "defer", "quote": skip}
    messages = deliver(node_scene, session, user, "好。引号里换成「晚安」，就会显示「晚安」。",
                       "can_continue", "小结", choice=choice)
    context = json.loads(next(message["content"].removeprefix("Learning context (data): ")
                              for message in messages
                              if message["content"].startswith("Learning context")))
    assert context["node"]["node_continuity"] == {
        "resume_at": "更换问候语", "checked_topics": ["显示的文字"],
    }
    continuation = client.post(root + "/continue", json=window(1, focus, user["turn_id"]))
    messages = deliver(node_scene, session, continuation.json(),
                       "这就是第一句问候的写法：`print` 把引号里的文字显示出来。", "wrap_up")
    context = json.loads(next(message["content"].removeprefix("Learning context (data): ")
                              for message in messages
                              if message["content"].startswith("Learning context")))
    assert context["node"]["node_continuity"]["practice_choice"] == choice


def test_first_question_owns_the_opening_and_requested_practice_holds(node_scene, session):
    client, root, focus, conversation, tutor, settings = node_scene
    request = "我想自己试着写一句。"
    human = client.post(f"/v1/conversations/{conversation.id}/turns",
                        headers={"Idempotency-Key": str(uuid4())}, json={
                            "text": request, "node_pacing": True,
                            "focus": focus, "teaching_session_revision": 1,
                            "presentation_capabilities": {"versions": ["learning_composition.v2"]},
                        }).json()
    assert client.post(root + "/continue", json=window(1, focus)).status_code == 409
    accepted = TurnAccepted(**human)
    pacing = {"next_step": "wait_for_action", "resume_at": "问候语",
              "practice_choice": {"choice": "request", "quote": request}}
    bad, _, _ = provider(settings, author=json.dumps({
        "text": "打开终端执行这行代码，把输出贴回来。",
        "interaction": {"type": "none"}, "pacing": pacing,
    }))
    AgentLoop(tutor, bad).run(accepted.run_id)
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "repairing"
    artifacts = LearningArtifactWorkflow(tutor.database)
    assert not artifacts.list_v2(session.token, conversation.id)
    gateway, sent, prepared = composition_provider(
        settings, definition=greeting_editor(), reply_text="在这里把「你好」换成你想说的话。",
        pacing=pacing,
    )
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    repair = json.loads(sent[0]["messages"][-1]["content"])
    assert repair["issues"][0]["code"] == "missing_teaching_action_surface"
    view = artifacts.get_v2(session.token, conversation.id,
                            artifacts.list_v2(session.token, conversation.id)[0].id)
    assert view.source_turn_id == accepted.turn_id and len(prepared) == 1
    assert not view.presentation.definition.states["greeting"].read_only
    assert not view.allowed_actions
    refused = client.post(root + "/continue", json=window(1, focus, human["turn_id"]))
    assert refused.status_code == 409
    for revision, action in enumerate((
        {"action": "pause"}, {"action": "set_topic", "focus": {**focus, "node_key": "name"}},
        {"action": "resume"}, {"action": "set_topic", "focus": focus},
    ), start=1):
        changed = client.post(root + "/actions", json={
            **action, "expected_session_revision": revision, "client_action_id": str(uuid4()),
        })
        assert changed.status_code == 200
    restored = client.get(root).json()
    assert restored["paused"] and restored["focus"]["node_key"] == "text"
    assert restored["node_window"] == {"after_turn_id": human["turn_id"],
                                       "next_step": "wait_for_action"}


@pytest.mark.parametrize("wraps_up", [False, True])
def test_return_from_edit_only_example_allows_the_next_activity(node_scene, session, wraps_up):
    client, root, focus, conversation, tutor, settings = node_scene

    def say(text):
        revision = client.get(root).json()["revision"]
        result = client.post(f"/v1/conversations/{conversation.id}/turns",
                             headers={"Idempotency-Key": str(uuid4())}, json={
                                 "text": text, "focus": focus, "node_pacing": True,
                                 "teaching_session_revision": revision,
                                 "presentation_capabilities": {
                                     "versions": ["learning_composition.v2"],
                                     "actions": ["learning_programs.v2"],
                                 },
                             })
        assert result.status_code == 202, result.text
        return result.json()

    edit = say("我想把问候改成早上好。")
    gateway, _, _ = composition_provider(
        settings, definition=greeting_editor(), reply_text="可以改引号里的文字。",
        pacing={"next_step": "wait_for_action", "resume_at": "问候语"},
    )
    assert drain(tutor, settings, TurnAccepted(**edit), gateway, session.token).status == "accepted"
    if wraps_up:
        asked = say("这两行看懂了，练习先跳过吧。")
        deliver(node_scene, session, asked, "两行按顺序显示，引号不在输出里。", "wrap_up",
                choice={"choice": "defer", "quote": "练习先跳过吧"})
    else:
        asked = say("引号也要换掉吗？")
        deliver(node_scene, session, asked, "保留引号，只换里面的字。", "wait_for_reply")
    state = client.get(root).json()
    assert state["active_branch_id"]
    assert state["node_window"]["next_step"] == "wait_for_action"
    returned = client.post(root + "/actions", json={
        "action": "return_to_main", "branch_id": state["active_branch_id"],
        "expected_session_revision": state["revision"], "client_action_id": str(uuid4()),
    })
    assert returned.status_code == 200
    if wraps_up:
        current = returned.json()
        assert current["focus"] == state["focus"] and current["active_branch_id"] is None
        assert current["node_window"] == {"next_step": "wrap_up", "after_turn_id": asked["turn_id"]}
        finished = client.post(root + "/actions", json={
            "action": "finish_node", "client_action_id": str(uuid4()), "focus": focus,
            "expected_session_revision": current["revision"], "after_turn_id": asked["turn_id"],
        })
        assert finished.status_code == 200 and finished.json()["focus"]["node_key"] == "name"
        return
    assert returned.json()["node_window"]["next_step"] == "wait_for_action"
    run = say("那换成双引号也行吗？")
    assert client.get(root).json()["active_branch_id"] is None
    messages = deliver(node_scene, session, run, "也行。`print(\"早上好\")` 显示的还是「早上好」。",
                       "can_continue", "更换问候语")
    facts = json.loads(messages[1]["content"].split(": ", 1)[1])
    prior = [item for group in facts["history"]["delivered_teaching"] for item in group["extracts"]]
    assert any(item.get("branch_id") == state["active_branch_id"]
               and item["excerpt"]["text"] == "保留引号，只换里面的字。" for item in prior)
    assert facts["node"]["confirmed_node"]["objective"] == "Print a greeting"


@pytest.mark.parametrize("tool,result,pending", [
    ("request_learning_program_supply", {"status": "accepted", "task_id": "supply"}, True),
    ("request_learning_program_supply", {"status": "conflict"}, False),
    ("get_learning_practice_supply", {"status": "completed", "task_id": "supply",
                                      "supply_status": "completed", "pack_status": "published"},
     False),
    ("request_execution_environment", {"status": "accepted", "demand": {"status": "queued"}}, True),
    ("request_execution_environment", {"status": "accepted", "demand": {"status": "ready"}}, False),
])
def test_unattached_wait_uses_actual_pending_receipt(monkeypatch, tool, result, pending):
    run_id = uuid4()
    monkeypatch.setattr(Runs, "tool_outputs", lambda _, run, name: (
        [result] if (run, name) == (run_id, tool) else []
    ))
    assert LearningArtifactWorkflow.pending_workspace_work(
        None, {"id": run_id, "tool_contracts": {tool: 1}},
    ) is pending


def test_simultaneous_expiry_and_learner_input_leave_only_the_learner_run(node_scene, session):
    client, root, focus, conversation, tutor, _ = node_scene
    start = Barrier(2)

    def dispatch(automatic):
        start.wait(timeout=5)
        if automatic:
            return client.post(root + "/continue", json=window(1, focus))
        return client.post(f"/v1/conversations/{conversation.id}/turns",
                           headers={"Idempotency-Key": str(uuid4())}, json={
                               "text": "第一行代码怎么写啊？", "node_pacing": True,
                               "focus": focus, "teaching_session_revision": 1,
                           })

    with ThreadPoolExecutor(max_workers=2) as pool:
        automatic, explicit = pool.map(dispatch, (True, False))
    assert explicit.status_code == 202 and automatic.status_code in {202, 409}
    if automatic.status_code == 202:
        assert tutor.get(session.token, automatic.json()["run_id"]).status == "cancelled"
    assert tutor.get(session.token, explicit.json()["run_id"]).status == "queued"
    tutor.cancel(session.token, explicit.json()["run_id"])


@pytest.mark.parametrize("action,extra", [("pause", {}), ("set_mode", {"mode": "free_reading"})])
def test_changed_control_invalidates_opening_even_with_a_fresh_revision(node_scene, action, extra):
    client, root, focus, *_ = node_scene
    result = client.post(root + "/actions", json={
        "action": action, "client_action_id": str(uuid4()), "expected_session_revision": 1, **extra,
    })
    assert result.status_code == 200
    for revision in (1, result.json()["revision"]):
        assert client.post(root + "/continue", json=window(revision, focus)).status_code == 409


def test_action_and_reply_cannot_start_a_timer():
    for interaction in [{"type": "composer"}, {"type": "artifact", "exact_handle": uuid4(),
                                              "intent": "introduce_only"}]:
        with pytest.raises(ValidationError):
            PacedLearningReply(text="Try this", interaction=interaction,
                               pacing={"next_step": "can_continue", "resume_at": "output"})


def test_silent_opening_and_repeated_check_are_rejected_before_delivery():
    manifest = {"node_pacing": True, "teaching_intent": {"window_phase": "opening"}}
    reply = {"text": "Try it.", "interaction": {"type": "none"},
             "pacing": {"next_step": "wait_for_action", "resume_at": "print the greeting"}}
    with pytest.raises(ModelProtocolError, match="opening_requires_explanation"):
        LearningArtifactWorkflow.validate_reply_in(
            None, None, {}, {"context_manifest": manifest}, json.dumps(reply),
        )
    reply["pacing"]["check_topic"] = "Interpolation"
    with pytest.raises(ModelProtocolError, match="repeated_comprehension_check"):
        LearningArtifactWorkflow.validate_reply_in(
            None, None, {}, {"context_manifest": {
                "node_pacing": True, "checked_topics": ["interpolation"],
            }}, json.dumps(reply),
        )
    reply["pacing"]["check_topic"] = None
    with pytest.raises(ModelProtocolError, match="practice_is_deferred"):
        LearningArtifactWorkflow.validate_reply_in(
            None, None, {}, {"context_manifest": {
                "node_pacing": True, "practice_deferred": True,
                "teaching_intent": {"window_phase": "continuation"},
            }}, json.dumps(reply),
        )
