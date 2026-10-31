"""Trusted local controller. Learner code only runs in isolated Docker containers."""

import json
import os
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request

IMAGE = os.environ.get("LEORNIAN_RUNNER_IMAGE", "python:3.12-slim")
API = os.environ.get("LEORNIAN_RUNNER_API", "http://127.0.0.1:8088")


class CleanupError(RuntimeError):
    """Stop claiming work if an isolated process cannot be confirmed stopped."""


def execute_case(code: str, numbers: list[int]) -> dict:
    name = "leornian-exec-" + secrets.token_hex(10)
    command = [
        "docker", "run", "--rm", "--name", name, "--pull=never", "--network=none",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=32", "--memory=128m", "--memory-swap=128m", "--cpus=0.5",
        "--user=65534:65534", "--ulimit", "nofile=64:64", "-i", IMAGE,
        "python", "-I", "-B", "-c", code,
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    limit = threading.Event()

    def drain(key, pipe):
        while chunk := pipe.read(512):
            target = output[key]
            target.extend(chunk[:max(0, 4096 - len(target))])
            if len(target) >= 4096:
                limit.set()

    threads = [threading.Thread(target=drain, args=(key, pipe), daemon=True)
               for key, pipe in (("stdout", process.stdout), ("stderr", process.stderr))]
    for thread in threads:
        thread.start()
    outcome = "completed"
    deadline = time.monotonic() + 6
    try:
        try:
            process.stdin.write((json.dumps(numbers) + "\n").encode())
            process.stdin.close()
        except BrokenPipeError:
            pass
        while process.poll() is None:
            if limit.is_set() or time.monotonic() >= deadline:
                outcome = "output_limit" if limit.is_set() else "timeout"
                break
            time.sleep(.03)
    finally:
        # Even a disconnected docker client is not proof that its container stopped.
        # Name is generated here, never supplied by learner code or API payloads.
        try:
            removed = subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, timeout=8,
            )
            if removed.returncode and b"No such container" not in removed.stderr:
                raise CleanupError("Cannot confirm learner container cleanup; controller stopped.")
        except subprocess.TimeoutExpired as error:
            raise CleanupError("Container cleanup timed out; controller stopped.") from error
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=8)
            for thread in threads:
                thread.join(timeout=2)
    if process.returncode in {125, 126, 127}:
        outcome = "infrastructure_error"
    if limit.is_set():
        outcome = "output_limit"
    return {
        "exit_code": process.returncode,
        "stdout": output["stdout"].decode("utf-8", errors="replace"),
        "stderr": output["stderr"].decode("utf-8", errors="replace"),
        "outcome": outcome,
    }


def api(path, token, payload):
    request = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main():
    token = os.environ.get("LEORNIAN_RUNNER_TOKEN", "")
    if not token:
        raise SystemExit("Configure a dedicated LEORNIAN_RUNNER_TOKEN before starting.")
    subprocess.run(["docker", "image", "inspect", IMAGE], check=True, capture_output=True)
    print("Leornian Runner ready; learner containers have no mounts, network or credentials.", flush=True)
    while True:
        try:
            claim = api("/internal/executions/claim", token, {"runner_id": "local-docker"})
            if not claim:
                time.sleep(1)
                continue
            report = {"claim_token": claim["claim_token"], "cases": [
                execute_case(claim["code"], numbers) for numbers in claim["inputs"]
            ]}
            # Retry this report only. A missing HTTP response never reruns learner code.
            for _attempt in range(3):
                try:
                    api("/internal/executions/" + claim["job_id"] + "/report", token, report)
                    break
                except urllib.error.HTTPError as error:
                    if error.code < 500:
                        print("Runner report rejected:", error.code, flush=True)
                        break
                    time.sleep(1)
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(1)
            else:
                print("Runner report not acknowledged; execution will not be repeated.", flush=True)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            print("Runner unavailable:", type(error).__name__, flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()
