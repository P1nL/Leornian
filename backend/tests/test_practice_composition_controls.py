import json
from uuid import uuid4

import pytest
from test_composition_practice import introduce_owned, practice_provider
from test_composition_practice import owned_setup as owned_setup
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_learning_artifacts import learning_setup as learning_setup
from test_learning_artifacts import selected
from test_python_execution import python_setup as python_setup
from test_runner import runner as runner

from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.compositions import CompositionWorkflow
from leornian.modules.tutor.composition_delivery_contracts import (
    CompositionCandidate,
    CompositionOwnerProposal,
    PreparePracticeComposition,
)
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2
from leornian.modules.tutor.compositions import Compositions
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.learning_artifact_contracts import LearningCandidateInput
from leornian.shared_kernel.errors import BusinessError


def owner_pair(component):
    definition = {
        "schema_version": "learning_composition.v2",
        "title": "Each bound practice needs its own explicit action",
        "states": {}, "components": [],
    }
    options = [{"id": "A", "text": "First"}, {"id": "B", "text": "Second"}]
    for key in ("first", "second"):
        props = {"label": key, "state": key}
        if component in {"CodeEditor", "CodeDiff"}:
            state = {"type": "code", "value": "print(0)"}
            if component == "CodeDiff":
                props["before"] = "print(0)"
        elif component == "LineRangeAnswer":
            state = {"type": "annotations"}
            definition["states"]["snapshot"] = {
                "type": "code", "value": "print(0)", "read_only": True,
            }
            props["code_state"] = "snapshot"
        elif component == "OrderingAnswer":
            state = {"type": "order", "value": ["A", "B"]}
            props["items"] = options
        elif component == "TextAnswer":
            state = {"type": "text"}
        else:
            state = {"type": "choice"}
            props["options"] = options
        definition["states"][key] = state
        definition["components"].append({
            "id": key, "component": component, "props": props,
        })
    bindings = [
        CompositionOwnerProposal(component_id=key, candidate_id=uuid4())
        for key in ("first", "second")
    ]
    return definition, bindings


def explicit_action(target, event):
    return {
        "id": target + "_" + event, "component": "ArtifactAction",
        "props": {"label": "Explicit action", "event": event, "for_component": target},
    }


@pytest.mark.parametrize(("component", "event"), [
    ("CodeEditor", "check_code"),
    ("CodeDiff", "check_code"),
    ("LineRangeAnswer", "submit_review"),
    ("ChoiceAnswer", "submit_answer"),
    ("TextAnswer", "submit_answer"),
    ("OrderingAnswer", "submit_answer"),
])
def test_each_bound_owner_requires_its_own_correct_submission_action(component, event):
    definition, bindings = owner_pair(component)
    with pytest.raises(BusinessError) as missing:
        Compositions.validate_owner_controls(
            LearningCompositionV2.model_validate(definition), bindings,
        )
    assert missing.value.code == "precondition_failed"
    assert "first" in missing.value.message and event in missing.value.message
    definition["components"].append(explicit_action("second", event))
    definition["components"].append(explicit_action("first", "cancel"))
    with pytest.raises(BusinessError) as wrong_owner:
        Compositions.validate_owner_controls(
            LearningCompositionV2.model_validate(definition), bindings,
        )
    assert wrong_owner.value.code == "precondition_failed"
    assert "for_component='first'" in wrong_owner.value.message
    definition["components"].append(explicit_action("first", event))
    with pytest.raises(BusinessError) as misleading_cancel:
        Compositions.validate_owner_controls(
            LearningCompositionV2.model_validate(definition), bindings,
        )
    assert misleading_cancel.value.code == "precondition_failed"
    assert "first" in misleading_cancel.value.message
    assert "cancels the whole artifact" in misleading_cancel.value.message
    assert "host provides the exact active-attempt cancellation" in misleading_cancel.value.message
    definition["components"] = [
        node for node in definition["components"] if node["id"] != "first_cancel"
    ]
    Compositions.validate_owner_controls(
        LearningCompositionV2.model_validate(definition), bindings,
    )


def test_unbound_global_cancel_and_display_only_cancel_keep_their_original_meaning():
    definition, bindings = owner_pair("ChoiceAnswer")
    display = {
        "id": "overview", "component": "Explanation",
        "props": {"text": "This cancellation applies to the whole artifact."},
    }
    cancel = explicit_action("overview", "cancel")
    definition["components"].extend([
        explicit_action("first", "submit_answer"),
        explicit_action("second", "submit_answer"), display, cancel,
    ])
    Compositions.validate_owner_controls(
        LearningCompositionV2.model_validate(definition), bindings,
    )
    definition["states"] = {}
    definition["components"] = [display, cancel]
    Compositions.validate_owner_controls(LearningCompositionV2.model_validate(definition), [])


