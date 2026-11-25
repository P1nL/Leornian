import json
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from test_item_supply import review, run_model, stages
from test_item_supply import supply_setup as supply_setup
from test_knowledge_responses import authored_response, response_definition
from test_teaching_delivery import body, drain, provider, report

from leornian.agent_runtime.contracts import ToolCall
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.automatic_supply import AutomaticSupply
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tools import ToolRouter
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import SLOTS
from leornian.modules.tutor.composition_delivery_contracts import CompositionAnswerAction
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput


def practice_turn(database, session, setup, *, actions=None, focus=None, mode="development"):
    settings = replace(
        setup[2], delivery_enabled=True, model_configuration_mode=mode,
        model_context_tokens=128000, model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, setup[3].goal_id)
    data = TurnInput(
        text="我想自己试一道。",
        focus=focus or TeachingFocus(
            kind="node", plan_id=setup[3].id, expected_plan_revision=1, node_key="loops"
        ),
        presentation_capabilities={
            "versions": ["learning_composition.v2"],
            "actions": actions if actions is not None else [
                "learning_practice.v2", "learning_responses.v1"
            ],
        },
    )
    accepted = tutor.submit(session.token, conversation.id, str(uuid4()), data)
    return tutor, settings, conversation, data, accepted


def supply_args(kind="response", **overrides):
    return {
        "command_key": "new-ordinary-practice", "kind": kind,
        "instruction": "Use distinct source-bound iteration decisions.",
        **({"response_formats": {
            "practice_1": "prediction", "practice_2": "ordering"
        }} if kind == "response" else {}),
        **overrides,
    }


def tool(database, scope, name, args):
    tutor, _, _, data, accepted = scope
    with database.transaction() as c:
        row = Runs(c).lock(accepted.run_id)
        result, _ = ToolRouter(
            tutor.database, row, data.focus.model_dump(mode="json"), lambda: {}
        ).execute(c, ToolCall(id=str(uuid4()), name=name, arguments=args))
    return result


def finish_teaching(scope, session):
    tutor, settings, _, _, accepted = scope
    gateway, _, _ = provider(settings, author="Preparation is queued; no practice is delivered.")
    return drain(tutor, settings, accepted, gateway, session.token)


def complete_response_pack(database, session, setup, pack_id, *, fail_role=None):
    supply, tutor, settings, _, source = setup
    with database.transaction() as c:
        actor = Identity(PgIdentityStore(c)).authenticate(session.token)
        row = Packs(c).row(actor, pack_id)
    document = {"items": [
        authored_response(source, row["response_formats"].get(slot, "multiple"), slot, index)
        for index, slot in enumerate(SLOTS)
    ]}
    observed = []
    for _ in range(8):
        pending = [s for s in stages(database, pack_id) if s["result"] is None]
        assert pending
        stage = pending[0]
        value = document if stage["role"] == "author" else {
            "answers": [
                {"slot": item["question"]["slot"], "response": item["answer"]["response"]}
                for item in document["items"]
            ]
        } if stage["role"] == "blind" else review(stage["role"] != fail_role)
        run_model(tutor, settings, stage["run_id"], value, observed.append)
    return supply.get(session.token, pack_id), observed


@pytest.mark.parametrize("kind", ["choice", "python_io", "response"])
def test_tool_queue_is_idempotent_yields_to_foreground_and_uses_original_task(
    database, session, supply_setup, kind,
):
    scope = practice_turn(database, session, supply_setup)
    args = supply_args(kind)
    result = tool(database, scope, "request_learning_practice_supply", args)
    assert result["status"] == "accepted" and "candidate" not in result
    assert tool(database, scope, "request_learning_practice_supply", args) == result
    changed = tool(database, scope, "request_learning_practice_supply", {
        **args, "instruction": "A different decision with the same command key."
    })
    assert changed["status"] == "conflict"
    pack_id = UUID(result["pack_id"])
    automatic = AutomaticSupply(database, scope[1])
    assert automatic.advance(pack_id) == 0
    assert stages(database, pack_id) == []
    read = tool(database, scope, "get_learning_practice_supply", {"task_id": result["task_id"]})
    assert read["action"] == "yield_foreground" and read["pack_status"] == "authoring"
    with database.transaction() as c:
        assert c.execute(
            "SELECT count(*) n FROM runtime.external_calls WHERE run_id=%s",
            (scope[-1].run_id,),
        ).fetchone()["n"] == 0
    assert finish_teaching(scope, session).status == "accepted"
    assert automatic.advance(pack_id) == 1
    assert automatic.advance(pack_id) == 0
    assert [s["role"] for s in stages(database, pack_id)] == ["author"]
    with database.transaction() as c:
        stage = stages(database, pack_id)[0]
        assert Runs(c).configuration_scope(stage["run_id"]) == "legacy_development"


