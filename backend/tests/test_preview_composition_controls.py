import json
from uuid import uuid4

import pytest
from test_composition_delivery import composition_provider
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_material_sources_and_goals import advance_consumer_materials
from test_teaching_delivery import drain

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.compositions import CompositionWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionCandidate,
    PrepareComposition,
    PrepareDemoComposition,
)
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2
from leornian.modules.tutor.compositions import Compositions
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.demo_contracts import (
    DemoCompleteAction,
    DemoEventAction,
    DemoStartAction,
)
from leornian.shared_kernel.errors import BusinessError


def preview_definition(*, update=False):
    definition = {
        "schema_version": "learning_composition.v2",
        "title": "Edit and explicitly update a restricted preview",
        "states": {
            "html": {"type": "code", "value": "<p>Initial</p>"},
            "css": {"type": "code", "value": "p { color: green; }"},
        },
        "components": [
            {
                "id": "html_editor", "component": "CodeEditor",
                "props": {"label": "HTML", "state": "html"},
            },
            {
                "id": "css_diff", "component": "CodeDiff",
                "props": {"label": "CSS changes", "state": "css", "before": ""},
            },
            {
                "id": "preview", "component": "IsolatedPreview",
                "props": {"title": "Preview", "html_state": "html", "css_state": "css"},
            },
        ],
    }
    if update:
        definition["components"].append({
            "id": "update_preview", "component": "ArtifactAction",
            "props": {"label": "Update preview", "event": "preview", "for_component": "preview"},
        })
    return definition


def wrong_target_definition():
    definition = preview_definition()
    definition["states"]["other_html"] = {
        "type": "code", "value": "<p>Static companion</p>", "read_only": True,
    }
    definition["components"].extend([
        {
            "id": "other_preview", "component": "IsolatedPreview",
            "props": {"title": "Static companion", "html_state": "other_html"},
        },
        {
            "id": "update_other", "component": "ArtifactAction",
            "props": {
                "label": "Update companion", "event": "preview", "for_component": "other_preview",
            },
        },
    ])
    return definition


@pytest.mark.parametrize("editor_id", ["html_editor", "css_diff"])
def test_new_editable_html_or_css_requires_its_previews_explicit_update(editor_id):
    data = preview_definition()
    data["components"] = [
        node for node in data["components"]
        if node["component"] == "IsolatedPreview" or node["id"] == editor_id
    ]
    definition = LearningCompositionV2.model_validate(data)
    with pytest.raises(BusinessError) as missing:
        Compositions.validate_preview_controls(definition)
    assert missing.value.code == "precondition_failed"


def test_update_for_a_different_preview_does_not_unlock_the_editable_preview():
    definition = LearningCompositionV2.model_validate(wrong_target_definition())
    with pytest.raises(BusinessError) as wrong:
        Compositions.validate_preview_controls(definition)
    assert wrong.value.code == "precondition_failed"


def test_read_only_editors_and_static_previews_do_not_require_update_controls():
    read_only = preview_definition()
    for state in read_only["states"].values():
        state["read_only"] = True
    Compositions.validate_preview_controls(LearningCompositionV2.model_validate(read_only))
    static = preview_definition()
    static["components"] = [
        node for node in static["components"] if node["component"] == "IsolatedPreview"
    ]
    Compositions.validate_preview_controls(LearningCompositionV2.model_validate(static))


def test_rejected_new_preparations_leave_no_presentation_candidate_or_partial_delivery(
    database, session, consumer,
):
    tutor, settings, conversation, *_ = consumer
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()),
        TurnInput(
            text="我想把这行字换个颜色。",
            presentation_capabilities={"versions": ["learning_composition.v2"]},
        ),
    )
    advance_consumer_materials(database, session, settings, conversation.goal_id)
    lease = tutor.claim(accepted.run_id)
    assert lease and tutor.context(lease)
    try:
        for definition in (preview_definition(), wrong_target_definition()):
            args = PrepareComposition(
                command_key=str(uuid4()),
                definition=LearningCompositionV2.model_validate(definition),
            )
            with database.transaction() as connection:
                with pytest.raises(BusinessError) as invalid:
                    CompositionWorkflow.prepare_in(
                        connection, session.actor, Runs(connection).lock(accepted.run_id), args,
                    )
                assert invalid.value.code == "precondition_failed"
                assert not connection.execute(
                    "SELECT 1 FROM tutor.learning_presentations WHERE prepared_run_id=%s",
                    (accepted.run_id,),
                ).fetchone()
                assert not connection.execute(
                    "SELECT 1 FROM tutor.learning_candidates WHERE actor_id=%s "
                    "AND conversation_id=%s",
                    (session.actor.id, conversation.id),
                ).fetchone()
        assert not LearningArtifactWorkflow(database).list_v2(session.token, conversation.id)
        turn = tutor.turn_history(session.token, conversation.id)[0]
        assert turn.assistant_text is None and turn.learning_interaction is None
    finally:
        tutor.cancel(session.token, accepted.run_id)


