import subprocess
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from leornian.modules.execution.contracts import (
    ExecutionProgram,
    ProjectProgram,
    RunnerReport,
    SqlEnvironment,
    WebCheckResult,
    WebProgram,
)
from leornian.modules.execution.environment_contracts import (
    EnvironmentDemandInput,
    EnvironmentPreparationReport,
)
from leornian.modules.execution.environment_recipes import requirements
from leornian.modules.execution.environment_runtime import (
    engine_observation,
    local_docker_endpoint,
    pin_local_engine,
)
from leornian.shared_kernel.errors import BusinessError


def project(language="javascript"):
    entrypoint = {
        "python": "main.py",
        "javascript": "main.js",
        "typescript": "main.ts",
        "java": "Main.java",
        "go": "main.go",
        "csharp": "Program.cs",
    }[language]
    return {
        "profile": "project-stdio.v1",
        "language": language,
        "runtime_version": "22.16.0",
        "environment_release_id": str(uuid4()),
        "files": [{"path": entrypoint, "content": ""}],
        "entrypoint": entrypoint,
        "inputs": ["4\n", "-3\n", "0\n"],
    }


@pytest.mark.parametrize(
    "language",
    [
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "csharp",
    ],
)
def test_closed_project_languages_use_text_stdin_and_exact_releases(language):
    data = project(language)
    parsed = TypeAdapter(ExecutionProgram).validate_python(data)
    assert parsed.inputs == ["4\n", "-3\n", "0\n"]
    for name, value in [("command", "anything"), ("image", "anything"), ("inputs", [[4]])]:
        with pytest.raises(ValidationError):
            ProjectProgram.model_validate({**data, name: value})
    data.pop("environment_release_id")
    with pytest.raises(ValidationError):
        ProjectProgram.model_validate(data)


@pytest.mark.parametrize(
    "path",
    [
        "data/../main.js",
        "package.json",
        "tsconfig.json",
        "build.csproj",
        "NuGet.Config",
    ],
)
def test_project_paths_and_build_configuration_remain_profile_owned(path):
    data = project()
    data["files"].append({"path": path, "content": "{}"})
    with pytest.raises(ValidationError):
        ProjectProgram.model_validate(data)


def test_new_optional_fields_preserve_historical_runner_receipt_and_sql_advertisement():
    receipt = {
        "claim_token": str(uuid4()),
        "cases": [
            {
                "exit_code": 0,
                "stdout": "5\n",
                "stderr": "",
                "outcome": "completed",
            }
        ],
    }
    assert RunnerReport.model_validate(receipt).model_dump(mode="json") == receipt
    assert SqlEnvironment(dialect="sqlite", runtime_version="3.46.1").model_dump(mode="json") == {
        "profile": "sql-query.v1",
        "dialect": "sqlite",
        "runtime_version": "3.46.1",
    }


def test_empty_runner_cases_require_a_distinct_unsuccessful_compilation():
    data = {
        "claim_token": str(uuid4()),
        "cases": [],
        "compilation": {
            "exit_code": 1, "outcome": "completed", "stdout": "", "stderr": "compile error",
        },
    }
    assert RunnerReport.model_validate(data).cases == []
    for compilation in (
        None,
        {"exit_code": 0, "outcome": "completed", "stdout": "", "stderr": ""},
    ):
        with pytest.raises(ValidationError):
            RunnerReport.model_validate({**data, "compilation": compilation})


def test_browser_checks_keep_expected_answers_out_and_actual_types_strict():
    data = {
        "profile": "web-check.v1",
        "runtime_version": "146.0.1",
        "environment_release_id": str(uuid4()),
        "entrypoint": "index.html",
        "files": [{"path": "index.html", "content": "<p id='x'>ready</p>"}],
        "checks": [{"key": "visible", "kind": "exists", "selector": "#x"}],
    }
    assert WebProgram.model_validate(data).language == "html-css"
    bad = deepcopy(data)
    bad["checks"][0]["expected"] = True
    with pytest.raises(ValidationError):
        WebProgram.model_validate(bad)
    for actual in (1, 0, [], {}):
        with pytest.raises(ValidationError):
            WebCheckResult(results=[{"key": "visible", "actual": actual}])
    with pytest.raises(ValidationError):
        WebCheckResult(
            results=[
                {"key": "same", "actual": True},
                {"key": "same", "actual": "text"},
            ]
        )


def test_environment_requirements_are_maintained_scopes_not_arbitrary_install_commands():
    all_recipes = requirements()
    assert len(all_recipes) == 11
    assert {item.language for item in all_recipes} == {
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "csharp",
        "html-css",
        "sql",
    }
    assert {item.dialect for item in all_recipes if item.language == "sql"} == {
        "sqlite",
        "postgresql",
        "mysql",
    }
    assert all(item.learner_network == "none" for item in all_recipes)
    with pytest.raises(ValidationError):
        EnvironmentDemandInput(recipe_id="python-standard.v1", command="pip install anything")
    with pytest.raises(ValidationError):
        EnvironmentDemandInput(recipe_id="python-standard.v1", plan_id=uuid4())
    with pytest.raises(ValidationError):
        EnvironmentPreparationReport(
            claim_token=uuid4(),
            outcome="ready",
            runtime_version="3.12.12",
        )


