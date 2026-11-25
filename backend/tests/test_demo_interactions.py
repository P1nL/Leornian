import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_composition_delivery import composition_provider
from test_composition_directory import bfs_composition
from test_composition_practice import practice_provider
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_learning_artifacts import selected
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_teaching_delivery import drain

from leornian.agent_runtime.tools import REGISTRY
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.tutor.composition_delivery_contracts import CompositionRespondAction
from leornian.modules.tutor.composition_v2_contracts import AlgorithmInput, LearningCompositionV2
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.demo_contracts import (
    DemoCompleteAction,
    DemoEventAction,
    DemoStartAction,
)
from leornian.modules.tutor.demos import algorithm_last_step, demo_bindings
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.shared_kernel.errors import BusinessError

ROOT = Path(__file__).parents[2]


def test_all_eight_endpoint_counters_agree_with_actual_shared_client_traces():
    from pydantic import TypeAdapter

    cases = [
        ({"type": "binary_search", "values": [1, 3, 7, 12], "target_state": "target"},
         {"target": target})
        for target in (0, 1, 3, 7, 12, 15, 3.5)
    ] + [
        ({"type": "brackets", "text": text}, {})
        for text in ("(", "()", "([]){}", "([)]", ")", "{}(")
    ] + [
        ({"type": "bfs", "nodes": ["A", "B", "C"], "start": "A", "edges": edges}, {})
        for edges in ([], [
            {"source": "A", "target": "B"}, {"source": "B", "target": "A"},
        ], [
            {"source": "A", "target": "B"}, {"source": "A", "target": "C"},
            {"source": "C", "target": "B"},
        ])
    ] + [
        ({"type": "grid_paths", "rows": 3, "columns": 4, "blocked": [
            {"row": 1, "column": 1},
        ]}, {}),
        ({"type": "combination_sum", "values": [1, 2, 3], "target": 4}, {}),
        ({"type": "combination_sum", "values": [9, 1, 1], "target": 1}, {}),
        ({"type": "combination_sum", "values": [1] * 10, "target": 1000}, {}),
        ({"type": "interval_scan", "intervals": [
            {"id": "x", "start": 1, "end": 3}, {"id": "y", "start": 2, "end": 4},
        ]}, {}),
        ({"type": "bitwise", "left": 9, "right": 3, "operation": "xor", "width": 4}, {}),
        ({"type": "geometry", "points": [
            {"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 1, "y": 2},
            {"id": "c", "x": 3, "y": 4},
        ]}, {}),
    ]
    uri = (ROOT / "apps/librechat/algorithm-demos.mjs").as_uri()
    script = (
        f"import {{compositionAlgorithm}} from {json.dumps(uri)};"
        "let body='';for await(const chunk of process.stdin)body+=chunk;"
        "console.log(JSON.stringify(JSON.parse(body).map(([input,values])=>"
        "compositionAlgorithm(input,values).steps.length-1)));"
    )
    result = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script],
        input=json.dumps(cases), capture_output=True, text=True, check=True, timeout=20,
    )
    expected = json.loads(result.stdout)
    assert [
        algorithm_last_step(TypeAdapter(AlgorithmInput).validate_python(source), values)
        for source, values in cases
    ] == expected


def demonstration(kind):
    definition = bfs_composition()
    if kind == "bfs":
        return definition
    definition["components"] = []
    definition["inputs"] = {}
    if kind == "binary":
        definition["states"]["target"] = {"type": "number", "value": 11}
        definition["inputs"]["numbers"] = {
            "type": "binary_search", "values": [2, 5, 8, 11, 14], "target_state": "target",
        }
        definition["components"] = [
            {"id": "parameter", "component": "ParameterControl", "props": {
                "label": "Target", "state": "target", "minimum": 0, "maximum": 20,
            }},
            {"id": "player", "component": "AlgorithmPlayer", "props": {
                "label": "Search", "algorithm": "binary_search", "input": "numbers",
                "state": "cursor",
            }},
            {"id": "values", "component": "AlgorithmSequence", "props": {
                "label": "Sorted values", "timeline": "player",
            }},
        ]
    elif kind == "step":
        definition["components"] = [{
            "id": "player", "component": "StepPlayer", "props": {
                "label": "Trace", "state": "cursor", "items": ["Prepare", "Inspect", "Finish"],
            },
        }]
    elif kind == "sequence":
        definition["components"] = [{
            "id": "player", "component": "SequenceDiagram", "props": {
                "label": "Sequence", "state": "cursor",
                "participants": [{"id": key, "label": key} for key in ("client", "server")],
                "steps": [
                    {"id": "request", "source": "client", "target": "server", "label": "Request"},
                    {"id": "reply", "source": "server", "target": "client", "label": "Reply"},
                ],
            },
        }]
    else:
        definition["states"] = {
            "html": {"type": "code", "value": "<p>Default</p>"},
            "css": {"type": "code", "value": "p { color: green; }"},
        }
        definition["components"] = [
            {"id": "editor", "component": "CodeEditor", "props": {
                "label": "HTML", "state": "html",
            }},
            {"id": "player", "component": "IsolatedPreview", "props": {
                "title": "Preview", "html_state": "html", "css_state": "css",
            }},
            {"id": "update", "component": "ArtifactAction", "props": {
                "label": "Update", "event": "preview", "for_component": "player",
            }},
        ]
    return definition


