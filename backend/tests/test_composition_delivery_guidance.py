import json
from uuid import uuid4

import pytest
from test_composition_delivery import composition_provider, request
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_teaching_delivery import drain

from leornian.agent_runtime.contracts import RoleSpec
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.teaching_delivery import TeachingDelivery


def test_interactive_author_and_review_guidance_preserves_checked_atomic_exact_handle_delivery(
    database, workflow, session, consumer,
):
    tutor, settings, conversation, *_ = consumer
    accepted = request(tutor, session, conversation)
    artifacts = LearningArtifactWorkflow(database)
    before_acceptance = []

    def observe_before_review_acceptance():
        assert not artifacts.list_v2(session.token, conversation.id)
        turn = next(
            turn for turn in tutor.turn_history(session.token, conversation.id)
            if turn.id == accepted.turn_id
        )
        assert turn.assistant_text is None and turn.learning_interaction is None
        before_acceptance.append(turn.id)

    introduction = "Observe the graph and its shared discovery queue."
    gateway, sent, prepared = composition_provider(
        settings, conflict=observe_before_review_acceptance, reply_text=introduction,
    )
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted" and len(sent) == 3
    assert before_acceptance == [accepted.turn_id]
    assert len(prepared) == 1
    handle = prepared[0]["id"]

    for wire in sent[:2]:
        instruction = wire["messages"][0]["content"]
        assert "final response MUST use the role's interaction JSON" in instruction
        assert "the exact candidate id from a successful tool receipt in this Run" in instruction
        assert "Return that JSON as the entire final response" in instruction
        assert "Never append the interaction JSON" in instruction
        assert "Preparation alone never attaches a presentation." in instruction
        assert "Plain text is only for a reply without an interaction." in instruction
        assert "Do not make dummy tool calls to carry a final answer" in instruction
        assert "use registered tool names exactly, without aliases" in instruction
        assert "do not ask the learner to approve or publish it" in instruction
        assert "narrate pending private review" in instruction
        assert "interaction only on the final complete=true envelope" in instruction

    review = sent[-1]
    instruction = review["messages"][0]["content"]
    assert "Independently review" in instruction
    assert "Artifact jobs with accepted/queued tool results are not delivered yet" in instruction
    assert "Distinguish those background document jobs" in instruction
    assert "this reply publish atomically only after this review accepts" in instruction
    assert "Assess its learner-facing introduction at that publication point" in instruction
    assert "Do not require it to announce pending approval" in instruction
    assert "execution, grading, mastery or other missing owner receipts" in instruction
    payload = json.loads(review["messages"][-1]["content"])
    assert "locally toggled unified inline diff" in payload["composition_checks"]
    assert "not separate left/right panes" in payload["composition_checks"]
    assert "Reject text or labels" in payload["composition_checks"]
    candidate = payload["candidate"]
    if isinstance(candidate, str):
        candidate = json.loads(candidate)
    assert candidate["text"] == introduction
    assert candidate["interaction"]["exact_handle"] == handle
    assert candidate["interaction"]["intent"] == "introduce_only"
    receipts = [
        json.loads(message["content"]) for message in payload["actual_author_input"]
        if message["role"] == "tool"
    ]
    assert any(
        receipt["status"] == "completed" and receipt["candidate"]["id"] == handle
        for receipt in receipts
    )
    summaries = artifacts.list_v2(session.token, conversation.id)
    assert len(summaries) == 1
    view = artifacts.get_v2(session.token, conversation.id, summaries[0].id)
    turn = next(
        turn for turn in tutor.turn_history(session.token, conversation.id)
        if turn.id == accepted.turn_id
    )
    assert turn.assistant_text == introduction
    assert str(turn.learning_interaction.exact_handle) == handle
    assert view.source_turn_id == turn.id
    assert str(view.content_ref.id) == prepared[0]["content_ref"]["id"]
    assert not view.allowed_actions
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.choice_results and not snapshot.attempts
    assert not snapshot.python_attempts and not snapshot.program_attempts
    assert not snapshot.node_progress and not snapshot.execution_progress


def test_legacy_author_without_interaction_manifest_keeps_plain_text_and_original_tools():
    role = RoleSpec(
        messages=[
            {"role": "system", "content": "Teach the exact current question."},
            {"role": "user", "content": "Explain iteration."},
        ],
        allowed_tools=("learning_get_context",),
        context_manifest={"sources": []},
    )
    original = role.model_dump(mode="json")
    task = {
        "kind": "teaching", "fragments": [], "issues": [],
        "context_manifest": {}, "output_multiplier": 1,
    }
    authored = TeachingDelivery.author_role(role, task)
    instruction = authored.messages[0]["content"]
    assert "For ordinary replies return plain text." in instruction
    assert "interaction JSON" not in instruction
    assert '"exact_handle"' not in instruction
    assert "final response MUST" not in instruction
    assert "prepare_learning" not in instruction
    assert authored.allowed_tools == ("learning_get_context",)
    assert authored.context_manifest == {"sources": []}
    assert role.model_dump(mode="json") == original
    assert TeachingDelivery.candidate(task, "A loop visits each element.") == (
        "A loop visits each element."
    )


