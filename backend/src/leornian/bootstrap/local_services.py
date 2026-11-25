"""Application-owned local services for a packaged desktop runtime."""

import argparse
import ctypes
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from leornian.modules.execution.environment_runtime import engine_observation


class LocalServices:
    def __init__(self, resources=None, state_directory=None):
        self.resources = self._path(resources or os.environ["LEORNIAN_RESOURCE_DIRECTORY"])
        self.manifest = json.loads((self.resources / "runtime.json").read_text(encoding="utf-8"))
        default_state = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Leornian" / "local"
        )
        self.state = self._path(
            state_directory
            or os.environ.get(
                "LEORNIAN_LOCAL_STATE_DIRECTORY",
                default_state,
            )
        )
        self.ports = self.manifest["ports"]
        self.project = self.manifest["compose_project"]

    @staticmethod
    def _path(value):
        # Tauri can return verbatim Windows paths that Node cannot resolve as an entry point.
        value = os.fspath(value)
        if os.name == "nt":
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\") and len(value) > 6 and value[5] == ":":
                value = value[4:]
        return Path(value).resolve()

    def _environment(self):
        self.state.mkdir(parents=True, exist_ok=True)
        path = self.state / "services.env"
        if not path.exists():
            content = (
                "LEORNIAN_POSTGRES_PASSWORD=" + secrets.token_hex(32) + "\n"
                "LEORNIAN_RUNNER_TOKEN=" + secrets.token_hex(32) + "\n"
            )
            with path.open("x", encoding="utf-8") as target:
                target.write(content)
            path.chmod(0o600)
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name in {"LEORNIAN_POSTGRES_PASSWORD", "LEORNIAN_RUNNER_TOKEN"}:
                values[name] = value
        if set(values) != {"LEORNIAN_POSTGRES_PASSWORD", "LEORNIAN_RUNNER_TOKEN"}:
            raise RuntimeError("The application's private service configuration is incomplete.")
        return values

    @staticmethod
    def _alive(pid):
        if not pid:
            return False
        try:
            if os.name == "nt":
                kernel = ctypes.windll.kernel32
                kernel.OpenProcess.restype = ctypes.c_void_p
                handle = kernel.OpenProcess(0x1000, False, pid)
                if not handle:
                    return False
                code = ctypes.c_ulong()
                try:
                    return (
                        bool(
                            kernel.GetExitCodeProcess(
                                ctypes.c_void_p(handle),
                                ctypes.byref(code),
                            )
                        )
                        and code.value == 259
                    )
                finally:
                    kernel.CloseHandle(ctypes.c_void_p(handle))
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

    def _pid(self, name):
        path = self.state / (name + ".pid")
        try:
            return int(path.read_text())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _listening(port):
        with socket.socket() as client:
            client.settimeout(0.2)
            return client.connect_ex(("127.0.0.1", port)) == 0

    def _compose(self, *arguments, timeout=180):
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(self.resources),
            "--env-file",
            str(self.state / "services.env"),
            "--file",
            str(self.resources / "compose.yaml"),
            *arguments,
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            raise RuntimeError(
                "Application-owned Docker services did not finish the requested action."
            )
        return result.stdout.decode("utf-8", errors="replace")

    def status(self):
        ready = False
        observation = engine_observation()
        services = {}
        if observation["status"] == "ready" and (self.state / "services.env").exists():
            try:
                text = self._compose("ps", "--format", "json", timeout=10)
                rows = (
                    json.loads(text)
                    if text.lstrip().startswith("[")
                    else [json.loads(line) for line in text.splitlines() if line.strip()]
                )
                services = {row["Service"]: row["State"] for row in rows}
            except (RuntimeError, ValueError, KeyError):
                pass
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:" + str(self.ports["api"]) + "/health/ready",
                timeout=1,
            ) as response:
                ready = response.status == 200
        except (OSError, urllib.error.URLError):
            pass
        return {
            "application": "ready"
            if ready
            and all(
                services.get(name) == "running"
                for name in ("api", "worker", "material-worker", "relay", "postgres", "redis")
            )
            else "stopped",
            "engine": observation,
            "services": services,
            "controller": "running" if self._alive(self._pid("controller")) else "stopped",
            "frontend": "running" if self._alive(self._pid("frontend")) else "stopped",
            "api_url": "http://127.0.0.1:" + str(self.ports["api"]),
            "frontend_url": "http://127.0.0.1:" + str(self.ports["frontend"]) + "/c/new",
            "runtime": "application-bundled",
        }

    def _spawn(self, name, command, environment):
        if self._alive(self._pid(name)):
            return
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / (name + ".stop")).unlink(missing_ok=True)
        with (self.state / (name + ".log")).open("ab") as output:
            process = subprocess.Popen(
                command,
                cwd=self.resources,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                close_fds=True,
            )
        (self.state / (name + ".pid")).write_text(str(process.pid), encoding="ascii")

    def start_frontend(self):
        if self._listening(self.ports["api"]):
            if (
                not (self.state / "services.env").exists()
                or "api"
                not in self._compose(
                    "ps",
                    "--status",
                    "running",
                    "--services",
                ).splitlines()
            ):
                raise RuntimeError(
                    "The API port belongs to another application; choose a free port."
                )
        if self._listening(self.ports["frontend"]) and not self._alive(self._pid("frontend")):
            raise RuntimeError(
                "The frontend port is in use; this application will not take it over."
            )
        environment = {
            **os.environ,
            "LEORNIAN_API_URL": "http://127.0.0.1:" + str(self.ports["api"]),
            "LEORNIAN_FRONT_PORT": str(self.ports["frontend"]),
            "LEORNIAN_LOCAL_STATE_DIRECTORY": str(self.state),
        }
        self._spawn(
            "frontend",
            [
                str(self.resources / "node" / "node.exe"),
                str(self.resources / "frontend.mjs"),
            ],
            environment,
        )
        deadline = time.monotonic() + 8
        while not self._listening(self.ports["frontend"]):
            if not self._alive(self._pid("frontend")) or time.monotonic() >= deadline:
                raise RuntimeError("The bundled local frontend did not become ready.")
            time.sleep(0.1)
        return self.status()

    def start(self):
        self.start_frontend()
        observation = engine_observation()
        if observation["status"] != "ready":
            return self.status()
        settings = self._environment()
        if self._listening(self.ports["api"]):
            # A port is reusable only when the fixed project owns its API container.
            owner = self._compose("ps", "--status", "running", "--services")
            if "api" not in owner.splitlines():
                raise RuntimeError("The API port is in use by another local application.")
        for image in self.manifest["images"].values():
            inspected = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image["tag"]],
                capture_output=True,
                timeout=8,
            )
            if inspected.returncode or inspected.stdout.decode().strip() != image["id"]:
                imported = subprocess.run(
                    [
                        "docker",
                        "load",
                        "--input",
                        str(self.resources / "images" / "application.tar"),
                    ],
                    capture_output=True,
                    timeout=240,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if imported.returncode:
                    raise RuntimeError("The bundled application images could not be imported.")
                break
        for image in self.manifest["images"].values():
            verified = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image["tag"]],
                capture_output=True,
                timeout=8,
            )
            if verified.returncode or verified.stdout.decode().strip() != image["id"]:
                raise RuntimeError("Bundled application image identity does not match the release.")
        self._compose("up", "--detach", "--no-build", "api", "worker", "material-worker", "relay")
        deadline = time.monotonic() + 90
        while not self.status()["application"] == "ready":
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "The local application API is still waiting for its dependencies."
                )
            time.sleep(0.5)
        self._spawn(
            "controller",
            [
                str(self.resources / "python" / "python.exe"),
                str(self.resources / "runner" / "controller.py"),
            ],
            {
                **os.environ,
                **settings,
                "PYTHONDONTWRITEBYTECODE": "1",
                "LEORNIAN_RUNNER_API": "http://127.0.0.1:" + str(self.ports["api"]),
                "LEORNIAN_RUNNER_CACHE_DIRECTORY": str(self.state / "environments"),
                "LEORNIAN_RUNNER_STOP_FILE": str(self.state / "controller.stop"),
                "LEORNIAN_RUNNER_RECIPE_DIRECTORY": str(self.resources / "runner"),
            },
        )
        return self.status()

    def stop(self):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "controller.stop").touch()
        deadline = time.monotonic() + 20
        while self._alive(self._pid("controller")):
            if time.monotonic() >= deadline:
                raise RuntimeError("The local controller is still stopping its isolated task.")
            time.sleep(0.2)
        if (self.state / "services.env").exists() and engine_observation()["status"] == "ready":
            self._compose(
                "stop", "api", "worker", "material-worker", "relay", "postgres", "redis",
                timeout=700,
            )
        (self.state / "frontend.stop").touch()
        return self.status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "start", "stop", "frontend"])
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--state", type=Path)
    options = parser.parse_args()
    operation = None
    try:
        manager = LocalServices(options.resources, options.state)
        if options.action in {"start", "stop"}:
            manager.state.mkdir(parents=True, exist_ok=True)
            operation = (manager.state / "services.lock").open("a+b")
            operation.write(b"1")
            operation.flush()
            operation.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(operation.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(operation.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError(
                    "本机服务正在启动或停止；请读取当前状态，等待原操作完成。"
                ) from None
        result = (
            manager.start_frontend()
            if options.action == "frontend"
            else getattr(
                manager,
                options.action,
            )()
        )
        print(json.dumps(result, ensure_ascii=True))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error)[:400]}, ensure_ascii=True))
        raise SystemExit(1) from None
    finally:
        if operation:
            operation.close()


if __name__ == "__main__":
    main()
