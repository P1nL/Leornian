import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.model_tests import ModelTestWorkflow
from leornian.entrypoints.api import create_app
from leornian.platform.config import Settings
from leornian.platform.model_contracts import (
    ModelConnectionInput,
    ModelConnectionPatch,
    ModelConnectionTestInput,
    ModelProfileInput,
    ModelProfilePatch,
    ModelRoleAssignmentInput,
)
from leornian.platform.models import UserModels
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def model_assignment_setup(database, session):
    settings = Settings(database_url=database.url, model_configuration_mode="user")
    service = ModelConfigurationWorkflow(database, settings)
    connection = service.create_connection(
        session.token,
        str(uuid4()),
        ModelConnectionInput(
            label="Owned model connection",
            protocol="chat_completions",
            base_url="https://models.example.org/v1",
            region="custom",
            enabled=True,
            api_key="offline-assignment-credential",
        ),
    )
    data = ModelProfileInput(
        label="Allowed teaching roles",
        connection_id=connection.id,
        model="owned-chat",
        operation="chat",
        roles=["tutor.v1", "material_review.v1"],
        context_tokens=131072,
        max_output_tokens=16384,
        enabled=True,
    )
    return service, settings, connection, data


def assignment(profile, mapping_revision):
    return ModelRoleAssignmentInput(
        profile_id=profile.id,
        expected_profile_revision=profile.revision,
        expected_mapping_revision=mapping_revision,
    )


def mappings(service, token):
    return {item.role: item for item in service.configuration(token).mappings}


def test_preparing_a_model_and_assigning_one_role_are_separate(
    database, session, model_assignment_setup
):
    service, settings, _, data = model_assignment_setup
    profile = service.save_profile(
        session.token, str(uuid4()), data, assign_roles=False
    )
    configuration = service.configuration(session.token)
    assert configuration.capabilities == [
        "explicit-role-assignment.v1", "provider-presets.v1",
        "provider-presets.v2", "provider-presets.v3",
    ]
    assert configuration.profiles == [profile] and configuration.mappings == []
    assert not profile.allow_private_material

    selected = service.assign_role(session.token, "tutor.v1", assignment(profile, 0))
    assert selected.profile_id == profile.id and selected.revision == 1
    assert set(mappings(service, session.token)) == {"tutor.v1"}
    assert service.configuration(session.token).profiles == [profile]
    with database.transaction(snapshot=True) as db:
        store = UserModels(db, settings)
        bound = store.binding(session.actor, "tutor.v1", require_private=False)
        assert bound["model"] == data.model
        with pytest.raises(BusinessError) as error:
            store.binding(session.actor, "tutor.v1")
    assert error.value.code == "model_unavailable"


def test_profile_creation_preserves_legacy_receipts_and_separates_assignment_mode(
    database, session, model_assignment_setup
):
    service, _, _, data = model_assignment_setup
    legacy_key, separate_key = str(uuid4()), str(uuid4())
    legacy = service.save_profile(session.token, legacy_key, data)
    assert service.save_profile(session.token, legacy_key, data) == legacy
    assert {item.profile_id for item in mappings(service, session.token).values()} == {legacy.id}
    separate = service.save_profile(
        session.token, separate_key, data, assign_roles=False
    )
    assert service.save_profile(
        session.token, separate_key, data, assign_roles=False
    ) == separate
    for key, mode in ((legacy_key, False), (separate_key, True)):
        with pytest.raises(BusinessError) as error:
            service.save_profile(session.token, key, data, assign_roles=mode)
        assert error.value.code == "idempotency_conflict"
    with database.transaction(snapshot=True) as db:
        commands = {
            row["command_key"]: row["request"]
            for row in db.execute(
                "SELECT command_key,request FROM platform.model_configuration_commands "
                "WHERE actor_id=%s AND command_key=ANY(%s)",
                (session.actor.id, [legacy_key, separate_key]),
            ).fetchall()
        }
    assert commands[legacy_key] == {"kind": "profile.create", **data.model_dump(mode="json")}
    assert commands[separate_key] == {**commands[legacy_key], "assign_roles": False}
    assert len(service.configuration(session.token).profiles) == 2
    assert {item.profile_id for item in mappings(service, session.token).values()} == {legacy.id}


