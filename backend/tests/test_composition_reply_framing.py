import json

import httpx
import pytest
from test_composition_delivery import composition_provider, request
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_teaching_delivery import body
from test_tutor_runtime import calls

from leornian.agent_runtime.contracts import RoleSpec
from leornian.agent_runtime.gateway import ChatCompletionsGateway, ModelProtocolError
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.teaching_delivery import TeachingDelivery
from leornian.modules.tutor.learning_artifacts import LearningArtifacts
from leornian.modules.tutor.teaching_guidance import INTERACTION_SELECTION_POLICY

ENVELOPE = json.dumps({
    "text": "Observe discovery and the shared queue.",
    "interaction": {
        "type": "artifact",
        "exact_handle": "11111111-1111-4111-8111-111111111111",
        "intent": "introduce_only",
    },
})
FRAMINGS = [
    ("An introduction outside the envelope.\n\n", ""),
    ("", "\n\nAn explanation after the envelope."),
    ("```json\n", "\n```"),
]


@pytest.fixture
def interactive_task():
    return {
        "kind": "teaching", "context_manifest": {"learning_interaction_contract": 1},
        "fragments": [],
    }


@pytest.mark.parametrize(("prefix", "suffix"), FRAMINGS, ids=["prefix", "suffix", "fence"])
def test_embedded_learning_reply_requires_author_format_repair(
    interactive_task, prefix, suffix,
):
    with pytest.raises(ValueError, match="complete LearningReply JSON"):
        TeachingDelivery.candidate(interactive_task, prefix + ENVELOPE + suffix)
    assert interactive_task["fragments"] == []


@pytest.mark.parametrize("text", [
    ENVELOPE.replace("discovery", "discovery\n"),
    ENVELOPE[:-1],
])
def test_malformed_interaction_is_not_downgraded_to_plain_text(interactive_task, text):
    with pytest.raises(ValueError, match="complete LearningReply JSON"):
        TeachingDelivery.candidate(interactive_task, text)
    interactive_task["context_manifest"] = {}
    assert TeachingDelivery.candidate(interactive_task, text) == text


def test_plain_text_and_unrelated_json_keep_their_original_representation(interactive_task):
    for text in (
        "A queue stores discovered vertices in order.",
        '{"queue":["Y","X"],"visited":["Y"]}',
        'For example, {"queue":["Y"]} describes data rather than a reply envelope.',
    ):
        assert TeachingDelivery.candidate(interactive_task, text) == text
    interactive_task["fragments"] = [{"text": "The first explanation."}]
    assert TeachingDelivery.candidate(interactive_task, json.dumps({
        "fragment": {"text": "The remaining explanation."}, "complete": True,
    })) == "The first explanation.\n\nThe remaining explanation."


def test_paced_question_shows_a_valid_text_reply_shape_and_keeps_read_tools(interactive_task):
    manifest = {**interactive_task["context_manifest"], "node_pacing": True,
                "teaching_session": {"branch_id": "current-branch"}}
    task = {**interactive_task, "context_manifest": manifest, "output_multiplier": 1, "issues": []}
    role = RoleSpec(
        allowed_tools=("learning_get_context",), context_manifest=manifest,
        messages=[
            {"role": "system", "content": "Teach."},
            {"role": "user", "content": "我点过运行呀。"},
        ],
    )
    author = TeachingDelivery.author_role(role, task)
    assert author.allowed_tools == role.allowed_tools and author.messages[-1] == role.messages[-1]
    shape, _ = json.JSONDecoder().raw_decode(author.messages[0]["content"].split("Shape: ")[1])
    candidate = json.loads(TeachingDelivery.candidate(task, json.dumps(shape)))
    assert candidate["interaction"] == {"type": "none"} and candidate["pacing"] == {
        **shape["pacing"], "check_topic": None,
    }


def test_legacy_noninteractive_reply_does_not_reinterpret_embedded_envelopes(interactive_task):
    interactive_task["context_manifest"] = {}
    for prefix, suffix in FRAMINGS:
        text = prefix + ENVELOPE + suffix
        assert TeachingDelivery.candidate(interactive_task, text) == text


def test_whole_learning_reply_can_teach_json_inside_its_text(interactive_task):
    envelope = json.loads(ENVELOPE)
    envelope["text"] = "The following is an example, not a second action:\n```json\n" + (
        ENVELOPE
    ) + "\n```"
    result = TeachingDelivery.candidate(interactive_task, json.dumps(envelope))
    assert json.loads(result) == envelope


