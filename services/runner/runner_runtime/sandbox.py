"""Bounded containers, owned volumes and workspace staging."""

import codecs
import io
import json
import os
import queue
import subprocess
import tarfile
import threading
import time
from pathlib import Path

IMAGE = os.environ.get("LEORNIAN_RUNNER_IMAGE", "python:3.12-slim")
STOP_FILE = os.environ.get("LEORNIAN_RUNNER_STOP_FILE")


def _stop_requested():
    return bool(STOP_FILE and Path(STOP_FILE).exists())



class CleanupError(RuntimeError):
    """Stop claiming work if an isolated process cannot be confirmed stopped."""



def _bounded_container(command, input_bytes, name, timeout, authorize=None, *, terminal=None):
    if authorize and not authorize():
        return _unavailable_cases(1, "execution_authorization_changed")[0]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    chunks, lines = queue.SimpleQueue(), queue.SimpleQueue()
    limit = threading.Event()
    revoked, finished = threading.Event(), threading.Event()

    def drain(key, pipe):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := pipe.read1(512):
            target = output[key]
            kept = chunk[:max(0, 4096 - len(target))]
            target.extend(kept)
            if terminal and kept:
                chunks.put(decoder.decode(kept).replace("\x00", "\ufffd"))
            if len(target) >= 4096:
                limit.set()
        if terminal:
            chunks.put(decoder.decode(b"", final=True))

    def exchange(*, closed=False):
        parts = []
        while True:
            try:
                parts.append(chunks.get_nowait())
            except queue.Empty:
                break
        for line in terminal("".join(parts), closed=closed):
            lines.put((line + "\n").encode("utf-8"))

    threads = [threading.Thread(target=drain, args=(key, pipe), daemon=True)
               for key, pipe in (("stdout", process.stdout), ("stderr", process.stderr))]
    if authorize:
        def monitor():
            while not finished.wait(2):
                if not authorize():
                    revoked.set()
                    return

        threads.append(threading.Thread(target=monitor, daemon=True))

    def feed():
        try:
            with process.stdin as pipe:
                if terminal:
                    while (line := lines.get()) is not None:
                        pipe.write(line)
                        pipe.flush()
                else:
                    pipe.write(input_bytes)
        except OSError:
            pass

    writer = threading.Thread(target=feed, daemon=True)
    for thread in threads:
        thread.start()
    writer.start()
    outcome = "completed"
    next_exchange = 0.0
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if revoked.is_set():
                outcome = "infrastructure_error"
                output["stderr"] = bytearray(b"execution_authorization_changed")
                break
            if limit.is_set() or time.monotonic() >= deadline:
                outcome = "output_limit" if limit.is_set() else "timeout"
                break
            if terminal and time.monotonic() >= next_exchange:
                try:
                    exchange()
                except (OSError, TimeoutError):
                    outcome = "infrastructure_error"
                    break
                next_exchange = time.monotonic() + .25
            time.sleep(.03)
    finally:
        finished.set()
        if terminal:
            lines.put(None)
        # Stop the client before cleanup so it cannot submit another start request.
        # A disconnected client alone is not proof that its container stopped.
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=8)
        finally:
            try:
                _remove_container(name)
            finally:
                for thread in [*threads, writer]:
                    thread.join(timeout=2)
    if terminal and outcome != "infrastructure_error":
        try:
            exchange(closed=True)
        except (OSError, TimeoutError):
            outcome = "infrastructure_error"
    if process.returncode in {125, 126, 127}:
        outcome = "infrastructure_error"
    if limit.is_set():
        outcome = "output_limit"
    def decoded(key):
        # Replacement characters can grow invalid/truncated UTF-8 beyond the byte limit.
        text = output[key].decode("utf-8", errors="replace").replace("\x00", "\ufffd")
        value = text.encode("utf-8")
        return value[:4096].decode("utf-8", errors="ignore")

    return {
        "exit_code": process.returncode,
        "stdout": decoded("stdout"),
        "stderr": decoded("stderr"),
        "outcome": outcome,
    }



def _docker(*arguments, input_bytes=None, timeout=10):
    result = subprocess.run(
        ["docker", *arguments], input=input_bytes, capture_output=True, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[:1000])
    return result.stdout.decode("utf-8").strip()



def _remove_container(name):
    try:
        try:
            result = subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, timeout=8,
            )
        except subprocess.TimeoutExpired:
            result = None
        if result is not None and result.returncode == 0:
            return
        # Automatic removal or a timed-out CLI can still finish in the daemon.
        # Only confirmed absence completes cleanup.
        deadline = time.monotonic() + 5
        while True:
            state = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", name],
                capture_output=True, timeout=3,
            )
            if state.returncode and any(
                value in state.stderr.lower() for value in (b"no such object", b"no such container")
            ):
                return
            if (
                state.returncode or state.stdout.strip() not in {b"exited", b"dead", b"removing"}
                or time.monotonic() >= deadline
            ):
                raise CleanupError("Cannot confirm program container cleanup: " + name)
            time.sleep(.05)
    except subprocess.TimeoutExpired as error:
        raise CleanupError("Program container cleanup timed out.") from error



