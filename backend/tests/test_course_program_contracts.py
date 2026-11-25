import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from leornian.agent_runtime.tools import PROGRAM_COMPOSITION_TOOLS, allowed
from leornian.bootstrap.material_repreparations import replace_accepted_ranges
from leornian.modules.assessment.program_contracts import ProgramGateSubmission
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.execution.contracts import CaseOutput, WebCheckResult
from leornian.modules.item_bank.program_contracts import (
    StdioAnswer,
    StdioItem,
    WebAnswer,
    WebItem,
)
from leornian.modules.knowledge.material_contracts import MaterialRef
from leornian.modules.learning.materials import MaterialBindings
from leornian.shared_kernel.errors import BusinessError


@pytest.mark.parametrize(("language", "entrypoint"), [
    ("python", "main.py"), ("javascript", "main.js"), ("typescript", "main.ts"),
    ("java", "Main.java"), ("go", "main.go"), ("csharp", "Program.cs"),
])
def test_six_language_items_preserve_raw_stdin_public_sample_and_file_manifest(
    language, entrypoint,
):
    item = StdioItem.model_validate({
        "slot": "practice_1", "title": "Text protocol", "prompt": "Read the exact input.",
        "difficulty": 1, "source_refs": [{"source_id": str(uuid4()), "revision": 1}],
        "environment": {
            "language": language, "runtime_version": "1.0.0",
            "environment_release_id": str(uuid4()),
        },
        "entrypoint": entrypoint, "files": [
            {"path": entrypoint, "content": "learner draft"},
            {"path": "notes.txt", "read_only": True, "content": "fixed context"},
        ],
        "sample": {"input": "word with spaces\n", "expected": ""},
        "tests": [
            {"input": "word with spaces\n", "expected": ""},
            {"input": "\tother\n", "expected": " a "},
            {"input": "", "expected": "\t"},
        ],
        "explanation": "The protocol preserves text rather than assuming JSON integers.",
    })
    answer = StdioAnswer(files=item.files)
    execution = item.execution(answer)
    assert execution.inputs == ["word with spaces\n", "\tother\n", ""]
    assert execution.language == language
    assert "tests" not in item.public().model_dump()
    assert "explanation" not in item.public().model_dump()
    changed = answer.model_copy(update={"files": [
        answer.files[0], answer.files[1].model_copy(update={"content": "changed"}),
    ]})
    with pytest.raises(ValueError, match="Read-only"):
        item.execution(changed)
    with pytest.raises(ValueError, match="manifest"):
        item.execution(StdioAnswer(files=[answer.files[0]]))


def row_for(profile, tests):
    return {
        "id": uuid4(), "status": "queued", "purpose": "training",
        "comparison_profile": profile, "comparison_order": None,
        "sample_case_index": 0, "test_cases": tests,
    }


def output(text, *, exit_code=0):
    return CaseOutput(stdout=text, stderr="", exit_code=exit_code, outcome="completed")


def test_stdio_scoring_normalizes_only_line_endings_and_one_terminal_newline():
    row = row_for("stdio-text.v1", [
        {"expected": "a\nb\n"}, {"expected": "  text  "}, {"expected": ""},
    ])
    scorer = ProgramAssessment(Mock())
    passed = scorer.complete(row, [output("a\r\nb\r\n"), output("  text  \n"), output("")])
    assert passed["status"] == "passed" and passed["passed_cases"] == 3
    assert passed["sample_result"]["text_output"] == "a\r\nb\r\n"
    failed = scorer.complete(row, [output("a\nb\n\n"), output("text"), output("\t")])
    assert failed["status"] == "not_passed" and failed["passed_cases"] == 0


def web_item():
    tests = [
        {"check": {"key": "present", "kind": "exists", "selector": "#heading"}, "expected": True},
        {"check": {"key": "label", "kind": "text", "selector": "#heading"}, "expected": "Hello"},
        {
            "check": {"key": "color", "kind": "style", "selector": "#heading", "property": "color"},
            "expected": "rgb(1, 2, 3)",
        },
    ]
    return WebItem.model_validate({
        "slot": "practice_1", "title": "Heading", "prompt": "Style the existing heading.",
        "difficulty": 1, "source_refs": [{"source_id": str(uuid4()), "revision": 1}],
        "environment": {"runtime_version": "1.0.0", "environment_release_id": str(uuid4())},
        "entrypoint": "index.html",
        "files": [{"path": "index.html", "content": '<h1 id="heading">Hello</h1>'}],
        "sample": tests[0], "tests": tests,
        "explanation": "Check the actual DOM and computed style.",
    })


