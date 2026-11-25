import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_item_supply import request_data, review, run_model, stages
from test_item_supply import supply_setup as supply_setup
from test_teaching_delivery import body, drain, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.gate_contracts import GateRequest
from leornian.modules.item_bank.response_contracts import ResponseSubmission
from leornian.modules.tutor.composition_delivery_contracts import CompositionAnswerAction
from leornian.modules.tutor.contracts import TurnInput
from leornian.shared_kernel.errors import BusinessError

RESPONSE_TYPES = ("multiple", "prediction", "short", "ordering", "line_review")
SLOTS = ("practice_1", "practice_2", "assessment_1", "assessment_2", "remediation_1")


def authored_response(source, kind, slot, index):
    options = [{"id": key, "text": f"Public {slot} {key}"} for key in ("A", "B", "C")]
    code = "xs = [1, 2]\nprint(xs[0])\nprint(xs[1])"
    response = {
        "multiple": {"type": kind, "selected_ids": ["A", "C"]},
        "prediction": {"type": kind, "text": "1\n2"},
        "short": {"type": kind, "text": "Reference iteration explanation, not a scored answer."},
        "ordering": {"type": kind, "ordered_ids": ["B", "A", "C"]},
        "line_review": {"type": kind, "annotations": [{"line": 2, "reason": "Reference reason."}]},
    }[kind]
    props = (
        {"options": options} if kind == "multiple" else
        {"items": options} if kind == "ordering" else
        {"code": code} if kind in {"prediction", "line_review"} else {}
    )
    return {
        "question": {
            "slot": slot, "title": f"{kind} practice {index}",
            "prompt": f"Use {kind} to explain this distinct iteration context {index}.",
            "difficulty": 1 if slot == "remediation_1" else 2,
            "source_refs": [{"source_id": str(source.id), "revision": 1}],
            "response_type": kind, **props,
        },
        "answer": {
            "response": response, "explanation": f"Private reference for {slot}.",
            "findings": [{"line": 2, "content": "Private reference finding."}]
            if kind == "line_review" else [],
        },
    }


def publish_responses(database, setup, session, kind, *, fail_blind=False, fail_role=None):
    supply, tutor, settings, plan, source = setup
    accepted = supply.submit(
        session.token, plan.id, str(uuid4()),
        request_data(kind="response"),
    )
    document = {
        "items": [authored_response(source, kind, slot, index) for index, slot in enumerate(SLOTS)]
    }
    observed = []
    for _ in range(8):
        pending = [s for s in stages(database, accepted.pack_id) if s["result"] is None]
        assert pending
        stage = pending[0]
        if stage["role"] == "author":
            value = document
        elif stage["role"] == "blind":
            value = {"answers": [
                {"slot": item["question"]["slot"], "response": item["answer"]["response"]}
                for item in document["items"]
            ]}
            if fail_blind:
                value["answers"][0]["response"] = {"type": "prediction", "text": "wrong"}
        else:
            value = review(stage["role"] != fail_role)
        run_model(tutor, settings, stage["run_id"], value, observed.append)
    result = supply.get(session.token, accepted.pack_id)
    if not fail_blind and not fail_role:
        assert result.status == "ready"
        result = supply.publish(session.token, accepted.pack_id)
    return result, document, observed


def response_definition(source):
    question = source["presentation"]["question"]
    kind = question["response_type"]
    component = {
        "multiple": "ChoiceAnswer", "prediction": "TextAnswer", "short": "TextAnswer",
        "ordering": "OrderingAnswer", "line_review": "LineRangeAnswer",
    }[kind]
    state = (
        {"type": "choice"} if kind == "multiple" else
        {"type": "order", "value": [o["id"] for o in question["items"]]}
        if kind == "ordering" else
        {"type": "annotations"} if kind == "line_review" else {"type": "text"}
    )
    props = {"label": "Your response", "state": "answer"}
    if kind == "multiple":
        props.update(options=question["options"], multiple=True)
    if kind == "ordering":
        props.update(items=question["items"])
    if kind == "line_review":
        props["code_state"] = "snapshot"
    return {
        "schema_version": "learning_composition.v2", "title": "Original-owner response",
        "states": {
            "answer": state, **({
                "snapshot": {"type": "code", "value": question["code"], "read_only": True},
            } if kind == "line_review" else {}),
        },
        "components": [
            {"id": "answer", "component": component, "props": props},
            {"id": "feedback", "component": "AnswerFeedback", "props": {
                "label": "Original feedback", "for_component": "answer",
            }},
            *([{"id": "finding", "component": "ReviewFinding", "props": {
                "label": "Reference findings", "for_component": "answer",
            }}] if kind == "line_review" else []),
            {"id": "submit", "component": "ArtifactAction", "props": {
                "label": "Submit review" if kind == "line_review" else "Submit answer",
                "event": "submit_review" if kind == "line_review" else "submit_answer",
                "for_component": "answer", "primary": True,
            }},
        ],
    }