@pytest.fixture
def demo_scene(database, session, consumer, request):
    tutor, settings, conversation, *_ = consumer
    from leornian.modules.learning.material_contracts import MaterialBindingInput

    consumer[3].bind(session.token, str(uuid4()), MaterialBindingInput(
        goal_id=conversation.goal_id, purpose="teaching", expected_binding_revision=0,
        refs=consumer[6].refs,
    ))
    kind = getattr(request, "param", "bfs")
    actions = ["learning_demo_events.v1"]
    if kind == "all_capabilities":
        actions += [
            "learning_practice.v2", "learning_responses.v1", "learning_code_review.v1",
            "learning_programs.v1", "learning_direct_answers.v1", "learning_hints.v1",
        ]
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(
            text="Show the supplied demonstration and explicit browsing records, not assessment.",
            presentation_capabilities={
                "versions": ["learning_composition.v2"], "actions": actions,
            },
        ),
    )
    definition = demonstration({"all_capabilities": "binary", "two_ports": "bfs"}.get(kind, kind))
    ports = ["player"]
    if kind == "two_ports":
        definition["states"]["other_cursor"] = {"type": "playback", "value": 0}
        definition["components"].append({"id": "other", "component": "StepPlayer", "props": {
            "label": "Second activity", "state": "other_cursor", "items": ["Start", "Finish"],
        }})
        ports.append("other")
    gateway, calls, prepared = composition_provider(
        settings, preparation="prepare_learning_demo_composition",
        extra={"demo_components": ports}, definition=definition,
    )
    delivered = drain(tutor, settings, accepted, gateway, session.token)
    if delivered.status == "waiting_dependency":
        from test_material_sources_and_goals import advance_consumer_materials
        advance_consumer_materials(database, session, settings, conversation.goal_id)
        tutor.resume_delivery(session.token, delivered.id)
        delivered = drain(tutor, settings, accepted, gateway, session.token)
    assert delivered.status == "accepted"
    assert len(calls) == 3 and prepared[0]["demo_bindings"][0]["component_id"] == "player"
    review = json.loads(calls[-1]["messages"][-1]["content"])
    assert "demo_interaction_checks" in review
    flow = LearningArtifactWorkflow(database)
    artifact_id = flow.list_v2(session.token, conversation.id)[0].id
    return flow, settings, conversation, artifact_id, calls


def view_for(scene, session):
    flow, _, conversation, artifact_id, _ = scene
    return flow.get_v2(
        session.token, conversation.id, artifact_id, demo_capability="learning_demo_events.v1",
    )


def start(scene, session, *, inputs=None):
    flow, _, conversation, artifact_id, _ = scene
    return flow.action(
        session.token, conversation.id, artifact_id, DemoStartAction(
            action="start_demo", component_id="player", inputs=inputs or {},
            client_action_id=uuid4(), expected_artifact_revision=view_for(scene, session).revision,
        ),
    )


def event(scene, session, **changes):
    view = view_for(scene, session)
    demo = view.demo_bindings[0]
    return DemoEventAction(**{
        "action": "acknowledge_demo_event", "component_id": "player",
        "generation": demo.generation, "nonce": demo.nonce, "sequence": 1,
        "event": "timeline_end", "step_index": demo.last_step,
        "client_action_id": uuid4(), "expected_artifact_revision": view.revision, **changes,
    })


def completion(scene, session, **changes):
    view = view_for(scene, session)
    demo = view.demo_bindings[0]
    return DemoCompleteAction(**{
        "action": "complete_demo", "component_id": "player",
        "generation": demo.generation, "nonce": demo.nonce, "sequence": 2,
        "client_action_id": uuid4(), "expected_artifact_revision": view.revision, **changes,
    })


