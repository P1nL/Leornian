import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from test_composition_delivery import composition_provider
from test_node_teaching_pacing import greeting_editor
from test_node_teaching_pacing import node_scene as node_scene
from test_teaching_delivery import body, drain, report
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.contracts import TurnAccepted
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.node_turn_context import CONTEXT_PREFIX, differences, evidence
from leornian.bootstrap.teaching_delivery import LearningReplyFramingError, TeachingDelivery
from leornian.modules.tutor.node_reply import (
    OPERATION_TARGET,
    MissingHandoff,
    node_candidate,
    operation_quotes,
    revise_operations,
)


def task(**changes):
    return {"kind": "teaching", "context_manifest": {"node_turn_contract": 1, "node_pacing": True},
            "issues": [], "fragments": [], **changes}


def say(scene, text):
    client, root, focus, conversation, *_ = scene
    response = client.post(f"/v1/conversations/{conversation.id}/turns", headers={
        "Idempotency-Key": str(uuid4()),
    }, json={"text": text, "focus": focus, "node_pacing": True,
             "teaching_session_revision": client.get(root).json()["revision"],
             "presentation_capabilities": {"versions": ["learning_composition.v2"]}})
    assert response.status_code == 202, response.text
    return TurnAccepted(**response.json())


def test_unambiguous_transport_and_fields_are_assembled_locally():
    original = "这段是代码示例：\n```python\nprint('你好')\n```"
    wrapped = "```json\n" + json.dumps({"text": original, "pacing": {"next_step": "wrap_up"}})
    result = json.loads(node_candidate(task(), wrapped + "\n```"))
    assert result == {"text": original, "interaction": {"type": "none"},
                      "pacing": {"next_step": "wrap_up", "resume_at": "", "check_topic": None}}
    with pytest.raises(MissingHandoff) as missing:
        node_candidate(task(fragments=[{"text": "第一段。"}]), json.dumps({
            "fragment": {"text": "第二段。"}, "complete": True, "interaction": {"type": "composer"},
        }))
    assert missing.value.draft["text"] == "第一段。\n\n第二段。"
    assert missing.value.fields == ["pacing.resume_at"]
    frozen = {"code": "node_handoff_required", "frozen_reply": missing.value.draft,
              "missing_fields": missing.value.fields}
    filled = json.loads(node_candidate(task(issues=[frozen]), '{"pacing.resume_at":"问候语"}'))
    assert filled["text"] == missing.value.draft["text"]
    assert filled["pacing"]["next_step"] == "wait_for_reply"
    with pytest.raises(ValueError):
        node_candidate(task(issues=[frozen]), '{"pacing":{"resume_at":"问候语"}}')
    data = {"text": original, "interaction": {"type": "none"},
            "pacing": {"next_step": "Think about the chart.", "resume_at": "读图"}}
    with pytest.raises(MissingHandoff) as invalid:
        node_candidate(task(), json.dumps(data))
    assert invalid.value.fields == ["pacing.next_step"]
    assert invalid.value.diagnostics[0]["path"] == ["pacing", "next_step"]
    assert invalid.value.draft == {**data, "pacing": {"resume_at": "读图"}}
    with pytest.raises(MissingHandoff) as repeated:
        node_candidate(task(issues=[{**frozen, "frozen_reply": invalid.value.draft,
                                     "missing_fields": invalid.value.fields}]),
                       '{"pacing.next_step":["still invalid"]}')
    assert not repeated.value.narrows(invalid.value.fields)
    with pytest.raises(ValidationError):
        node_candidate(task(), '{"text":"", "interaction":{"type":"none"}}')
    with pytest.raises(ValueError, match="Ambiguous"):
        node_candidate(task(), '我先说一句。\n{"text":"正文？","interaction":{"type":"none"}}')
    with pytest.raises(ValueError, match="duplicate"):
        node_candidate(task(), '{"text":"原稿","text":"替换"}')
    example = '返回的数据是这样的：\n```json\n{"text":"你好"}\n```'
    with pytest.raises(MissingHandoff) as plain:
        node_candidate(task(), example)
    assert plain.value.draft["text"] == example
    handle = str(uuid4())
    direct = task(context_manifest={"node_turn_contract": 1, "required_learning_handle": handle})
    assert json.loads(node_candidate(direct, "先看看这道题。"))["interaction"] == {
        "type": "artifact", "exact_handle": handle, "intent": "introduce_only",
    }
    with pytest.raises(LearningReplyFramingError):
        TeachingDelivery.candidate(task(context_manifest={"node_pacing": True}), wrapped + "\n```")


