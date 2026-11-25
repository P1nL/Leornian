import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_composition_delivery import composition_provider
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_teaching_delivery import drain

from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.demo_contracts import (
    DemoCompleteAction,
    DemoEventAction,
    DemoStartAction,
)
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.shared_kernel.errors import BusinessError

PORTS = ("algorithm", "steps", "sequence", "preview")
INPUTS = {
    "algorithm": {"target": 11},
    "steps": {},
    "sequence": {},
    "preview": {"html": "<p>Learner draft</p>", "css": "p { color: teal; }"},
}


def four_port_composition():
    return {
        "schema_version": "learning_composition.v2",
        "title": "Four independently reported demonstrations",
        "states": {
            "target": {"type": "number", "value": 11},
            "algorithm_cursor": {"type": "playback"},
            "step_cursor": {"type": "playback"},
            "sequence_cursor": {"type": "playback"},
            "html": {"type": "code", "value": "<p>Initial preview</p>"},
            "css": {"type": "code", "value": "p { color: green; }"},
        },
        "inputs": {
            "numbers": {
                "type": "binary_search", "values": [2, 5, 8, 11, 14],
                "target_state": "target",
            },
        },
        "components": [
            {
                "id": "parameter", "component": "ParameterControl", "props": {
                    "label": "Search target", "state": "target", "minimum": 0, "maximum": 20,
                },
            },
            {
                "id": "algorithm", "component": "AlgorithmPlayer", "props": {
                    "label": "Binary search", "algorithm": "binary_search",
                    "input": "numbers", "state": "algorithm_cursor",
                },
            },
            {
                "id": "steps", "component": "StepPlayer", "props": {
                    "label": "Inspect the condition", "state": "step_cursor",
                    "items": ["Read the condition", "Inspect the body", "Explain the outcome"],
                },
            },
            {
                "id": "sequence", "component": "SequenceDiagram", "props": {
                    "label": "Request and response", "state": "sequence_cursor",
                    "participants": [
                        {"id": "client", "label": "Client"}, {"id": "server", "label": "Server"},
                    ],
                    "steps": [
                        {
                            "id": "request", "source": "client", "target": "server",
                            "label": "Request",
                        },
                        {
                            "id": "response", "source": "server", "target": "client",
                            "label": "Response",
                        },
                    ],
                },
            },
            {
                "id": "html_editor", "component": "CodeEditor", "props": {
                    "label": "HTML draft", "state": "html",
                },
            },
            {
                "id": "css_editor", "component": "CodeEditor", "props": {
                    "label": "CSS draft", "state": "css",
                },
            },
            {
                "id": "preview", "component": "IsolatedPreview", "props": {
                    "title": "Restricted preview", "html_state": "html", "css_state": "css",
                },
            },
            {
                "id": "update_preview", "component": "ArtifactAction", "props": {
                    "label": "Update preview", "event": "preview", "for_component": "preview",
                },
            },
        ],
    }


@pytest.fixture
def multi_demo(database, session, consumer):
    tutor, settings, conversation, materials, _, _, binding, *_ = consumer
    materials.bind(
        session.token, str(uuid4()), MaterialBindingInput(
            goal_id=conversation.goal_id, purpose="teaching", expected_binding_revision=0,
            refs=binding.refs,
        ),
    )
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()),
        TurnInput(
            text="Present four separate demonstrations; browsing is not assessment.",
            presentation_capabilities={
                "versions": ["learning_composition.v2"], "actions": ["learning_demo_events.v1"],
            },
        ),
    )
    gateway, calls, prepared = composition_provider(
        settings, preparation="prepare_learning_demo_composition",
        definition=four_port_composition(), extra={"demo_components": list(PORTS)},
    )
    task = drain(tutor, settings, accepted, gateway, session.token)
    if task.status == "waiting_dependency":
        from test_material_sources_and_goals import advance_consumer_materials

        advance_consumer_materials(database, session, settings, conversation.goal_id)
        tutor.resume_delivery(session.token, task.id)
        task = drain(tutor, settings, accepted, gateway, session.token)
    assert task.status == "accepted" and len(calls) == 3
    assert len(prepared) == 1
    assert [binding["component_id"] for binding in prepared[0]["demo_bindings"]] == list(PORTS)
    review = json.loads(calls[-1]["messages"][-1]["content"])
    assert "demo_interaction_checks" in review and "composition_checks" in review
    flow = LearningArtifactWorkflow(database)
    artifact = flow.list_v2(session.token, conversation.id)[0]
    turn = next(
        turn for turn in tutor.turn_history(session.token, conversation.id)
        if turn.id == accepted.turn_id
    )
    assert str(turn.learning_interaction.exact_handle) == prepared[0]["id"]
    return SimpleNamespace(
        flow=flow, conversation=conversation, artifact_id=artifact.id,
        calls=calls, prepared=prepared[0],
    )


