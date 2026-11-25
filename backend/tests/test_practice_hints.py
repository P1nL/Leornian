import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_practice_assistance import assisted_setup as assisted_setup
from test_practice_assistance import introduce
from test_python_execution import python_setup as python_setup
from test_teaching_delivery import body, drain, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.assistance import PracticeAssistance
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionCancelRunAction,
    CompositionDirectAnswerAction,
    CompositionHintAction,
    CompositionHintBinding,
    CompositionRespondAction,
    CompositionRunAction,
)
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.shared_kernel.errors import BusinessError

HINTS = [
    {"level": 1, "purpose": "concept",
     "text": "Recall how an iteration carries a state forward while the input is processed."},
    {"level": 2, "purpose": "strategy",
     "text": "Trace the task's changing state, separating one step from the final state."},
    {"level": 3, "purpose": "next_step",
     "text": "Write the state around the first step, then continue the same rule yourself."},
]


def introduce_hints(
    session, setup, *, direct=True, original_capability=True, reject=False, leak=False,
    reply_leak=False,
):
    calls, prepared = [], []
    capabilities = ([setup["capability"]] if original_capability else []) + [
        "learning_hints.v1",
    ] + (["learning_direct_answers.v1"] if direct else [])
    turn = TurnInput(
        text="Introduce ordinary practice with private H1-H3, requested in order by the learner.",
        focus=setup["focus"], presentation_capabilities={
            "versions": ["learning_composition.v2"], "actions": capabilities,
        },
    )
    key = str(uuid4())
    accepted = setup["tutor"].submit(session.token, setup["conversation"].id, key, turn)

    def tool(name, args):
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": name, "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }]}, "finish_reason": "tool_calls",
        }]})

    def handle(request):
        wire = json.loads(request.content)
        calls.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            if prepared[0]["status"] == "completed":
                assert "graduated_hint_checks" in payload
                assert all(hint["text"] in json.dumps(payload) for hint in HINTS)
            else:
                assert "graduated_hint_checks" not in payload
                assert not any(hint["text"] in json.dumps(payload) for hint in HINTS)
            decision = report(payload, bad=bool(reject))
            if reject == "needs_input":
                decision["verdict"] = "needs_input"
                for check in decision["checks"]:
                    check["verdict"] = "needs_input"
                    check["issues"][0]["repair_instruction"] = HINTS[2]["text"]
            return httpx.Response(200, json=body(json.dumps(decision)))
        if wire["messages"][-1]["role"] != "tool":
            return tool(setup["listing"], {})
        value = json.loads(wire["messages"][-1]["content"])
        if "items" in value:
            source = next(
                item for item in value["items"]
                if item["content_ref"]["id"] == str(setup["pack_id"])
                and item["content_ref"]["slot"] == "practice_1"
            )
            definition = setup["define"](source)
            component = definition["components"][0]["id"]
            if leak:
                definition["title"] = HINTS[0]["text"]
            return tool("prepare_learning_hint_composition", {
                "command_key": "owned-graduated-hints", "definition": definition,
                "owner_bindings": [{"component_id": component, "candidate_id": source["id"]}],
                "hint_bindings": [{"component_id": component, "hints": HINTS}],
            })
        prepared.append(value)
        return httpx.Response(200, json=body(json.dumps({
            "text": HINTS[0]["text"] if reply_leak else
            "Hints stay private until you explicitly request each next level.",
            "interaction": {
                "type": "artifact", "exact_handle": value["candidate"]["id"],
                "intent": "introduce_only",
            } if value["status"] == "completed" else {"type": "none"},
        })))

    gateway = ChatCompletionsGateway(setup["settings"], httpx.MockTransport(handle))
    if reject or reply_leak:
        for _ in range(8):
            AgentLoop(setup["tutor"], gateway).run(accepted.run_id)
            if reply_leak and len(calls) == 3 or (
                reject and calls and "Independently review" in calls[-1]["messages"][0]["content"]
            ):
                break
        assert len(calls) == (3 if reply_leak else 4)
        assert setup["tutor"].delivery_task(session.token, accepted.delivery_task_id).status != (
            "accepted"
        )
    else:
        task = drain(setup["tutor"], setup["settings"], accepted, gateway, session.token)
        assert task.status == "accepted" and len(calls) == 4
    return accepted, key, turn, prepared, calls


