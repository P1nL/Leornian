import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_teaching_delivery import drain, provider
from test_tutor_runtime import response as tool_response
from test_tutor_runtime import setup_tutor as setup_tutor

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.model_tests import ModelTestWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.tutor.contracts import TurnInput
from leornian.platform.config import Settings
from leornian.platform.credentials import CredentialVault
from leornian.platform.model_contracts import (
    CHAT_ROLES,
    ModelConnectionInput,
    ModelConnectionPatch,
    ModelConnectionTestInput,
    ModelProfileInput,
    ModelProfilePatch,
)
from leornian.platform.model_network import (
    PinnedModelTransport,
    resolve_destination,
    validate_endpoint,
)
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def model_setup(database, session):
    settings = Settings(
        database_url=database.url,
        model_configuration_mode="user",
        model_enabled=True,
        model_api_key="not-a-user-default",
        model_base_url="https://platform.invalid/v1",
        model_name="not-a-user-default",
    )
    workflow = ModelConfigurationWorkflow(database, settings)
    data = ModelConnectionInput(
        label="Personal provider",
        protocol="chat_completions",
        base_url="https://models.example.org/v1",
        region="custom",
        enabled=True,
        api_key="test-personal-secret",
    )
    connection = workflow.create_connection(session.token, str(uuid4()), data)
    profile_data = ModelProfileInput(
        label="Teaching",
        connection_id=connection.id,
        model="personal-chat",
        operation="chat",
        roles=list(CHAT_ROLES),
        context_tokens=131072,
        max_output_tokens=16384,
        enabled=True,
        allow_private_material=True,
    )
    profile = workflow.save_profile(session.token, str(uuid4()), profile_data)
    return workflow, settings, connection, profile, profile_data


def test_local_vault_authenticates_owner_reference_and_credential_version():
    vault = CredentialVault()
    if not vault.available():
        pytest.skip("This host needs an explicitly protected Linux master file")
    owner, connection = uuid4(), uuid4()
    scheme, ciphertext = vault.seal(owner, connection, 1, "personal-secret")
    assert b"personal-secret" not in ciphertext
    assert vault.open(owner, connection, 1, scheme, ciphertext) == "personal-secret"
    for changed in ((uuid4(), connection, 1), (owner, uuid4(), 1), (owner, connection, 2)):
        with pytest.raises(BusinessError):
            vault.open(*changed, scheme, ciphertext)


def test_profile_routing_rotation_revocation_and_private_boundary(
    database, workflow, session, model_setup
):
    service, settings, connection, profile, data = model_setup
    assert service.availability(session.token).ready
    with database.transaction() as db:
        store = UserModels(db, settings)
        frozen = store.binding(session.actor, "tutor.v1")
        resolved = store.resolve_chat(session.actor, frozen)
    assert resolved.model_api_key == "test-personal-secret"
    assert resolved.model_name == "personal-chat"
    assert "test-personal-secret" not in repr(resolved)
    assert resolved.model_network_guard
    assert "test-personal-secret" not in service.configuration(session.token).model_dump_json()
    other = workflow.create_session("Other model owner")
    assert not service.availability(other.token).ready
    with pytest.raises(BusinessError) as error:
        service.save_profile(
            other.token,
            str(uuid4()),
            data.model_copy(update={"connection_id": connection.id}),
        )
    assert error.value.code == "not_found"
    service.patch_connection(
        session.token,
        connection.id,
        ModelConnectionPatch(expected_revision=1, api_key="rotated-personal-secret"),
    )
    with database.transaction() as db:
        with pytest.raises(BusinessError):
            UserModels(db, settings).resolve_chat(session.actor, frozen)
    with database.transaction() as db:
        store = UserModels(db, settings)
        current = store.binding(session.actor, "tutor.v1")
        assert current["credential_version"] == 2
        assert store.resolve_chat(session.actor, current).model_api_key == "rotated-personal-secret"
    changed = service.save_profile(
        session.token,
        "",
        ModelProfilePatch(
            **data.model_dump(),
            expected_revision=1,
        ).model_copy(update={"allow_private_material": False}),
        profile.id,
    )
    assert changed.revision == 2 and not service.availability(session.token).ready
    deleted = service.delete_connection(session.token, connection.id, 2)
    assert not deleted.enabled and not deleted.credential_present and deleted.deleted
    assert service.delete_connection(session.token, connection.id, 2) == deleted
    with database.transaction(snapshot=True) as db:
        assert all(
            row["ciphertext"] is None
            for row in db.execute(
                "SELECT ciphertext FROM platform.model_credentials WHERE connection_id=%s",
                (connection.id,),
            ).fetchall()
        )
        assert (
            db.execute(
                "SELECT count(*) AS n FROM platform.model_connection_versions "
                "WHERE connection_id=%s",
                (connection.id,),
            ).fetchone()["n"]
            == 3
        )


