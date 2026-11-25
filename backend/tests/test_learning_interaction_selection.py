import json
from uuid import uuid4

import httpx
import pytest
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_learning_artifacts import selected
from test_teaching_delivery import body, drain, provider, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.teaching_delivery import TeachingDelivery
from leornian.modules.tutor.contracts import TurnInput


def selecting_provider(settings, *, before_review=None):
    sent, options = [], []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            if before_review:
                before_review()
            return httpx.Response(
                200, json=body(json.dumps(report(json.loads(wire["messages"][-1]["content"]))))
            )
        if wire["messages"][-1]["role"] == "tool":
            result = json.loads(wire["messages"][-1]["content"])
            options.extend(result["items"])
            return httpx.Response(200, json=body(json.dumps({
                "text": "Try this practice. It has not been answered or executed.",
                "interaction": {
                    "type": "artifact", "exact_handle": options[0]["id"],
                    "intent": "introduce_only",
                },
            })))
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{
                        "id": "owned-candidates", "type": "function",
                        "function": {
                            "name": "list_learning_artifact_candidates", "arguments": "{}",
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), sent, options


@pytest.mark.parametrize("anchor_lesson", [False, True])
def test_model_selects_only_listed_practice_and_delivers_atomically(
    session, workflow, learning_setup, anchor_lesson
):
    setup = learning_setup
    candidate = selected(session, setup)
    key = str(uuid4())
    focus = candidate.focus
    if anchor_lesson:
        focus = focus.model_copy(
            update={"lesson_id": workflow.snapshot(session.token).lessons[0].id}
        )
    data = TurnInput(text="Give me suitable practice.", focus=focus)
    accepted = setup["tutor"].submit(session.token, setup["conversation"].id, key, data)
    gateway, sent, options = selecting_provider(setup["settings"])
    task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
    assert task.status == "accepted" and len(sent) == 3
    assert options and all(o["content_ref"]["slot"].startswith("practice_") for o in options)
    assert "correct_key" not in json.dumps(options)
    assert "explanation" not in json.dumps(options)
    artifacts = setup["flow"].list(session.token, setup["conversation"].id)
    assert len(artifacts) == 1
    snapshot = workflow.snapshot(session.token)
    turn = next(t for p in snapshot.turns for t in p.turns if t.id == accepted.turn_id)
    assert turn.assistant_text.startswith("Try this practice.")
    assert turn.learning_interaction.type == "artifact"
    assert turn.context_focus == focus
    assert str(turn.learning_interaction.exact_handle) == options[0]["id"]
    assert not snapshot.choice_results and not snapshot.attempts and not snapshot.python_attempts
    assert setup["tutor"].submit(
        session.token, setup["conversation"].id, key, data
    ) == accepted
    assert len(setup["flow"].list(session.token, setup["conversation"].id)) == 1


@pytest.mark.parametrize("interaction", ["none", "composer"])
def test_closed_nonartifact_selection_is_persisted_without_action(
    session, workflow, learning_setup, interaction
):
    setup = learning_setup
    accepted = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()),
        TurnInput(text="Ask me a question."),
    )
    gateway, _, _ = provider(setup["settings"], author=json.dumps({
        "text": "What would you like to learn?", "interaction": {"type": interaction},
    }))
    task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
    assert task.status == "accepted"
    snapshot = workflow.snapshot(session.token)
    turn = next(t for p in snapshot.turns for t in p.turns if t.id == accepted.turn_id)
    assert turn.assistant_text == "What would you like to learn?"
    assert turn.learning_interaction.type == interaction
    assert not snapshot.learning_artifacts


def test_model_cannot_guess_a_valid_but_unlisted_handle(session, learning_setup):
    setup = learning_setup
    candidate = selected(session, setup)
    accepted = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()),
        TurnInput(text="Give me practice.", focus=candidate.focus),
    )
    gateway, _, _ = provider(setup["settings"], author=json.dumps({
        "text": "Try this.", "interaction": {
            "type": "artifact", "exact_handle": str(candidate.id), "intent": "introduce_only",
        },
    }))
    AgentLoop(setup["tutor"], gateway).run(accepted.run_id)
    assert setup["tutor"].delivery_task(
        session.token, accepted.delivery_task_id
    ).status != "accepted"
    assert not setup["flow"].list(session.token, setup["conversation"].id)
    setup["tutor"].cancel(session.token, accepted.run_id)


def test_selection_cas_failure_has_no_half_published_reply_or_artifact(
    database, session, workflow, learning_setup
):
    setup = learning_setup
    candidate = selected(session, setup)
    accepted = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()),
        TurnInput(text="Give me practice.", focus=candidate.focus),
    )

    def conflict():
        with database.transaction() as connection:
            connection.execute(
                "UPDATE tutor.conversations SET teaching_revision=teaching_revision+1 WHERE id=%s",
                (setup["conversation"].id,),
            )

    gateway, _, _ = selecting_provider(setup["settings"], before_review=conflict)
    task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
    assert task.status == "superseded"
    snapshot = workflow.snapshot(session.token)
    turn = next(t for p in snapshot.turns for t in p.turns if t.id == accepted.turn_id)
    assert turn.assistant_text is None and turn.learning_interaction is None
    assert not snapshot.learning_artifacts
    assert not any(e.payload.learning_artifact_id for e in snapshot.events)
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT 1 FROM tutor.learning_turn_candidates WHERE turn_id=%s", (accepted.turn_id,)
        ).fetchone() is None


def test_old_run_keeps_frozen_tools_and_reply_semantics(
    database, session, workflow, learning_setup
):
    setup = learning_setup
    accepted = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()), TurnInput(text="Explain iteration.")
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE runtime.runs SET tool_contracts=tool_contracts-"
            "'list_learning_artifact_candidates' WHERE id=%s",
            (accepted.run_id,),
        )
    gateway, sent, _ = provider(setup["settings"])
    assert drain(
        setup["tutor"], setup["settings"], accepted, gateway, session.token
    ).status == "accepted"
    assert "list_learning_artifact_candidates" not in {
        t["function"]["name"] for t in sent[0]["tools"]
    }
    turn = next(
        t for p in workflow.snapshot(session.token).turns
        for t in p.turns if t.id == accepted.turn_id
    )
    assert turn.learning_interaction is None


@pytest.mark.parametrize("interaction", [
    {"type": "artifact", "exact_handle": str(uuid4()), "intent": "run"},
    {"type": "artifact", "exact_handle": str(uuid4()), "intent": "introduce_only", "command": "id"},
    {"type": "arbitrary_widget", "html": "<script>run()</script>"},
    {"type": "artifact", "intent": "introduce_only"},
])
def test_interaction_output_is_closed(interaction):
    with pytest.raises(ValueError):
        TeachingDelivery.candidate(
            {"kind": "teaching", "fragments": [],
             "context_manifest": {"learning_interaction_contract": 1}},
            json.dumps({"text": "Try this.", "interaction": interaction}),
        )