def response_provider(settings, source_id, *, mutate=None, conflict=None, extra_source_ids=()):
    calls, prepared = [], []

    def tool(name, arguments):
        return httpx.Response(200, json={
            "choices": [{"message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": name, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }],
            }, "finish_reason": "tool_calls"}],
        })

    def handle(request):
        wire = json.loads(request.content)
        calls.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            if conflict:
                conflict()
            return httpx.Response(200, json=body(json.dumps(report(
                json.loads(wire["messages"][-1]["content"])
            ))))
        if wire["messages"][-1]["role"] != "tool":
            return tool("list_learning_response_candidates", {})
        value = json.loads(wire["messages"][-1]["content"])
        if "items" in value:
            source = next(item for item in value["items"] if item["id"] == str(source_id))
            args = {
                "command_key": "response-composition", "definition": response_definition(source),
                "owner_bindings": [{"component_id": "answer", "candidate_id": source["id"]}],
            }
            for index, candidate_id in enumerate(extra_source_ids, 1):
                extra = next(item for item in value["items"] if item["id"] == str(candidate_id))
                definition = response_definition(extra)
                prefix = f"q{index}_"
                args["definition"]["states"].update({
                    prefix + key: state for key, state in definition["states"].items()
                })
                for node in definition["components"]:
                    node["id"] = prefix + node["id"]
                    for port in ("state", "code_state", "for_component"):
                        if port in node["props"]:
                            node["props"][port] = prefix + node["props"][port]
                args["definition"]["components"].extend(definition["components"])
                args["owner_bindings"].append({
                    "component_id": prefix + "answer", "candidate_id": extra["id"],
                })
            if mutate:
                mutate(args)
            return tool("prepare_learning_response_composition", args)
        prepared.append(value)
        return httpx.Response(200, json=body(json.dumps({
            "text": "Complete the response; it is not formal Gate or semantic grading.",
            "interaction": {
                "type": "artifact", "exact_handle": value["candidate"]["id"],
                "intent": "introduce_only",
            } if value["status"] == "completed" else {"type": "none"},
        })))

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), calls, prepared


def introduce_response(database, session, supply_setup, pack, *, mutate=None, conflict=None):
    settings = replace(
        supply_setup[2], delivery_enabled=True,
        model_context_tokens=128000, model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, supply_setup[3].goal_id)
    flow = LearningArtifactWorkflow(database)
    with database.transaction() as c:
        from leornian.modules.identity.application import Identity
        from leornian.modules.identity.infrastructure import PgIdentityStore

        actor = Identity(PgIdentityStore(c)).authenticate(session.token)
        source = flow.candidate_in(c, actor, conversation.id, pack.id, "practice_1")
    data = TurnInput(
        text="Compose this response with actual owner feedback.", focus=source.focus,
        presentation_capabilities={
            "versions": ["learning_composition.v2"], "actions": ["learning_responses.v1"],
        },
    )
    accepted = tutor.submit(session.token, conversation.id, str(uuid4()), data)
    gateway, calls, prepared = response_provider(
        settings, source.id, mutate=mutate, conflict=conflict
    )
    task = drain(tutor, settings, accepted, gateway, session.token)
    return task, flow, conversation, calls, prepared