def test_editing_a_profile_never_reclaims_another_profiles_current_role(
    database, session, model_assignment_setup
):
    service, settings, _, data = model_assignment_setup
    original = service.save_profile(session.token, str(uuid4()), data)
    replacement = service.save_profile(
        session.token,
        str(uuid4()),
        data.model_copy(update={"model": "other-chat"}),
        assign_roles=False,
    )
    selected = service.assign_role(session.token, "tutor.v1", assignment(replacement, 1))
    edited = service.save_profile(
        session.token,
        "",
        ModelProfilePatch(**data.model_dump(), expected_revision=1),
        original.id,
    )
    assert mappings(service, session.token)["tutor.v1"] == selected
    before = mappings(service, session.token)
    restricted = service.save_profile(
        session.token,
        "",
        ModelProfilePatch(
            **{
                **data.model_dump(),
                "expected_revision": edited.revision,
                "roles": ["tutor.v1"],
                "enabled": False,
            }
        ),
        original.id,
        assign_roles=False,
    )
    assert not restricted.enabled
    assert mappings(service, session.token) == before
    with database.transaction(snapshot=True) as db:
        store = UserModels(db, settings)
        assert store.binding(session.actor, "tutor.v1", require_private=False)["profile_id"] == str(
            replacement.id
        )
        with pytest.raises(BusinessError) as error:
            store.binding(session.actor, "material_review.v1", require_private=False)
    assert error.value.code == "model_unavailable"


def test_removing_a_profiles_allowed_role_disables_its_binding_without_reassignment(
    database, session, model_assignment_setup
):
    service, settings, _, data = model_assignment_setup
    original = service.save_profile(session.token, str(uuid4()), data)
    before = mappings(service, session.token)
    service.save_profile(
        session.token,
        "",
        ModelProfilePatch(
            **{
                **data.model_dump(),
                "expected_revision": original.revision,
                "roles": ["material_review.v1"],
            }
        ),
        original.id,
        assign_roles=False,
    )
    assert mappings(service, session.token) == before
    with database.transaction(snapshot=True) as db:
        store = UserModels(db, settings)
        with pytest.raises(BusinessError) as error:
            store.binding(session.actor, "tutor.v1", require_private=False)
        assert store.binding(
            session.actor, "material_review.v1", require_private=False
        )["profile_revision"] == 2
    assert error.value.code == "model_unavailable"


def test_assigning_a_role_checks_both_profile_and_mapping_revisions(
    session, model_assignment_setup
):
    service, _, _, data = model_assignment_setup
    original = service.save_profile(
        session.token, str(uuid4()), data, assign_roles=False
    )
    edited = service.save_profile(
        session.token,
        "",
        ModelProfilePatch(**data.model_dump(), expected_revision=original.revision),
        original.id,
        assign_roles=False,
    )
    with pytest.raises(BusinessError) as error:
        service.assign_role(session.token, "tutor.v1", assignment(original, 0))
    assert error.value.code == "stale_version"
    selected = service.assign_role(session.token, "tutor.v1", assignment(edited, 0))
    assert selected.revision == 1
    with pytest.raises(BusinessError) as error:
        service.assign_role(session.token, "tutor.v1", assignment(edited, 0))
    assert error.value.code == "stale_version"
    assert mappings(service, session.token)["tutor.v1"] == selected