def test_http_configuration_never_echoes_key_even_in_validation_errors(database, workflow, session):
    client = TestClient(
        create_app(
            Settings(
                database_url=database.url,
                model_configuration_mode="user",
            )
        )
    )
    headers = {"Authorization": f"Bearer {session.token}", "Idempotency-Key": str(uuid4())}
    payload = {
        "label": "My provider",
        "protocol": "chat_completions",
        "base_url": "https://models.example.org/v1",
        "region": "custom",
        "enabled": True,
        "api_key": "secret-that-must-not-be-echoed",
    }
    result = client.post("/v1/model-connections", headers=headers, json=payload)
    assert result.status_code == 201 and result.json()["credential_present"]
    assert payload["api_key"] not in result.text
    assert (
        client.post(
            "/v1/model-connections",
            headers=headers,
            json=payload,
        ).json()
        == result.json()
    )
    conflict = client.post(
        "/v1/model-connections",
        headers=headers,
        json={**payload, "api_key": "different-personal-secret"},
    )
    assert conflict.status_code == 409 and "different-personal-secret" not in conflict.text
    invalid = client.post(
        "/v1/model-connections",
        headers=headers,
        json={**payload, "actor_id": str(uuid4())},
    )
    assert invalid.status_code == 422 and payload["api_key"] not in invalid.text
    other = workflow.create_session("Another owner")
    foreign = client.patch(
        "/v1/model-connections/" + result.json()["id"],
        headers={"Authorization": f"Bearer {other.token}"},
        json={"expected_revision": 1, "enabled": False},
    )
    assert foreign.status_code == 404
    snapshot = client.get("/v1/snapshot", headers=headers)
    assert payload["api_key"] not in snapshot.text
    with database.transaction(snapshot=True) as db:
        encrypted = db.execute(
            "SELECT ciphertext FROM platform.model_credentials WHERE connection_id=%s",
            (result.json()["id"],),
        ).fetchone()["ciphertext"]
        commands = db.execute(
            "SELECT request FROM platform.model_configuration_commands WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchall()
    assert payload["api_key"].encode() not in bytes(encrypted)
    assert payload["api_key"] not in json.dumps(commands)


@pytest.mark.parametrize(
    "url,local",
    [
        ("http://example.org/v1", False),
        ("https://127.0.0.1/v1", False),
        ("https://[::ffff:127.0.0.1]/v1", False),
        ("http://192.168.1.1/v1", True),
        ("https://user:token@example.org/v1", False),
    ],
)
def test_model_network_rejects_nonpublic_and_misdeclared_local_endpoints(url, local):
    with pytest.raises(BusinessError):
        validate_endpoint(url, local)


def test_dns_is_checked_and_socket_destination_is_pinned(monkeypatch):
    monkeypatch.setattr(
        "leornian.platform.model_network.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("1.1.1.1", 443))],
    )
    destination = resolve_destination("https://models.example.org/v1", False)
    observed = {}

    def receive(request):
        observed.update(
            host=request.url.host,
            authority=request.headers["Host"],
            sni=request.extensions["sni_hostname"],
        )
        return httpx.Response(200, json={})

    with httpx.Client(
        transport=PinnedModelTransport(
            "https://models.example.org/v1", destination, httpx.MockTransport(receive)
        )
    ) as client:
        client.post("https://models.example.org/v1/chat/completions", json={})
    assert observed == {
        "host": "1.1.1.1",
        "authority": "models.example.org",
        "sni": "models.example.org",
    }
    monkeypatch.setattr(
        "leornian.platform.model_network.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(BusinessError):
        resolve_destination("https://models.example.org/v1", False)


def test_byok_drives_author_and_independent_review_without_shared_key(
    database, session, model_setup, setup_tutor, monkeypatch
):
    service, settings, connection, _, profile_data = model_setup
    _, _, conversation = setup_tutor
    service.save_profile(
        session.token,
        str(uuid4()),
        profile_data.model_copy(
            update={
                "label": "Independent check",
                "model": "personal-check",
                "roles": ["delivery_review.v1"],
            }
        ),
    )
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination",
        lambda *args: "1.1.1.1",
    )
    tutor = TutorWorkflow(database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain iteration.")
    )
    gateway, sent, _ = provider(settings, author="Iteration reads each sequence item.")
    result = drain(tutor, settings, accepted, gateway, session.token)
    assert result.status == "accepted"
    assert [request["model"] for request in sent] == ["personal-chat", "personal-check"]
    with database.transaction(snapshot=True) as db:
        calls = db.execute(
            "SELECT request,context_manifest,policy_snapshot FROM runtime.external_calls "
            "WHERE run_id=%s ORDER BY step",
            (accepted.run_id,),
        ).fetchall()
    assert all(
        row["context_manifest"]["model_binding"]["connection_id"] == str(connection.id)
        for row in calls
    )
    assert "test-personal-secret" not in json.dumps(calls)
    assert "not-a-user-default" not in json.dumps(calls)


def test_missing_byok_waits_for_configuration_never_uses_development_key(
    database, session, setup_tutor
):
    _, _, conversation = setup_tutor
    settings = Settings(
        database_url=database.url,
        model_configuration_mode="user",
        model_enabled=True,
        model_base_url="https://platform.invalid/v1",
        model_name="shared",
        model_api_key="must-not-send",
    )
    tutor = TutorWorkflow(database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="A user question")
    )

    def forbidden(_request):
        pytest.fail("An unconfigured user must never use the process-level model key")

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(forbidden))).run(
        accepted.run_id
    )
    task = tutor.delivery_task(session.token, accepted.delivery_task_id)
    assert task.status == "waiting_config"
    with database.transaction(snapshot=True) as db:
        assert (
            db.execute(
                "SELECT count(*) AS n FROM runtime.external_calls WHERE run_id=%s",
                (accepted.run_id,),
            ).fetchone()["n"]
            == 0
        )


