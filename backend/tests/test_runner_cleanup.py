import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner():
    source = Path(__file__).parents[2] / "services" / "runner" / "controller.py"
    spec = importlib.util.spec_from_file_location("runner_cleanup", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from runner_runtime import sandbox
    return sandbox


def result(code, stdout=b"", stderr=b""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def test_automatic_removal_race_needs_confirmed_absence(runner, monkeypatch):
    commands = []
    responses = iter([
        result(1, stderr=b"removal of container is already in progress"),
        result(0, stdout=b"removing\n"),
        result(1, stderr=b"Error: No such object: owned-container"),
    ])

    def docker(command, **_kwargs):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(runner.subprocess, "run", docker)
    runner._remove_container("owned-container")
    assert commands[0] == ["docker", "rm", "--force", "owned-container"]
    assert len(commands) == 3
    assert all(command[-1] == "owned-container" for command in commands)


def test_unconfirmed_running_container_stops_controller(runner, monkeypatch):
    responses = iter([result(1, stderr=b"permission denied"), result(0, stdout=b"running\n")])
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: next(responses))
    with pytest.raises(runner.CleanupError):
        runner._remove_container("owned-container")


def test_timed_out_removal_can_complete_only_after_confirmed_absence(runner, monkeypatch):
    calls = []

    def docker(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(command, 8)
        return result(1, stderr=b"Error: No such container: owned-container")

    monkeypatch.setattr(runner.subprocess, "run", docker)
    runner._remove_container("owned-container")
    assert calls[-1] == [
        "docker", "inspect", "--format", "{{.State.Status}}", "owned-container",
    ]


def test_unknown_volume_creation_never_continues_execution(runner, monkeypatch):
    def docker(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["docker", "volume", "create"], 10)

    monkeypatch.setattr(runner, "_docker", docker)
    with pytest.raises(runner.CleanupError, match="owned-volume"):
        runner._new_volume("owned-volume")


def test_optional_program_probe_failure_does_not_upgrade_or_disable_old_runner(runner, monkeypatch):
    from runner_runtime import stdio
    runner = stdio
    def unavailable(_image):
        raise RuntimeError("Optional program runtime not prepared.")

    monkeypatch.setattr(runner, "_python_versions", unavailable)
    assert runner.program_environments() == []

    def unknown_cleanup(_image):
        raise runner.CleanupError("Runtime inspection cleanup unconfirmed.")

    monkeypatch.setattr(runner, "_python_versions", unknown_cleanup)
    with pytest.raises(runner.CleanupError):
        runner.program_environments()


def test_terminal_wait_keeps_the_engine_visible(runner, monkeypatch):
    from runner_runtime import api_client

    from leornian.modules.execution import environment_runtime

    clock, calls = [0], []
    monkeypatch.setattr(api_client.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(environment_runtime, "engine_observation", lambda: {"status": "ready"})
    def api(path, _token, body, **_options):
        calls.append((clock[0], path, body))
        return {"allowed": True}
    monkeypatch.setattr(api_client, "api", api)
    verify = api_client._execution_authorizer({
        "interactive": True, "job_id": "example", "claim_token": "claim",
    }, "controller")
    for clock[0] in (0, 9, 10, 12, 30, 50, 52):
        assert verify()
    observations = [(moment, obs) for moment, path, obs in calls
                    if path == "/internal/environment-engine"]
    assert observations == [(moment, {"status": "ready"}) for moment in (10, 30, 50)]
    assert sum(path == "/internal/executions/example/verify" for _, path, _ in calls) == 7