def test_legacy_role_removal_cannot_reset_the_assignment_revision(
    session, model_assignment_setup
):
    service, _, _, data = model_assignment_setup
    original = service.save_profile(session.token, str(uuid4()), data)
    pending = service.save_profile(
        session.token,
        str(uuid4()),
        data.model_copy(update={"model": "pending-explicit-choice"}),
        assign_roles=False,
    )
    stale_choice = assignment(pending, 1)
    service.save_profile(
        session.token,
        "",
        ModelProfilePatch(
            **{
                **data.model_dump(),
                "expected_revision": original.revision,
                "roles": ["material_review.v1"],
            }
        ),
        original.id,
    )
    latest = service.save_profile(
        session.token,
        str(uuid4()),
        data.model_copy(update={"model": "latest-legacy-choice"}),
    )
    current = mappings(service, session.token)["tutor.v1"]
    assert current.profile_id == latest.id and current.revision == 2
    with pytest.raises(BusinessError) as error:
        service.assign_role(session.token, "tutor.v1", stale_choice)
    assert error.value.code == "stale_version"
    assert mappings(service, session.token)["tutor.v1"] == current


@pytest.mark.parametrize(
    "case",
    ["disabled_profile", "disabled_connection", "deleted_connection", "missing_credential", "role"],
)
def test_assignment_rejects_ineligible_profiles(
    case, database, session, model_assignment_setup
):
    service, _, connection, data = model_assignment_setup
    profile = service.save_profile(
        session.token,
        str(uuid4()),
        data.model_copy(update={"enabled": case != "disabled_profile"}),
        assign_roles=False,
    )
    if case == "disabled_connection":
        service.patch_connection(
            session.token, connection.id, ModelConnectionPatch(expected_revision=1, enabled=False)
        )
    if case == "deleted_connection":
        service.delete_connection(session.token, connection.id, 1)
    if case == "missing_credential":
        with database.transaction() as db:
            db.execute(
                "UPDATE platform.model_credentials SET ciphertext=NULL WHERE connection_id=%s",
                (connection.id,),
            )
    with pytest.raises(BusinessError) as error:
        service.assign_role(
            session.token,
            "embedding" if case == "role" else "tutor.v1",
            assignment(profile, 0),
        )
    assert error.value.code == "precondition_failed"
    assert mappings(service, session.token) == {}


def test_assignment_cannot_use_another_owners_profile(
    session, workflow, model_assignment_setup
):
    service, _, _, data = model_assignment_setup
    profile = service.save_profile(
        session.token, str(uuid4()), data, assign_roles=False
    )
    other = workflow.create_session("Separate assignment owner")
    with pytest.raises(BusinessError) as error:
        service.assign_role(other.token, "tutor.v1", assignment(profile, 0))
    assert error.value.code == "not_found"
    assert mappings(service, other.token) == {}


def test_concurrent_assignment_preserves_the_first_accepted_mapping(
    session, model_assignment_setup
):
    service, _, _, data = model_assignment_setup
    profiles = [
        service.save_profile(
            session.token,
            str(uuid4()),
            data.model_copy(update={"model": f"candidate-{number}"}),
            assign_roles=False,
        )
        for number in range(2)
    ]

    def assign(profile):
        try:
            return service.assign_role(session.token, "tutor.v1", assignment(profile, 0))
        except BusinessError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(assign, profiles))
    assert results.count("stale_version") == 1
    accepted = next(result for result in results if result != "stale_version")
    assert accepted.revision == 1
    assert mappings(service, session.token)["tutor.v1"] == accepted


