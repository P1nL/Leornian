"""Assemble an app-local runtime; no developer credentials or global runtime dependency."""

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def copy_tree(source, destination, excluded=()):
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            *excluded,
        ),
    )


def python_runtime(destination):
    base = Path(sys.base_prefix)
    destination.mkdir(parents=True, exist_ok=True)
    for name in (
        "python.exe",
        "pythonw.exe",
        "python312.dll",
        "python3.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    ):
        source = base / name
        if source.exists():
            shutil.copy2(source, destination / name)
    copy_tree(base / "DLLs", destination / "DLLs")
    copy_tree(
        base / "Lib",
        destination / "Lib",
        excluded=(
            "site-packages",
            "test",
            "tests",
            "idlelib",
            "turtledemo",
            "tkinter",
            "ensurepip",
        ),
    )
    site = destination / "Lib" / "site-packages"
    for name in (
        "pydantic",
        "pydantic-core",
        "annotated-types",
        "typing-inspection",
        "typing-extensions",
    ):
        distribution = importlib.metadata.distribution(name)
        for relative in distribution.files or []:
            source = Path(distribution.locate_file(relative)).resolve()
            if ".." in relative.parts or "__pycache__" in relative.parts or not source.is_file():
                continue
            target = site / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (destination / "python312._pth").write_text(
        ".\nDLLs\nLib\nLib/site-packages\n../backend/src\nimport site\n",
        encoding="ascii",
    )


def docker_images(destination, backend_image, version):
    names = {"backend": backend_image, "postgres": "postgres:15", "redis": "redis:7.2.7"}
    result = {}
    for key, source in names.items():
        identity = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", source],
            text=True,
        ).strip()
        tag = "leornian-local-" + key + ":" + version
        subprocess.run(["docker", "tag", identity, tag], check=True, capture_output=True)
        result[key] = {"tag": tag, "id": identity}
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "docker",
            "save",
            "--output",
            str(destination / "application.tar"),
            *[image["tag"] for image in result.values()],
        ],
        check=True,
        capture_output=True,
    )
    return result


def compose(images, ports):
    environment = """
    LEORNIAN_DATABASE_URL: postgresql://leornian:${LEORNIAN_POSTGRES_PASSWORD}@postgres:5432/leornian
    LEORNIAN_BROKER_URL: redis://redis:6379/0
    LEORNIAN_MODEL_CONFIGURATION_MODE: user
    LEORNIAN_MODEL_ENABLED: "false"
    LEORNIAN_CREDENTIAL_MASTER_FILE: /run/leornian-model-keys/master.key
    LEORNIAN_MATERIAL_STORAGE_DIR: /var/lib/leornian/materials
    LEORNIAN_RUNNER_TOKEN: ${LEORNIAN_RUNNER_TOKEN}
"""
    return f"""x-application: &application
  image: {images["backend"]["tag"]}
  environment:{environment}
  volumes:
    - model-keys:/run/leornian-model-keys:ro
    - material-originals:/var/lib/leornian/materials
  restart: unless-stopped
services:
  postgres:
    image: {images["postgres"]["tag"]}
    restart: unless-stopped
    environment:
      POSTGRES_USER: leornian
      POSTGRES_PASSWORD: ${{LEORNIAN_POSTGRES_PASSWORD}}
      POSTGRES_DB: leornian
    ports: ["127.0.0.1:{ports["database"]}:5432"]
    volumes: ["postgres-data:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U leornian -d leornian"]
      interval: 2s
      timeout: 3s
      retries: 25
  redis:
    image: {images["redis"]["tag"]}
    restart: unless-stopped
    ports: ["127.0.0.1:{ports["redis"]}:6379"]
  migrate:
    <<: *application
    command: ["leornian-migrate"]
    restart: "no"
    depends_on:
      postgres: {{condition: service_healthy}}
  credential-init:
    <<: *application
    command: ["python", "-m", "leornian.platform.credentials", "--initialize"]
    restart: "no"
    volumes: ["model-keys:/run/leornian-model-keys"]
  api:
    <<: *application
    ports: ["127.0.0.1:{ports["api"]}:8088"]
    depends_on:
      migrate: {{condition: service_completed_successfully}}
      credential-init: {{condition: service_completed_successfully}}
  worker:
    <<: *application
    command: ["celery", "-A", "leornian.entrypoints.worker:app", "worker",
              "--loglevel=INFO", "--concurrency=2", "--queues=leornian.foreground"]
    stop_grace_period: 650s
    depends_on:
      migrate: {{condition: service_completed_successfully}}
      credential-init: {{condition: service_completed_successfully}}
      redis: {{condition: service_started}}
  material-worker:
    <<: *application
    command: ["celery", "-A", "leornian.entrypoints.worker:app", "worker",
              "--loglevel=INFO", "--concurrency=2", "--queues=leornian.materials,leornian"]
    stop_grace_period: 650s
    depends_on:
      migrate: {{condition: service_completed_successfully}}
      credential-init: {{condition: service_completed_successfully}}
      redis: {{condition: service_started}}
  relay:
    <<: *application
    command: ["python","-m","leornian.platform.relay"]
    depends_on:
      migrate: {{condition: service_completed_successfully}}
      credential-init: {{condition: service_completed_successfully}}
      redis: {{condition: service_started}}
volumes:
  postgres-data:
  model-keys:
  material-originals:
"""


