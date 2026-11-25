import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.model_tests import ModelTestWorkflow
from leornian.platform.config import Settings
from leornian.platform.model_contracts import (
    ModelConnectionInput,
    ModelConnectionPatch,
    ModelConnectionTestInput,
    ModelProfileInput,
)
from leornian.platform.model_probes import MaterialProbeGateway
from leornian.platform.models import MaterialProbeConfiguration, UserModels
from leornian.shared_kernel.errors import BusinessError


def probe_response(operation, protocol="dashscope"):
    if operation == "embedding":
        native = protocol == "dashscope"
        embeddings = [
            {"text_index" if native else "index": i, "embedding": [0.1, 0.2, 0.3, 0.4]}
            for i in range(2)
        ]
        body = {"output": {"embeddings": embeddings}} if native else {"data": embeddings}
    elif operation == "rerank":
        body = {
            "output": {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.1},
                ]
            }
        }
    else:
        body = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "LEORNIAN 123\n"},
                    "finish_reason": "stop",
                }
            ]
        }
    return {**body, "usage": {"total_tokens": 12, "input_tokens": 10, "output_tokens": 2}}


@pytest.fixture
def probe_setup(database, session, monkeypatch):
    monkeypatch.setattr("leornian.platform.model_probes.resolve_destination", lambda *_: "1.1.1.1")
    settings = Settings(database_url=database.url, model_configuration_mode="user")
    configuration = ModelConfigurationWorkflow(database, settings)
    tests = ModelTestWorkflow(database, settings)

    def prepare(operation, protocol="dashscope"):
        connection = configuration.create_connection(
            session.token,
            str(uuid4()),
            ModelConnectionInput(
                label="Native probe",
                protocol=protocol,
                base_url="https://dashscope.aliyuncs.com"
                if protocol == "dashscope"
                else "https://probe.example.org",
                region="cn-beijing" if protocol == "dashscope" else "test-region",
                enabled=True,
                api_key="fixed-native-probe-secret",
            ),
        )
        profile = configuration.save_profile(
            session.token,
            str(uuid4()),
            ModelProfileInput(
                label="Dedicated " + operation,
                connection_id=connection.id,
                model="fixture-" + operation,
                operation=operation,
                roles=[operation],
                enabled=True,
                embedding_dimensions=4,
            ),
        )
        job = tests.submit(
            session.token,
            connection.id,
            str(uuid4()),
            ModelConnectionTestInput(
                expected_connection_revision=connection.revision,
                profile_id=profile.id,
                allow_billable=True,
            ),
        )
        return configuration, tests, connection, profile, job

    return prepare


@pytest.mark.parametrize(
    "operation,protocol",
    [
        ("embedding", "dashscope"),
        ("embedding", "chat_completions"),
        ("rerank", "dashscope"),
        ("ocr", "dashscope"),
        ("ocr", "chat_completions"),
    ],
)
def test_dedicated_fixed_probe_uses_its_protocol_and_same_call_ledger(
    database, session, probe_setup, operation, protocol
):
    _, tests, _, _, job = probe_setup(operation, protocol)
    requests = []

    def handle(request):
        requests.append(request)
        wire = json.loads(request.content)
        assert wire["model"] == "fixture-" + operation
        assert not {"thinking", "tools", "tool_choice"} & wire.keys()
        if operation == "embedding":
            assert (
                request.url.path.endswith("text-embedding")
                if protocol == "dashscope"
                else (request.url.path.endswith("/embeddings"))
            )
            assert "messages" not in wire
        elif operation == "rerank":
            assert request.url.path.endswith("/services/rerank/text-rerank/text-rerank")
            assert len(wire["input"]["documents"]) == 2 and "messages" not in wire
            assert wire["parameters"] == {"top_n": 2}
        else:
            assert request.url.path.endswith("/chat/completions")
            assert wire["messages"][0]["content"][0]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        return httpx.Response(200, json=probe_response(operation, protocol))

    transport = httpx.MockTransport(handle)
    tests.execute(job.id, transport)
    tests.execute(job.id, transport)
    result = tests.get(session.token, job.id)
    assert len(requests) == 1 and result.status == "succeeded"
    assert result.result["tools"] == "not_applicable"
    assert result.result["material_quality"] == "not_tested"
    assert result.result["usage"]["input_tokens"] == 10
    assert "fixed-native-probe-secret" not in result.model_dump_json()
    with database.transaction(snapshot=True) as db:
        call = Runs(db).operation(job.id)
        assert call.applied and call.status == "result_recorded"
        assert call.request["model"] == "fixture-" + operation
        assert "fixed-native-probe-secret" not in json.dumps(call.request)