def test_switching_a_role_preserves_the_original_unknown_call(
    database, session, model_assignment_setup, monkeypatch
):
    service, settings, connection, data = model_assignment_setup
    original = service.save_profile(session.token, str(uuid4()), data)
    tests = ModelTestWorkflow(database, settings)
    probe = tests.submit(
        session.token,
        connection.id,
        str(uuid4()),
        ModelConnectionTestInput(
            expected_connection_revision=connection.revision,
            profile_id=original.id,
            allow_billable=True,
        ),
    )
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination", lambda *args: "1.1.1.1"
    )
    sent = []

    def timeout(request):
        sent.append(request)
        raise httpx.ReadTimeout("Offline assignment probe lost the receipt")

    tests.execute(probe.id, httpx.MockTransport(timeout))
    assert tests.get(session.token, probe.id).status == "unknown"
    with database.transaction(snapshot=True) as db:
        fact = db.execute(
            "SELECT id,status,request,applied FROM runtime.external_calls WHERE operation_ref=%s",
            (probe.id,),
        ).fetchone()
        frozen = UserModels(db, settings).binding(
            session.actor, "tutor.v1", require_private=False
        )
    replacement = service.save_profile(
        session.token,
        str(uuid4()),
        data.model_copy(update={"model": "new-current-chat"}),
        assign_roles=False,
    )
    service.assign_role(session.token, "tutor.v1", assignment(replacement, 1))
    tests.execute(probe.id, httpx.MockTransport(timeout))
    assert tests.get(session.token, probe.id).status == "unknown"
    assert len(sent) == 1
    with database.transaction(snapshot=True) as db:
        assert db.execute(
            "SELECT id,status,request,applied FROM runtime.external_calls WHERE operation_ref=%s",
            (probe.id,),
        ).fetchone() == fact
        with pytest.raises(BusinessError) as error:
            UserModels(db, settings).validate_binding(
                session.actor, frozen, require_private=False
            )
    assert error.value.code == "model_unavailable"


@pytest.fixture
def unassigned_probe(database, session, model_assignment_setup, monkeypatch):
    service, settings, connection, data = model_assignment_setup
    profile = service.save_profile(
        session.token, str(uuid4()), data, assign_roles=False
    )
    tests = ModelTestWorkflow(database, settings)
    probe = tests.submit(
        session.token,
        connection.id,
        str(uuid4()),
        ModelConnectionTestInput(
            expected_connection_revision=connection.revision,
            profile_id=profile.id,
            allow_billable=True,
        ),
    )
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination", lambda *args: "1.1.1.1"
    )
    return service, settings, connection, data, profile, tests, probe


def chat_probe_response():
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": '{"ok":true}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        },
    )


def test_an_unassigned_model_can_be_explicitly_tested_without_material_permission(
    database, session, unassigned_probe
):
    service, _, _, _, profile, tests, probe = unassigned_probe
    sent = []

    def receive(request):
        sent.append(json.loads(request.content))
        return chat_probe_response()

    tests.execute(probe.id, httpx.MockTransport(receive))
    tests.execute(probe.id, httpx.MockTransport(receive))
    assert tests.get(session.token, probe.id).status == "succeeded"
    assert len(sent) == 1 and sent[0]["model"] == profile.model
    assert sent[0]["messages"][-1]["content"] == 'Return exactly the JSON object {"ok": true}.'
    assert mappings(service, session.token) == {}
    assert not service.configuration(session.token).profiles[0].allow_private_material
    with database.transaction(snapshot=True) as db:
        call = db.execute(
            "SELECT status,applied,run_id,context_manifest FROM runtime.external_calls "
            "WHERE operation_ref=%s",
            (probe.id,),
        ).fetchone()
    assert call["status"] == "result_recorded" and call["applied"] and call["run_id"] is None
    assert call["context_manifest"]["model_binding"]["purpose"] == "connection-probe.v1"
    assert "role" not in call["context_manifest"]["model_binding"]