def read(scene, session):
    return scene.flow.get_v2(
        session.token, scene.conversation.id, scene.artifact_id,
        demo_capability="learning_demo_events.v1",
    )


def ports(view):
    return {demo.component_id: demo for demo in view.demo_bindings}


def apply(scene, session, command):
    return scene.flow.action(
        session.token, scene.conversation.id, scene.artifact_id, command,
    )


def start(scene, session, component, inputs=None):
    view = read(scene, session)
    return apply(scene, session, DemoStartAction(
        action="start_demo", component_id=component,
        inputs=INPUTS[component] if inputs is None else inputs,
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
    ))


def acknowledge(scene, session, component):
    view = read(scene, session)
    demo = ports(view)[component]
    return apply(scene, session, DemoEventAction(
        action="acknowledge_demo_event", component_id=component,
        generation=demo.generation, nonce=demo.nonce, sequence=1,
        event=demo.event, step_index=demo.last_step,
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
    ))


def complete(scene, session, component):
    view = read(scene, session)
    demo = ports(view)[component]
    command = DemoCompleteAction(
        action="complete_demo", component_id=component,
        generation=demo.generation, nonce=demo.nonce, sequence=2,
        client_action_id=uuid4(), expected_artifact_revision=view.revision,
    )
    return apply(scene, session, command), command


def assert_no_assessment(workflow, session):
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.attempts and not snapshot.choice_results
    assert not snapshot.python_attempts and not snapshot.program_attempts
    assert not snapshot.node_progress and not snapshot.execution_progress


def test_four_ports_complete_independently_and_keep_original_reports_during_free_practice(
    database, workflow, session, multi_demo,
):
    scene = multi_demo
    initial = read(scene, session)
    assert initial.revision == 1 and initial.state == "ready"
    assert set(ports(initial)) == set(PORTS)
    assert str(initial.content_ref.id) == scene.prepared["content_ref"]["id"]
    assert all(
        demo.generation == 0 and demo.nonce is None and not demo.completions
        for demo in initial.demo_bindings
    )
    started = {}
    for component in PORTS:
        before = ports(read(scene, session))
        receipt = start(scene, session, component)
        started[component] = receipt
        after = ports(read(scene, session))
        assert receipt.generation == 1 and receipt.sequence == 0 and receipt.result_id is None
        assert after[component].inputs == INPUTS[component]
        assert {key: demo for key, demo in after.items() if key != component} == {
            key: demo for key, demo in before.items() if key != component
        }
    assert len({receipt.nonce for receipt in started.values()}) == 4
    for component in ("algorithm", "preview", "steps", "sequence"):
        acknowledge(scene, session, component)
        assert ports(read(scene, session))[component].state == "acknowledged"
    assert all(not demo.completions for demo in read(scene, session).demo_bindings)
    reports, commands = {}, {}
    for index, component in enumerate(PORTS):
        receipt, command = complete(scene, session, component)
        reports[component], commands[component] = receipt, command
        assert receipt.result_owner == "tutor" and receipt.result_id
        assert receipt.state == ("completed" if index == len(PORTS) - 1 else "ready")
    first_cycle = read(scene, session)
    assert first_cycle.revision == 13 and first_cycle.state == "completed"
    first_ports = ports(first_cycle)
    for component in PORTS:
        facts = first_ports[component].completions
        assert len(facts) == 1 and facts[0].id == reports[component].result_id
        assert facts[0].component_id == component and facts[0].inputs == INPUTS[component]
        assert facts[0].content_identity == first_cycle.content_ref.public_identity
        assert facts[0].evidence_kind == "learner_demo_report.v1"
    assert first_cycle.practice_only
    with pytest.raises(BusinessError, match="自由练习"):
        start(scene, session, "algorithm", {"target": 5})
    with pytest.raises(BusinessError, match="自由练习"):
        apply(scene, session, CancelAction(
            action="cancel", client_action_id=uuid4(),
            expected_artifact_revision=first_cycle.revision,
        ))
    final = read(scene, session)
    assert final == first_cycle and not final.allowed_actions
    for component, demo in ports(final).items():
        assert demo.completions == first_ports[component].completions and not demo.allowed_actions
        assert scene.flow.demo_history(
            session.token, scene.conversation.id, scene.artifact_id, component, None, 20,
        ).items == demo.completions
        assert apply(scene, session, commands[component]) == reports[component]
        with pytest.raises(BusinessError, match="自由练习"):
            start(scene, session, component)
    assert read(scene, session).revision == final.revision
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.demo_completions WHERE artifact_id=%s",
            (scene.artifact_id,),
        ).fetchone()["n"] == 4
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.learning_artifact_actions WHERE artifact_id=%s",
            (scene.artifact_id,),
        ).fetchone()["n"] == 12
    assert len(scene.calls) == 3
    assert_no_assessment(workflow, session)


