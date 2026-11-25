import importlib.util
import json
import os
import secrets
from pathlib import Path

import pytest
from test_program_contracts import project_program, sql_program

pytestmark = pytest.mark.skipif(
    os.environ.get("LEORNIAN_TEST_DOCKER") != "1",
    reason="Set LEORNIAN_TEST_DOCKER=1 for real local SQL/project isolation tests",
)


@pytest.fixture(scope="module")
def runner():
    source = Path(__file__).parents[2] / "services" / "runner" / "controller.py"
    spec = importlib.util.spec_from_file_location("program_runner", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def successful_table(result):
    assert result["outcome"] == "completed" and result["exit_code"] == 0, result
    return json.loads(result["stdout"])


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
def test_real_sql_dialects_rows_nulls_empty_results_and_exact_text(runner, dialect):
    data = sql_program(dialect)
    text = "quote' backslash\\ newline\n\u4e2d\u6587"
    data["datasets"] = [
        {"rows": {"records": [[1, text], [2, None]]}},
        {"rows": {"records": []}},
    ]
    results = runner.execute_sql(data)
    assert successful_table(results[0]) == {
        "profile": "sql-table.v1", "columns": ["id", "name"],
        "rows": [["1", text], ["2", None]],
        "types": [["integer", "text"], ["integer", "null"]],
    }
    assert successful_table(results[1])["rows"] == []
    assert successful_table(results[1])["columns"] == ["id", "name"]


@pytest.mark.parametrize("dialect,query", [
    ("sqlite", "SELECT sqlite_version() AS engine"),
    ("postgresql", "SELECT version() AS engine"),
    ("mysql", "SELECT VERSION() AS engine"),
])
def test_real_dialects_are_not_a_sqlite_alias(runner, dialect, query):
    result = successful_table(runner.execute_sql(sql_program(dialect, query))[0])
    version = result["rows"][0][0]
    if dialect == "postgresql":
        assert "PostgreSQL" in version
    elif dialect == "mysql":
        assert version.startswith("8.0.")
    else:
        assert version.startswith("3.")


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
def test_real_sql_keeps_duplicate_rows_and_materializes_declared_foreign_keys(runner, dialect):
    data = sql_program(
        dialect,
        "SELECT records.name FROM children JOIN records ON children.parent=records.id "
        "ORDER BY records.id",
    )
    data["schema_definition"]["tables"].insert(0, {
        "name": "children", "columns": [{"name": "parent", "type": "integer"}],
        "foreign_keys": [
            {"column": "parent", "references_table": "records", "references_column": "id"},
        ],
    })
    data["datasets"][0]["rows"] = {
        "children": [[1], [2]], "records": [[1, "duplicate"], [2, "duplicate"]],
    }
    result = successful_table(runner.execute_sql(data)[0])
    assert result == {
        "profile": "sql-table.v1", "columns": ["name"],
        "rows": [["duplicate"], ["duplicate"]],
        "types": [["text"], ["text"]],
    }


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
def test_sql_cannot_write_or_execute_multiple_statements(runner, dialect):
    for query in ("DELETE FROM records", "SELECT 1; SELECT 2"):
        result = runner.execute_sql(sql_program(dialect, query))[0]
        assert result["outcome"] == "completed" and result["exit_code"] == 2, result
        assert result["stdout"] == ""


@pytest.mark.parametrize("dialect,query", [
    ("sqlite", "SELECT load_extension('/host/extension')"),
    ("postgresql", "SELECT pg_read_file('/etc/passwd')"),
    ("mysql", "SELECT LOAD_FILE('/etc/passwd')"),
])
def test_sql_has_no_database_file_privilege(runner, dialect, query):
    result = runner.execute_sql(sql_program(dialect, query))[0]
    if dialect == "mysql":
        assert successful_table(result)["rows"] == [[None]]
    else:
        assert result["outcome"] == "completed" and result["exit_code"] == 2, result


def test_real_sql_bounded_time_and_output(runner):
    result = runner.execute_sql(sql_program(
        "sqlite",
        "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM r) SELECT sum(x) FROM r",
    ))[0]
    assert result["outcome"] == "timeout"
    result = runner.execute_sql(sql_program("sqlite", "SELECT printf('%05000d', 1)"))[0]
    assert result["exit_code"] == 2 and result["stdout"] == ""


@pytest.mark.parametrize("nested", [False, True])
def test_real_multifile_import_and_declared_data_file(runner, nested):
    data = project_program()
    if nested:
        for item in data["files"][:2]:
            item["path"] = "src/" + item["path"]
        data["entrypoint"] = "src/main.py"
    results = runner.execute_project(data)
    assert [r["stdout"].strip() for r in results] == ["6", "0", "3"]
    assert all(r["outcome"] == "completed" and r["exit_code"] == 0 for r in results), results


def test_multifile_cannot_modify_project_or_receive_host_credentials(runner):
    data = project_program()
    data["inputs"] = [[]]
    data["files"][0]["content"] = """
import json,os,socket
denied = []
for path in ('helpers.py', '/host/something'):
    try:
        open(path, 'w').close()
    except OSError:
        denied.append(path)
print(json.dumps({'denied': denied, 'uid': os.getuid(),
    'interfaces': socket.if_nameindex(),
    'credentials': [key for key in os.environ if key.startswith('LEORNIAN_')]}))
"""
    result = runner.execute_project(data)[0]
    assert result["outcome"] == "completed" and result["exit_code"] == 0, result
    assert json.loads(result["stdout"]) == {
        "denied": ["helpers.py", "/host/something"], "uid": 65534,
        "interfaces": [[1, "lo"]], "credentials": [],
    }


def test_large_stdin_cannot_block_the_container_deadline(runner):
    from runner_runtime import sandbox
    name = "leornian-feed-" + secrets.token_hex(10)
    command = sandbox._container_options(name) + [
        "-i", sandbox.IMAGE, "python", "-I", "-B", "-c", "import time; time.sleep(60)",
    ]
    result = sandbox._bounded_container(command, b"x" * 300000, name, 2)
    assert result["outcome"] == "timeout"


def test_exact_runtime_mismatch_never_executes_the_learner_program(runner):
    data = sql_program("sqlite", "SELECT 1 AS answer")
    data["runtime_version"] = "999.0"
    result = runner.execute_sql(data)[0]
    assert result["outcome"] == "infrastructure_error" and result["stdout"] == ""
    data = project_program()
    data["runtime_version"] = "999.0"
    result = runner.execute_project(data)[0]
    assert result["outcome"] == "infrastructure_error" and result["stdout"] == ""


def test_learner_exit_seventy_is_not_forged_as_a_trusted_environment_failure(runner):
    from runner_runtime import stdio
    data = project_program()
    data["runtime_version"] = stdio._python_versions(stdio.IMAGE)[0]
    data["inputs"] = [[]]
    data["files"][0]["content"] = "raise SystemExit(70)"
    result = runner.execute_project(data)[0]
    assert result["outcome"] == "completed" and result["exit_code"] == 70


def test_real_postgres_numeric_precision_survives_output_encoding(runner):
    value = "123456789012345678901234567890.0001"
    data = sql_program("postgresql", "SELECT " + value + "::numeric AS answer")
    result = successful_table(runner.execute_sql(data)[0])
    assert result["rows"] == [[value]] and result["types"] == [["number"]]