@pytest.mark.parametrize("owned_setup", ["code_workspace"], indirect=True)
@pytest.mark.parametrize(("invalid_control", "expected_message"), [
    ("missing_submit", "check_code"),
    ("owner_cancel", "cancels the whole artifact"),
])
def test_original_runtime_rejects_invalid_python_controls_despite_choice_control_without_residue(
    database, session, owned_setup, invalid_control, expected_message,
):
    setup = owned_setup
    python = selected(session, setup)
    choice = setup["flow"].candidate(
        session.token, setup["conversation"].id,
        LearningCandidateInput(pack_id=setup["choice_pack"].pack_id, slot="practice_1"),
    )

    def invalid_python_action(args):
        if invalid_control == "missing_submit":
            args["definition"]["components"] = [
                node for node in args["definition"]["components"] if node["id"] != "submit"
            ]
        else:
            cancel = explicit_action("response", "cancel")
            cancel["props"]["label"] = "Cancel only this practice"
            args["definition"]["components"].append(cancel)

    accepted = setup["tutor"].submit(
        session.token, setup["conversation"].id, str(uuid4()), TurnInput(
            text="Compose these original Python and choice practices with explicit controls.",
            focus=python.focus,
            presentation_capabilities={
                "versions": ["learning_composition.v2"], "actions": ["learning_practice.v2"],
            },
        ),
    )
    gateway, wires, _ = practice_provider(
        setup["settings"], python.id, extra_source_id=choice.id, mutate=invalid_python_action,
    )
    try:
        loop = AgentLoop(setup["tutor"], gateway)
        loop.run(accepted.run_id)
        loop.run(accepted.run_id)
        assert len(wires) == 2
        preparation = json.loads(wires[-1]["messages"][-1]["content"])
        assert "items" in preparation
        with database.transaction() as connection:
            receipts = Runs(connection).tool_outputs(
                accepted.run_id, "prepare_learning_practice_composition",
            )
            assert len(receipts) == 1 and receipts[0]["status"] == "waiting_dependency"
            assert expected_message in json.dumps(receipts[0])
            assert not connection.execute(
                "SELECT 1 FROM tutor.learning_presentations WHERE prepared_run_id=%s",
                (accepted.run_id,),
            ).fetchone()
            assert not connection.execute(
                "SELECT 1 FROM tutor.learning_candidates WHERE actor_id=%s "
                "AND conversation_id=%s AND kind='learning_composition'",
                (session.actor.id, setup["conversation"].id),
            ).fetchone()
            task = connection.execute(
                "SELECT candidate,candidate_call_id FROM tutor.delivery_tasks WHERE run_id=%s",
                (accepted.run_id,),
            ).fetchone()
            assert task["candidate"] is None and task["candidate_call_id"] is None
        assert not setup["flow"].list_v2(session.token, setup["conversation"].id)
        turn = next(
            turn for turn in setup["tutor"].turn_history(session.token, setup["conversation"].id)
            if turn.id == accepted.turn_id
        )
        assert turn.assistant_text is None and turn.learning_interaction is None
    finally:
        setup["tutor"].cancel(session.token, accepted.run_id)


@pytest.mark.parametrize("owned_setup", ["knowledge_check"], indirect=True)
def test_historical_missing_control_reads_and_owner_prepare_replays_without_new_admission(
    database, session, owned_setup, monkeypatch,
):
    setup = owned_setup

    def remove_actions(args):
        args["definition"]["components"] = [
            node for node in args["definition"]["components"]
            if node["component"] != "ArtifactAction"
        ]
        args["definition"]["components"].append(explicit_action("response", "cancel"))

    with monkeypatch.context() as historical:
        historical.setattr(
            Compositions, "validate_owner_controls",
            staticmethod(lambda _definition, _bindings: None),
        )
        task, accepted, prepared, wires, _, _ = introduce_owned(
            session, setup, mutate=remove_actions,
        )
    assert task.status == "accepted" and len(wires) == 4
    candidate = CompositionCandidate.model_validate_json(
        json.dumps(prepared[0]["candidate"]),
    )
    artifact = setup["flow"].list_v2(session.token, setup["conversation"].id)[0]
    original = setup["flow"].get_v2(
        session.token, artifact.conversation_id, artifact.id,
    )
    actions = [
        node for node in original.presentation.definition.components
        if node.component == "ArtifactAction"
    ]
    assert len(actions) == 1
    assert actions[0].props.event == "cancel" and actions[0].props.for_component == "response"
    args = PreparePracticeComposition(
        command_key="owned-practice-composition", definition=candidate.presentation.definition,
        owner_bindings=[
            CompositionOwnerProposal(
                component_id=binding.component_id, candidate_id=binding.source.id,
            )
            for binding in candidate.owner_bindings
        ],
    )

    def no_reinterpretation(_definition, _bindings):
        raise AssertionError("Historical records must not receive new admission semantics.")

    with monkeypatch.context() as replay:
        replay.setattr(
            Compositions, "validate_owner_controls", staticmethod(no_reinterpretation),
        )
        assert setup["flow"].get_v2(
            session.token, original.conversation_id, original.id,
        ) == original
        with database.transaction() as connection:
            with pytest.raises(BusinessError, match="already delivered") as delivered:
                CompositionWorkflow.prepare_in(
                    connection, session.actor, Runs(connection).lock(accepted.run_id),
                    args, practice=True,
                )
            assert delivered.value.code == "precondition_failed"
            store = Compositions(connection)
            stored = store.get(session.actor, candidate.content_ref.id)
            result = store.prepare(
                session.actor, original.conversation_id, accepted.run_id, candidate.focus,
                stored["command_key"], candidate.presentation.definition,
                stored["context_manifest"], owner_bindings=candidate.owner_bindings,
                review_bindings=candidate.review_bindings, demo_bindings=candidate.demo_bindings,
            )
            assert connection.execute(
                "SELECT count(*) AS n FROM tutor.learning_presentations WHERE prepared_run_id=%s",
                (accepted.run_id,),
            ).fetchone()["n"] == 1
        assert result == candidate
    restored = setup["flow"].get_v2(session.token, original.conversation_id, original.id)
    assert restored == original
    assert restored.content_ref.id == candidate.content_ref.id