@pytest.mark.parametrize("kind", RESPONSE_TYPES)
def test_response_quality_delivery_original_owner_lock_receipt_and_exposure(
    database, workflow, session, supply_setup, kind,
):
    pack, document, calls = publish_responses(database, supply_setup, session, kind)
    assert pack.kind == "response" and pack.status == "published"
    assert pack.blind_passed is (None if kind == "short" else True)
    blind_wire = next(w for w in calls if "questions" in json.loads(w["messages"][-1]["content"]))
    blind_context = json.loads(blind_wire["messages"][-1]["content"])
    assert set(blind_context) == {"objective", "node_title", "questions"}
    assert "Private reference" not in json.dumps(blind_context)
    assert "Reference iteration explanation" not in json.dumps(blind_context)
    task, flow, conversation, _, prepared = introduce_response(
        database, session, supply_setup, pack
    )
    assert task.status == "accepted" and prepared[0]["status"] == "completed"
    summary = flow.list_v2(session.token, conversation.id)[0]
    view = flow.get_v2(
        session.token, conversation.id, summary.id, response_capability="learning_responses.v1"
    )
    assert "Private reference" not in view.model_dump_json()
    assert view.component_bindings[0].source.kind == "knowledge_response"
    data = CompositionAnswerAction(
        action="answer_component", component_id="answer", client_action_id=uuid4(),
        expected_artifact_revision=view.revision,
        payload=document["items"][0]["answer"]["response"],
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(
            lambda _: flow.action(session.token, conversation.id, view.id, data), range(2)
        ))
    assert receipts[0] == receipts[1] and receipts[0].result_id
    assert receipts[0].component_state == receipts[0].state == "completed"
    final = flow.get_v2(
        session.token, conversation.id, view.id, response_capability="learning_responses.v1"
    )
    result = final.component_bindings[0].result
    assert result.correct is (None if kind == "short" else True)
    assert result.explanation == "Private reference for practice_1."
    assert final.component_bindings[0].action_id == data.client_action_id
    direct = supply_setup[0].respond(
        session.token, pack.id, str(data.client_action_id),
        ResponseSubmission(slot="practice_1", response=data.payload),
    )
    assert direct == result
    client = TestClient(create_app(supply_setup[2]))
    path = f"/v2/conversations/{conversation.id}/learning-artifacts/{view.id}"
    headers = {"Authorization": "Bearer " + session.token}
    assert client.get(path, headers=headers).status_code == 409
    assert client.get(
        path + "?response_capability=learning_responses.v1", headers=headers
    ).status_code == 200
    replay = client.post(path + "/actions", json=data.model_dump(mode="json"), headers=headers)
    assert replay.json()["result_id"] == str(result.id)
    receipt = client.get(path + f"/actions/{data.client_action_id}", headers=headers)
    assert receipt.status_code == 200
    saved = client.get(f"/v2/packs/{pack.id}/response-results", headers=headers)
    assert [row["id"] for row in saved.json()] == [str(result.id)]
    assert not workflow.snapshot(session.token).node_progress
    with database.transaction() as c:
        assert c.execute(
            "SELECT count(*) AS n FROM assessment.response_results WHERE pack_id=%s", (pack.id,)
        ).fetchone()["n"] == 1
        assert c.execute(
            "SELECT public_content FROM item_bank.exposure_facts WHERE pack_id=%s "
            "AND slot='practice_1' AND kind='feedback'", (pack.id,),
        ).fetchone()["public_content"]["feedback"]["correct"] is result.correct


def test_reference_blind_is_not_a_pass_and_negative_quality_still_blocks(
    database, session, supply_setup,
):
    pack, _, _ = publish_responses(
        database, supply_setup, session, "prediction", fail_blind=True
    )
    assert pack.status == "changes_required" and pack.blind_passed is False
    with pytest.raises(BusinessError, match="blind and six-role"):
        supply_setup[0].publish(session.token, pack.id)
    pack, _, _ = publish_responses(
        database, supply_setup, session, "short", fail_role="technical"
    )
    assert pack.status == "changes_required" and pack.blind_passed is None
    with pytest.raises(BusinessError):
        supply_setup[0].publish(session.token, pack.id)


@pytest.mark.parametrize("kind", ("multiple", "ordering", "line_review"))
def test_response_preparation_rejects_changed_published_options_order_and_snapshot(
    database, session, supply_setup, kind,
):
    pack, _, _ = publish_responses(database, supply_setup, session, kind)

    def mutate(args):
        if kind == "multiple":
            args["definition"]["components"][0]["props"]["options"][0]["text"] = "Invented choice"
        elif kind == "ordering":
            args["definition"]["states"]["answer"]["value"] = ["B", "A", "C"]
        else:
            args["definition"]["states"]["snapshot"]["value"] += "\nprint('new')"

    task, flow, conversation, _, prepared = introduce_response(
        database, session, supply_setup, pack, mutate=mutate
    )
    assert task.status == "accepted" and prepared[0]["status"] == "waiting_dependency"
    assert not flow.list_v2(session.token, conversation.id)
    with database.transaction() as c:
        assert not c.execute(
            "SELECT 1 FROM item_bank.exposures WHERE pack_id=%s", (pack.id,)
        ).fetchone()