def test_unknown_dedicated_probe_does_not_repeat_after_rotation(database, session, probe_setup):
    configuration, tests, connection, _, job = probe_setup("embedding")
    sent = []

    def lost(request):
        sent.append(request)
        raise httpx.ReadError("fixture unknown")

    transport = httpx.MockTransport(lost)
    tests.execute(job.id, transport)
    assert tests.get(session.token, job.id).status == "unknown"
    configuration.patch_connection(
        session.token,
        connection.id,
        ModelConnectionPatch(expected_revision=1, api_key="new-native-probe-secret"),
    )
    tests.execute(job.id, transport)
    assert len(sent) == 1
    with database.transaction(snapshot=True) as db:
        assert Runs(db).operation(job.id).status == "unknown"


def test_revoked_dedicated_probe_has_no_dispatch(session, probe_setup):
    configuration, tests, connection, _, job = probe_setup("rerank")
    configuration.delete_connection(session.token, connection.id, 1)

    def unexpected(_):
        pytest.fail("Revoked credentials must not dispatch")

    tests.execute(job.id, httpx.MockTransport(unexpected))
    assert tests.get(session.token, job.id).status == "failed"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "dimensions", "nonfinite"])
def test_embedding_probe_rejects_incomplete_or_mixed_dimensions(mutation):
    config = MaterialProbeConfiguration(
        base_url="https://probe.example.org",
        protocol="dashscope",
        operation="embedding",
        model="fixture-embedding",
        dimensions=4,
        timeout=10,
        local_endpoint=False,
        api_key="probe-secret",
    )
    body = probe_response("embedding")
    values = body["output"]["embeddings"]
    if mutation == "missing":
        values.pop()
    elif mutation == "duplicate":
        values[1]["text_index"] = 0
    elif mutation == "dimensions":
        values[0]["embedding"].pop()
    else:
        values[0]["embedding"][0] = float("inf")
    with pytest.raises(ModelProtocolError):
        MaterialProbeGateway(config).validate(json.dumps(body))
    assert "probe-secret" not in repr(config)
    assert (
        MaterialProbeGateway(replace(config, dimensions=4)).probe()[0]["parameters"]["dimension"]
        == 4
    )


def test_rerank_requires_its_own_protocol(database, session):
    service = ModelConfigurationWorkflow(database, Settings())
    connection = service.create_connection(
        session.token,
        str(uuid4()),
        ModelConnectionInput(
            label="Compatible only",
            protocol="chat_completions",
            base_url="https://probe.example.org/v1",
            region="test",
            api_key="probe-secret",
        ),
    )
    with pytest.raises(BusinessError):
        service.save_profile(
            session.token,
            str(uuid4()),
            ModelProfileInput(
                label="Not a chat call",
                model="fixture-rerank",
                operation="rerank",
                connection_id=connection.id,
                roles=["rerank"],
            ),
        )


def test_workspace_roots_match_their_actual_region():
    UserModels._dashscope_region(
        "https://workspace-123.cn-beijing.maas.aliyuncs.com",
        "cn-beijing",
        False,
    )
    UserModels._dashscope_region(
        "https://workspace-123.ap-southeast-1.maas.aliyuncs.com",
        "singapore",
        False,
    )
    for endpoint in (
        "https://workspace-123.us-east-1.maas.aliyuncs.com",
        "https://workspace-123.cn-beijing.maas.aliyuncs.com.attacker.invalid",
        "https://workspace-123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    ):
        with pytest.raises(BusinessError):
            UserModels._dashscope_region(endpoint, "cn-beijing", False)