def test_rotation_does_not_resend_unknown_user_call(
    database, session, model_setup, setup_tutor, monkeypatch
):
    service, settings, connection, _, _ = model_setup
    _, _, conversation = setup_tutor
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination",
        lambda *args: "1.1.1.1",
    )
    tutor = TutorWorkflow(database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain iteration")
    )
    sent = []

    def timeout(request):
        sent.append(request)
        raise httpx.ReadTimeout("Owned fixture dropped the receipt")

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(timeout))
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert tutor.get(session.token, accepted.run_id).status == "blocked_unknown"
    service.patch_connection(
        session.token,
        connection.id,
        ModelConnectionPatch(expected_revision=1, api_key="a-new-personal-secret"),
    )
    AgentLoop(tutor, gateway).run(accepted.run_id)
    with pytest.raises(BusinessError) as error:
        tutor.resume(session.token, accepted.run_id)
    assert error.value.code == "unknown_unresolved"
    assert len(sent) == 1


@pytest.mark.parametrize(
    ("content", "expected_status", "expected_error", "expected_applied"),
    [
        pytest.param('{"ok":true}', "succeeded", None, True, id="boolean-true"),
        pytest.param(
            '{"ok":package.json}',
            "failed",
            "invalid_probe_response",
            False,
            id="invalid-json",
        ),
        pytest.param(
            '{"ok":1}', "failed", "invalid_probe_response", False, id="integer-one"
        ),
    ],
)
def test_explicit_probe_is_idempotent_and_uses_original_external_receipts(
    database,
    session,
    model_setup,
    monkeypatch,
    content,
    expected_status,
    expected_error,
    expected_applied,
):
    _, settings, connection, profile, _ = model_setup
    tests = ModelTestWorkflow(database, settings)
    data = ModelConnectionTestInput(
        expected_connection_revision=connection.revision,
        profile_id=profile.id,
        allow_billable=True,
    )
    key = str(uuid4())
    job = tests.submit(session.token, connection.id, key, data)
    assert tests.submit(session.token, connection.id, key, data).id == job.id
    assert job.status == "queued"
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination",
        lambda *args: "1.1.1.1",
    )
    sent = []

    def receive(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    tests.execute(job.id, httpx.MockTransport(receive))
    tests.execute(job.id, httpx.MockTransport(receive))
    result = tests.get(session.token, job.id)
    assert len(sent) == 1
    assert result.status == expected_status
    assert result.error_code == expected_error
    if expected_status == "succeeded":
        assert result.result["protocol"] == "chat-json-roundtrip.v1"
        assert result.result["json_response"] == "verified"
        assert result.result["tools"] == "not_tested"
        assert result.result["usage"]["completion_tokens"] == 4
    else:
        assert result.result is None
    with database.transaction(snapshot=True) as db:
        fact = db.execute(
            "SELECT status,applied,run_id FROM runtime.external_calls WHERE operation_ref=%s",
            (job.id,),
        ).fetchone()
    assert fact == {
        "status": "result_recorded",
        "applied": expected_applied,
        "run_id": None,
    }


def test_revoked_queued_probe_never_sends_and_unknown_is_not_replayed(
    database, session, model_setup, monkeypatch
):
    service, settings, connection, profile, _ = model_setup
    tests = ModelTestWorkflow(database, settings)
    data = ModelConnectionTestInput(
        expected_connection_revision=1,
        profile_id=profile.id,
        allow_billable=True,
    )
    first = tests.submit(session.token, connection.id, str(uuid4()), data)
    second = tests.submit(session.token, connection.id, str(uuid4()), data)
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination",
        lambda *args: "1.1.1.1",
    )
    sent = []

    def timeout(request):
        sent.append(request)
        raise httpx.ReadTimeout("Owned fixture transport loss")

    tests.execute(first.id, httpx.MockTransport(timeout))
    service.patch_connection(
        session.token,
        connection.id,
        ModelConnectionPatch(expected_revision=1, enabled=False),
    )
    tests.execute(first.id, httpx.MockTransport(timeout))
    tests.execute(second.id, httpx.MockTransport(timeout))
    assert tests.get(session.token, first.id).status == "unknown"
    assert tests.get(session.token, second.id).status == "failed"
    assert len(sent) == 1