@pytest.mark.parametrize("program", [True, False])
def test_wrong_supply_reader_returns_recoverable_problem_without_requeue(
    database, session, supply_setup, program,
):
    scope = practice_turn(database, session, supply_setup,
                          actions=["learning_practice.v2", "learning_programs.v2"])
    right, wrong = ("program", "practice") if program else ("practice", "program")
    args = supply_args("sql_query", program_environment={
        "profile": "sql-query.v1", "dialect": "sqlite", "runtime_version": "3.46.1",
    }) if program else supply_args("choice")
    queued = tool(database, scope, f"request_learning_{right}_supply", args)
    query = {"task_id": queued["task_id"]}
    problem = tool(database, scope, f"get_learning_{wrong}_supply", query)
    assert problem["status"] == "waiting_dependency"
    assert f"get_learning_{right}_supply" in problem["message"]
    result = tool(database, scope, f"get_learning_{right}_supply", query)
    assert result["task_id"] == query["task_id"] and result["status"] == "completed"
    assert stages(database, UUID(queued["pack_id"])) == []


def test_natural_response_request_publication_listing_checked_delivery_and_real_owner(
    database, workflow, session, supply_setup,
):
    scope = practice_turn(database, session, supply_setup)
    tutor, settings, conversation, _, accepted = scope
    queued, seen = [], []
    automatic = AutomaticSupply(database, settings)

    def request_supply(request):
        wire = json.loads(request.content)
        seen.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            return httpx.Response(200, json=body(json.dumps(report(
                json.loads(wire["messages"][-1]["content"])
            ))))
        if wire["messages"][-1]["role"] != "tool":
            return tool_response("request_learning_practice_supply", supply_args())
        result = json.loads(wire["messages"][-1]["content"])
        queued.append(result)
        assert automatic.advance(UUID(result["pack_id"])) == 0
        assert stages(database, UUID(result["pack_id"])) == []
        return httpx.Response(200, json=body(json.dumps({
            "text": "The original supply task is queued, not yet a usable practice.",
            "interaction": {"type": "none"},
        })))

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(request_supply))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    pack_id = UUID(queued[0]["pack_id"])
    assert automatic.advance(pack_id) == 1
    pack, wires = complete_response_pack(database, session, supply_setup, pack_id)
    assert pack.status == "ready"
    assert automatic.advance(pack_id) == 1
    assert supply_setup[0].get(session.token, pack_id).status == "published"
    author = json.loads(wires[0]["messages"][-1]["content"])
    assert author["requested_practice_formats"] == supply_args()["response_formats"]
    blind = json.loads(wires[1]["messages"][-1]["content"])
    assert set(blind) == {"objective", "node_title", "questions"}
    assert "private" not in json.dumps(blind).lower()
    second = practice_turn(database, session, supply_setup)
    read = tool(database, second, "get_learning_practice_supply", {
        "task_id": queued[0]["task_id"],
    })
    assert read["supply_status"] == "completed" and read["pack_id"] == str(pack_id)
    prepared = []

    def introduce(request):
        wire = json.loads(request.content)
        if "Independently review" in wire["messages"][0]["content"]:
            return httpx.Response(200, json=body(json.dumps(report(
                json.loads(wire["messages"][-1]["content"])
            ))))
        if wire["messages"][-1]["role"] != "tool":
            return tool_response("list_learning_response_candidates", {})
        result = json.loads(wire["messages"][-1]["content"])
        if "items" in result:
            source = next(item for item in result["items"]
                          if item["content_ref"]["id"] == str(pack_id)
                          and item["content_ref"]["slot"] == "practice_1")
            return tool_response("prepare_learning_response_composition", {
                "command_key": "introduce-new-supply", "definition": response_definition(source),
                "owner_bindings": [{"component_id": "answer", "candidate_id": source["id"]}],
            })
        prepared.append(result)
        return httpx.Response(200, json=body(json.dumps({
            "text": "Predict the reviewed output; this is ordinary practice.",
            "interaction": {
                "type": "artifact", "exact_handle": result["candidate"]["id"],
                "intent": "introduce_only",
            },
        })))

    gateway = ChatCompletionsGateway(second[1], httpx.MockTransport(introduce))
    assert drain(second[0], second[1], second[-1], gateway, session.token).status == "accepted"
    flow = LearningArtifactWorkflow(database)
    summary = flow.list_v2(session.token, conversation.id)[0]
    view = flow.get_v2(
        session.token, conversation.id, summary.id, response_capability="learning_responses.v1"
    )
    assert view.component_bindings[0].source.content_ref.id == pack_id
    receipt = flow.action(session.token, conversation.id, summary.id, CompositionAnswerAction(**{
        "action": "answer_component", "component_id": "answer",
        "payload": {"type": "prediction", "text": "1\n2"},
        "client_action_id": str(uuid4()), "expected_artifact_revision": view.revision,
    }))
    final = flow.get_v2(
        session.token, conversation.id, summary.id, response_capability="learning_responses.v1"
    )
    assert receipt.result_id == final.component_bindings[0].result.id
    assert final.component_bindings[0].result.correct is True
    assert workflow.snapshot(session.token).node_progress == []
    assert prepared[0]["status"] == "completed"


