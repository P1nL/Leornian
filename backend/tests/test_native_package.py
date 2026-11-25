import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def packager():
    path = Path(__file__).resolve().parents[2] / "apps" / "desktop" / "package-native.py"
    spec = importlib.util.spec_from_file_location("leornian_native_package", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaged_workers_use_the_original_foreground_and_material_queues(packager):
    images = {"backend": {"tag": "backend:test"}, "postgres": {"tag": "postgres:15"},
              "redis": {"tag": "redis:7.2.7"}}
    ports = {"api": 8122, "frontend": 5202, "database": 5462, "redis": 6392}
    document = packager.compose(images, ports)
    for service, queue in (
        ("worker", "leornian.foreground"),
        ("material-worker", "leornian.materials,leornian"),
    ):
        section = re.search(rf"(?ms)^  {service}:\n(.*?)(?=^  \S|\Z)", document).group(1)
        command = json.loads(re.search(r"(?s)command:\s*(\[.*?\])", section).group(1))
        assert command == [
            "celery", "-A", "leornian.entrypoints.worker:app", "worker",
            "--loglevel=INFO", "--concurrency=2", f"--queues={queue}",
        ]
        assert "migrate: {condition: service_completed_successfully}" in section
        assert "credential-init: {condition: service_completed_successfully}" in section
        assert "redis: {condition: service_started}" in section
        assert "stop_grace_period: 650s" in section


@pytest.mark.parametrize("packaged", [False, True])
def test_dependencies_resume_after_engine_restart_but_one_shot_jobs_do_not(packager, packaged):
    if packaged:
        images = {name: {"tag": f"{name}:test"} for name in ("backend", "postgres", "redis")}
        ports = {"api": 8122, "frontend": 5202, "database": 5462, "redis": 6392}
        document = packager.compose(images, ports)
    else:
        document = (packager.ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8")
    for name in ("postgres", "redis", "migrate", "credential-init"):
        section = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  \S|\Z)", document).group(1)
        expected = "unless-stopped" if name in {"postgres", "redis"} else '"no"'
        assert f"restart: {expected}" in section


def test_packaged_frontend_imports_its_shipped_modules_and_serves_the_local_shell(
    packager, tmp_path,
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("The packaging host needs its existing Node runtime.")
    frontend = tmp_path / "built"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><head></head><body>local-shell</body></html>")
    resources = tmp_path / "runtime"
    resources.mkdir()
    packager.frontend_runtime(resources, frontend)
    assert (resources / "native-reply-outcome.mjs").is_file()
    assert (resources / "frontend.mjs").is_file()
    assert (resources / "frontend" / "local-setup.html").is_file()
    script = """
        import assert from 'node:assert/strict';
        import { pathToFileURL } from 'node:url';
        const { createNativeServer } = await import(pathToFileURL(process.argv[2]));
        const server = await createNativeServer({
          directory: process.argv[3],
          fetchBackend: () => { throw new Error('The shell must not contact the backend.'); }
        });
        await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
        try {
          const origin = `http://127.0.0.1:${server.address().port}`;
          const shell = await fetch(origin + '/c/new', { headers: { Accept: 'text/html' } });
          assert.equal(shell.status, 200);
          assert.match(await shell.text(), /local-shell/);
          const setup = await fetch(origin + '/local-setup.html');
          assert.equal(setup.status, 200);
          assert.match(await setup.text(), /Leornian/);
        } finally {
          await new Promise(resolve => server.close(resolve));
        }
    """
    probe = tmp_path / "probe.mjs"
    probe.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(probe), str(resources / "native-server.mjs"),
         str(resources / "frontend")],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