def test_review_projects_only_selected_evidence_and_latest_baseline_relative_refresh():
    state = {"workspace": {}, "node": {"focus": {}}, "origin": {}, "history": {},
             "observations": {"before": True}, "materials": {"bound_materials": ["原文"]}}
    bound = task(author_messages=[
        {"role": "system", "content": "Author instructions."},
        {"role": "user", "content": CONTEXT_PREFIX + json.dumps(state)},
        {"role": "user", "content": "我想看看效果。"},
    ])
    selected = {"candidate": {"id": "chosen", "presentation": {"definition": "实际预览"}},
                "status": "completed"}
    receipts = [
        {"name": "learning_get_context", "result": {"relative_to": "initial_node_turn",
         "changes": [{"path": ["workspace", "obsolete"], "value": True}]}},
        {"name": "learning_get_context", "result": {"relative_to": "initial_node_turn",
         "changes": list(differences(state, {**state, "observations": {"after": "真实结果"}}))}},
        {"name": "get_learning_component_contracts", "result": {"components": "整个目录"}},
        {"name": "prepare_learning_hint_composition", "result": {
            "candidate": {"id": "unused", "presentation": "未选工件"},
            "hint_bindings": ["锁定提示"],
        }},
        {"name": "prepare_learning_composition", "result": selected},
    ]
    actual = evidence(bound, receipts, "chosen")
    assert actual["workspace"] == {} and actual["selected_artifact"] == selected
    assert actual["observations"] == {"after": "真实结果"}
    assert actual["materials"]["bound_materials"] == ["原文"]
    assert actual["undelivered_private_hints"] == [{"hint_bindings": ["锁定提示"]}]
    assert all(text not in str(actual) for text in ("整个目录", "未选工件", "Author instructions"))


def test_review_prefix_survives_node_and_surface_changes_without_shortening_evidence():
    manifest = {**task()["context_manifest"], "example_runs": True, "operation_wording_repair": 1,
                "learning_interaction_contract": 1, "learning_composition_contract": 2}
    inputs = {"node": {"title": "声音"}, "materials": {}, "workspace": {},
              "learner_messages": ["怎样听音高？"], "origin": {"turn_id": str(uuid4())}}
    candidate = json.dumps({"text": "先比较两个音的高低。" * 700}, ensure_ascii=False)
    plain = task(candidate=candidate, candidate_call_id=uuid4(), output_multiplier=1,
                 candidate_input=inputs, context_manifest=manifest)
    selected = {"candidate": {"kind": "learning_composition", "id": str(uuid4()),
                              "presentation": {"definition": {"title": "两种音高"}}}}
    problem = {**plain, "candidate_call_id": uuid4(), "candidate": "另一份完整的候选正文",
               "context_manifest": {**manifest, "teaching_intent": {"window_phase": "opening"}},
               "candidate_input": {**inputs, "node": {"title": "音程"},
                                   "origin": {"turn_id": str(uuid4())},
                                   "selected_artifact": selected}}
    plain_role, selected_role = map(TeachingDelivery.review_role, (plain, problem))
    common = ("kind", "teaching_turn_checks", "example_run_checks", "pacing_checks",
              "interaction_selection_checks", "execution_environment_checks")
    first, second = (json.loads(role.messages[-1]["content"]) for role in (
        plain_role, selected_role,
    ))
    prefix = json.dumps({key: first[key] for key in common}, ensure_ascii=False,
                        separators=(",", ":"))[:-1] + ","
    assert plain_role.messages[0] == selected_role.messages[0]
    for role in (plain_role, selected_role):
        assert role.messages[-1]["content"].startswith(prefix)
        assert role.allowed_tools == () and role.context_manifest["review_scope"] == "full"
    assert not {"opening_checks", "composition_checks"} & set(first["required_checks"])
    assert {"opening_checks", "composition_checks"} <= set(second["required_checks"])
    assert [first["candidate"], second["candidate"]] == [candidate, problem["candidate"]]
    assert first["candidate_call_id"] != second["candidate_call_id"]
    assert second["turn_evidence"] == problem["candidate_input"]


