import importlib.util
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LEORNIAN_TEST_DOCKER") != "1",
    reason="Set LEORNIAN_TEST_DOCKER=1 for real local Docker isolation tests",
)


@pytest.fixture(scope="module")
def runner():
    source = Path(__file__).parents[2] / "services" / "runner" / "controller.py"
    spec = importlib.util.spec_from_file_location("local_runner", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_container_has_no_credentials_network_or_writable_root(runner):
    code = """
import json, os, socket
try:
    open('/tmp/learner-write', 'w').close()
    writable = True
except OSError:
    writable = False
print(json.dumps({
    'uid': os.getuid(), 'interfaces': socket.if_nameindex(), 'writable': writable,
    'credentials': [key for key in os.environ if key.startswith('LEORNIAN_')],
}))
"""
    result = runner.execute_case(code, [])
    assert result["outcome"] == "completed" and result["exit_code"] == 0
    data = json.loads(result["stdout"])
    assert data == {"uid": 65534, "interfaces": [[1, "lo"]], "writable": False, "credentials": []}


def test_real_container_timeout_is_not_success(runner):
    result = runner.execute_case("while True: pass", [])
    assert result["outcome"] == "timeout" and result["exit_code"] != 0


def test_real_container_output_is_bounded(runner):
    result = runner.execute_case("while True: print('x' * 1024, flush=True)", [])
    assert result["outcome"] == "output_limit" and len(result["stdout"].encode()) <= 4096