def test_web_runner_receives_operations_without_private_expected_answers():
    item = web_item()
    data = item.execution(WebAnswer(files=item.files)).model_dump(mode="json")
    assert len(data["checks"]) == 3
    assert all("expected" not in value for value in data["checks"])
    assert "tests" not in item.public().model_dump()
    assert item.public().sample.expected is True


@pytest.mark.parametrize("values", [
    [True, "Hello", "rgb(1, 2, 3)"],
    [False, "hello", "rgb(1, 2, 3)"],
    ["true", "Hello", "rgb(1, 2, 3)"],
])
def test_web_scoring_uses_strict_types_and_exact_observation_keys(values):
    item = web_item()
    row = row_for("web-check.v1", [test.model_dump(mode="json") for test in item.tests])
    document = WebCheckResult(results=[
        {"key": test.check.key, "actual": value}
        for test, value in zip(item.tests, values, strict=True)
    ])
    result = ProgramAssessment(Mock()).complete(row, [output(document.model_dump_json())])
    expected = 3 if values[0] is True else 1 if values[0] is False else 2
    assert result["passed_cases"] == expected
    assert result["sample_result"]["output"]["results"] == [{
        "key": "present", "actual": values[0],
    }]
    incomplete = json.loads(document.model_dump_json())
    incomplete["results"].pop()
    invalid = ProgramAssessment(Mock()).complete(row, [output(json.dumps(incomplete))])
    assert invalid["status"] == "error"
    assert invalid["error_code"] == "invalid_execution_report"


def test_failed_compilation_has_no_sample_or_executed_case_credit():
    row = row_for("stdio-text.v1", [{"expected": "ok"}] * 3)
    compilation = CaseOutput(
        stdout="", stderr="Main.java: syntax error", exit_code=1, outcome="completed",
    )
    result = ProgramAssessment(Mock()).complete(row, [], compilation)
    assert result["status"] == "not_passed"
    assert result["passed_cases"] == 0 and result["sample_result"] is None
    assert result["compilation"] == compilation
    assert "no learner case" in result["feedback"]
    contradictory = ProgramAssessment(Mock()).complete(
        row, [output("ok")] * 3, compilation,
    )
    assert contradictory["status"] == "error"
    assert contradictory["passed_cases"] == 0


def test_program_gate_requires_both_distinct_reserved_slots():
    with pytest.raises(ValidationError):
        ProgramGateSubmission(programs=[])
    answer = {"type": "stdio", "files": [{"path": "main.py", "content": "print(1)"}]}
    with pytest.raises(ValidationError):
        ProgramGateSubmission(programs=[
            {"slot": "assessment_1", "answer": answer},
            {"slot": "assessment_1", "answer": answer},
        ])
    assert len(ProgramGateSubmission(programs=[
        {"slot": "assessment_1", "answer": answer}, {"slot": "assessment_2", "answer": answer},
    ]).programs) == 2


def test_new_environment_and_program_supply_tools_do_not_expand_old_frozen_runs():
    old = {"learning_get_context": 1, "prepare_learning_program_composition": 1}
    assert not set(allowed(old)) & {
        "get_execution_environments", "request_execution_environment",
        "request_learning_program_supply", "get_learning_program_supply",
    }
    assert {
        "get_execution_environments", "request_execution_environment",
        "request_learning_program_supply", "get_learning_program_supply",
    } <= set(PROGRAM_COMPOSITION_TOOLS)


def test_accepted_partial_update_retains_unaffected_exact_ranges_and_binding_boundaries():
    text = "abcdefghij"
    ref = MaterialRef(
        document_id=uuid4(), document_revision=1, block_id=uuid4(),
        span={"start": 0, "end": len(text)},
        content_digest=hashlib.sha256(text.encode()).hexdigest(),
    )
    old = ref.model_copy(update={
        "span": ref.span.model_copy(update={"start": 3, "end": 7}),
        "content_digest": hashlib.sha256(b"defg").hexdigest(),
    })
    successor = ref.model_copy(update={
        "document_revision": 2, "block_id": uuid4(),
        "span": ref.span.model_copy(update={"end": 7}),
        "content_digest": hashlib.sha256(b"updated").hexdigest(),
    })
    pieces = replace_accepted_ranges([SimpleNamespace(text=text, ref=ref)], [old], [successor])
    assert [(r.document_revision, r.span.start, r.span.end) for r in pieces] == [
        (1, 0, 3), (1, 7, 10), (2, 0, 7),
    ]
    binding = SimpleNamespace(refs=[ref])
    MaterialBindings.require_ref_in(binding, pieces[0])
    MaterialBindings.require_ref_in(binding, pieces[1])
    with pytest.raises(BusinessError, match="bound source range"):
        MaterialBindings.require_ref_in(binding, successor)
