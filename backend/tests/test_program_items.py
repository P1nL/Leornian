from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.item_bank.program_contracts import (
    ProjectAnswer,
    ProjectPack,
    SqlPack,
)
from leornian.modules.item_bank.supply_contracts import SLOTS, PackRequest

EXPRESSIONS = {
    "practice_1": "sum(xs)",
    "practice_2": "sum(1 for x in xs if x > 0)",
    "assessment_1": "sum(abs(x) for x in xs)",
    "assessment_2": "max(xs) if xs else 0",
    "remediation_1": "sum(1 for x in xs if x % 2 == 0)",
}
SQL_EXPRESSIONS = {
    "practice_1": "COALESCE(SUM(n),0)",
    "practice_2": "COUNT(CASE WHEN n>0 THEN 1 END)",
    "assessment_1": "COALESCE(SUM(ABS(n)),0)",
    "assessment_2": "COALESCE(MAX(n),0)",
    "remediation_1": "COUNT(CASE WHEN n%2=0 THEN 1 END)",
}
EXPECTED = {
    "practice_1": [6, 0, -3],
    "practice_2": [3, 0, 1],
    "assessment_1": [6, 0, 7],
    "assessment_2": [3, 0, 2],
    "remediation_1": [1, 0, 2],
}
INPUTS = [[1, 2, 3], [], [-4, 2, -1]]


def environment(kind="sql_query", dialect="sqlite"):
    if kind == "python_project":
        return {"profile": "python-project-io.v1", "runtime_version": "3.12.14"}
    return {
        "profile": "sql-query.v1",
        "dialect": dialect,
        "runtime_version": {"sqlite": "3.46.1", "postgresql": "15.19", "mysql": "8.0.46"}[dialect],
    }


def table(value, kind="integer"):
    return {
        "profile": "sql-table.v1",
        "columns": ["answer"],
        "rows": [[None if value is None else str(value)]],
        "types": [["null" if value is None else kind]],
    }


def item_document(source, env):
    items = []
    for slot in SLOTS:
        common = {
            "slot": slot,
            "title": "Bound program " + slot,
            "prompt": "Compute the exact contextual operation: " + EXPRESSIONS[slot],
            "difficulty": 1 if slot == "remediation_1" else 2,
            "source_refs": [{"source_id": str(source.id), "revision": 1}],
            "environment": env,
            "explanation": "Private fixed explanation " + slot,
        }
        if env["profile"] == "sql-query.v1":
            kind = (
                "number"
                if env["dialect"] == "mysql"
                and slot
                in {
                    "practice_1",
                    "assessment_1",
                }
                else "integer"
            )
            tests = [
                {
                    "dataset": {"rows": {"records": [[value] for value in values]}},
                    "expected": table(expected, kind),
                }
                for values, expected in zip(INPUTS, EXPECTED[slot], strict=True)
            ]
            items.append(
                {
                    **common,
                    "language": "sql_query",
                    "schema_definition": {
                        "tables": [
                            {
                                "name": "records",
                                "columns": [
                                    {"name": "n", "type": "integer", "nullable": False},
                                ],
                            }
                        ]
                    },
                    "starter_query": "SELECT 0 AS answer",
                    "comparison": "ordered",
                    "sample": tests[0],
                    "tests": tests,
                }
            )
        else:
            tests = [
                {"input": values, "expected": expected}
                for values, expected in zip(INPUTS, EXPECTED[slot], strict=True)
            ]
            items.append(
                {
                    **common,
                    "language": "python_project",
                    "entrypoint": "src/main.py",
                    "files": [
                        {
                            "path": "src/main.py",
                            "read_only": True,
                            "content": (
                                "import json,sys\nfrom helpers import calculate\n"
                                "print(calculate(json.load(sys.stdin)))\n"
                            ),
                        },
                        {
                            "path": "src/helpers.py",
                            "read_only": False,
                            "content": "def calculate(xs):\n    return 0\n",
                        },
                        {"path": "data/offset.txt", "read_only": True, "content": "0"},
                    ],
                    "sample": tests[0],
                    "tests": tests,
                }
            )
    return {"items": items}


def answer_for(item, *, wrong=False, changed=False):
    if item["language"] == "sql_query":
        return {
            "type": "sql",
            "query": "SELECT 0 AS answer"
            if wrong
            else "SELECT "
            + SQL_EXPRESSIONS[item["slot"]]
            + " AS answer FROM records"
            + (" /* explicit revision */" if changed else ""),
        }
    files = deepcopy(item["files"])
    if not wrong:
        files[1]["content"] = (
            "from pathlib import Path\n"
            "def calculate(xs):\n    return ("
            + EXPRESSIONS[item["slot"]]
            + ") + int(Path('data/offset.txt').read_text())"
            + (" + 0" if changed else "")
            + "\n"
        )
    return {"type": "project", "files": files}


@pytest.mark.parametrize(
    "kind,dialect",
    [
        ("sql_query", "sqlite"),
        ("sql_query", "postgresql"),
        ("sql_query", "mysql"),
        ("python_project", None),
    ],
)
def test_closed_program_documents_public_sample_and_private_cases(kind, dialect):
    source = type("Source", (), {"id": uuid4()})()
    env = environment(kind, dialect)
    schema = SqlPack if kind == "sql_query" else ProjectPack
    pack = schema.model_validate(item_document(source, env))
    for item in pack.items:
        public = item.public().model_dump()
        assert "tests" not in public and "explanation" not in public
        assert item.environment.model_dump() == env
        assert item.sample in item.tests
    with pytest.raises(ValidationError):
        PackRequest(
            expected_plan_revision=1,
            node_key="node",
            instruction="A bounded task",
            kind=kind,
        )


def test_protected_project_manifest_is_authority_not_caller_metadata():
    source = type("Source", (), {"id": uuid4()})()
    item = ProjectPack.model_validate(
        item_document(source, environment("python_project")),
    ).items[0]
    correct = answer_for(item.model_dump())
    item.execution(ProjectAnswer.model_validate(correct))
    for mutate in ("contents", "flag", "extra"):
        invalid = deepcopy(correct)
        if mutate == "contents":
            invalid["files"][0]["content"] = "print(6)"
        elif mutate == "flag":
            invalid["files"][0]["read_only"] = False
        else:
            invalid["files"].append({"path": "outside.py", "content": "print(6)"})
        with pytest.raises(ValueError):
            item.execution(ProjectAnswer.model_validate(invalid))


def test_sql_comparison_preserves_types_null_order_and_duplicate_counts():
    expected = table("1", "integer")
    assert ProgramAssessment.matches_sql(expected, expected, "ordered")
    assert not ProgramAssessment.matches_sql(table("1", "text"), expected, "ordered")
    assert not ProgramAssessment.matches_sql(table(None), table("NULL", "text"), "ordered")
    expected = {
        "profile": "sql-table.v1",
        "columns": ["v"],
        "rows": [["1"], ["2"], ["1"]],
        "types": [["integer"]] * 3,
    }
    reordered = {**expected, "rows": [["2"], ["1"], ["1"]]}
    assert not ProgramAssessment.matches_sql(reordered, expected, "ordered")
    assert ProgramAssessment.matches_sql(reordered, expected, "multiset")
    assert not ProgramAssessment.matches_sql(
        {**expected, "rows": [["1"], ["2"]], "types": [["integer"]] * 2},
        expected,
        "multiset",
    )
