import importlib.util
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from leornian.modules.execution.environment_recipes import recipe
from leornian.modules.execution.environment_runtime import EnvironmentInstaller, PreparationStopped

pytestmark = pytest.mark.skipif(
    os.environ.get("LEORNIAN_TEST_DOCKER") != "1",
    reason="Set LEORNIAN_TEST_DOCKER=1 for actual prepared local runtime execution.",
)
ROOT = Path(__file__).parents[2]
SOURCES = {
    "python": ("main.py", "import sys\nprint(int(sys.stdin.read())*2)\n"),
    "javascript": ("main.js", "console.log(Number(require('node:fs').readFileSync(0,'utf8'))*2)"),
    "typescript": (
        "main.ts",
        "import {readFileSync} from 'node:fs';console.log(Number(readFileSync(0,'utf8'))*2);",
    ),
    "java": (
        "Main.java",
        "import java.util.Scanner; class Main {"
        "public static void main(String[] args){"
        "System.out.println(new Scanner(System.in).nextInt()*2);}}",
    ),
    "go": (
        "main.go",
        'package main\nimport("fmt";"os")\n'
        "func main(){var x int;fmt.Fscan(os.Stdin,&x);fmt.Println(x*2)}",
    ),
    "csharp": ("Program.cs", "System.Console.WriteLine(int.Parse(System.Console.ReadLine()!)*2);"),
}


