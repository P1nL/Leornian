import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from leornian.modules.tutor.composition_contracts import LearningComposition
from leornian.modules.tutor.composition_guidance import composition_guidance

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads(
    (ROOT / "apps/librechat/composition-examples.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("example", EXAMPLES, ids=[item["title"] for item in EXAMPLES])
def test_frontend_examples_match_the_authoritative_contract(example):
    parsed = LearningComposition.model_validate_json(json.dumps(example), strict=True)
    assert parsed.model_dump(mode="json") == example


@pytest.mark.parametrize(
    "field,value",
    [
        ("nodes", ["A", "A"]),
        ("nodes", []),
        ("nodes", ["X" + str(i) for i in range(13)]),
        ("start", "missing"),
        ("edges", [{"source": "A", "target": "missing"}]),
        ("edges", [{"source": "A", "target": "B"}] * 2),
        ("views", ["queue"]),
        ("views", ["graph", "graph"]),
        ("views", ["graph", "browser_script"]),
    ],
)
def test_rejects_invalid_graph_bindings(field, value):
    example = deepcopy(EXAMPLES[0])
    example["scene"][field] = value
    with pytest.raises(ValidationError):
        LearningComposition.model_validate_json(json.dumps(example), strict=True)


@pytest.mark.parametrize("field", ["onClick", "endpoint", "allowed_actions", "result", "answer"])
def test_proposal_cannot_supply_callbacks_permissions_or_results(field):
    example = deepcopy(EXAMPLES[2])
    example["scene"][field] = "not-authorized"
    with pytest.raises(ValidationError):
        LearningComposition.model_validate_json(json.dumps(example), strict=True)


def test_requires_version_and_editor_and_accepts_cycles():
    example = deepcopy(EXAMPLES[3])
    example["scene"]["views"] = ["diff", "cases"]
    with pytest.raises(ValidationError):
        LearningComposition.model_validate_json(json.dumps(example), strict=True)
    example = deepcopy(EXAMPLES[0])
    example["schema_version"] = "learning_composition.v2"
    with pytest.raises(ValidationError):
        LearningComposition.model_validate_json(json.dumps(example), strict=True)
    example = deepcopy(EXAMPLES[1])
    example["scene"]["edges"].append({"source": "C", "target": "C"})
    LearningComposition.model_validate_json(json.dumps(example), strict=True)


def test_guidance_uses_the_current_schema_without_changing_tool_registry():
    from leornian.agent_runtime.tools import COMPOSITION_TOOLS, TEACHING_TOOLS

    guide = composition_guidance()
    schema = json.loads(guide.split("## Authoritative JSON Schema\n\n")[1])
    assert schema == LearningComposition.model_json_schema()
    assert "prepare_learning_composition" in COMPOSITION_TOOLS
    assert "prepare_learning_composition" not in TEACHING_TOOLS
    assert "not tools or execution permissions" in guide


def test_exported_schema_matches_backend():
    exported = json.loads(
        (ROOT / "apps/librechat/composition-schema.json").read_text(encoding="utf-8")
    )
    assert exported == LearningComposition.model_json_schema()