def test_final_plain_fragment_cannot_smuggle_an_embedded_learning_reply(interactive_task):
    interactive_task["fragments"] = [{"text": "The first explanation."}]
    with pytest.raises(ValueError, match="complete LearningReply JSON"):
        TeachingDelivery.candidate(interactive_task, json.dumps({
            "fragment": {"text": "A final explanation.\n\n" + ENVELOPE},
            "complete": True,
        }))
    assert interactive_task["fragments"] == [{"text": "The first explanation."}]


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("code", [
    "learning_reply_selection_required",
    "learning_reply_framing_required",
    "missing_preview_action",
])
def test_only_current_interactive_format_repair_closes_tools_and_requests_json(interactive, code):
    manifest = {"learning_interaction_contract": 1} if interactive else {}
    role = RoleSpec(
        allowed_tools=("prepare_learning_composition",),
        messages=[{"role": "system", "content": "Teach the learner."}],
        context_manifest=manifest,
    )
    task = {
        "kind": "teaching", "fragments": [], "candidate": None,
        "context_manifest": manifest, "issues": [{"code": code}],
        "repair_strategy": "diagnostic", "output_multiplier": 1,
    }
    repaired = TeachingDelivery.author_role(role, task)
    format_only = interactive and code in {
        "learning_reply_selection_required", "learning_reply_framing_required",
    }
    assert repaired.json_output == format_only
    assert repaired.allowed_tools == (() if format_only else role.allowed_tools)
    assert repaired.messages[-1]["role"] == "user"
    assert role.allowed_tools == ("prepare_learning_composition",)
    assert role.json_output is False
    assert role.messages == [{"role": "system", "content": "Teach the learner."}]
    if format_only:
        repair = json.loads(repaired.messages[-1]["content"])
        assert "Correct only the final reply framing" in repair["instruction"]
        assert "previous_candidate can be an older rejected" in repair["instruction"]


@pytest.mark.parametrize("wire_format", ["embedded", "raw_newline", "plain"])
def test_runtime_repairs_mixed_reply_before_independent_review_and_atomic_delivery(
    database, workflow, session, consumer, wire_format,
):
    tutor, settings, conversation, *_ = consumer
    accepted = request(tutor, session, conversation)
    artifacts = LearningArtifactWorkflow(database)
    introduction = "Observe discovery and the shared queue.\nKeep the queue and graph linked."
    wires, before_review = [], []
    bad_content = None
    whole_reply = None

    def observe_before_acceptance():
        assert not artifacts.list_v2(session.token, conversation.id)
        turn = next(
            turn for turn in tutor.turn_history(session.token, conversation.id)
            if turn.id == accepted.turn_id
        )
        assert turn.assistant_text is None and turn.learning_interaction is None
        before_review.append(turn.id)

    original, _, prepared = composition_provider(
        settings, reply_text=introduction, conflict=observe_before_acceptance,
    )

    def handle(http_request):
        nonlocal bad_content, whole_reply
        wire = json.loads(http_request.content)
        wires.append(wire)
        reviewing = "Independently review" in wire["messages"][0]["content"]
        if bad_content is not None and not reviewing:
            assert whole_reply is not None
            assert wire["messages"][-1]["role"] == "user"
            repair = json.loads(wire["messages"][-1]["content"])
            assert repair["issues"]
            assert any(message["role"] == "tool" for message in wire["messages"][:-1])
            assert wire.get("response_format") == {"type": "json_object"}
            assert "tools" not in wire
            return httpx.Response(200, json=body(whole_reply))
        response = original.transport.handle_request(http_request)
        if not reviewing and wire["messages"][-1]["role"] == "tool":
            payload = response.json()
            whole_reply = payload["choices"][0]["message"]["content"]
            bad_content = {
                "embedded": "A long introduction outside the JSON.\n\n" + whole_reply,
                "raw_newline": whole_reply.replace("\\n", "\n"),
                "plain": introduction,
            }[wire_format]
            payload["choices"][0]["message"]["content"] = bad_content
            return httpx.Response(200, json=payload)
        return response

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    loop = AgentLoop(tutor, gateway)
    loop.run(accepted.run_id)
    loop.run(accepted.run_id)
    assert len(wires) == 2 and len(prepared) == 1
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "repairing"
    assert tutor.get(session.token, accepted.run_id).status == "queued"
    assert not artifacts.list_v2(session.token, conversation.id)
    turn = next(
        turn for turn in tutor.turn_history(session.token, conversation.id)
        if turn.id == accepted.turn_id
    )
    assert turn.assistant_text is None and turn.learning_interaction is None
    with database.transaction() as connection:
        task = connection.execute(
            "SELECT candidate,candidate_call_id,issues FROM tutor.delivery_tasks WHERE id=%s",
            (accepted.delivery_task_id,),
        ).fetchone()
        assert task["candidate"] is None and task["candidate_call_id"] is None
        error_code = (
            "learning_reply_selection_required" if wire_format == "plain"
            else "learning_reply_framing_required"
        )
        assert [issue["code"] for issue in task["issues"]] == [error_code]
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.delivery_checks WHERE task_id=%s",
            (accepted.delivery_task_id,),
        ).fetchone()["n"] == 0
    records = calls(database, accepted.run_id)
    assert json.loads(records[1]["response_body"])["choices"][0]["message"]["content"] == (
        bad_content
    )
    assert records[1]["status"] == "result_recorded" and records[1]["applied"]

    loop.run(accepted.run_id)
    assert len(wires) == 3
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "checking"
    repair = next(
        json.loads(message["content"]) for message in wires[2]["messages"]
        if message["role"] == "user" and '"repair_strategy"' in message["content"]
    )
    assert repair["repair_strategy"] == "diagnostic"
    assert repair["issues"][0]["code"] == error_code
    if wire_format == "plain":
        assert "Reuse its tool receipt" in repair["issues"][0]["repair_instruction"]
    else:
        assert "invalid JSON syntax" in repair["issues"][0]["repair_instruction"]
        assert "already has a completed" not in repair["issues"][0]["repair_instruction"]
    assert repair["issues"][0]["previous_response"] == bad_content
    assert not artifacts.list_v2(session.token, conversation.id)
    assert not before_review
    for wire in wires:
        instruction = wire["messages"][0]["content"]
        assert INTERACTION_SELECTION_POLICY in instruction
        assert "JSON as the entire final response, without surrounding prose" in instruction
        assert "or Markdown fences; put every explanation in its text field" in instruction
        assert "Never append the interaction JSON to an otherwise plain-text answer" in instruction

    loop.run(accepted.run_id)
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "accepted"
    assert len(wires) == 4 and len(prepared) == 1
    assert before_review == [accepted.turn_id]
    records = calls(database, accepted.run_id)
    review = json.loads(wires[-1]["messages"][-1]["content"])
    assert review["interaction_selection_checks"] == INTERACTION_SELECTION_POLICY
    assert review["candidate_call_id"] == str(records[2]["id"])
    candidate = review["candidate"]
    if isinstance(candidate, str):
        candidate = json.loads(candidate)
    assert candidate == json.loads(whole_reply)
    assert candidate["interaction"]["exact_handle"] == prepared[0]["id"]
    assert json.loads(records[1]["response_body"])["choices"][0]["message"]["content"] == (
        bad_content
    )
    summaries = artifacts.list_v2(session.token, conversation.id)
    assert len(summaries) == 1
    view = artifacts.get_v2(session.token, conversation.id, summaries[0].id)
    turn = next(
        turn for turn in tutor.turn_history(session.token, conversation.id)
        if turn.id == accepted.turn_id
    )
    assert turn.assistant_text == introduction
    assert str(turn.learning_interaction.exact_handle) == prepared[0]["id"]
    assert view.source_turn_id == turn.id
    assert str(view.content_ref.id) == prepared[0]["content_ref"]["id"]
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.choice_results and not snapshot.attempts
    assert not snapshot.python_attempts and not snapshot.program_attempts
    assert not snapshot.node_progress and not snapshot.execution_progress