def test_distinct_ports_share_artifact_cas_and_partial_cancel_keeps_only_committed_reports(
    database, workflow, session, multi_demo,
):
    scene = multi_demo
    initial = read(scene, session)
    commands = [
        DemoStartAction(
            action="start_demo", component_id=component, inputs=INPUTS[component],
            client_action_id=uuid4(), expected_artifact_revision=initial.revision,
        )
        for component in ("algorithm", "steps")
    ]

    def attempt(command):
        try:
            return command, apply(scene, session, command)
        except BusinessError as error:
            return command, error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, commands))
    winners = [
        (command, result) for command, result in results if not isinstance(result, BusinessError)
    ]
    failures = [
        (command, result) for command, result in results if isinstance(result, BusinessError)
    ]
    assert len(winners) == len(failures) == 1
    winner, receipt = winners[0]
    loser, conflict = failures[0]
    assert conflict.code == "stale_version"
    current = read(scene, session)
    current_ports = ports(current)
    assert current.revision == 2 and current_ports[winner.component_id].generation == 1
    assert current_ports[loser.component_id].generation == 0
    with pytest.raises(BusinessError, match="No committed"):
        scene.flow.action_receipt(
            session.token, scene.conversation.id, scene.artifact_id, loser.client_action_id,
        )
    start(scene, session, loser.component_id)
    assert ports(read(scene, session))[winner.component_id] == current_ports[winner.component_id]
    acknowledge(scene, session, winner.component_id)
    report, complete_command = complete(scene, session, winner.component_id)
    before_cancel = read(scene, session)
    assert before_cancel.state == "ready"
    assert ports(before_cancel)[loser.component_id].state == "started"
    apply(scene, session, CancelAction(
        action="cancel", client_action_id=uuid4(),
        expected_artifact_revision=before_cancel.revision,
    ))
    cancelled = read(scene, session)
    assert cancelled.state == "cancelled" and cancelled.revision == 6
    assert not any(demo.allowed_actions for demo in cancelled.demo_bindings)
    assert [fact.id for fact in ports(cancelled)[winner.component_id].completions] == [
        report.result_id,
    ]
    assert all(
        not demo.completions for key, demo in ports(cancelled).items() if key != winner.component_id
    )
    assert apply(scene, session, complete_command) == report
    assert apply(scene, session, winner) == receipt
    with pytest.raises(BusinessError, match="No ready demonstration"):
        acknowledge(scene, session, loser.component_id)
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.demo_completions WHERE artifact_id=%s",
            (scene.artifact_id,),
        ).fetchone()["n"] == 1
    assert len(scene.calls) == 3
    assert_no_assessment(workflow, session)
