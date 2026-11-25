from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.services import GoalWorkflow
from leornian.entrypoints.api import create_app
from leornian.platform.config import Settings
from leornian.platform.model_contracts import (
    CHAT_ROLES,
    ModelConnectionPatch,
    ModelConnectionUseInput,
    ModelCustomProviderInput,
    ModelPresetInput,
    ModelProfilePatch,
)
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def presets(database, monkeypatch):
    def no_provider_request(*args, **kwargs):
        pytest.fail("Saving a preset must not contact a model provider")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_provider_request)
    settings = Settings(database_url=database.url, model_configuration_mode="user")
    return ModelConfigurationWorkflow(database, settings), settings


def revision_input(configuration, **fields):
    return ModelPresetInput(
        api_key="offline-preset-credential",
        allow_private_material=True,
        expected_mapping_revisions={item.role: item.revision for item in configuration.mappings},
        **fields,
    )


@pytest.mark.parametrize("preset_id,profile_count", [("deepseek", 1), ("qwen", 4)])
def test_key_only_preset_is_atomic_private_enabled_idempotent_and_secret_safe(
    database, session, presets, preset_id, profile_count
):
    service, settings = presets
    key = str(uuid4())
    data = revision_input(service.configuration(session.token))
    first = service.apply_preset(session.token, key, preset_id, data)
    saved = service.configuration(session.token)
    assert first.enabled and first.credential_present and first.credential_version == 1
    assert len(saved.connections) == 1 and len(saved.profiles) == profile_count
    assert all(profile.enabled and profile.allow_private_material for profile in saved.profiles)
    expected_roles = set(CHAT_ROLES) | (
        {"ocr", "embedding", "rerank"} if preset_id == "qwen" else set()
    )
    assert {mapping.role for mapping in saved.mappings} == expected_roles
    assert service.apply_preset(session.token, key, preset_id, data) == first
    assert service.configuration(session.token) == saved
    assert "offline-preset-credential" not in saved.model_dump_json()
    assert "offline-preset-credential" not in repr(data)
    with database.transaction(snapshot=True) as db:
        for role in expected_roles:
            assert UserModels(db, settings).binding(session.actor, role)
        requests = db.execute(
            "SELECT request FROM platform.model_configuration_commands WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchall()
        assert "offline-preset-credential" not in str(requests)
        for table in ("platform.model_connection_tests", "runtime.runs"):
            assert db.execute(
                f"SELECT count(*) AS n FROM {table} WHERE actor_id=%s", (session.actor.id,)
            ).fetchone()["n"] == 0
    with pytest.raises(BusinessError, match="different input"):
        service.apply_preset(
            session.token, key, preset_id,
            data.model_copy(update={"api_key": ModelPresetInput(
                api_key="offline-changed-key", allow_private_material=True
            ).api_key}),
        )


def test_qwen_preserves_teaching_and_key_rotation_reuses_profiles(database, session, presets):
    service, _ = presets
    deepseek = service.apply_preset(
        session.token, str(uuid4()), "deepseek",
        revision_input(service.configuration(session.token)),
    )
    teaching = service.configuration(session.token).mappings
    qwen = service.apply_preset(
        session.token, str(uuid4()), "qwen",
        revision_input(service.configuration(session.token)),
    )
    saved = service.configuration(session.token)
    assert [item for item in saved.mappings if item.role in CHAT_ROLES] == teaching
    assert len(saved.profiles) == 5
    rotated = service.apply_preset(
        session.token, str(uuid4()), "qwen",
        revision_input(saved, connection_id=qwen.id, expected_connection_revision=qwen.revision),
    )
    final = service.configuration(session.token)
    assert rotated.id == qwen.id and rotated.credential_version == 2
    assert len(final.connections) == 2 and final.profiles == saved.profiles
    assert final.connections[0] == deepseek
    assert [item for item in final.mappings if item.role in CHAT_ROLES] == teaching


def test_stale_role_rolls_back_connection_key_and_all_preset_profiles(session, presets):
    service, _ = presets
    original = service.apply_preset(
        session.token, str(uuid4()), "deepseek",
        revision_input(service.configuration(session.token)),
    )
    before = service.configuration(session.token)
    with pytest.raises(BusinessError) as failure:
        service.apply_preset(
            session.token, str(uuid4()), "deepseek",
            ModelPresetInput(
                api_key="offline-new-key", allow_private_material=True,
                connection_id=original.id, expected_connection_revision=original.revision,
            ),
        )
    assert failure.value.code == "stale_version"
    assert service.configuration(session.token) == before
    with pytest.raises(BusinessError):
        service.apply_preset(
            session.token, str(uuid4()), "qwen",
            ModelPresetInput(
                api_key="offline-new-key", allow_private_material=True,
                expected_mapping_revisions={"ocr": 2},
            ),
        )
    assert service.configuration(session.token) == before


def test_preset_cannot_rotate_another_owners_or_other_providers_connection(
    database, session, presets
):
    service, _ = presets
    other = GoalWorkflow(database).create_session("Other preset owner")
    connection = service.apply_preset(
        session.token, str(uuid4()), "deepseek",
        revision_input(service.configuration(session.token)),
    )
    for token, preset_id, code in (
        (other.token, "deepseek", "not_found"),
        (session.token, "qwen", "precondition_failed"),
    ):
        before = service.configuration(token)
        with pytest.raises(BusinessError) as failure:
            service.apply_preset(
                token, str(uuid4()), preset_id,
                revision_input(
                    before, connection_id=connection.id,
                    expected_connection_revision=connection.revision,
                ),
            )
        assert failure.value.code == code
        assert service.configuration(token) == before


def test_preset_api_requires_consent_and_returns_only_public_configuration(session, presets):
    _, settings = presets
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
        for body in (
            {"api_key": "offline-secret-do-not-echo"},
            {"api_key": "offline-secret-do-not-echo", "allow_private_material": False},
            {"api_key": "invalid secret with spaces", "allow_private_material": True},
        ):
            response = client.post("/v1/model-presets/deepseek", headers=headers, json=body)
            assert response.status_code == 422 and body["api_key"] not in response.text
        response = client.post(
            "/v1/model-presets/deepseek", headers=headers,
            json={"api_key": "offline-secret-do-not-echo", "allow_private_material": True},
        )
        assert response.status_code == 201 and "offline-secret-do-not-echo" not in response.text
        assert response.json()["enabled"] and response.json()["credential_present"]
        configuration = client.get("/v1/model-configuration", headers=headers).json()
        assert len(configuration["presets"]) == 2 and len(configuration["profiles"]) == 1
        assert "provider-presets.v2" in configuration["capabilities"]
        preset = configuration["presets"][0]
        assert preset["api_key_url"] == "https://platform.deepseek.com/api_keys"
        assert preset["model_details"][0]["context_tokens"] == 1_048_576


def test_selected_models_only_create_and_assign_the_requested_material_profiles(session, presets):
    service, _ = presets
    service.apply_preset(
        session.token, str(uuid4()), "qwen",
        revision_input(service.configuration(session.token), models=[
            "qwen3.5-ocr", "text-embedding-v4", "qwen3-rerank",
        ]),
    )
    saved = service.configuration(session.token)
    assert len(saved.connections) == 1 and len(saved.profiles) == 3
    assert {item.operation for item in saved.profiles} == {"ocr", "embedding", "rerank"}
    assert {item.role for item in saved.mappings} == {"ocr", "embedding", "rerank"}


@pytest.mark.parametrize("models", [["not-in-the-preset"], ["qwen-plus", "qwen-plus"]])
def test_unapproved_or_duplicate_models_leave_the_configuration_unchanged(session, presets, models):
    service, _ = presets
    before = service.configuration(session.token)
    with pytest.raises(BusinessError) as failure:
        service.apply_preset(
            session.token, str(uuid4()), "qwen", revision_input(before, models=models)
        )
    assert failure.value.code == "precondition_failed"
    assert service.configuration(session.token) == before


def two_providers(service, token):
    deepseek = service.apply_preset(
        token, str(uuid4()), "deepseek", revision_input(service.configuration(token))
    )
    qwen = service.apply_preset(
        token, str(uuid4()), "qwen", revision_input(service.configuration(token))
    )
    return deepseek, qwen, service.configuration(token)


def use_input(configuration, connection, group):
    return ModelConnectionUseInput(
        expected_connection_revision=connection.revision,
        group=group,
        profiles=[
            {"profile_id": item.id, "expected_revision": item.revision}
            for item in configuration.profiles
            if item.connection_id == connection.id and
            (item.operation == "chat") == (group == "teaching")
        ],
        expected_mapping_revisions={item.role: item.revision for item in configuration.mappings},
    )


def test_teaching_switch_is_atomic_idempotent_and_preserves_material_configuration(
    session, presets
):
    service, _ = presets
    deepseek, qwen, before = two_providers(service, session.token)
    key = str(uuid4())
    data = use_input(before, qwen, "teaching")
    result = service.use_connection(session.token, key, qwen.id, data)
    teaching = next(item for item in before.profiles
                    if item.connection_id == qwen.id and item.operation == "chat")
    assert all(
        item.profile_id == teaching.id for item in result.mappings if item.role in CHAT_ROLES
    )
    assert [item for item in result.mappings if item.role not in CHAT_ROLES] == [
        item for item in before.mappings if item.role not in CHAT_ROLES
    ]
    assert result.connections == before.connections and result.profiles == before.profiles
    assert service.use_connection(session.token, key, qwen.id, data) == result
    restored = service.use_connection(
        session.token, str(uuid4()), deepseek.id, use_input(result, deepseek, "teaching")
    )
    assert {item.profile_id for item in restored.mappings if item.role in CHAT_ROLES} == {
        before.profiles[0].id
    }


def test_one_stale_role_rolls_back_the_entire_teaching_switch(session, presets):
    service, _ = presets
    _, qwen, before = two_providers(service, session.token)
    data = use_input(before, qwen, "teaching")
    data.expected_mapping_revisions["transfer_relation.v1"] += 1
    with pytest.raises(BusinessError) as failure:
        service.use_connection(session.token, str(uuid4()), qwen.id, data)
    assert failure.value.code == "stale_version"
    assert service.configuration(session.token) == before


@pytest.mark.parametrize("stale", ["connection", "profile"])
def test_switch_rejects_changed_connection_or_profile_revisions(session, presets, stale):
    service, _ = presets
    _, qwen, before = two_providers(service, session.token)
    data = use_input(before, qwen, "teaching")
    if stale == "connection":
        data = data.model_copy(update={
            "expected_connection_revision": data.expected_connection_revision + 1
        })
    else:
        data = data.model_copy(update={"profiles": [
            data.profiles[0].model_copy(update={
                "expected_revision": data.profiles[0].expected_revision + 1
            })
        ]})
    with pytest.raises(BusinessError) as failure:
        service.use_connection(session.token, str(uuid4()), qwen.id, data)
    assert failure.value.code == "stale_version"
    assert service.configuration(session.token) == before


@pytest.mark.parametrize(
    "invalid", ["foreign-owner", "other-connection", "wrong-group", "duplicate"]
)
def test_switch_rejects_foreign_or_incompatible_profiles(
    database, session, presets, invalid
):
    service, _ = presets
    deepseek, qwen, before = two_providers(service, session.token)
    data = use_input(before, qwen, "teaching")
    token, connection_id = session.token, qwen.id
    if invalid == "foreign-owner":
        token = GoalWorkflow(database).create_session("Other switch owner").token
    elif invalid == "other-connection":
        connection_id = deepseek.id
    elif invalid == "wrong-group":
        data = data.model_copy(update={"group": "material"})
    else:
        data.profiles.append(data.profiles[0])
    with pytest.raises(BusinessError) as failure:
        service.use_connection(token, str(uuid4()), connection_id, data)
    assert failure.value.code == (
        "not_found" if invalid == "foreign-owner" else "precondition_failed"
    )
    assert service.configuration(session.token) == before


def test_material_switch_preserves_teaching_and_key_patch_preserves_all_assignments(
    session, presets
):
    service, _ = presets
    deepseek, _, before = two_providers(service, session.token)
    other_qwen = service.apply_preset(
        session.token, str(uuid4()), "qwen", revision_input(before, models=["qwen-plus"])
    )
    service.apply_preset(
        session.token, str(uuid4()), "qwen",
        revision_input(
            service.configuration(session.token), connection_id=other_qwen.id,
            expected_connection_revision=other_qwen.revision,
            models=["qwen3.5-ocr", "text-embedding-v4", "qwen3-rerank"],
        ),
    )
    current = service.configuration(session.token)
    original_qwen = before.connections[1]
    result = service.use_connection(
        session.token, str(uuid4()), original_qwen.id,
        use_input(current, original_qwen, "material"),
    )
    assert [item for item in result.mappings if item.role in CHAT_ROLES] == [
        item for item in before.mappings if item.role in CHAT_ROLES
    ]
    assert {item.profile_id for item in result.mappings if item.role not in CHAT_ROLES} == {
        item.id for item in before.profiles if item.operation != "chat"
    }
    rotated = service.patch_connection(
        session.token, deepseek.id,
        ModelConnectionPatch(expected_revision=deepseek.revision, api_key="offline-rotated-key"),
    )
    final = service.configuration(session.token)
    assert rotated.credential_version == 2
    assert final.profiles == result.profiles and final.mappings == result.mappings


def test_switch_api_exposes_an_authenticated_versioned_nonbillable_command(session, presets):
    service, settings = presets
    _, qwen, before = two_providers(service, session.token)
    body = use_input(before, qwen, "teaching").model_dump(mode="json")
    with TestClient(create_app(settings)) as client:
        url = f"/v1/model-connections/{qwen.id}/use"
        assert client.post(url, json=body).status_code == 401
        headers = {"Authorization": "Bearer " + session.token}
        assert client.post(url, headers=headers, json=body).status_code == 422
        headers["Idempotency-Key"] = str(uuid4())
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 200
        assert "offline-preset-credential" not in response.text
        assert client.post(url, headers=headers, json=body).json() == response.json()


@pytest.mark.parametrize("blocked", ["private-permission", "disabled", "partial-teaching"])
def test_switch_requires_an_enabled_fully_authorized_teaching_profile(session, presets, blocked):
    service, _ = presets
    _, qwen, configuration = two_providers(service, session.token)
    profile = next(item for item in configuration.profiles
                   if item.connection_id == qwen.id and item.operation == "chat")
    changes = {
        "private-permission": {"allow_private_material": False},
        "disabled": {"enabled": False},
        "partial-teaching": {"roles": ["tutor.v1"]},
    }[blocked]
    service.save_profile(
        session.token, str(uuid4()),
        ModelProfilePatch(
            **{**profile.model_dump(exclude={"id", "revision", "created_at"}), **changes},
            expected_revision=profile.revision,
        ),
        profile.id, assign_roles=False,
    )
    before = service.configuration(session.token)
    with pytest.raises(BusinessError) as failure:
        service.use_connection(
            session.token, str(uuid4()), qwen.id, use_input(before, qwen, "teaching")
        )
    assert failure.value.code == "precondition_failed"
    assert service.configuration(session.token) == before


@pytest.mark.parametrize("group,operations", [
    ("teaching", {"chat"}), ("material", {"ocr", "embedding", "rerank"}),
])
def test_grouped_qwen_presets_configure_only_the_selected_category(
    session, presets, group, operations
):
    service, _ = presets
    service.apply_preset(
        session.token, str(uuid4()), "qwen",
        revision_input(service.configuration(session.token), group=group),
    )
    saved = service.configuration(session.token)
    assert {item.operation for item in saved.profiles} == operations
    assert {item.role for item in saved.mappings} == (
        set(CHAT_ROLES) if group == "teaching" else operations
    )
    assert "provider-presets.v3" in saved.capabilities


@pytest.mark.parametrize("group,preset_id,models", [
    ("teaching", "qwen", ["text-embedding-v4"]),
    ("material", "qwen", ["qwen-plus"]),
    ("material", "deepseek", None),
])
def test_grouped_presets_reject_models_from_the_other_category(
    session, presets, group, preset_id, models
):
    service, _ = presets
    before = service.configuration(session.token)
    with pytest.raises(BusinessError) as failure:
        service.apply_preset(
            session.token, str(uuid4()), preset_id,
            revision_input(before, group=group, models=models),
        )
    assert failure.value.code == "precondition_failed"
    assert service.configuration(session.token) == before


def custom_input(configuration, operation, **overrides):
    return ModelCustomProviderInput.model_validate({
        "group": "teaching" if operation == "chat" else "material",
        "connection": {
            "label": "Custom provider", "protocol": "chat_completions",
            "base_url": "https://models.example.test/v1", "region": "custom",
            "enabled": True, "api_key": "offline-custom-provider-secret",
        },
        "profile": {
            "label": "Custom model", "operation": operation, "model": "custom-model",
            "context_tokens": 65536 if operation == "chat" else 0,
            "max_output_tokens": 8192 if operation == "chat" else 0,
            "embedding_dimensions": 2048,
        },
        "allow_private_material": True,
        "expected_mapping_revisions": {
            item.role: item.revision for item in configuration.mappings
        },
        **overrides,
    })


@pytest.mark.parametrize("operation", ["chat", "ocr", "embedding"])
def test_custom_providers_are_atomic_idempotent_category_scoped_and_secret_safe(
    database, session, presets, operation
):
    service, _ = presets
    data = custom_input(service.configuration(session.token), operation)
    key = str(uuid4())
    first = service.create_custom_provider(session.token, key, data)
    saved = service.configuration(session.token)
    assert len(saved.connections) == 1 and len(saved.profiles) == 1
    assert saved.profiles[0].operation == operation
    assert saved.profiles[0].enabled and saved.profiles[0].allow_private_material
    assert {item.role for item in saved.mappings} == (
        set(CHAT_ROLES) if operation == "chat" else {operation}
    )
    assert service.create_custom_provider(session.token, key, data) == first
    assert service.configuration(session.token) == saved
    assert "offline-custom-provider-secret" not in repr(data) + saved.model_dump_json()
    with database.transaction(snapshot=True) as db:
        requests = db.execute(
            "SELECT request FROM platform.model_configuration_commands WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchall()
        assert "offline-custom-provider-secret" not in str(requests)
        assert db.execute(
            "SELECT count(*) AS n FROM runtime.runs WHERE actor_id=%s", (session.actor.id,)
        ).fetchone()["n"] == 0


def test_custom_material_setup_preserves_teaching_and_stale_setup_rolls_back_everything(
    session, presets
):
    service, _ = presets
    _, _, before = two_providers(service, session.token)
    service.create_custom_provider(
        session.token, str(uuid4()), custom_input(before, "embedding")
    )
    current = service.configuration(session.token)
    assert [item for item in current.mappings if item.role in CHAT_ROLES] == [
        item for item in before.mappings if item.role in CHAT_ROLES
    ]
    stale = custom_input(current, "chat", expected_mapping_revisions={})
    with pytest.raises(BusinessError) as failure:
        service.create_custom_provider(session.token, str(uuid4()), stale)
    assert failure.value.code == "stale_version"
    assert service.configuration(session.token) == current


def test_custom_provider_api_validates_category_consent_and_nested_secret_without_echo(
    session, presets
):
    service, settings = presets
    body = custom_input(service.configuration(session.token), "chat").model_dump(mode="json")
    body["connection"]["api_key"] = "offline-custom-provider-secret"
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
        for invalid in (
            {**body, "group": "material"},
            {**body, "allow_private_material": False},
            {**body, "connection": {**body["connection"], "api_key": "invalid secret with spaces"}},
        ):
            response = client.post("/v1/model-providers/custom", headers=headers, json=invalid)
            assert response.status_code == 422
            assert "offline-custom-provider-secret" not in response.text
            assert "invalid secret with spaces" not in response.text
        assert not service.configuration(session.token).connections
        response = client.post("/v1/model-providers/custom", headers=headers, json=body)
        assert response.status_code == 201 and "offline-custom-provider-secret" not in response.text