def test_an_unassigned_dedicated_model_uses_its_explicit_synthetic_probe(
    database, session, model_assignment_setup, monkeypatch
):
    service, settings, connection, _ = model_assignment_setup
    profile = service.save_profile(
        session.token,
        str(uuid4()),
        ModelProfileInput(
            label="Unassigned embedding",
            connection_id=connection.id,
            model="owned-embedding",
            operation="embedding",
            roles=["embedding"],
            embedding_dimensions=4,
            enabled=True,
        ),
        assign_roles=False,
    )
    tests = ModelTestWorkflow(database, settings)
    probe = tests.submit(
        session.token,
        connection.id,
        str(uuid4()),
        ModelConnectionTestInput(
            expected_connection_revision=connection.revision,
            profile_id=profile.id,
            allow_billable=True,
        ),
    )
    monkeypatch.setattr(
        "leornian.platform.model_probes.resolve_destination", lambda *args: "1.1.1.1"
    )
    sent = []

    def receive(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [0.1, 0.2, 0.3, 0.4]}
                    for index in range(2)
                ],
                "usage": {"total_tokens": 8},
            },
        )

    tests.execute(probe.id, httpx.MockTransport(receive))
    result = tests.get(session.token, probe.id)
    assert result.status == "succeeded"
    assert result.result["protocol"] == "material-embedding-roundtrip.v1"
    assert len(sent) == 1 and "messages" not in sent[0]
    assert mappings(service, session.token) == {}


@pytest.mark.parametrize("changed", ["profile", "credential", "session"])
def test_a_queued_unassigned_probe_revalidates_original_configuration_and_session(
    changed, database, session, unassigned_probe
):
    service, _, connection, data, profile, tests, probe = unassigned_probe
    if changed == "profile":
        service.save_profile(
            session.token,
            "",
            ModelProfilePatch(**data.model_dump(), expected_revision=profile.revision),
            profile.id,
            assign_roles=False,
        )
    elif changed == "credential":
        service.patch_connection(
            session.token,
            connection.id,
            ModelConnectionPatch(expected_revision=1, api_key="rotated-offline-probe-credential"),
        )
    else:
        with database.transaction() as db:
            db.execute(
                "UPDATE identity.sessions SET revoked_at=now() WHERE actor_id=%s",
                (session.actor.id,),
            )

    def unexpected(_):
        pytest.fail("A changed queued probe must not dispatch.")

    tests.execute(probe.id, httpx.MockTransport(unexpected))
    with database.transaction(snapshot=True) as db:
        assert db.execute(
            "SELECT status FROM platform.model_connection_tests WHERE id=%s",
            (probe.id,),
        ).fetchone()["status"] == "failed"
        assert db.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE operation_ref=%s",
            (probe.id,),
        ).fetchone() == {"status": "not_sent", "applied": False}


@pytest.mark.parametrize("changed", ["profile", "connection", "session"])
def test_an_unassigned_probes_late_receipt_is_recorded_without_application(
    changed, database, session, unassigned_probe
):
    service, _, connection, data, profile, tests, probe = unassigned_probe
    sent = []

    def receive(request):
        sent.append(request)
        if changed == "profile":
            service.save_profile(
                session.token,
                "",
                ModelProfilePatch(**data.model_dump(), expected_revision=profile.revision),
                profile.id,
                assign_roles=False,
            )
        elif changed == "connection":
            service.delete_connection(session.token, connection.id, 1)
        else:
            with database.transaction() as db:
                db.execute(
                    "UPDATE identity.sessions SET revoked_at=now() WHERE actor_id=%s",
                    (session.actor.id,),
                )
        return chat_probe_response()

    tests.execute(probe.id, httpx.MockTransport(receive))
    tests.execute(probe.id, httpx.MockTransport(receive))
    assert len(sent) == 1
    with database.transaction(snapshot=True) as db:
        assert db.execute(
            "SELECT status,error_code FROM platform.model_connection_tests WHERE id=%s",
            (probe.id,),
        ).fetchone() == {
            "status": "cancelled",
            "error_code": "configuration_or_session_changed",
        }
        call = db.execute(
            "SELECT status,applied,response_body FROM runtime.external_calls "
            "WHERE operation_ref=%s",
            (probe.id,),
        ).fetchone()
    assert call["status"] == "result_recorded" and not call["applied"]
    assert json.loads(call["response_body"])["choices"][0]["message"]["content"] == '{"ok":true}'