def current(session, setup):
    summary = setup["flow"].list_v2(session.token, setup["conversation"].id)[0]
    return setup["flow"].get_v2(
        session.token, summary.conversation_id, summary.id,
        direct_answer_capability="learning_direct_answers.v1", hint_capability="learning_hints.v1",
        program_capability="learning_programs.v1", response_capability="learning_responses.v1",
    )


def command(view, level):
    return CompositionHintAction(
        action="request_hint", component_id=view.component_bindings[0].component_id,
        level=level, client_action_id=uuid4(), expected_artifact_revision=view.revision,
    )


@pytest.mark.parametrize("assisted_setup", [
    "choice", "python", "multiple", "prediction", "short", "ordering", "line_review",
    "sqlite", "project",
], indirect=True)
def test_checked_hint_series_sequential_release_replay_private_reader_and_original_owners(
    database, workflow, session, assisted_setup,
):
    setup = assisted_setup
    accepted, key, turn, prepared, _ = introduce_hints(session, setup)
    assert setup["tutor"].submit(session.token, setup["conversation"].id, key, turn) == accepted
    with pytest.raises(BusinessError, match="support changed"):
        setup["tutor"].submit(session.token, setup["conversation"].id, key, turn.model_copy(update={
            "presentation_capabilities": turn.presentation_capabilities.model_copy(update={
                "actions": [setup["capability"], "learning_direct_answers.v1"],
            }),
        }))
    assert prepared[0]["hint_bindings"][0]["hints"] == HINTS
    view = current(session, setup)
    binding = view.component_bindings[0]
    assert binding.hint_receipts == [] and binding.next_hint_level == 1 and binding.result is None
    assert all(hint["text"] not in view.model_dump_json() for hint in HINTS)
    assert all(
        hint["text"] not in workflow.snapshot(session.token).model_dump_json() for hint in HINTS
    )
    client = TestClient(create_app(setup["settings"]))
    path = f"/v2/conversations/{view.conversation_id}/learning-artifacts/{view.id}"
    headers = {"Authorization": "Bearer " + session.token}
    readers = {
        "direct_answer_capability": "learning_direct_answers.v1",
        "response_capability": "learning_responses.v1",
        "program_capability": "learning_programs.v1",
    }
    assert client.get(path, headers=headers, params=readers).status_code == 409
    for level in (2, 3):
        with pytest.raises(BusinessError, match="in order"):
            setup["flow"].action(session.token, view.conversation_id, view.id, command(view, level))
    first = command(view, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(
            lambda _: setup["flow"].action(session.token, view.conversation_id, view.id, first),
            range(2),
        ))
    assert replies[0] == replies[1]
    shown = current(session, setup)
    receipt = shown.component_bindings[0].hint_receipts[0]
    assert receipt.id == replies[0].result_id and receipt.content.model_dump() == HINTS[0]
    assert receipt.hint_identity == shown.content_ref.public_identity
    assert shown.revision == 2 and shown.component_bindings[0].next_hint_level == 2
    assert shown.component_bindings[0].result is None
    assert all(hint["text"] not in shown.model_dump_json() for hint in HINTS[1:])
    assert setup["flow"].action_receipt(
        session.token, view.conversation_id, view.id, first.client_action_id,
    ) == replies[0]
    assert "content" not in replies[0].model_dump()
    assert current(session, setup) == shown
    with pytest.raises(BusinessError, match="changed"):
        setup["flow"].action(session.token, view.conversation_id, view.id, command(view, 2))
    for level in (2, 3):
        setup["flow"].action(session.token, shown.conversation_id, shown.id, command(shown, level))
        shown = current(session, setup)
        assert shown.component_bindings[0].result is None
    assert len(shown.component_bindings[0].hint_receipts) == 3
    assert shown.component_bindings[0].next_hint_level is None
    assert "request_hint" not in shown.component_bindings[0].allowed_actions
    direct = CompositionDirectAnswerAction(
        action="request_direct_answer", component_id=binding.component_id,
        client_action_id=uuid4(), expected_artifact_revision=shown.revision,
    )
    setup["flow"].action(session.token, shown.conversation_id, shown.id, direct)
    final = current(session, setup)
    assert len(final.component_bindings[0].hint_receipts) == 3
    assert final.component_bindings[0].assistance_receipt is not None
    assert final.component_bindings[0].result is None
    with database.transaction() as connection:
        receipts = PracticeAssistance(connection).hints(
            session.actor, setup["pack_id"], "practice_1",
        )
        assert [receipt.level for receipt in receipts] == [1, 2, 3]
        for receipt in receipts:
            assert connection.execute(
                "SELECT count(*) AS n FROM item_bank.exposure_facts "
                "WHERE actor_id=%s AND receipt_key=%s",
                (session.actor.id, f"assistance:{receipt.id}"),
            ).fetchone()["n"] == 1
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.node_progress and not snapshot.execution_progress


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
def test_hint_receipt_atomic_rollback_and_later_hint_keeps_original_wrong_grade(
    database, workflow, session, assisted_setup, monkeypatch,
):
    setup = assisted_setup
    introduce_hints(session, setup, direct=False)
    view = current(session, setup)
    assert "request_direct_answer" not in view.component_bindings[0].allowed_actions
    action = command(view, 1)

    def fail(*args, **kwargs):
        raise RuntimeError("owned hint exposure rollback")

    with monkeypatch.context() as patch:
        patch.setattr(Exposures, "record", fail)
        with pytest.raises(RuntimeError, match="rollback"):
            setup["flow"].action(session.token, view.conversation_id, view.id, action)
    with database.transaction() as connection:
        assert PracticeAssistance(connection).hints(
            session.actor, setup["pack_id"], "practice_1",
        ) == []
    assert current(session, setup).revision == 1
    setup["flow"].action(session.token, view.conversation_id, view.id, action)
    shown = current(session, setup)
    second = command(shown, 2)
    result = setup["flow"].action(session.token, shown.conversation_id, shown.id, second)
    shown = current(session, setup)
    setup["flow"].action(session.token, shown.conversation_id, shown.id, CompositionRespondAction(
        action="respond_component", component_id=shown.component_bindings[0].component_id,
        expected_artifact_revision=shown.revision, client_action_id=uuid4(),
        payload={"selected_key": "B"},
    ))
    answered = current(session, setup)
    original = answered.component_bindings[0].result
    assert original.correct is False
    with pytest.raises(BusinessError, match="自由练习"):
        setup["flow"].action(
            session.token, answered.conversation_id, answered.id, command(answered, 3),
        )
    after = current(session, setup)
    assert after.component_bindings[0].result == original
    assert result.result_id == after.component_bindings[0].hint_receipts[1].id
    assert result.result_id != original.id
    assert not workflow.snapshot(session.token).node_progress
    KnowledgeWorkflow(database).revoke(session.token, setup["source"].id, 1)
    with pytest.raises(BusinessError):
        current(session, setup)
    assert setup["flow"].action_receipt(
        session.token, view.conversation_id, view.id, second.client_action_id,
    ) == result
    with pytest.raises(BusinessError):
        setup["flow"].action(session.token, view.conversation_id, view.id, CancelAction(
            action="cancel", client_action_id=uuid4(), expected_artifact_revision=after.revision,
        ))


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
def test_legacy_owner_has_no_hints_or_new_read_requirement(session, assisted_setup):
    setup = assisted_setup
    introduce(session, setup, assisted=False)
    view = current(session, setup)
    assert "hint_profile" not in view.component_bindings[0].model_dump()
    with pytest.raises(BusinessError, match="does not allow"):
        setup["flow"].action(session.token, view.conversation_id, view.id, command(view, 1))


