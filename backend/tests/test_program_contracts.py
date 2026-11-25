from copy import deepcopy

import pytest
from pydantic import ValidationError

from leornian.modules.execution.contracts import PythonProjectProgram, SqlProgram


def sql_program(dialect="sqlite", query="SELECT id, name FROM records ORDER BY id"):
    return {
        "dialect": dialect, "query": query,
        "schema_definition": {"tables": [{
            "name": "records", "columns": [
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "name", "type": "text"},
            ],
        }]},
        "datasets": [{"rows": {"records": [[1, "one"], [2, None]]}}],
    }


def project_program():
    return {
        "files": [
            {"path": "main.py", "content": (
                "import json,sys\nfrom helpers import total\n"
                "print(total(json.load(sys.stdin)))\n"
            )},
            {"path": "helpers.py", "read_only": True, "content": (
                "from pathlib import Path\n"
                "def total(values):\n"
                "    return sum(values) + int(Path('data/offset.txt').read_text())\n"
            )},
            {"path": "data/offset.txt", "read_only": True, "content": "3"},
        ], "entrypoint": "main.py", "inputs": [[1, 2], [-3], []],
    }


def test_closed_program_inputs_do_not_accept_commands_images_or_authority():
    for value in ("sqlite", "postgresql", "mysql"):
        assert SqlProgram.model_validate(sql_program(value)).dialect == value
    for value in ("shell", "mariadb", "duckdb"):
        with pytest.raises(ValidationError):
            SqlProgram.model_validate(sql_program(value))
    for key in ("image", "command", "expected_rows", "database_url"):
        with pytest.raises(ValidationError):
            SqlProgram.model_validate({**sql_program(), key: "caller input"})
    assert PythonProjectProgram.model_validate(project_program()).entrypoint == "main.py"


@pytest.mark.parametrize("rows", [
    [[1, "x"], [1, "duplicate"]],
    [[True, "not an integer"]],
    [[None, "null primary key"]],
    [[1, "x", "extra"]],
    [[1, "x"]] * 101,
    [[1, "\x00"]],
])
def test_sql_rejects_invalid_or_unbounded_typed_rows(rows):
    data = sql_program()
    data["datasets"][0]["rows"]["records"] = rows
    with pytest.raises(ValidationError):
        SqlProgram.model_validate(data)


def test_schema_foreign_keys_have_real_compatible_primary_key_targets():
    data = sql_program()
    data["schema_definition"]["tables"].insert(0, {
        "name": "children", "columns": [{"name": "parent", "type": "integer"}],
        "foreign_keys": [
            {"column": "parent", "references_table": "records", "references_column": "id"},
        ],
    })
    data["datasets"][0]["rows"]["children"] = [[1], [None]]
    SqlProgram.model_validate(data)
    invalid = deepcopy(data)
    invalid["datasets"][0]["rows"]["children"] = [[3]]
    with pytest.raises(ValidationError, match="existing row"):
        SqlProgram.model_validate(invalid)
    invalid = deepcopy(data)
    invalid["schema_definition"]["tables"][1]["columns"][0]["primary_key"] = False
    with pytest.raises(ValidationError, match="exact declared target"):
        SqlProgram.model_validate(invalid)


@pytest.mark.parametrize("path", [
    "../outside.py", "/absolute.py", "C:/host.py", "nested/../../outside.py", "nested\\main.py",
    "nested/./main.py",
])
def test_project_rejects_host_paths_and_traversal(path):
    data = project_program()
    data["files"][0]["path"] = data["entrypoint"] = path
    with pytest.raises(ValidationError):
        PythonProjectProgram.model_validate(data)


def test_project_requires_exact_distinct_files_and_utf8_budget():
    data = project_program()
    data["files"][0]["content"] = "\u4e2d" * 34000
    with pytest.raises(ValidationError):
        PythonProjectProgram.model_validate(data)
    data = project_program()
    data["files"].append({"path": "helpers.py/nested.py", "content": ""})
    with pytest.raises(ValidationError):
        PythonProjectProgram.model_validate(data)
    data = project_program()
    data["files"].append(data["files"][0])
    with pytest.raises(ValidationError):
        PythonProjectProgram.model_validate(data)