@pytest.mark.parametrize(
    ("endpoint", "allowed"),
    [
        ("npipe:////./pipe/dockerDesktopLinuxEngine", True),
        ("npipe://./pipe/docker_engine", True),
        ("unix:///var/run/docker.sock", True),
        ("unix:///run/user/1000/docker.sock", True),
        ("ssh://user@example.test", False),
        ("tcp://127.0.0.1:2375", False),
        ("tcp://example.test:2376", False),
        ("npipe:////remote-host/pipe/docker_engine", False),
        ("unix://remote-host/var/run/docker.sock", False),
    ],
)
def test_only_local_docker_ipc_endpoints_are_allowed(endpoint, allowed):
    assert local_docker_endpoint(endpoint) is allowed


def test_context_takes_precedence_then_process_endpoint_is_pinned(monkeypatch):
    calls = []
    endpoint = "npipe:////./pipe/dockerDesktopLinuxEngine"
    monkeypatch.setenv("DOCKER_CONTEXT", "desktop-linux")
    monkeypatch.setenv("DOCKER_HOST", "ssh://old-host")

    def inspect(command, **options):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=(endpoint + "\n").encode())

    monkeypatch.setattr(
        "leornian.modules.execution.environment_runtime.subprocess.run", inspect,
    )
    assert pin_local_engine() == endpoint
    assert pin_local_engine() == endpoint
    assert len(calls) == 1
    assert "desktop-linux" in calls[0]


def test_remote_engine_is_rejected_without_contacting_its_server(monkeypatch):
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://example.test:2376")
    monkeypatch.setattr("leornian.modules.execution.environment_runtime.shutil.which",
                        lambda name: "docker")
    monkeypatch.setattr(
        "leornian.modules.execution.environment_runtime.subprocess.run",
        lambda *args, **options: pytest.fail("A remote Docker engine was contacted."),
    )
    assert engine_observation()["status"] == "unsupported"


@pytest.mark.parametrize("kind", ["project_stdio", "web_project"])
def test_new_program_supply_requires_and_rechecks_exact_owner_release(kind, monkeypatch):
    from leornian.bootstrap import item_supply

    pack = {"kind": kind, "program_environment": None}
    with pytest.raises(BusinessError, match="prepared local environment"):
        item_supply.ItemSupply.require_program_release(None, None, pack)
    environment = {
        "profile": "project-stdio.v1" if kind == "project_stdio" else "web-check.v1",
        "language": "javascript" if kind == "project_stdio" else "html-css",
        "runtime_version": "22.16.0",
    }
    pack["program_environment"] = environment
    with pytest.raises(BusinessError, match="explicitly allow"):
        item_supply.ItemSupply.require_program_release(None, None, pack)
    release_id, plan_id = uuid4(), uuid4()
    pack.update(plan_id=plan_id, plan_revision=3)
    environment["environment_release_id"] = str(release_id)
    calls = []

    def require_release(actor, selected, **scope):
        calls.append((actor, selected, scope))
        return "current-owner-release"

    monkeypatch.setattr(item_supply, "Environments",
                        lambda connection: SimpleNamespace(require_release=require_release))
    actor = object()
    assert (
        item_supply.ItemSupply.require_program_release(None, actor, pack)
        == "current-owner-release"
    )
    assert calls == [(actor, release_id, {
        "profile": environment["profile"], "language": environment["language"],
        "dialect": None, "runtime_version": "22.16.0",
        "plan_id": plan_id, "plan_revision": 3,
    })]


@pytest.mark.parametrize("kind", ["sql_query", "python_project"])
def test_historical_program_supply_keeps_its_original_optional_release_shape(kind):
    from leornian.bootstrap.item_supply import ItemSupply

    assert ItemSupply.require_program_release(
        None, None, {"kind": kind, "program_environment": {"runtime_version": "3.12.1"}},
    ) is None


@pytest.mark.parametrize("failed_phase", ["client_wait", "container_removal"])
def test_unconfirmed_verification_cleanup_stops_the_controller(failed_phase, monkeypatch):
    from leornian.modules.execution import environment_runtime

    calls = []

    def wait(**options):
        if failed_phase == "client_wait":
            raise subprocess.TimeoutExpired("docker", 8)
        return 0

    process = SimpleNamespace(
        returncode=0, poll=lambda: 0,
        communicate=lambda **options: (b"ready", b""), wait=wait,
    )
    monkeypatch.setattr(environment_runtime.subprocess, "Popen", lambda *a, **k: process)

    def remove(command, **options):
        calls.append(command)
        if failed_phase == "container_removal":
            raise subprocess.TimeoutExpired("docker", 10)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(environment_runtime.subprocess, "run", remove)
    with pytest.raises(environment_runtime.EnvironmentCleanupError):
        environment_runtime.EnvironmentInstaller._run("trusted-smoke", ["true"])
    assert calls[0][:3] == ["docker", "rm", "--force"]