def apply(scene, session, data):
    flow, _, conversation, artifact_id, _ = scene
    return flow.action(session.token, conversation.id, artifact_id, data)


@pytest.mark.parametrize("demo_scene", ["two_ports"], indirect=True)
def test_explicit_events_receipts_restart_history_cancel_and_no_assessment(
    database, session, demo_scene,
):
    flow, settings, conversation, artifact_id, calls = demo_scene
    initial = view_for(demo_scene, session)
    assert initial.demo_bindings[0].nonce is None and initial.revision == 1
    with pytest.raises(BusinessError, match="learning_demo_events"):
        flow.get_v2(session.token, conversation.id, artifact_id)
    started = start(demo_scene, session)
    assert started.generation == 1 and started.sequence == 0
    assert started.result_id is None and started.result_owner is None
    with pytest.raises(BusinessError, match="sequence"):
        apply(demo_scene, session, completion(demo_scene, session))
    for changes in ({"nonce": uuid4()}, {"generation": 2}, {"step_index": 0}):
        with pytest.raises(BusinessError):
            apply(demo_scene, session, event(demo_scene, session, **changes))
    command = event(demo_scene, session)
    acknowledged = apply(demo_scene, session, command)
    assert apply(demo_scene, session, command) == acknowledged
    assert view_for(demo_scene, session).state == "ready"
    complete_command = completion(demo_scene, session)
    receipt = apply(demo_scene, session, complete_command)
    assert receipt.result_owner == "tutor" and receipt.state == "ready"
    assert apply(demo_scene, session, complete_command) == receipt
    view = view_for(demo_scene, session)
    facts = view.demo_bindings[0].completions
    assert len(facts) == 1 and facts[0].id == receipt.result_id
    assert facts[0].content_identity == view.content_ref.public_identity
    assert facts[0].evidence_kind == "learner_demo_report.v1"
    restarted = start(demo_scene, session)
    assert restarted.generation == 2 and restarted.nonce != started.nonce
    with pytest.raises(BusinessError):
        apply(demo_scene, session, event(
            demo_scene, session, generation=1, nonce=started.nonce,
        ))
    assert view_for(demo_scene, session).demo_bindings[0].completions == facts
    apply(demo_scene, session, event(demo_scene, session))
    apply(demo_scene, session, completion(demo_scene, session))
    final = view_for(demo_scene, session)
    assert len(final.demo_bindings[0].completions) == 2
    headers = {"Authorization": f"Bearer {session.token}"}
    client = TestClient(create_app(settings))
    path = f"/v2/conversations/{conversation.id}/learning-artifacts/{artifact_id}"
    assert client.get(f"{path}/actions/{receipt.client_action_id}", headers=headers).json() == (
        receipt.model_dump(mode="json")
    )
    assert client.get(path, headers=headers).status_code == 409
    assert client.get(
        path + "?demo_capability=learning_demo_events.v1", headers=headers,
    ).status_code == 200
    cancelled = apply(demo_scene, session, CancelAction(
        action="cancel", client_action_id=uuid4(), expected_artifact_revision=final.revision,
    ))
    assert cancelled.state == "cancelled"
    assert not view_for(demo_scene, session).demo_bindings[0].allowed_actions
    with pytest.raises(BusinessError):
        start(demo_scene, session)
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.demo_completions WHERE artifact_id=%s",
            (artifact_id,),
        ).fetchone()["n"] == 2
        assert connection.execute(
            "SELECT count(*) AS n FROM assessment.choice_results WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"] == 0
    assert len(calls) == 3  # No interaction dispatches another model call.


def test_concurrent_event_replay_and_failed_transaction_do_not_advance(
    database, session, demo_scene, monkeypatch,
):
    start(demo_scene, session)
    command = event(demo_scene, session)

    def fail(*args):
        raise BusinessError("precondition_failed", "Injected commit-path failure.")

    with monkeypatch.context() as patch:
        patch.setattr(LearningArtifactWorkflow, "event", staticmethod(fail))
        with pytest.raises(BusinessError, match="Injected"):
            apply(demo_scene, session, command)
    assert view_for(demo_scene, session).demo_bindings[0].state == "started"
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: apply(demo_scene, session, command), range(2)))
    assert receipts[0] == receipts[1]
    assert view_for(demo_scene, session).demo_bindings[0].sequence == 1
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.learning_artifact_actions WHERE client_action_id=%s",
            (command.client_action_id,),
        ).fetchone()["n"] == 1


