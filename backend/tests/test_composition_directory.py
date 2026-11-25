import copy
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from leornian.modules.tutor.composition_catalog import COMPONENTS, component_directory
from leornian.modules.tutor.composition_guidance import composition_guidance
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2

ROOT = Path(__file__).parents[2]


def bfs_composition():
    return {
        "schema_version": "learning_composition.v2",
        "title": "Explore traversal",
        "states": {"cursor": {"type": "playback"}},
        "inputs": {
            "network": {
                "type": "bfs", "nodes": ["X", "Y", "Z"], "start": "Y",
                "edges": [{"source": "Y", "target": "X"}, {"source": "X", "target": "Z"}],
            }
        },
        "components": [
            {"id": "title", "component": "Explanation", "props": {"text": "Observe discovery."}},
            {"id": "player", "component": "AlgorithmPlayer", "props": {
                "label": "Traversal", "algorithm": "bfs", "input": "network", "state": "cursor",
            }},
            {"id": "graph", "component": "AlgorithmGraph", "props": {
                "label": "Graph", "timeline": "player",
            }},
            {"id": "queue", "component": "AlgorithmContainer", "props": {
                "label": "Queue", "timeline": "player",
            }},
        ],
    }


def test_directory_matches_all_31_existing_component_names_and_eight_categories():
    text = (ROOT / "apps/librechat/component-catalog.mjs").read_text(encoding="utf-8")
    frontend = set(re.findall(r"^\s{2}([A-Z][A-Za-z]+):", text, re.MULTILINE))
    assert frontend == {entry[0] for entry in COMPONENTS}
    assert len(frontend) == 31 and len({entry[1] for entry in COMPONENTS}) == 8
    schema = LearningCompositionV2.model_json_schema()
    mapping = schema["properties"]["components"]["items"]["discriminator"]["mapping"]
    assert set(mapping) == frontend
    assert {d["component"] for d in component_directory()} == frontend
    assert len(component_directory(["CodeEditor", "CodeDiff"])) == 2
    with pytest.raises(ValueError, match="Unknown"):
        component_directory(["UnregisteredExecutor"])


def test_bfs_is_a_component_composition_with_one_shared_state_not_a_recipe_switch():
    value = LearningCompositionV2.model_validate(bfs_composition())
    assert value.components[2].props.timeline == value.components[3].props.timeline
    assert value.inputs["network"].start == "Y"
    changed = bfs_composition()
    changed["components"].append({
        "id": "table", "component": "DataTable",
        "props": {"label": "Initial data", "columns": ["Node"], "rows": [["X"], ["Y"], ["Z"]]},
    })
    assert LearningCompositionV2.model_validate(changed).components[-1].component == "DataTable"


def test_timeline_diagnostic_and_guide_distinguish_player_id_from_playback_state():
    value = bfs_composition()
    value["components"][2]["props"]["timeline"] = "cursor"
    with pytest.raises(ValidationError) as error:
        LearningCompositionV2.model_validate(value)
    assert "graph.timeline must reference an AlgorithmPlayer component id using bfs" in str(
        error.value
    )
    assert "not a playback state key" in str(error.value)
    guide = composition_guidance("learning_composition.v2")
    assert "timeline names the AlgorithmPlayer component id" in guide
    assert "not its playback state key" in guide


@pytest.mark.parametrize("change", [
    "duplicate_node", "missing_state", "wrong_state", "missing_timeline",
    "incompatible_timeline", "dangling_input", "callback", "url", "permission", "result",
])
def test_invalid_ports_or_authority_fields_are_rejected(change):
    value = bfs_composition()
    if change == "duplicate_node":
        value["components"].append(copy.deepcopy(value["components"][0]))
    elif change == "missing_state":
        value["states"] = {}
    elif change == "wrong_state":
        value["states"]["cursor"] = {"type": "code", "value": "inert"}
    elif change == "missing_timeline":
        value["components"][2]["props"]["timeline"] = "missing"
    elif change == "incompatible_timeline":
        value["components"][2]["component"] = "AlgorithmGrid"
    elif change == "dangling_input":
        value["components"][1]["props"]["input"] = "missing"
    else:
        field = {
            "callback": "onClick", "url": "endpoint", "permission": "allowed_actions",
            "result": "correct_key",
        }[change]
        value["components"][2]["props"][field] = "not allowed"
    with pytest.raises(ValidationError):
        LearningCompositionV2.model_validate(value)


def test_editor_diff_share_code_without_callbacks_and_actions_are_explicit_intents():
    value = {
        "schema_version": "learning_composition.v2", "title": "Repair",
        "states": {"program": {"type": "code", "value": "print(0)"}},
        "components": [
            {"id": "editor", "component": "CodeEditor", "props": {
                "label": "Program", "state": "program",
            }},
            {"id": "diff", "component": "CodeDiff", "props": {
                "label": "Changes", "state": "program", "before": "print(0)",
            }},
            {"id": "check", "component": "ArtifactAction", "props": {
                "label": "Check", "event": "check_code", "for_component": "editor",
            }},
            {"id": "actions", "component": "ActionGroup", "props": {"members": ["check"]}},
            {"id": "feedback", "component": "ResultFeedback", "props": {
                "label": "Result", "for_component": "editor",
            }},
        ],
    }
    parsed = LearningCompositionV2.model_validate(value)
    assert parsed.components[0].props.state == parsed.components[1].props.state
    value["components"][2]["props"]["event"] = "submit_review"
    with pytest.raises(ValidationError, match="not supported"):
        LearningCompositionV2.model_validate(value)


def test_answer_initial_state_cannot_be_a_model_supplied_learner_response():
    value = {
        "schema_version": "learning_composition.v2", "title": "Question",
        "states": {"answer": {"type": "choice", "value": ["A"]}},
        "components": [{
            "id": "question", "component": "ChoiceAnswer",
            "props": {"label": "Choose", "state": "answer",
                      "options": [{"id": "A", "text": "First"}, {"id": "B", "text": "Second"}]},
        }],
    }
    with pytest.raises(ValidationError):
        LearningCompositionV2.model_validate(value)