def test_fields_only_then_evidenced_revision_and_atomic_delivery(node_scene, session):
    client, root, _, conversation, tutor, settings = node_scene
    question = "换成双引号也行吗？"
    accepted = say(node_scene, question)
    draft = "双引号也会显示在问候语里。\n\n    print(\"你好\")\n"
    corrected = "也行。`print(\"你好\")` 和 `print('你好')` 都显示「你好」，不带引号。"
    handoff = {"interaction": {"type": "none"},
               "pacing": {"next_step": "wait_for_reply", "resume_at": "改问候语"}}
    wires = []
    reviewed = []

    def handle(request):
        wire = json.loads(request.content)
        wires.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            reviewed.append(payload)
            reply = report(payload)
            if len(reviewed) == 1:
                reply["verdict"] = "changes_required"
                check = next(item for item in reply["checks"]
                             if item["code"] == "factual_grounding")
                check.update(verdict="changes_required", issues=[{
                    "code": "wrong_output", "target_ref": "candidate.text: 双引号也会显示",
                    "evidence_ref": "Python string delimiters in the supplied example",
                    "repair_instruction": "Explain that the delimiters are not printed.",
                }])
                other = next(item for item in reply["checks"] if item["code"] == "teaching_intent")
                other.update(verdict="changes_required", issues=[
                    {**check["issues"][0], "code": "same_correction"},
                ])
        elif len(wires) == 1:
            return httpx.Response(200, json=body(draft))
        elif len(wires) in {2, 3}:
            payload = json.loads(wire["messages"][-1]["content"])
            assert payload["frozen_reply"] == {"text": draft}
            assert set(payload["missing_fields"]) == {"interaction", "pacing"}
            assert wire["response_format"] == {"type": "json_object"} and "tools" not in wire
            reply = {**handoff, "text": "替换正文"} if len(wires) == 2 else handoff
        else:
            payload = json.loads(wire["messages"][-1]["content"])
            assert [issue["code"] for issue in payload["issues"]] == ["wrong_output"]
            reply = {**handoff, "text": corrected}
        return httpx.Response(200, json=body(json.dumps(reply)))

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle)))
    for _ in range(6):
        before = next(item for item in tutor.turn_history(session.token, conversation.id)
                      if item.id == accepted.turn_id)
        assert before.assistant_text is None and before.pacing is None
        assert client.get(root).json()["node_window"]["next_step"] == "hold"
        loop.run(accepted.run_id)
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "accepted"
    assert [json.loads(item["candidate"])["text"] for item in reviewed] == [draft, corrected]
    assert reviewed[0]["candidate_call_id"] != reviewed[1]["candidate_call_id"]
    assert reviewed[0]["turn_evidence"] == reviewed[1]["turn_evidence"]
    assert reviewed[0]["turn_evidence"]["learner_messages"] == [question]
    assert "替换正文" not in str(reviewed)
    turn = next(item for item in tutor.turn_history(session.token, conversation.id)
                if item.id == accepted.turn_id)
    assert turn.assistant_text == corrected and turn.pacing.next_step == "wait_for_reply"
    assert client.get(root).json()["node_window"]["next_step"] == "wait_for_reply"