def test_provider_echoed_credential_is_redacted_before_receipt_storage(
    database, session, model_setup, monkeypatch
):
    _, settings, connection, profile, _ = model_setup
    tests = ModelTestWorkflow(database, settings)
    job = tests.submit(
        session.token,
        connection.id,
        str(uuid4()),
        ModelConnectionTestInput(
            expected_connection_revision=1,
            profile_id=profile.id,
            allow_billable=True,
        ),
    )
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination",
        lambda *args: "1.1.1.1",
    )

    def echo(_request):
        return httpx.Response(
            200,
            headers={"x-request-id": _request.headers["Authorization"].removeprefix("Bearer ")},
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok":true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "unexpected": "test-personal-secret"},
            },
        )

    tests.execute(job.id, httpx.MockTransport(echo))
    result = tests.get(session.token, job.id)
    assert result.status == "succeeded"
    assert result.result["usage"] == {"prompt_tokens": 8}
    with database.transaction(snapshot=True) as db:
        recorded = db.execute(
            "SELECT response_body,provider_request_id FROM runtime.external_calls "
            "WHERE operation_ref=%s",
            (job.id,),
        ).fetchone()
        body = recorded["response_body"]
        assert recorded["provider_request_id"] == "[leornian-redacted-credential]"
    assert "test-personal-secret" not in body
    assert "[leornian-redacted-credential]" in body


def test_runtime_configuration_does_not_invert_actor_command_and_run_locks(
    database, session, model_setup, setup_tutor
):
    _, settings, _, _, _ = model_setup
    _, _, conversation = setup_tutor
    tutor = TutorWorkflow(database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="A configuration lock check")
    )
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.transaction() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("actor-command:" + str(session.actor.id),),
            )
            future = pool.submit(
                tutor.gateway_for, lease, role, None, ChatCompletionsGateway(settings)
            )
            assert future.result(timeout=5).model_binding["scope"] == "user"
    tutor.cancel(session.token, accepted.run_id)


def test_rotation_cannot_silently_change_a_frozen_tool_continuation(
    database, session, model_setup, setup_tutor, monkeypatch
):
    service, settings, connection, _, _ = model_setup
    _, _, conversation = setup_tutor
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination",
        lambda *args: "1.1.1.1",
    )
    tutor = TutorWorkflow(database, settings)
    accepted = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Refresh the bound context")
    )
    sent = []

    def tool(request):
        sent.append(request)
        return httpx.Response(200, json=tool_response())

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(tool))
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert len(sent) == 1
    service.patch_connection(
        session.token,
        connection.id,
        ModelConnectionPatch(expected_revision=1, api_key="rotated-tool-fixture-key"),
    )
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert tutor.delivery_task(session.token, accepted.delivery_task_id).status == "waiting_config"
    tutor.resume_delivery(session.token, accepted.delivery_task_id)
    AgentLoop(tutor, gateway).run(accepted.run_id)
    assert len(sent) == 1
    tutor.cancel(session.token, accepted.run_id)
