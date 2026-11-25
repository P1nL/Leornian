import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from leornian.bootstrap import local_services


@pytest.fixture
def manager(tmp_path):
    resources = tmp_path / "runtime"
    resources.mkdir()
    (resources / "runtime.json").write_text(
        json.dumps(
            {
                "ports": {"api": 8122, "frontend": 5202, "database": 5462, "redis": 6392},
                "compose_project": "leornian-local",
                "images": {},
            }
        ),
        encoding="utf-8",
    )
    return local_services.LocalServices(resources, tmp_path / "application-state")


def test_unrelated_api_port_is_rejected_before_starting_any_application_process(
    manager,
    monkeypatch,
):
    monkeypatch.setattr(manager, "_listening", lambda port: port == manager.ports["api"])
    monkeypatch.setattr(
        manager, "_spawn", lambda *args: pytest.fail("An unrelated port was taken over.")
    )
    with pytest.raises(RuntimeError, match="belongs to another application"):
        manager.start_frontend()
    assert not manager.state.exists()


def test_frontend_uses_its_bundled_node_and_exact_local_proxy(manager, monkeypatch):
    calls, ports = [], []

    def listening(port):
        ports.append(port)
        return port == manager.ports["frontend"] and len(ports) > 2

    monkeypatch.setattr(manager, "_listening", listening)
    monkeypatch.setattr(manager, "_spawn", lambda *args: calls.append(args))
    monkeypatch.setattr(manager, "status", lambda: {"frontend": "running"})
    assert manager.start_frontend() == {"frontend": "running"}
    name, command, environment = calls[0]
    assert name == "frontend"
    assert command == [
        str(manager.resources / "node" / "node.exe"),
        str(manager.resources / "frontend.mjs"),
    ]
    assert environment["LEORNIAN_API_URL"] == "http://127.0.0.1:8122"
    assert environment["LEORNIAN_FRONT_PORT"] == "5202"
    assert environment["LEORNIAN_LOCAL_STATE_DIRECTORY"] == str(manager.state)


@pytest.mark.skipif(local_services.os.name != "nt", reason="Tauri verbatim paths are Windows-only.")
def test_tauri_verbatim_paths_are_normalized_before_spawning_node(manager):
    current = local_services.LocalServices(
        "\\\\?\\" + str(manager.resources), "\\\\?\\" + str(manager.state),
    )
    assert current.resources == manager.resources
    assert current.state == manager.state
    assert not str(current.resources).startswith("\\\\?\\")


def test_missing_engine_keeps_first_run_ui_without_installing_system_components(
    manager,
    monkeypatch,
):
    monkeypatch.setattr(manager, "start_frontend", lambda: {"frontend": "running"})
    monkeypatch.setattr(local_services, "engine_observation", lambda: {"status": "missing"})
    monkeypatch.setattr(manager, "status", lambda: {"application": "stopped", "engine": "missing"})
    monkeypatch.setattr(
        manager, "_environment", lambda: pytest.fail("Missing engine started app dependencies.")
    )
    assert manager.start() == {"application": "stopped", "engine": "missing"}
    assert not manager.state.exists()


@pytest.mark.parametrize("material_worker", ["running", "exited", None])
def test_readiness_requires_the_material_worker(manager, monkeypatch, material_worker):
    manager._environment()
    services = [
        {"Service": name, "State": "running"}
        for name in ("api", "worker", "relay", "postgres", "redis")
    ]
    if material_worker is not None:
        services.append({"Service": "material-worker", "State": material_worker})
    monkeypatch.setattr(local_services, "engine_observation", lambda: {"status": "ready"})
    monkeypatch.setattr(manager, "_compose", lambda *args, **kwargs: json.dumps(services))
    monkeypatch.setattr(
        local_services.urllib.request, "urlopen",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(status=200)),
    )
    result = manager.status()
    assert result["application"] == ("ready" if material_worker == "running" else "stopped")
    assert result["services"].get("material-worker") == material_worker


def test_start_includes_the_material_worker_before_starting_the_controller(manager, monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "start_frontend", lambda: None)
    monkeypatch.setattr(local_services, "engine_observation", lambda: {"status": "ready"})
    monkeypatch.setattr(manager, "_environment", lambda: {})
    monkeypatch.setattr(manager, "_listening", lambda port: False)
    monkeypatch.setattr(
        manager, "_compose", lambda *args, **kwargs: calls.append(("compose", args)),
    )
    monkeypatch.setattr(manager, "status", lambda: {"application": "ready"})
    monkeypatch.setattr(manager, "_spawn", lambda name, *args: calls.append(("spawn", name)))
    assert manager.start() == {"application": "ready"}
    assert calls == [
        ("compose", ("up", "--detach", "--no-build", "api", "worker", "material-worker", "relay")),
        ("spawn", "controller"),
    ]


def test_stop_targets_only_this_app_and_uses_controller_and_frontend_stop_signals(
    manager,
    monkeypatch,
):
    manager._environment()
    calls = []
    monkeypatch.setattr(manager, "_alive", lambda pid: False)
    monkeypatch.setattr(local_services, "engine_observation", lambda: {"status": "ready"})
    monkeypatch.setattr(manager, "_compose", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(manager, "status", lambda: {"application": "stopped"})
    assert manager.stop() == {"application": "stopped"}
    assert calls == [("stop", "api", "worker", "material-worker", "relay", "postgres", "redis")]
    assert (manager.state / "controller.stop").is_file()
    assert (manager.state / "frontend.stop").is_file()