def tool_response(name, arguments):
    return httpx.Response(200, json={
        "choices": [{"message": {
            "role": "assistant", "content": None, "tool_calls": [{
                "id": str(uuid4()), "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }],
        }, "finish_reason": "tool_calls"}],
    })


def test_requested_formats_reject_wrong_author_and_survive_quality_revision(
    database, session, supply_setup,
):
    scope = practice_turn(database, session, supply_setup)
    result = tool(database, scope, "request_learning_practice_supply", supply_args())
    finish_teaching(scope, session)
    pack_id = UUID(result["pack_id"])
    automatic = AutomaticSupply(database, scope[1])
    automatic.advance(pack_id)
    bad = {"items": [
        authored_response(supply_setup[4], "multiple", slot, index)
        for index, slot in enumerate(SLOTS)
    ]}
    first_run = stages(database, pack_id)[0]["run_id"]
    run_model(supply_setup[1], supply_setup[2], first_run, bad)
    assert supply_setup[1].get(session.token, first_run).error_code == "invalid_item_output"
    assert automatic.advance(pack_id) == 1
    parent, _ = complete_response_pack(
        database, session, supply_setup, pack_id, fail_role="technical"
    )
    assert parent.status == "changes_required"
    assert automatic.advance(pack_id) == 1
    with database.transaction() as c:
        child = c.execute(
            "SELECT * FROM item_bank.packs WHERE predecessor_id=%s", (pack_id,)
        ).fetchone()
    assert child["response_formats"] == supply_args()["response_formats"]
    read = tool(database, scope, "get_learning_practice_supply", {"task_id": result["task_id"]})
    assert read["pack_id"] == str(child["id"]) and read["revision"] == 2
    assert "technical" not in parent.passed_roles


def test_cancellation_and_source_revocation_do_not_start_queued_author(
    database, session, supply_setup,
):
    scope = practice_turn(database, session, supply_setup)
    result = tool(database, scope, "request_learning_practice_supply", supply_args())
    scope[0].cancel(session.token, scope[-1].run_id)
    automatic = AutomaticSupply(database, scope[1])
    assert automatic.advance(UUID(result["pack_id"])) == 1
    assert stages(database, UUID(result["pack_id"])) == []
    cancelled = supply_setup[0].get(session.token, UUID(result["pack_id"]))
    assert cancelled.automation_status == "cancelled"
    other = practice_turn(database, session, supply_setup)
    request = tool(database, other, "request_learning_practice_supply", supply_args())
    finish_teaching(other, session)
    KnowledgeWorkflow(database).revoke(session.token, supply_setup[4].id, 1)
    assert automatic.advance(UUID(request["pack_id"])) == 0
    assert stages(database, UUID(request["pack_id"])) == []
    read = tool(database, other, "get_learning_practice_supply", {"task_id": request["task_id"]})
    assert read["supply_status"] == "waiting" and read["reason"] == "source_not_current"


@pytest.mark.parametrize("actions,kind", [
    ([], "response"), (["learning_practice.v2"], "response"),
    (["learning_responses.v1"], "python_io"),
])
def test_frozen_reader_capabilities_do_not_grant_other_supply_formats(
    database, session, supply_setup, actions, kind,
):
    scope = practice_turn(database, session, supply_setup, actions=actions)
    result = tool(database, scope, "request_learning_practice_supply", supply_args(kind))
    assert result["status"] == "waiting_dependency"
    with database.transaction() as c:
        assert not c.execute(
            "SELECT 1 FROM item_bank.packs WHERE actor_id=%s", (session.actor.id,)
        ).fetchone()


def test_response_supply_requires_typed_formats_and_an_exact_node(database, session, supply_setup):
    scope = practice_turn(database, session, supply_setup)
    args = supply_args()
    args.pop("response_formats")
    assert tool(database, scope, "request_learning_practice_supply", args)["code"] \
        == "invalid_arguments"
    args = supply_args(response_formats={"practice_1": "sql", "practice_2": "prediction"})
    assert tool(database, scope, "request_learning_practice_supply", args)["code"] \
        == "invalid_arguments"
    scope[0].cancel(session.token, scope[-1].run_id)
    goal = practice_turn(database, session, supply_setup, focus=TeachingFocus())
    assert tool(database, goal, "request_learning_practice_supply", supply_args())["code"] \
        == "precondition_failed"


def test_queued_unknown_author_is_not_resubmitted(database, session, supply_setup):
    scope = practice_turn(database, session, supply_setup)
    result = tool(database, scope, "request_learning_practice_supply", supply_args())
    finish_teaching(scope, session)
    pack_id = UUID(result["pack_id"])
    automatic = AutomaticSupply(database, scope[1])
    automatic.advance(pack_id)
    stage = stages(database, pack_id)[0]
    calls = []

    def unknown(request):
        calls.append(request)
        raise httpx.ReadTimeout("Owned fixture result unknown", request=request)

    AgentLoop(supply_setup[1], ChatCompletionsGateway(
        supply_setup[2], httpx.MockTransport(unknown)
    )).run(stage["run_id"])
    assert supply_setup[1].get(session.token, stage["run_id"]).status == "blocked_unknown"
    assert automatic.advance(pack_id) == 0
    assert automatic.advance(pack_id) == 0
    read = tool(database, scope, "get_learning_practice_supply", {"task_id": result["task_id"]})
    assert read["reason"] == "external_result_unknown" and len(calls) == 1


def test_queued_supply_freezes_user_scope_even_for_a_development_reconciler(
    database, session, supply_setup,
):
    scope = practice_turn(database, session, supply_setup, mode="user")
    result = tool(database, scope, "request_learning_practice_supply", supply_args())
    with database.transaction() as c:
        # This fixture ends the parent without any provider, leaving only scheduling to verify.
        Runs(c).finish(scope[-1].run_id, "succeeded")
    no_shared_model = replace(supply_setup[2], model_enabled=False, model_api_key="")
    assert AutomaticSupply(database, no_shared_model).advance(UUID(result["pack_id"])) == 1
    with database.transaction() as c:
        stage = stages(database, UUID(result["pack_id"]))[0]
        assert Runs(c).configuration_scope(stage["run_id"]) == "user"
