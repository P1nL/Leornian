"""Trusted local Runner entrypoint: prepare, dispatch and report bounded work."""

import os
import subprocess
import sys
import threading
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlparse

# Direct script startup and maintenance loaders use the same local package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runner_runtime.api_client import (
    API,
    _execution_authorizer,
    _release_authorizer,
    _report,
    api,
    terminal_exchange,
)
from runner_runtime.sandbox import CleanupError, _stop_requested
from runner_runtime.service import execute_http
from runner_runtime.sql import execute_sql, verify_sql_environment
from runner_runtime.stdio import execute_case, execute_project, execute_stdio, program_environments
from runner_runtime.web import execute_web as execute_web
from runner_runtime.web import execute_web_with_build


def _controller_lock(directory):
    handle = (directory / "controller.lock").open("a+b")
    handle.seek(0)
    handle.write(b"1")
    handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit("This application's local controller is already running.") from None
    return handle



def _prepare_environment(installer, claim, token):
    from leornian.modules.execution.environment_runtime import EnvironmentCleanupError

    phase = {"value": "downloading"}
    stopped, finished = threading.Event(), threading.Event()

    def progress(value):
        phase["value"] = value
        if stopped.is_set() or _stop_requested():
            return False
        try:
            allowed = api(
                "/internal/environment-preparations/" + claim["job_id"] + "/progress", token,
                {"claim_token": claim["claim_token"], "phase": value},
            )["allowed"]
            from leornian.modules.execution.environment_runtime import (
                engine_observation,
            )

            api("/internal/environment-engine", token, engine_observation())
            if not allowed:
                stopped.set()
            return allowed
        except (urllib.error.URLError, OSError, TimeoutError):
            stopped.set()
            return False

    def heartbeat():
        while not finished.wait(10):
            if not progress(phase["value"]):
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        try:
            payload = installer.prepare(
                claim, progress,
                should_continue=lambda: not stopped.is_set() and not _stop_requested(),
            )
        except (CleanupError, EnvironmentCleanupError):
            raise
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            print("Environment preparation stopped:", phase["value"],
                  type(error).__name__, flush=True)
            payload = {
                "outcome": "failed", "error_code": phase["value"] + "_failed",
            }
        payload = {"claim_token": claim["claim_token"], **payload}
        acknowledged, release = _report(
            "/internal/environment-preparations/" + claim["job_id"] + "/report", token, payload,
        )
        if acknowledged and release:
            installer.register_release(release)
    finally:
        finished.set()
        thread.join(timeout=12)



def main():
    from leornian.modules.execution.environment_runtime import (
        EnvironmentInstaller,
        engine_observation,
    )

    token = os.environ.get("LEORNIAN_RUNNER_TOKEN", "")
    if not token:
        raise SystemExit("Configure a dedicated LEORNIAN_RUNNER_TOKEN before starting.")
    if urlparse(API).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("The local controller only connects to this device's application API.")
    installer = EnvironmentInstaller(verify_sql=verify_sql_environment)
    controller_lock = _controller_lock(installer.directory)
    next_scan, environments = 0.0, []
    missing_reported = set()
    print("Leornian local controller connected; course environments are prepared on demand.",
          flush=True)
    while not _stop_requested():
        try:
            if time.monotonic() >= next_scan:
                observation = engine_observation()
                api("/internal/environment-engine", token, observation)
                if observation["status"] != "ready":
                    api("/internal/environment-preparations/claim", token, {
                        "runner_id": "local-docker",
                    })
                    time.sleep(2)
                    continue
                prepared, missing = installer.program_environments()
                environments = program_environments() + prepared
                for release_id in set(missing) - missing_reported:
                    api("/internal/environment-releases/" + release_id + "/unavailable", token, {
                        "reason": "image_missing",
                    })
                    missing_reported.add(release_id)
                next_scan = time.monotonic() + 10
            preparation = api("/internal/environment-preparations/claim", token, {
                "runner_id": "local-docker",
            })
            if preparation:
                _prepare_environment(installer, preparation, token)
                next_scan = 0.0
                continue
            claim = api("/internal/executions/claim", token, {
                "runner_id": "local-docker", "program_environments": environments,
                "example_terminal": True,
            })
            if not claim:
                time.sleep(1)
                continue
            compilation = None
            if "program" in claim:
                program = claim["program"]
                release = installer.release(program["environment_release_id"]) \
                    if program.get("environment_release_id") else None
                release_authorize = _release_authorizer(program, token) \
                    if program.get("environment_release_id") else None
                authorize = _execution_authorizer(claim, token, release_authorize)
                if program["profile"] == "sql-query.v1":
                    cases = execute_sql(program, release, authorize)
                elif program["profile"] == "python-project-io.v1":
                    cases = execute_project(program, authorize)
                elif program["profile"] == "project-stdio.v1":
                    exchange = terminal_exchange(claim, token) if claim.get("interactive") else None
                    compilation, cases = execute_stdio(
                        program, release, authorize, terminal=exchange,
                    )
                elif program["profile"] == "web-check.v1":
                    compilation, cases = execute_web_with_build(program, release, authorize)
                elif program["profile"] == "project-http.v1":
                    compilation, cases = execute_http(program, release, authorize)
                else:
                    raise SystemExit("Unsupported execution profile; controller stopped.")
            else:
                authorize = _execution_authorizer(claim, token)
                cases = [
                    execute_case(claim["code"], numbers, authorize) for numbers in claim["inputs"]
                ]
            report = {"claim_token": claim["claim_token"], "cases": cases}
            if compilation is not None:
                report["compilation"] = compilation
            _report("/internal/executions/" + claim["job_id"] + "/report", token, report)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            print("Runner unavailable:", type(error).__name__, flush=True)
            time.sleep(2)
    controller_lock.close()



if __name__ == "__main__":
    main()