def test_selected_editor_survives_field_repair_without_repreparation(node_scene, session, workflow):
    client, root, _, conversation, tutor, settings = node_scene
    accepted = say(node_scene, "我想自己改一下问候语。")
    intro = "把引号里的「你好」换成你想说的话。"
    original, _, prepared = composition_provider(settings, definition=greeting_editor(),
                                                  reply_text=intro)
    wires = []

    def handle(request):
        wire = json.loads(request.content)
        wires.append(wire)
        if len(wires) == 2:
            original.transport.handle_request(request)
            return httpx.Response(200, json=body(intro))
        if len(wires) == 3:
            data = json.loads(wire["messages"][-1]["content"])
            assert data["turn"]["selectable"][0]["id"] == prepared[0]["id"]
            return httpx.Response(200, json=body(json.dumps({
                "interaction": {"type": "artifact", "exact_handle": prepared[0]["id"]},
                "pacing": {"next_step": "在卡片上继续操作", "resume_at": "继续改问候语"},
            })))
        if len(wires) == 4:
            data = json.loads(wire["messages"][-1]["content"])
            assert data["frozen_reply"]["text"] == intro
            assert data["frozen_reply"]["interaction"]["exact_handle"] == prepared[0]["id"]
            assert data["missing_fields"] == ["pacing.next_step"]
            assert data["diagnostics"][0]["path"] == ["pacing", "next_step"]
            assert "wait_for_action" in data["diagnostics"][0]["message"]
            assert "tools" not in wire
            return httpx.Response(200, json=body('{"pacing.next_step":"wait_for_action"}'))
        if len(wires) == 5:
            data = json.loads(wire["messages"][-1]["content"])
            surface = data["turn_evidence"]["selected_artifact"]["candidate"]
            assert surface["id"] == prepared[0]["id"]
            components = surface["presentation"]["definition"]["components"]
            assert components[0]["component"] == "CodeEditor"
            assert "tools" not in wire
            assert not client.get(f"/v2/conversations/{conversation.id}/learning-artifacts").json()
        return original.transport.handle_request(request)

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert len(wires) == 5 and len(prepared) == 1
    turn = next(item for item in tutor.turn_history(session.token, conversation.id)
                if item.id == accepted.turn_id)
    assert turn.assistant_text == intro and str(turn.learning_interaction.exact_handle) == (
        prepared[0]["id"]
    )
    assert client.get(root).json()["node_window"]["next_step"] == "wait_for_action"
    assert not workflow.snapshot(session.token).node_progress


def test_operation_scope_requires_unambiguous_disjoint_quotes_and_no_other_issue():
    candidate = json.dumps({"text": "Click Run, then Run. Edit cell A1.",
                            "interaction": {"type": "none"}})

    def quotes(*targets):
        return operation_quotes(candidate, [{"target_ref": target} for target in targets])

    click, cell = OPERATION_TARGET + "Click Run", OPERATION_TARGET + "cell A1"
    assert quotes(cell, click, cell) == ["Click Run", "cell A1"]
    assert quotes(click, "selected_artifact.definition") == []
    assert quotes(click, OPERATION_TARGET + "Run") == []
    assert quotes(click, OPERATION_TARGET + "Run, then") == []
    assert quotes(OPERATION_TARGET + "cell A2") == []
    result, _ = revise_operations(candidate, quotes(cell, click), json.dumps({
        "cell A1": "cell B2", "Click Run": "Select cell A1",
    }))
    assert json.loads(result) == {"text": "Select cell A1, then Run. Edit cell B2.",
                                  "interaction": {"type": "none"}}