def test_only_existing_closed_demonstration_ports_are_eligible():
    definition = LearningCompositionV2.model_validate(bfs_composition())
    assert demo_bindings(definition, ["player"])[0].event == "timeline_end"
    for ids in (["player", "player"], ["graph"], ["missing"], ["title"]):
        with pytest.raises(BusinessError):
            demo_bindings(definition, ids)


@pytest.mark.parametrize("demo_scene", ["binary", "step", "sequence", "preview"], indirect=True)
def test_each_port_freezes_exact_inputs_and_rejects_other_inputs(session, demo_scene):
    view = view_for(demo_scene, session)
    definition = view.presentation.definition
    node = next(node for node in definition.components if node.id == "player")
    if node.component == "AlgorithmPlayer":
        inputs = {"target": 5}
        invalid = {"target": 25}
    elif node.component == "IsolatedPreview":
        inputs = {"html": "<p>Actual learner draft</p>", "css": ""}
        invalid = {"html": "<p>Missing CSS port</p>"}
    else:
        inputs, invalid = {}, {"unexpected": 4}
    with pytest.raises(BusinessError):
        start(demo_scene, session, inputs=invalid)
    started = start(demo_scene, session, inputs=inputs)
    current = view_for(demo_scene, session).demo_bindings[0]
    assert current.inputs == inputs
    command = event(demo_scene, session, event=current.event)
    apply(demo_scene, session, command)
    with pytest.raises(BusinessError):
        apply(demo_scene, session, event(demo_scene, session, event=current.event))
    receipt = apply(demo_scene, session, completion(demo_scene, session))
    fact = view_for(demo_scene, session).demo_bindings[0].completions[0]
    assert fact.inputs == inputs and fact.id == receipt.result_id
    assert fact.generation == started.generation


@pytest.mark.parametrize("own_capability", [True, False])
def test_mixed_practice_retains_its_own_capability_grade_and_aggregate_state(
    database, workflow, session, learning_setup, own_capability,
):
    setup = learning_setup
    candidate = selected(session, setup)

    def mix(args):
        demo = bfs_composition()
        args["definition"]["states"].update(demo["states"])
        args["definition"]["inputs"] = demo["inputs"]
        args["definition"]["components"].extend(demo["components"])
        args["demo_components"] = ["player"]

    request = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()), TurnInput(
            text="Present the practice and graph, keeping browsing and assessment separate.",
            focus=candidate.focus,
            presentation_capabilities={
                "versions": ["learning_composition.v2"],
                "actions": ["learning_demo_events.v1"]
                + (["learning_practice.v2"] if own_capability else []),
            },
        ),
    )
    gateway, calls, prepared = practice_provider(
        setup["settings"], candidate.id, mutate=mix,
        preparation="prepare_learning_demo_composition",
    )
    assert drain(
        setup["tutor"], setup["settings"], request, gateway, session.token,
    ).status == "accepted"
    if not own_capability:
        assert prepared[0]["status"] == "waiting_dependency"
        assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
        return
    assert prepared[0]["status"] == "completed"
    artifact_id = setup["flow"].list_v2(session.token, setup["conversation"].id)[0].id
    scene = setup["flow"], setup["settings"], setup["conversation"], artifact_id, calls
    view = view_for(scene, session)
    result = apply(scene, session, CompositionRespondAction(
        action="respond_component", component_id="response", payload={"selected_key": "B"},
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
    ))
    assert result.result_owner == "assessment" and result.state == "ready"
    assert view_for(scene, session).component_bindings[0].result.id == result.result_id
    start(scene, session)
    apply(scene, session, event(scene, session))
    completed = apply(scene, session, completion(scene, session))
    assert completed.state == "completed" and completed.result_owner == "tutor"
    with pytest.raises(BusinessError, match="自由练习"):
        start(scene, session)
    assert view_for(scene, session).practice_only
    assert view_for(scene, session).component_bindings[0].result.id == result.result_id
    assert not workflow.snapshot(session.token).node_progress
    assert not workflow.snapshot(session.token).execution_progress


def test_material_revocation_prevents_completion_but_retains_original_receipts(
    database, session, demo_scene, consumer,
):
    from leornian.modules.knowledge.material_contracts import DocumentPermissionAction

    flow, _, conversation, artifact_id, _ = demo_scene
    receipt = start(demo_scene, session)
    apply(demo_scene, session, event(demo_scene, session))
    command = completion(demo_scene, session)
    materials, version = consumer[3], consumer[5]
    materials.revoke(
        session.token, version.document_id, version.revision,
        DocumentPermissionAction(expected_revision=1, action="revoke"),
    )
    with pytest.raises(BusinessError):
        apply(demo_scene, session, command)
    assert flow.action_receipt(
        session.token, conversation.id, artifact_id, receipt.client_action_id,
    ) == receipt
    with database.transaction() as connection:
        assert not connection.execute(
            "SELECT 1 FROM tutor.demo_completions WHERE artifact_id=%s", (artifact_id,),
        ).fetchone()