@pytest.mark.parametrize("assisted_setup", ["python"], indirect=True)
def test_running_owner_cannot_release_a_hint_and_exact_cancel_does_not_auto_request_one(
    database, session, assisted_setup,
):
    setup = assisted_setup
    introduce_hints(session, setup)
    view = current(session, setup)
    component = view.component_bindings[0].component_id
    setup["flow"].action(session.token, view.conversation_id, view.id, CompositionRunAction(
        action="run_component", component_id=component, client_action_id=uuid4(),
        expected_artifact_revision=view.revision,
        payload={"code": "print(0)", "previous_attempt_id": None, "retry": False},
    ))
    queued = current(session, setup)
    binding = queued.component_bindings[0]
    assert binding.state == "running" and binding.next_hint_level is None
    assert "request_hint" not in binding.allowed_actions
    with pytest.raises(BusinessError, match="does not allow hints"):
        setup["flow"].action(session.token, queued.conversation_id, queued.id, command(queued, 1))
    cancel = CompositionCancelRunAction(
        action="cancel_component_run", component_id=component,
        client_action_id=uuid4(), expected_artifact_revision=queued.revision,
        expected_attempt_id=binding.result.id,
    )
    setup["flow"].action(session.token, queued.conversation_id, queued.id, cancel)
    stopped = current(session, setup)
    assert stopped.component_bindings[0].next_hint_level == 1
    with database.transaction() as connection:
        assert not PracticeAssistance(connection).hints(
            session.actor, setup["pack_id"], "practice_1",
        )


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
@pytest.mark.parametrize("failure", ["no_original_capability", "visible_hint"])
def test_hint_capability_does_not_grant_owner_authority_or_reveal_locked_text(
    session, assisted_setup, failure,
):
    _, _, _, prepared, _ = introduce_hints(
        session, assisted_setup, original_capability=failure != "no_original_capability",
        leak=failure == "visible_hint",
    )
    assert prepared[0]["status"] == "waiting_dependency"
    assert prepared[0]["code"] == "precondition_failed"
    assert not assisted_setup["flow"].list_v2(session.token, assisted_setup["conversation"].id)


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
@pytest.mark.parametrize("reject", [True, "needs_input"])
def test_rejected_independent_hint_check_never_publishes_or_records_assistance(
    database, workflow, session, assisted_setup, reject,
):
    setup = assisted_setup
    accepted, _, _, prepared, _ = introduce_hints(session, setup, reject=reject)
    assert prepared[0]["status"] == "completed"
    assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
    assert all(
        hint["text"] not in workflow.snapshot(session.token).model_dump_json() for hint in HINTS
    )
    with database.transaction() as connection:
        assert not PracticeAssistance(connection).hints(
            session.actor, setup["pack_id"], "practice_1",
        )
    setup["tutor"].cancel(session.token, accepted.run_id)


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
def test_locked_hint_in_assistant_text_never_reaches_public_reply(
    workflow, session, assisted_setup,
):
    setup = assisted_setup
    accepted, _, _, _, _ = introduce_hints(session, setup, reply_leak=True)
    assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
    assert all(
        hint["text"] not in workflow.snapshot(session.token).model_dump_json() for hint in HINTS
    )
    setup["tutor"].cancel(session.token, accepted.run_id)


def test_hint_contract_requires_distinct_ordered_purposes_and_identity_only_commands():
    assert CompositionHintBinding(component_id="answer", hints=HINTS)
    for invalid in (
        [HINTS[1], HINTS[0], HINTS[2]],
        [HINTS[0], {**HINTS[1], "text": HINTS[0]["text"]}, HINTS[2]],
        [HINTS[0], {**HINTS[1], "purpose": "concept"}, HINTS[2]],
    ):
        with pytest.raises(ValidationError):
            CompositionHintBinding(component_id="answer", hints=invalid)
    with pytest.raises(ValidationError):
        CompositionHintAction(
            action="request_hint", component_id="answer", level=1, client_action_id=uuid4(),
            expected_artifact_revision=1, payload={"text": "Caller supplied private content."},
        )