@pytest.mark.parametrize("manifest_key", [
    "learning_practice_composition_contract",
    "learning_response_composition_contract",
    "learning_program_composition_contract",
    None,
])
def test_owner_review_accounts_for_original_host_prompts_without_duplicating_them(manifest_key):
    task = {
        "kind": "teaching", "candidate_call_id": uuid4(), "candidate": "Try the exercise.",
        "candidate_input": [{"role": "system", "content": "Original author instructions."}],
        "context_manifest": {manifest_key: 1} if manifest_key else {},
        "issues": [], "output_multiplier": 1,
    }
    payload = json.loads(TeachingDelivery.review_role(task).messages[-1]["content"])
    if manifest_key is None:
        assert "practice_owner_checks" not in payload
        return
    checks = payload["practice_owner_checks"]
    assert "owner_bindings[].source.presentation" in checks
    assert "host displays each bound original question/task prompt" in checks
    assert "Python's public sample input/expected output" in checks
    assert "Do not require these host-provided fields" in checks
    assert "Still reject conflicting substitutes" in checks
    assert "answer or locked hint leakage" in checks
    assert "not an execution receipt or a grade" in checks
    assert "event='cancel' cancels the whole artifact regardless of its target" in checks
    assert "Reject owner-targeted static cancel actions" in checks
    assert "separate host-provided controls" in checks


def test_interaction_repair_receives_only_its_selected_successful_preparation():
    handle, other = str(uuid4()), str(uuid4())
    selected = {
        "status": "completed", "candidate": {
            "id": handle, "presentation": {"definition": {"title": "Preserve this composition"}},
        },
        "hint_bindings": [{"component_id": "answer", "text": "Selected private hint."}],
    }
    task = {
        "kind": "teaching", "fragments": [], "repair_strategy": "repair",
        "issues": [{"code": "locked_hint_leak_in_reply"}],
        "candidate": json.dumps({
            "text": "Original introduction.",
            "interaction": {"type": "artifact", "exact_handle": handle, "intent": "introduce_only"},
        }),
        "context_manifest": {"learning_interaction_contract": 1}, "output_multiplier": 1,
        "candidate_input": [
            {"role": "assistant", "content": json.dumps(selected)},
            {"role": "tool", "content": "An unrelated legacy tool message."},
            {"role": "tool", "content": "[]"},
            {"role": "tool", "content": json.dumps({
                "status": "waiting_dependency", "candidate": {"id": handle},
            })},
            {"role": "tool", "content": json.dumps({
                "status": "completed", "candidate": {"id": other},
                "hint_bindings": ["Unselected private hint."],
            })},
            {
                "role": "tool", "content": json.dumps(selected),
                "reasoning_content": "Not a receipt.",
            },
        ],
    }
    role = RoleSpec(
        messages=[{"role": "system", "content": "Introduce the original exercises."}],
        allowed_tools=(), context_manifest=task["context_manifest"],
    )
    authored = TeachingDelivery.author_role(role, task)
    repair = json.loads(authored.messages[-1]["content"])
    assert repair["previous_preparation"] == selected
    assert repair["previous_candidate"] == task["candidate"]
    assert repair["issues"] == task["issues"]
    assert "Unselected private hint." not in authored.messages[-1]["content"]
    assert "Not a receipt." not in authored.messages[-1]["content"]
    assert len(role.messages) == 1


@pytest.mark.parametrize("candidate", [None, "A legacy plain-text introduction."])
def test_non_interactive_repair_does_not_invent_a_previous_preparation(candidate):
    role = RoleSpec(messages=[{"role": "system", "content": "Teach the current question."}])
    task = {
        "kind": "teaching", "fragments": [], "repair_strategy": "repair",
        "issues": [{"code": "unclear_explanation"}], "candidate": candidate,
        "context_manifest": {"learning_interaction_contract": 1}, "candidate_input": [],
        "output_multiplier": 1,
    }
    authored = TeachingDelivery.author_role(role, task)
    repair = json.loads(authored.messages[-1]["content"])
    assert repair["previous_candidate"] == candidate
    assert "previous_preparation" not in repair


def test_demo_review_distinguishes_local_frames_from_server_reports():
    role = TeachingDelivery.review_role({
        "kind": "teaching", "candidate_call_id": uuid4(), "candidate": "Observe the input.",
        "candidate_input": [], "issues": [], "output_multiplier": 1,
        "context_manifest": {"learning_demo_contract": 1},
    })
    checks = json.loads(role.messages[-1]["content"])["demo_interaction_checks"]
    assert "Timeline frames, variables and diagrams are computed locally" in checks
    assert "the server validates inputs and endpoints" in checks
    assert "starting a report starts playback" in checks
    assert "Play, manual stepping and the timeline slider can each advance" in checks