@pytest.mark.parametrize("demo_scene", ["all_capabilities"], indirect=True)
def test_native_full_capability_run_fits_original_budget_without_weakening_validation(
    session, demo_scene,
):
    from pydantic import ValidationError

    _, _, _, _, calls = demo_scene
    names = {tool["function"]["name"] for tool in calls[0]["tools"]}
    assert {
        "prepare_learning_demo_composition", "prepare_learning_hint_composition",
        "prepare_learning_assisted_composition", "prepare_learning_program_composition",
        "prepare_learning_code_review_composition", "prepare_learning_response_composition",
        "prepare_learning_practice_composition",
    } <= names
    assert view_for(demo_scene, session).demo_bindings
    invalid = bfs_composition()
    invalid["components"][1]["props"]["onClick"] = "forbidden"
    with pytest.raises(ValidationError):
        REGISTRY["prepare_learning_demo_composition"].validate({
            "command_key": "strict-after-compact-wire", "definition": invalid,
            "demo_components": ["player"],
        })
    for name in names - {"prepare_learning_demo_composition"}:
        assert REGISTRY[name].wire()["function"]["parameters"] == (
            REGISTRY[name].arguments.model_json_schema()
        )
    tools = {item["function"]["name"]: item["function"]["parameters"] for item in calls[0]["tools"]}
    assert "LearningCompositionV2" in tools["prepare_learning_composition"]["$defs"]
    for name in names - {"prepare_learning_composition"}:
        if not name.startswith("prepare_learning_"):
            continue
        assert "LearningCompositionV2" not in tools[name].get("$defs", {})
        definition = tools[name]["properties"]["definition"]
        assert "prepare_learning_composition" in definition["description"]


@pytest.mark.parametrize("demo_scene", ["two_ports"], indirect=True)
def test_completion_history_is_paged_scoped_read_only_and_keeps_all_generations(
    session, demo_scene, workflow,
):
    flow, settings, conversation, artifact_id, calls = demo_scene
    for _ in range(8):
        start(demo_scene, session)
        apply(demo_scene, session, event(demo_scene, session))
        apply(demo_scene, session, completion(demo_scene, session))
    view = view_for(demo_scene, session)
    current = view.demo_bindings[0]
    assert current.completion_count == 8 and len(current.completions) == 5
    assert current.next_completion_before == 4
    client = TestClient(create_app(settings))
    path = (
        f"/v2/conversations/{conversation.id}/learning-artifacts/{artifact_id}"
        "/demos/player/completions?demo_capability=learning_demo_events.v1"
    )
    headers = {"Authorization": f"Bearer {session.token}"}
    page = client.get(path + "&before=4&limit=2", headers=headers)
    assert page.status_code == 200, page.text
    assert [item["generation"] for item in page.json()["items"]] == [3, 2]
    assert page.json()["next_before"] == 2
    last = client.get(path + "&before=2&limit=2", headers=headers).json()
    assert [item["generation"] for item in last["items"]] == [1]
    assert last["next_before"] is None
    other = workflow.create_session("Other history reader")
    assert client.get(
        path, headers={"Authorization": f"Bearer {other.token}"},
    ).status_code == 404
    assert view_for(demo_scene, session).revision == view.revision
    assert len(calls) == 3


def test_demo_without_original_program_cannot_borrow_file_budget(database, session, demo_scene):
    from leornian.agent_runtime.repository import Runs
    from leornian.bootstrap.compositions import CompositionWorkflow
    from leornian.modules.tutor.composition_delivery_contracts import PrepareDemoComposition

    view = view_for(demo_scene, session)
    definition = bfs_composition()
    definition["states"]["files"] = {
        "type": "files", "files": [{"path": "main.py", "content": "x" * 21000}],
    }
    args = PrepareDemoComposition.model_validate({
        "command_key": "demo-has-no-program-owner", "definition": definition,
        "demo_components": ["player"],
    })
    with database.transaction() as connection:
        run = Runs(connection).for_turn(session.actor.id, view.source_turn_id)
        with pytest.raises(BusinessError, match="20,000"):
            CompositionWorkflow.prepare_in(
                connection, session.actor, Runs(connection).lock(run.id), args, demos=True,
            )
