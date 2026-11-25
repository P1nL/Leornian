import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_composition_practice import definition_for
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_knowledge_responses import publish_responses, response_definition
from test_learning_artifacts import learning_setup as learning_setup
from test_program_compositions import program_definition
from test_program_items import environment
from test_program_practice import program_setup, publish
from test_python_execution import publish_python
from test_python_execution import python_setup as python_setup
from test_teaching_delivery import body, drain, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.assistance import PracticeAssistance
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionDirectAnswerAction,
    CompositionRespondAction,
)
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def assisted_setup(request, database, session, supply_setup):
    kind = request.param
    fixture = None
    base = supply_setup
    if kind == "choice":
        pack = request.getfixturevalue("learning_setup")["pack"]
        listing, define, capability = (
            "list_learning_artifact_candidates", definition_for, "learning_practice.v2",
        )
    elif kind == "python":
        setup = request.getfixturevalue("python_setup")
        publish_python(database, session, setup)
        pack = setup[1]
        listing, define, capability = (
            "list_learning_artifact_candidates", definition_for, "learning_practice.v2",
        )
    elif kind in {"sqlite", "project"}:
        parameters = ("sql_query", "sqlite") if kind == "sqlite" else ("python_project", None)
        fixture = program_setup.__wrapped__(
            database, session, base, [environment(*parameters)],
            SimpleNamespace(param=parameters),
        )
        setup = next(fixture)
        publish(database, session, setup)
        pack = setup[1]
        listing, define, capability = (
            "list_learning_program_candidates", program_definition, "learning_programs.v1",
        )
    else:
        pack, _, _ = publish_responses(database, base, session, kind)
        listing, define, capability = (
            "list_learning_response_candidates", response_definition, "learning_responses.v1",
        )
    settings = replace(
        base[2], delivery_enabled=True, model_context_tokens=128000,
        model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    try:
        yield {
            "pack_id": pack.pack_id if hasattr(pack, "pack_id") else pack.id,
            "settings": settings, "tutor": tutor, "source": base[4],
            "conversation": tutor.conversation(session.token, base[3].goal_id),
            "focus": TeachingFocus(
                kind="node", plan_id=base[3].id, expected_plan_revision=1, node_key="loops",
            ),
            "flow": LearningArtifactWorkflow(database),
            "listing": listing, "define": define, "capability": capability,
        }
    finally:
        if fixture:
            fixture.close()


def introduce(session, setup, *, assisted=True, original_capability=True):
    calls, prepared = [], []
    capabilities = ([setup["capability"]] if original_capability else []) + (
        ["learning_direct_answers.v1"] if assisted else []
    )
    turn = TurnInput(
        text="Introduce ordinary practice; show references only after an explicit request.",
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
            return httpx.Response(200, json=body(json.dumps(report(
                json.loads(wire["messages"][-1]["content"]),
            ))))
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
            return tool(
                "prepare_learning_assisted_composition" if assisted
                else "prepare_learning_practice_composition",
                {
                    "command_key": "owned-direct-reference", "definition": definition,
                    "owner_bindings": [{
                        "component_id": definition["components"][0]["id"],
                        "candidate_id": source["id"],
                    }],
                },
            )
        prepared.append(value)
        return httpx.Response(200, json=body(json.dumps({
            "text": "The learner must explicitly request a reference; no automatic submission.",
            "interaction": {
                "type": "artifact", "exact_handle": value["candidate"]["id"],
                "intent": "introduce_only",
            } if value["status"] == "completed" else {"type": "none"},
        })))

    task = drain(
        setup["tutor"], setup["settings"], accepted,
        ChatCompletionsGateway(setup["settings"], httpx.MockTransport(handle)), session.token,
    )
    assert task.status == "accepted" and len(calls) == 4
    return accepted, key, turn, prepared


def current(session, setup):
    summary = setup["flow"].list_v2(session.token, setup["conversation"].id)[0]
    return setup["flow"].get_v2(
        session.token, summary.conversation_id, summary.id,
        direct_answer_capability="learning_direct_answers.v1",
        program_capability="learning_programs.v1", response_capability="learning_responses.v1",
    )


def command(view):
    return CompositionDirectAnswerAction(
        action="request_direct_answer", component_id=view.component_bindings[0].component_id,
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
    )


@pytest.mark.parametrize("assisted_setup", [
    "choice", "python", "multiple", "prediction", "short", "ordering", "line_review",
    "sqlite", "project",
], indirect=True)
def test_explicit_direct_reference_atomic_original_owners_replay_reader_and_no_grade(
    database, workflow, session, assisted_setup,
):
    setup = assisted_setup
    accepted, key, turn, prepared = introduce(session, setup)
    assert prepared[0]["status"] == "completed"
    assert setup["tutor"].submit(session.token, setup["conversation"].id, key, turn) == accepted
    with pytest.raises(BusinessError, match="support changed"):
        setup["tutor"].submit(session.token, setup["conversation"].id, key, turn.model_copy(update={
            "presentation_capabilities": turn.presentation_capabilities.model_copy(update={
                "actions": [setup["capability"]],
            }),
        }))
    view = current(session, setup)
    binding = view.component_bindings[0]
    assert binding.assistance_receipt is None and binding.result is None
    assert binding.assistance_profile == "practice-direct-answer.v1"
    assert "request_direct_answer" in binding.allowed_actions
    assert "correct_key" not in json.dumps(prepared) and '"tests":' not in json.dumps(prepared)
    client = TestClient(create_app(setup["settings"]))
    path = f"/v2/conversations/{view.conversation_id}/learning-artifacts/{view.id}"
    headers = {"Authorization": "Bearer " + session.token}
    assert client.get(path, headers=headers).status_code == 409
    action = command(view)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(
            lambda _: setup["flow"].action(session.token, view.conversation_id, view.id, action),
            range(2),
        ))
    assert replies[0] == replies[1]
    shown = current(session, setup)
    receipt = shown.component_bindings[0].assistance_receipt
    assert receipt.id == replies[0].result_id
    assert shown.revision == view.revision + 1 and shown.state == view.state == "ready"
    assert shown.component_bindings[0].result is None
    assert "request_direct_answer" not in shown.component_bindings[0].allowed_actions
    with database.transaction() as connection:
        assert PracticeAssistance(connection).get(
            session.actor, setup["pack_id"], "practice_1",
        ) == receipt
        _, expected = Packs(connection).direct_answer(
            session.actor, setup["pack_id"], "practice_1",
        )
        assert receipt.content == expected
        assert connection.execute(
            "SELECT count(*) AS n FROM item_bank.exposure_facts "
            "WHERE actor_id=%s AND receipt_key=%s",
            (session.actor.id, f"assistance:{receipt.id}"),
        ).fetchone()["n"] == 1
        with pytest.raises(BusinessError, match="ordinary"):
            Packs(connection).direct_answer(session.actor, setup["pack_id"], "assessment_1")
    assert setup["flow"].action_receipt(
        session.token, view.conversation_id, view.id, action.client_action_id,
    ) == replies[0]
    assert not workflow.snapshot(session.token).node_progress
    assert not workflow.snapshot(session.token).execution_progress


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
def test_direct_answer_rollback_then_original_answer_preserves_assistance(
    database, workflow, session, assisted_setup, monkeypatch,
):
    setup = assisted_setup
    introduce(session, setup)
    view = current(session, setup)
    action = command(view)
    original = Exposures.record

    def fail(*args, **kwargs):
        raise RuntimeError("owned exposure rollback")

    monkeypatch.setattr(Exposures, "record", fail)
    with pytest.raises(RuntimeError, match="rollback"):
        setup["flow"].action(session.token, view.conversation_id, view.id, action)
    with database.transaction() as connection:
        assert PracticeAssistance(connection).get(
            session.actor, setup["pack_id"], "practice_1",
        ) is None
    assert current(session, setup).revision == view.revision
    monkeypatch.setattr(Exposures, "record", original)
    setup["flow"].action(session.token, view.conversation_id, view.id, action)
    shown = current(session, setup)
    reference = shown.component_bindings[0].assistance_receipt
    setup["flow"].action(session.token, shown.conversation_id, shown.id, CompositionRespondAction(
        action="respond_component", component_id=shown.component_bindings[0].component_id,
        expected_artifact_revision=shown.revision, client_action_id=uuid4(),
        payload={"selected_key": reference.content.correct_key},
    ))
    answered = current(session, setup)
    assert answered.component_bindings[0].result.correct
    assert answered.component_bindings[0].assistance_receipt == reference
    assert not workflow.snapshot(session.token).node_progress


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
def test_legacy_capabilities_revocation_cancel_and_foreign_actor_do_not_reveal(
    database, workflow, session, assisted_setup,
):
    setup = assisted_setup
    introduce(session, setup, assisted=False)
    view = current(session, setup)
    assert "assistance_profile" not in view.component_bindings[0].model_dump()
    with pytest.raises(BusinessError, match="does not allow"):
        setup["flow"].action(session.token, view.conversation_id, view.id, command(view))
    other = workflow.create_session("Other reference reader")
    with pytest.raises(BusinessError):
        setup["flow"].get_v2(
            other.token, view.conversation_id, view.id,
            direct_answer_capability="learning_direct_answers.v1",
        )
    KnowledgeWorkflow(database).revoke(session.token, setup["source"].id, 1)
    with pytest.raises(BusinessError):
        setup["flow"].action(session.token, view.conversation_id, view.id, command(view))
    setup["flow"].action(session.token, view.conversation_id, view.id, CancelAction(
        action="cancel", client_action_id=uuid4(), expected_artifact_revision=view.revision,
    ))
    with database.transaction() as connection:
        assert PracticeAssistance(connection).get(
            session.actor, setup["pack_id"], "practice_1",
        ) is None


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
def test_assistance_capability_cannot_replace_the_original_owner_capability(
    session, assisted_setup,
):
    _, _, _, prepared = introduce(session, assisted_setup, original_capability=False)
    assert prepared[0]["status"] == "waiting_dependency"
    assert prepared[0]["code"] == "precondition_failed"
    assert "own capability" in prepared[0]["message"]


@pytest.mark.parametrize("assisted_setup", ["choice"], indirect=True)
def test_finished_answer_does_not_open_new_assistance_and_revocation_blocks_its_body(
    database, session, assisted_setup,
):
    setup = assisted_setup
    introduce(session, setup)
    view = current(session, setup)
    setup["flow"].action(session.token, view.conversation_id, view.id, CompositionRespondAction(
        action="respond_component", component_id=view.component_bindings[0].component_id,
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
        payload={"selected_key": "B"},
    ))
    answered = current(session, setup)
    original = answered.component_bindings[0].result
    assert not original.correct
    action = command(answered)
    with pytest.raises(BusinessError, match="自由练习"):
        setup["flow"].action(session.token, view.conversation_id, view.id, action)
    assisted = current(session, setup)
    assert assisted.practice_only and assisted.component_bindings[0].assistance_receipt is None
    assert assisted.component_bindings[0].result == original
    KnowledgeWorkflow(database).revoke(session.token, setup["source"].id, 1)
    with pytest.raises(BusinessError):
        current(session, setup)
    with pytest.raises(BusinessError, match="No committed"):
        setup["flow"].action_receipt(
            session.token, view.conversation_id, view.id, action.client_action_id,
        )