@pytest.fixture(scope="module")
def runner():
    source = ROOT / "services" / "runner" / "controller.py"
    spec = importlib.util.spec_from_file_location("multilanguage_runner", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def engineering_release(language, dialect=None):
    group = dialect if language == "sql" else {
        "javascript": "js", "typescript": "js", "python": "python", "html-css": "web",
    }.get(language, language)
    installer = EnvironmentInstaller(ROOT / ".local" / "environment-engineering" / group)
    key = dialect + "-query.v1" if language == "sql" else (
        "html-css-browser.v1" if language == "html-css" else language + "-standard.v1"
    )
    result = installer.cache["recipes"].get(key)
    if not result or any(installer.image(image) is None for image in result["image_ids"].values()):
        current = EnvironmentInstaller(ROOT / ".local" / "execution-environments")
        result = current.cache["recipes"].get(key)
        if result and any(current.image(image) is None for image in result["image_ids"].values()):
            result = None
    if not result:
        pytest.skip("Actual recipe has not completed engineering preparation: " + key)
    required = recipe(key).requirement
    return {
        "id": str(uuid4()),
        "profile": required.profile,
        "language": required.language,
        "dialect": required.dialect or "",
        **result,
    }


def program(language, release):
    path, source = SOURCES[language]
    return {
        "profile": "project-stdio.v1",
        "language": language,
        "environment_release_id": release["id"],
        "runtime_version": release["runtime_version"],
        "entrypoint": path,
        "files": [{"path": path, "content": source}],
        "inputs": ["4\n", "-3\n", "0\n"],
    }


def test_terminal_delivers_unterminated_prompts_and_multiple_inputs_to_one_process(runner):
    release = engineering_release("python")
    project = program("python", release)
    project["inputs"] = [""]
    project["files"][0]["content"] = (
        'minutes = int(input("分钟："))\nprint(f"{minutes // 60} 小时 {minutes % 60:02d} 分钟")\n'
        'print("继续？", end="")\nprint("再见！" if input() == "q" else "继续")'
    )
    transcript, sent = "", []
    def exchange(text, *, closed=False):
        nonlocal transcript
        transcript += text
        if closed:
            return []
        if not sent and transcript.endswith("分钟："):
            sent.append("65")
            return ["65"]
        if sent == ["65"] and transcript.endswith("1 小时 05 分钟\n继续？"):
            sent.append("q")
            return ["q"]
        return []
    deadline = time.monotonic() + 20
    compilation, cases = runner.execute_stdio(project, release, lambda: time.monotonic() < deadline,
                                               terminal=exchange)
    assert compilation is None and sent == ["65", "q"]
    assert transcript == "分钟：1 小时 05 分钟\n继续？再见！\n"
    assert cases == [{"outcome": "completed", "exit_code": 0, "stdout": transcript, "stderr": ""}]


@pytest.mark.parametrize("language", list(SOURCES))
def test_actual_six_language_compile_and_text_stdin_run_are_separate(runner, language):
    release = engineering_release(language)
    compilation, results = runner.execute_stdio(program(language, release), release)
    if language in {"typescript", "java", "go", "csharp"}:
        assert compilation["outcome"] == "completed" and compilation["exit_code"] == 0, compilation
    else:
        assert compilation is None
    assert [result["stdout"].rstrip("\n") for result in results] == ["8", "-6", "0"], results
    assert all(result["outcome"] == "completed" and result["exit_code"] == 0 for result in results)


@pytest.mark.parametrize("language", ["typescript", "java", "go", "csharp"])
def test_actual_compilation_failure_does_not_invent_a_learner_runtime(runner, language):
    release = engineering_release(language)
    data = program(language, release)
    data["files"][0]["content"] = "invalid syntax @@@"
    compilation, results = runner.execute_stdio(data, release)
    assert compilation["outcome"] == "completed" and compilation["exit_code"] != 0, compilation
    assert results == []


def test_actual_node_project_has_no_host_secret_or_writable_sources(runner, monkeypatch):
    release = engineering_release("javascript")
    data = program("javascript", release)
    monkeypatch.setenv("LEORNIAN_HOST_ONLY_TEST", "must-stay-outside-container")
    data["files"][0]["content"] = (
        "const fs=require('node:fs');"
        "if(process.env.LEORNIAN_HOST_ONLY_TEST)throw Error('host variable leaked');"
        "try{fs.writeFileSync('/workspace/main.js','changed');throw Error('source writable')}"
        "catch(e){if(e.code!=='EROFS'&&e.code!=='EACCES')throw e}"
        "console.log('isolated')"
    )
    data["inputs"] = [""]
    compilation, results = runner.execute_stdio(data, release)
    assert compilation is None and results[0]["stdout"] == "isolated\n", results
    assert results[0]["exit_code"] == 0


def test_actual_go_multifile_import_uses_only_the_trusted_local_module(runner):
    release = engineering_release("go")
    data = program("go", release)
    data["files"] = [
        {"path": "main.go", "content": 'package main\nimport("fmt";'
         '"learner.local/project/calculate")\nfunc main(){fmt.Println(calculate.Double(4))}'},
        {"path": "calculate/value.go", "content":
         "package calculate\nfunc Double(value int) int {return value*2}"},
    ]
    data["inputs"] = [""]
    compilation, results = runner.execute_stdio(data, release)
    assert compilation["outcome"] == "completed" and compilation["exit_code"] == 0, compilation
    assert results[0]["stdout"] == "8\n" and results[0]["exit_code"] == 0, results


def test_revoked_execution_does_not_start_a_container(runner, monkeypatch):
    def unexpected_start(*args, **kwargs):
        raise AssertionError("A revoked execution attempted to start a container.")

    monkeypatch.setattr(runner.subprocess, "Popen", unexpected_start)
    result = runner.execute_case("print(1)", [], authorize=lambda: False)
    assert result["outcome"] == "infrastructure_error"
    assert result["stderr"] == "execution_authorization_changed"
    assert result["exit_code"] is None


def test_actual_legacy_execution_stops_when_its_current_authority_changes(runner):
    checks = []

    def authorize():
        checks.append(time.monotonic())
        return len(checks) == 1

    started = time.monotonic()
    result = runner.execute_case("import time; time.sleep(30)", [], authorize)
    assert len(checks) >= 2
    assert result["outcome"] == "infrastructure_error", result
    assert "execution_authorization_changed" in result["stderr"]
    assert time.monotonic() - started < 6


def test_actual_environment_verification_stops_when_its_scope_is_withdrawn():
    release = engineering_release("python")
    started = time.monotonic()
    with pytest.raises(PreparationStopped, match="no longer authorized"):
        EnvironmentInstaller._run(
            release["image_id"],
            ["python", "-I", "-B", "-c", "import time;time.sleep(30)"],
            should_continue=lambda: time.monotonic() - started < 0.6,
        )
    assert time.monotonic() - started < 5


def sql_program(release):
    return {
        "profile": "sql-query.v1", "dialect": release["dialect"],
        "environment_release_id": release["id"], "runtime_version": release["runtime_version"],
        "schema_definition": {"tables": [{
            "name": "records", "columns": [{"name": "id", "type": "integer"}],
        }]},
        "datasets": [{"rows": {"records": [[4], [-3]]}}],
        "query": "SELECT id FROM records ORDER BY id",
    }


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql", "mysql"])
def test_actual_sql_consumer_uses_the_exact_prepared_client_and_engine(runner, dialect):
    release = engineering_release("sql", dialect)
    result = runner.execute_sql(sql_program(release), release)[0]
    assert result["outcome"] == "completed" and result["exit_code"] == 0, result
    table = json.loads(result["stdout"])
    assert table["rows"] == [["-3"], ["4"]]
    assert table["types"] == [["integer"], ["integer"]]


def test_actual_sql_initialization_stops_before_a_query_after_source_authority_changes(runner):
    release = engineering_release("sql", "postgresql")
    checks = []

    def authorize():
        checks.append(True)
        return len(checks) == 1

    result = runner.execute_sql(sql_program(release), release, authorize)[0]
    assert len(checks) >= 2
    assert result["outcome"] == "infrastructure_error", result
    assert "execution_authorization_changed" in result["stderr"]


def test_actual_browser_checks_structure_style_and_click_without_scoring(runner):
    release = engineering_release("html-css")
    data = {
        "profile": "web-check.v1",
        "language": "html-css",
        "environment_release_id": release["id"],
        "runtime_version": release["runtime_version"],
        "entrypoint": "index.html",
        "files": [
            {
                "path": "index.html",
                "content": "<style>#answer{color:rgb(26,85,70)}</style>"
                "<button id='go' onclick=\""
                "document.querySelector('#answer').textContent='done'\">Go</button>"
                "<p id='answer'>ready</p>",
            }
        ],
        "checks": [
            {"key": "structure", "kind": "exists", "selector": "#answer"},
            {"key": "style", "kind": "style", "selector": "#answer", "property": "color"},
            {
                "key": "interaction",
                "kind": "click_text",
                "selector": "#answer",
                "action_selector": "#go",
            },
        ],
    }
    result = runner.execute_web(data, release)[0]
    assert result["outcome"] == "completed" and result["exit_code"] == 0, result
    assert json.loads(result["stdout"]) == {
        "protocol": "web-check-result.v1",
        "results": [
            {"key": "structure", "actual": True},
            {"key": "style", "actual": "rgb(26, 85, 70)"},
            {"key": "interaction", "actual": "done"},
        ],
    }