FRONTEND_LAUNCHER = r"""
import { createNativeServer } from './native-server.mjs';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const directory = fileURLToPath(new URL('./frontend/',import.meta.url));
const server = await createNativeServer({directory,backend:process.env.LEORNIAN_API_URL});
server.listen(Number(process.env.LEORNIAN_FRONT_PORT),'127.0.0.1');
const timer=setInterval(()=>{
  if(existsSync(resolve(process.env.LEORNIAN_LOCAL_STATE_DIRECTORY,'frontend.stop'))){
    clearInterval(timer);server.close();server.closeAllConnections();
  }
},500);
"""


def frontend_runtime(destination, frontend):
    copy_tree(frontend, destination / "frontend")
    copy_tree(ROOT / "apps" / "desktop" / "native-bootstrap", destination / "frontend")
    for name in ("native-server.mjs", "native-reply-outcome.mjs"):
        shutil.copy2(ROOT / "apps" / "librechat" / name, destination / name)
    (destination / "frontend.mjs").write_text(FRONTEND_LAUNCHER, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "native-package")
    parser.add_argument("--backend-image", default="leornian-backend:dev")
    parser.add_argument("--version", default="phase4-20261107")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--api-port", type=int, default=8122)
    parser.add_argument("--frontend-port", type=int, default=5202)
    parser.add_argument("--database-port", type=int, default=5462)
    parser.add_argument("--redis-port", type=int, default=6392)
    options = parser.parse_args()
    output, frontend = options.output.resolve(), options.frontend.resolve()
    if not output.is_relative_to(ROOT / ".local") or output == ROOT / ".local":
        raise SystemExit(
            "Native output must be a dedicated directory under this workspace's .local."
        )
    if not (frontend / "index.html").is_file():
        raise SystemExit("Build the current native LibreChat frontend before packaging.")
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise SystemExit("Package the Windows release with the dedicated Python 3.12 environment.")
    resources = output / "runtime"
    resources.mkdir(parents=True, exist_ok=True)
    python_runtime(resources / "python")
    node = shutil.which("node")
    if not node:
        raise SystemExit("The packaging machine needs its existing trusted Node runtime.")
    (resources / "node").mkdir(exist_ok=True)
    shutil.copy2(node, resources / "node" / "node.exe")
    copy_tree(ROOT / "backend" / "src", resources / "backend" / "src")
    copy_tree(ROOT / "backend" / "migrations", resources / "backend" / "migrations")
    copy_tree(ROOT / "services" / "runner", resources / "runner")
    frontend_runtime(resources, frontend)
    ports = {
        "api": options.api_port,
        "frontend": options.frontend_port,
        "database": options.database_port,
        "redis": options.redis_port,
    }
    if len(set(ports.values())) != 4 or any(not 1024 <= value <= 65535 for value in ports.values()):
        raise SystemExit("Use four distinct unprivileged local ports.")
    images = docker_images(resources / "images", options.backend_image, options.version)
    (resources / "compose.yaml").write_text(compose(images, ports), encoding="utf-8")
    (resources / "runtime.json").write_text(
        json.dumps(
            {
                "version": options.version,
                "ports": ports,
                "compose_project": "leornian-local",
                "images": images,
                "backend": "application-owned local Docker services",
                "learner_execution": "local isolated containers only",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Tauri parses a Windows drive-prefixed frontendDist as a URL rather than a path.
    frontend_dist = Path(
        os.path.relpath(resources / "frontend", ROOT / "apps" / "desktop" / "src-tauri")
    ).as_posix()
    configuration = {
        "build": {"beforeBuildCommand": "", "frontendDist": frontend_dist},
        "app": {
            "withGlobalTauri": True,
            "windows": [
                {
                    "label": "main",
                    "url": "local-setup.html",
                    "title": "Leornian",
                    "width": 1280,
                    "height": 880,
                    "minWidth": 760,
                    "minHeight": 600,
                }
            ],
            "security": {
                "capabilities": [
                    {
                        "identifier": "local-services",
                        "windows": ["main"],
                        "remote": {"urls": ["http://127.0.0.1:" + str(ports["frontend"]) + "/*"]},
                        "permissions": ["core:default"],
                    }
                ]
            },
        },
        "bundle": {
            "active": True,
            "targets": ["nsis"],
            "resources": {
                str(resources) + "/": "runtime/",
            },
        },
    }
    (output / "tauri.portable.json").write_text(
        json.dumps(configuration, indent=2), encoding="utf-8"
    )
    if options.executable:
        shutil.copy2(options.executable, output / "Leornian.exe")
    result = subprocess.run(
        [
            str(resources / "python" / "python.exe"),
            "-c",
            "from leornian.modules.execution.environment_runtime import EnvironmentInstaller;"
            "from leornian.modules.execution.contracts import ProjectProgram;"
            "import ssl,socket;print('bundled-runtime-ready')",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode:
        raise RuntimeError("The dedicated packaged Python runtime did not pass its import check.")
    print("Native application resources: " + str(output))


if __name__ == "__main__":
    main()
