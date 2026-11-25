"""Authenticated local API requests and execution authorization callbacks."""

import json
import os
import time
import urllib.error
import urllib.request

from .sandbox import _stop_requested

API = os.environ.get("LEORNIAN_RUNNER_API", "http://127.0.0.1:8088")


def api(path, token, payload, *, timeout=10):
    request = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)



def _report(path, token, payload):
    for _attempt in range(3):
        try:
            return True, api(path, token, payload)
        except urllib.error.HTTPError as error:
            if error.code < 500:
                print("Runner receipt rejected:", error.code, flush=True)
                return False, None
            time.sleep(1)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    print("Runner receipt not acknowledged; the original work will not be repeated.", flush=True)
    return False, None



def _release_authorizer(program, token):
    body = {
        key: program[key] for key in ("profile", "language", "dialect", "runtime_version")
        if key in program
    }

    def authorize():
        if _stop_requested():
            return False
        try:
            return api(
                "/internal/environment-releases/" + program["environment_release_id"] + "/verify",
                token, body, timeout=2,
            )["allowed"]
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    return authorize



def _execution_authorizer(claim, token, release_authorize=None):
    next_observation = time.monotonic() + 10

    def authorize():
        nonlocal next_observation
        if _stop_requested():
            return False
        try:
            if claim.get("interactive") and time.monotonic() >= next_observation:
                from leornian.modules.execution.environment_runtime import engine_observation

                observation = engine_observation()
                api("/internal/environment-engine", token, observation, timeout=2)
                next_observation = time.monotonic() + 10
                if observation["status"] != "ready":
                    return False
            current = api(
                "/internal/executions/" + claim["job_id"] + "/verify", token,
                {"claim_token": claim["claim_token"]}, timeout=2,
            )["allowed"]
            return current and (release_authorize is None or release_authorize())
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    return authorize


def terminal_exchange(claim, token):
    frame, after_input = 0, 0

    def exchange(text, *, closed=False):
        nonlocal frame, after_input
        if _stop_requested():
            raise OSError("Local controller stopped")
        frame += bool(text)
        reply = api("/internal/executions/" + claim["job_id"] + "/terminal", token, {
            "claim_token": claim["claim_token"], "frame": frame, "text": text,
            "after_input": after_input, "closed": closed,
        }, timeout=2)
        after_input += len(reply["lines"])
        return reply["lines"]

    return exchange