def test_response_owner_checks_format_scope_permission_and_does_not_open_gate(
    database, workflow, session, supply_setup,
):
    pack, document, _ = publish_responses(database, supply_setup, session, "line_review")
    task, flow, conversation, _, _ = introduce_response(database, session, supply_setup, pack)
    assert task.status == "accepted"
    summary = flow.list_v2(session.token, conversation.id)[0]
    view = flow.get_v2(
        session.token, conversation.id, summary.id, response_capability="learning_responses.v1"
    )
    before = workflow.snapshot(session.token).cursor
    for payload in (
        {"type": "line_review", "annotations": [{"line": 240, "reason": "Outside snapshot"}]},
        {"type": "ordering", "ordered_ids": ["A", "B", "C"]},
    ):
        with pytest.raises(BusinessError):
            flow.action(session.token, conversation.id, view.id, CompositionAnswerAction(
                action="answer_component", component_id="answer", client_action_id=uuid4(),
                expected_artifact_revision=view.revision, payload=payload,
            ))
    assert workflow.snapshot(session.token).cursor == before
    assert flow.get_v2(
        session.token, conversation.id, view.id, response_capability="learning_responses.v1"
    ).revision == view.revision
    gate = ConceptGate(database, supply_setup[2])
    with pytest.raises(BusinessError, match="matching Gate endpoint"):
        gate.request(
            session.token, pack.id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )
    from leornian.bootstrap.knowledge import KnowledgeWorkflow

    KnowledgeWorkflow(database).revoke(session.token, supply_setup[4].id, 1)
    with pytest.raises(BusinessError):
        flow.action(session.token, conversation.id, view.id, CompositionAnswerAction(
            action="answer_component", component_id="answer", client_action_id=uuid4(),
            expected_artifact_revision=view.revision,
            payload=document["items"][0]["answer"]["response"],
        ))
    with database.transaction() as c:
        assert not c.execute(
            "SELECT 1 FROM assessment.response_results WHERE pack_id=%s", (pack.id,)
        ).fetchone()


def test_response_sources_are_not_available_to_old_list_or_direct_legacy_delivery(
    database, session, supply_setup,
):
    from leornian.modules.identity.application import Identity
    from leornian.modules.identity.infrastructure import PgIdentityStore
    from leornian.modules.tutor.learning_artifact_contracts import LearningCandidateInput

    pack, _, _ = publish_responses(database, supply_setup, session, "short")
    tutor = supply_setup[1]
    conversation = tutor.conversation(session.token, supply_setup[3].goal_id)
    flow = LearningArtifactWorkflow(database)
    with database.transaction() as c:
        actor = Identity(PgIdentityStore(c)).authenticate(session.token)
        source = flow.candidate_in(c, actor, conversation.id, pack.id, "practice_1")
        assert not flow.candidates_in(c, actor, conversation.id, source.focus)["items"]
        assert len(flow.candidates_in(
            c, actor, conversation.id, source.focus, responses=True
        )["items"]) == 2
    with pytest.raises(BusinessError, match="response-capable"):
        flow.candidate(session.token, conversation.id, LearningCandidateInput(
            pack_id=pack.id, slot="practice_1"
        ))
    with pytest.raises(BusinessError, match="checked composition"):
        tutor.submit(session.token, conversation.id, str(uuid4()), TurnInput(
            text="Do not silently turn the old artifact into a response artifact.",
            focus=source.focus, learning_candidate_id=source.id,
        ))


@pytest.mark.parametrize(("text", "expected"), [
    ("1\r\n2 \n\n", True), (" 1\n2", False), ("1 2", False), ("", False),
])
def test_prediction_comparison_preserves_meaningful_whitespace(text, expected):
    from types import SimpleNamespace

    from leornian.modules.item_bank.response_contracts import (
        AuthoredResponseQuestion,
        PredictionResponse,
        compare_response,
    )

    item = AuthoredResponseQuestion.model_validate(authored_response(
        SimpleNamespace(id=uuid4()), "prediction", "practice_1", 0
    ))
    assert compare_response(
        item.public(), PredictionResponse(type="prediction", text=text), item.answer
    ) is expected
    empty_key = item.answer.model_copy(update={
        "response": PredictionResponse(type="prediction", text=""),
    })
    assert compare_response(
        item.public(), PredictionResponse(type="prediction", text=""), empty_key
    ) is True


def test_v2_guide_is_generated_from_all_components_without_a_recipe_limit():
    from leornian.modules.tutor.composition_catalog import component_directory
    from leornian.modules.tutor.composition_guidance import composition_guidance

    guide = composition_guidance("learning_composition.v2").split(
        "## Authoritative JSON Schema"
    )[0]
    for item in component_directory():
        assert f"- {item['component']} [{item['category']}]" in guide
    assert "there is no recipe switch" in guide.lower()
    assert "Short answers are reference-only" in guide