def publish_demo_preview(database, session, consumer, definition):
    tutor, settings, conversation, *_ = consumer
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()),
        TurnInput(
            text="我改完颜色，在哪儿看效果？",
            presentation_capabilities={
                "versions": ["learning_composition.v2"], "actions": ["learning_demo_events.v1"],
            },
        ),
    )
    advance_consumer_materials(database, session, settings, conversation.goal_id)
    gateway, sent, prepared = composition_provider(
        settings, definition=definition, preparation="prepare_learning_demo_composition",
        extra={"demo_components": ["preview"]},
    )
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    flow = LearningArtifactWorkflow(database)
    artifact_id = flow.list_v2(session.token, conversation.id)[0].id
    view = flow.get_v2(
        session.token, conversation.id, artifact_id, demo_capability="learning_demo_events.v1",
    )
    assert len(sent) == 3 and len(prepared) == 1
    assert str(next(
        turn for turn in tutor.turn_history(session.token, conversation.id)
        if turn.id == accepted.turn_id
    ).learning_interaction.exact_handle) == prepared[0]["id"]
    return flow, view, accepted, sent, prepared[0]


def test_explicit_preview_update_survives_original_checked_delivery_and_demo_reporting(
    database, workflow, session, consumer,
):
    flow, view, _, sent, _ = publish_demo_preview(
        database, session, consumer, preview_definition(update=True),
    )
    actions = [
        node for node in view.presentation.definition.components
        if node.component == "ArtifactAction" and node.props.event == "preview"
    ]
    assert len(actions) == 1 and actions[0].props.for_component == "preview"
    inputs = {"html": "<p>Explicitly updated learner draft</p>", "css": "p { color: teal; }"}
    started = flow.action(
        session.token, view.conversation_id, view.id,
        DemoStartAction(
            action="start_demo", component_id="preview", inputs=inputs,
            client_action_id=uuid4(), expected_artifact_revision=view.revision,
        ),
    )
    acknowledged = flow.action(
        session.token, view.conversation_id, view.id,
        DemoEventAction(
            action="acknowledge_demo_event", component_id="preview",
            generation=started.generation, nonce=started.nonce, sequence=1,
            event="preview_snapshot", step_index=None,
            client_action_id=uuid4(), expected_artifact_revision=started.artifact_revision,
        ),
    )
    completed = flow.action(
        session.token, view.conversation_id, view.id,
        DemoCompleteAction(
            action="complete_demo", component_id="preview",
            generation=started.generation, nonce=started.nonce, sequence=2,
            client_action_id=uuid4(), expected_artifact_revision=acknowledged.artifact_revision,
        ),
    )
    final = flow.get_v2(
        session.token, view.conversation_id, view.id, demo_capability="learning_demo_events.v1",
    )
    assert final.demo_bindings[0].completions[0].id == completed.result_id
    assert final.demo_bindings[0].completions[0].inputs == inputs
    assert len(sent) == 3
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.choice_results and not snapshot.attempts
    assert not snapshot.python_attempts and not snapshot.program_attempts
    assert not snapshot.node_progress and not snapshot.execution_progress


def test_historical_missing_control_is_readable_and_original_preparation_replays(
    database, session, consumer, monkeypatch,
):
    historical = preview_definition()
    with monkeypatch.context() as old_version:
        old_version.setattr(
            Compositions, "validate_preview_controls", staticmethod(lambda _definition: None),
        )
        flow, original, accepted, _, candidate = publish_demo_preview(
            database, session, consumer, historical,
        )
    reread = flow.get_v2(
        session.token, original.conversation_id, original.id,
        demo_capability="learning_demo_events.v1",
    )
    assert reread == original
    args = PrepareDemoComposition(
        command_key="owned-bfs-presentation",
        definition=LearningCompositionV2.model_validate(historical),
        demo_components=["preview"],
    )

    def no_reinterpretation(_definition):
        raise AssertionError("An existing preparation must not receive new admission semantics.")

    with monkeypatch.context() as replay:
        replay.setattr(
            Compositions, "validate_preview_controls", staticmethod(no_reinterpretation),
        )
        with database.transaction() as connection:
            result = CompositionWorkflow.prepare_in(
                connection, session.actor, Runs(connection).lock(accepted.run_id), args, demos=True,
            )
        assert CompositionCandidate.model_validate_json(json.dumps(result["candidate"])) == (
            CompositionCandidate.model_validate_json(json.dumps(candidate))
        )
    assert flow.get_v2(
        session.token, original.conversation_id, original.id,
        demo_capability="learning_demo_events.v1",
    ) == original