def _new_volume(name, *, temporary=False):
    try:
        options = (
            ["--driver", "local", "--opt", "type=tmpfs", "--opt", "device=tmpfs",
             "--opt", "o=size=64m,mode=0777"] if temporary else []
        )
        _docker("volume", "create", "--label", "leornian.execution=" + name, *options, name)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise CleanupError("Cannot confirm isolated volume preparation: " + name) from error



def _remove_volume(name):
    try:
        owner = _docker(
            "volume", "inspect", "--format", '{{index .Labels "leornian.execution"}}', name,
        )
        if owner != name:
            raise CleanupError("Program volume ownership changed; controller stopped.")
        _docker("volume", "rm", name)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise CleanupError("Cannot confirm program volume cleanup.") from error



def _mount(volume, target, *, readonly=False):
    return "type=volume,source=" + volume + ",target=" + target + (",readonly" if readonly else "")



def _container_options(name, *, user="65534:65534", memory="128m", network="none"):
    return [
        "docker", "run", "--rm", "--name", name, "--pull=never", "--network=" + network,
        "--label", "leornian.execution=" + name,
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--memory=" + memory, "--memory-swap=" + memory, "--cpus=0.5",
        "--user=" + user, "--ulimit", "nofile=64:64",
    ]



_STAGE_FILES = """
import json, os, pathlib, sys
root = pathlib.Path("/workspace")
data = json.load(sys.stdin)
for item in data:
    path = root / item["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(item["content"], encoding="utf-8")
    path.chmod(0o444)
root.chmod(0o755 if data else 0o777)
"""



def _stage_volume(volume, files, image=IMAGE):
    name = volume + "-stage"
    command = _container_options(name, user="0:0") + [
        "--mount", _mount(volume, "/workspace"), "-i", image,
        "python", "-I", "-B", "-c", _STAGE_FILES,
    ]
    result = _bounded_container(command, json.dumps(files).encode(), name, 8)
    if result["outcome"] != "completed" or result["exit_code"]:
        raise RuntimeError("Could not prepare the isolated program volume.")



def _project_options(name, memory="512m", *, network="none"):
    return _container_options(name, memory=memory, network=network) + [
        "--pids-limit=192", "--cpus=1", "--ulimit", "nofile=256:256",
        "--env", "HOME=/tmp",
        "--env", "DOTNET_CLI_HOME=/tmp/dotnet", "--env", "DOTNET_CLI_TELEMETRY_OPTOUT=1",
        "--env", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1", "--env", "DOTNET_NOLOGO=1",
        "--env", "DOTNET_PROCESSOR_COUNT=2",
        "--env", "GOCACHE=/tmp/go-cache", "--env", "GOMAXPROCS=2",
        "--env", "CGO_ENABLED=0", "--env", "GOPROXY=off", "--env", "GOSUMDB=off",
        "--env", "GO111MODULE=off", "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--tmpfs", "/tmp:rw,nosuid,size=256m,mode=1777",
    ]



def _stage_archive(volume, files, image, course=None):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as target:
        for item in files:
            content = item["content"].encode("utf-8")
            info = tarfile.TarInfo(item["path"])
            info.size, info.mode = len(content), 0o444
            target.addfile(info, io.BytesIO(content))
    name = volume + "-stage"
    managed_files = ""
    if course and course["language"] in {"javascript", "typescript"}:
        managed_files = "ln -s /opt/leornian/course/node_modules /workspace/node_modules; "
    elif course and course["language"] == "go":
        managed_files = (
            "for file in go.mod go.sum; do "
            'if test -f "/opt/leornian/course/$file"; then '
            'cp "/opt/leornian/course/$file" "/workspace/$file"; fi; done; '
        )
    command = _container_options(name, user="0:0") + [
        "--mount", _mount(volume, "/workspace"), "-i", image, "sh", "-ceu",
        "tar --no-same-owner -xf - -C /workspace; "
        + managed_files
        + "find /workspace -type d -exec chmod 755 {} +; "
        + ("chmod 755 /workspace" if files else "chmod 777 /workspace"),
    ]
    result = _bounded_container(command, archive.getvalue(), name, 12)
    if result["outcome"] != "completed" or result["exit_code"]:
        raise RuntimeError("Could not stage the isolated project manifest.")



def _unavailable_cases(count, message):
    return [{
        "exit_code": None, "stdout": "", "stderr": message[:1000],
        "outcome": "infrastructure_error",
    } for _index in range(count)]