@pytest.mark.parametrize("tool", [
    "prepare_learning_composition",
    "prepare_learning_practice_composition",
    "prepare_learning_response_composition",
    "prepare_learning_code_review_composition",
    "prepare_learning_code_review_composition_v2",
    "prepare_learning_program_composition",
    "prepare_learning_assisted_composition",
    "prepare_learning_hint_composition",
    "prepare_learning_demo_composition",
])
def test_each_preparation_receipt_requires_an_explicit_final_selection(monkeypatch, tool):
    monkeypatch.setattr(Runs, "tool_outputs", lambda _self, _run, name: [{
        "status": "completed", "candidate": {"id": "prepared-candidate"},
    }] if name == tool else [])
    row = {"id": "run", "tool_contracts": {tool: 1}}
    task = {"context_manifest": {"learning_interaction_contract": 1}}
    with pytest.raises(ModelProtocolError, match="learning_reply_selection_required"):
        LearningArtifactWorkflow.validate_reply_in(None, None, row, task, "Use this artifact.")
    task["context_manifest"] = {}
    assert LearningArtifactWorkflow.validate_reply_in(None, None, row, task, "Legacy text.") is None


@pytest.mark.parametrize("result", [
    {"status": "rejected", "candidate": {"id": "not-prepared"}},
    {"status": "unknown"},
    {"status": "completed", "items": []},
])
def test_unsuccessful_preparation_does_not_invent_a_candidate(monkeypatch, result):
    monkeypatch.setattr(Runs, "tool_outputs", lambda *_args: [result])
    assert LearningArtifactWorkflow.validate_reply_in(
        None, None, {"id": "run", "tool_contracts": {"prepare_learning_composition": 1}},
        {"context_manifest": {"learning_interaction_contract": 1}}, "Explain without an artifact.",
    ) is None


def test_prepared_candidate_can_be_explicitly_declined_without_publication(monkeypatch):
    monkeypatch.setattr(LearningArtifacts, "for_turn", lambda *_args: None)
    row = {"id": "run", "scope_id": "conversation", "input_ref": "turn",
           "tool_contracts": {"list_learning_artifact_candidates": 1}}
    reply = LearningArtifactWorkflow.validate_reply_in(
        None, None, row, {"context_manifest": {"learning_interaction_contract": 1}},
        json.dumps({"text": "An explanation is enough; no artifact is attached.",
                    "interaction": {"type": "none"}}),
    )
    assert reply.interaction.type == "none"