def test_queued_legacy_role_bound_probes_keep_their_original_validation(
    session, model_assignment_setup, monkeypatch
):
    service, settings, connection, data = model_assignment_setup
    profile = service.save_profile(session.token, str(uuid4()), data)
    tests = ModelTestWorkflow(service.database, settings)
    with monkeypatch.context() as legacy:
        legacy.setattr(
            UserModels,
            "probe_binding",
            lambda store, actor, _profile_id: store.binding(
                actor, data.roles[0], require_private=False
            ),
        )
        probe = tests.submit(
            session.token,
            connection.id,
            str(uuid4()),
            ModelConnectionTestInput(
                expected_connection_revision=connection.revision,
                profile_id=profile.id,
                allow_billable=True,
            ),
        )
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination", lambda *args: "1.1.1.1"
    )
    tests.execute(probe.id, httpx.MockTransport(lambda _: chat_probe_response()))
    assert tests.get(session.token, probe.id).status == "succeeded"


def test_http_model_storage_does_not_assign_roles_when_explicitly_requested(
    session, model_assignment_setup
):
    _, settings, _, data = model_assignment_setup
    client = TestClient(create_app(settings))
    headers = {
        "Authorization": f"Bearer {session.token}",
        "Idempotency-Key": str(uuid4()),
    }
    created = client.post(
        "/v1/model-profiles?assign_roles=false",
        headers=headers,
        json=data.model_dump(mode="json"),
    )
    assert created.status_code == 201
    profile = created.json()
    changed = client.patch(
        f"/v1/model-profiles/{profile['id']}?assign_roles=false",
        headers=headers,
        json={
            **data.model_dump(mode="json"),
            "label": "Revised without assignment",
            "expected_revision": 1,
        },
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2
    configuration = client.get("/v1/model-configuration", headers=headers).json()
    assert configuration["capabilities"] == [
        "explicit-role-assignment.v1", "provider-presets.v1",
        "provider-presets.v2", "provider-presets.v3",
    ]
    assert len(configuration["profiles"]) == 1 and configuration["mappings"] == []
    conflict = client.post(
        "/v1/model-profiles", headers=headers, json=data.model_dump(mode="json")
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_http_role_assignment_uses_current_profile_and_mapping_revisions(
    session, model_assignment_setup
):
    service, settings, _, data = model_assignment_setup
    client = TestClient(create_app(settings))
    headers = {"Authorization": f"Bearer {session.token}"}
    first, second = [
        service.save_profile(
            session.token,
            str(uuid4()),
            data.model_copy(update={"model": f"http-choice-{number}"}),
            assign_roles=False,
        )
        for number in range(2)
    ]
    body = assignment(first, 0).model_dump(mode="json")
    path = "/v1/model-role-mappings/tutor.v1"
    selected = client.put(path, headers=headers, json=body)
    assert selected.status_code == 200
    assert selected.json() == {"role": "tutor.v1", "profile_id": str(first.id), "revision": 1}
    stale = client.put(path, headers=headers, json=body)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    changed = client.put(
        path, headers=headers, json=assignment(second, 1).model_dump(mode="json")
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2
    stale_profile = client.put(
        path,
        headers=headers,
        json={
            **assignment(first, 2).model_dump(mode="json"),
            "expected_profile_revision": 2,
        },
    )
    assert stale_profile.status_code == 409
    assert stale_profile.json()["code"] == "stale_version"
    invalid_role = client.put(
        "/v1/model-role-mappings/unsupported-role", headers=headers, json=body
    )
    assert invalid_role.status_code == 422
    current = client.get("/v1/model-configuration", headers=headers).json()["mappings"]
    assert current == [{"role": "tutor.v1", "profile_id": str(second.id), "revision": 2}]