@pytest.mark.parametrize("broader_defect", [False, True])
def test_wrong_editor_line_is_repaired_against_the_same_surface(
    node_scene, session, database, broader_defect,
):
    client, _, _, conversation, tutor, settings = node_scene
    question = "能先写 minutes = 95，再 print(minutes) 吗？"
    accepted = say(node_scene, question)
    editor = greeting_editor()
    code = 'minutes = 95\nprint(minutes)\n\n# print("minutes")'
    editor["states"]["greeting"]["value"] = code
    wrong = "取消第三行的注释。"
    correction = '把 `# print("minutes")` 改成 `print("minutes")`。'
    intro = "可以。先运行这两行。"
    pacing = {"next_step": "wait_for_action", "resume_at": "变量名和字符串"}
    original, _, prepared = composition_provider(
        settings, definition=editor, reply_text=intro + wrong, pacing=pacing,
    )
    reviews, repairs = [], []
    artifacts = f"/v2/conversations/{conversation.id}/learning-artifacts"

    def handle(request):
        wire = json.loads(request.content)
        system = wire["messages"][0]["content"]
        if "Independently review" in system:
            data = json.loads(wire["messages"][-1]["content"])
            reviews.append(data)
            reply = report(data)
            candidate = json.loads(data["candidate"])
            assert candidate["interaction"]["exact_handle"] == prepared[0]["id"]
            assert candidate["pacing"]["next_step"] == pacing["next_step"]
            assert data["turn_evidence"]["selected_artifact"]["candidate"]["presentation"][
                "definition"]["states"]["greeting"]["value"] == code
            assert data["turn_evidence"]["learner_messages"] == [question]
            assert not client.get(artifacts).json()
            if len(reviews) == 1:
                assert candidate["text"] == intro + wrong and code.splitlines()[2] == ""
                assert OPERATION_TARGET in data["operation_issue_target"]
                reason = ("composition_checks", OPERATION_TARGET + wrong, "wrong_line",
                          "Name the commented print statement instead.")
            elif len(reviews) == 2:
                assert data["turn_evidence"] == reviews[0]["turn_evidence"]
                revision = data["operation_revision"]
                assert revision["candidate_call_id"] == reviews[0]["candidate_call_id"]
                assert data["candidate_call_id"] != revision["candidate_call_id"]
                assert revision["replacements"] == {wrong: candidate["text"][len(intro):]}
                assert set(data["required_checks"]) == {
                    "composition_checks", "operation_wording_impact",
                }
                reason = (("operation_wording_impact", "candidate.text", "invented_run",
                           "Remove the claim the code already ran.") if broader_defect else None)
            else:
                assert "operation_revision" not in data
                assert data["required_checks"] == reviews[0]["required_checks"]
                reason = None
            if reason:
                check_code, target, problem, instruction = reason
                check = next(item for item in reply["checks"] if item["code"] == check_code)
                check.update(verdict="changes_required", issues=[{
                    "code": problem, "target_ref": target, "evidence_ref": "editor and run facts",
                    "repair_instruction": instruction,
                }])
                reply["verdict"] = "changes_required"
        elif "Correct only the quoted" in system:
            data = json.loads(wire["messages"][-1]["content"])
            assert data["quotes"] == [wrong] and data["candidate"]["text"] == intro + wrong
            assert "tools" not in wire and wire["response_format"] == {"type": "json_object"}
            repairs.append(data)
            reply = {wrong: correction + ("代码已经自动运行。" if broader_defect else "")}
            if len(repairs) == 1 and not broader_defect:
                reply["interaction"] = {"type": "none"}
        elif len(reviews) == 2:
            assert broader_defect and wire["tools"]
            data = json.loads(wire["messages"][-1]["content"])
            assert data["issues"][0]["code"] == "invented_run"
            reply = {**json.loads(data["previous_candidate"]), "text": intro + correction}
        else:
            assert "exact visible code" in system
            return original.transport.handle_request(request)
        return httpx.Response(200, json=body(json.dumps(reply, ensure_ascii=False)))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert len(prepared) == 1 and len(client.get(artifacts).json()) == 1
    assert len(reviews) == (3 if broader_defect else 2)
    assert len(repairs) == (1 if broader_defect else 2)
    with database.transaction(snapshot=True) as connection:
        calls = connection.execute(
            "SELECT policy_snapshot->>'review_scope' AS scope FROM runtime.external_calls "
            "WHERE run_id=%s AND policy_snapshot->>'stage'='delivery_review.v1' ORDER BY step",
            (accepted.run_id,),
        ).fetchall()
        assert [call["scope"] for call in calls] == [
            "full", "operation_impact", *(["full"] if broader_defect else []),
        ]
    turn = next(item for item in tutor.turn_history(session.token, conversation.id)
                if item.id == accepted.turn_id)
    assert turn.assistant_text == intro + correction
    assert str(turn.learning_interaction.exact_handle) == prepared[0]["id"]


def test_unknown_handoff_stays_unpublished_and_is_not_dispatched_again(node_scene, session):
    client, root, _, conversation, tutor, settings = node_scene
    accepted = say(node_scene, "这行是什么意思？")
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json=body("它会显示一行问候。"))
        raise httpx.ReadTimeout("No provider receipt")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(handle)))
    for _ in range(3):
        loop.run(accepted.run_id)
    assert len(calls) == 2 and "tools" not in calls[1]
    assert tutor.get(session.token, accepted.run_id).status == "blocked_unknown"
    turn = next(item for item in tutor.turn_history(session.token, conversation.id)
                if item.id == accepted.turn_id)
    assert turn.assistant_text is None and turn.pacing is None
    assert client.get(root).json()["node_window"]["next_step"] == "hold"
