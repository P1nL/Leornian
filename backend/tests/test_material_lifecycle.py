from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.materials import MaterialWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.contracts import AdmitSource, SourceInput, SourceRevision
from leornian.modules.knowledge.material_contracts import (
    DocumentPermissionAction,
    TextMaterialImport,
)
from leornian.modules.knowledge.materials import digest, parse_blocks
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.learning.materials import review_due_at
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError

ORIGINAL = (
    "# Iteration\n\n中文教材：items 是序列。\n\n"
    "```python\nfor x in items:\n    print(x)\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
)


@pytest.fixture
def material_setup(database, workflow, session):
    accepted = workflow.submit(session.token, str(uuid4()), GoalInput(title="Learn iteration"))
    with database.transaction() as connection:
        event_id = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (accepted.job_id,)
        ).fetchone()["event_id"]
    workflow.process_goal(event_id)
    goal = workflow.snapshot(session.token).goals[0]
    data = TextMaterialImport(
        goal_id=goal.id,
        title="Iteration",
        source_url="https://example.org/iteration",
        format="markdown",
        text=ORIGINAL,
        authorized_use=True,
        purposes=["reference", "teaching", "planning", "indexing"],
    )
    return MaterialWorkflow(database), goal, data


def test_exact_parser_preserves_code_tables_offsets_and_non_ascii():
    blocks = parse_blocks(ORIGINAL, True)
    assert [b["kind"] for b in blocks] == ["heading", "paragraph", "code", "table"]
    assert all(ORIGINAL[b["start"] : b["end"]] == b["text"] for b in blocks)
    assert "    print(x)" in blocks[2]["text"]
    assert blocks[2]["section_path"] == ["Iteration"]
    with pytest.raises(BusinessError):
        parse_blocks("```python\nprint(1)", True)


def test_review_defaults_cover_course_and_are_not_real_deadlines():
    now = datetime(2026, 11, 3, tzinfo=UTC)
    assert review_due_at(now) == now + timedelta(days=180)
    assert review_due_at(now, now + timedelta(days=400)) == now + timedelta(days=430)
    assert review_due_at(now, now - timedelta(days=100)) == now + timedelta(days=180)


def test_import_is_exact_append_only_and_actor_serialized(database, session, material_setup):
    service, _, data = material_setup
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.import_text(session.token, key, data), range(2)))
    version = results[0]
    assert version == results[1]
    assert version.content_digest == digest(ORIGINAL)
    assert version.permission.use_until is None and version.permission.retain_until is None
    assert version.processing_state == "parsed"
    page = service.blocks(session.token, version.document_id, 1, "reference", limit=2)
    rest = service.blocks(
        session.token, version.document_id, 1, "reference", after=page.next_after, limit=2
    )
    assert len(page.blocks) == len(rest.blocks) == 2 and rest.next_after is None
    assert all(
        block.ref.content_digest == digest(block.text) for block in page.blocks + rest.blocks
    )
    with pytest.raises(BusinessError, match="different content"):
        service.import_text(session.token, key, data.model_copy(update={"text": "Other"}))
    revised = data.model_copy(
        update={
            "document_id": version.document_id,
            "expected_revision": 1,
            "text": "New edition",
        }
    )
    second = service.import_text(session.token, str(uuid4()), revised)
    assert second.revision == 2
    assert service.version(session.token, version.document_id, 1) == version
    with database.transaction(snapshot=True) as connection:
        text = connection.execute(
            "SELECT original_text FROM knowledge.document_versions "
            "WHERE document_id=%s AND revision=1",
            (version.document_id,),
        ).fetchone()["original_text"]
    assert text == ORIGINAL


def test_binding_remains_pinned_after_new_edition_and_review_date(
    database, session, material_setup
):
    service, goal, data = material_setup
    version = service.import_text(session.token, str(uuid4()), data)
    page = service.blocks(session.token, version.document_id, 1, "teaching")
    binding_data = MaterialBindingInput(
        goal_id=goal.id,
        purpose="teaching",
        expected_binding_revision=0,
        refs=[block.ref for block in page.blocks],
        expected_completion_at=datetime.now(UTC) + timedelta(days=365),
    )
    key = str(uuid4())
    binding = service.bind(session.token, key, binding_data)
    assert service.bind(session.token, key, binding_data) == binding
    assert binding.review_due_at > datetime.now(UTC) + timedelta(days=394)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.documents SET next_check_at=now()-interval '1 year' WHERE id=%s",
            (version.document_id,),
        )
        connection.execute(
            "UPDATE learning.material_binding_revisions "
            "SET review_due_at=now()-interval '1 year' WHERE binding_id=%s",
            (binding.id,),
        )
    service.import_text(
        session.token,
        str(uuid4()),
        data.model_copy(
            update={
                "document_id": version.document_id,
                "expected_revision": 1,
                "text": "Changed meaning",
            }
        ),
    )
    bound = service.bound_blocks(session.token, binding.id, 1)
    assert [b.text for b in bound.blocks] == [b.text for b in page.blocks]
    assert all(b.ref.document_revision == 1 for b in bound.blocks)
    replacement = binding_data.model_copy(update={"expected_binding_revision": 1})
    changed = service.bind(session.token, str(uuid4()), replacement)
    assert changed.revision == 2
    assert service.binding(session.token, binding.id, 1).refs == binding.refs
    with pytest.raises(BusinessError) as error:
        service.bound_blocks(session.token, binding.id, 1)
    assert error.value.code == "stale_version"


def test_permission_goal_scope_and_locator_cannot_be_forged(
    database, workflow, session, material_setup
):
    service, goal, data = material_setup
    version = service.import_text(session.token, str(uuid4()), data)
    page = service.blocks(session.token, version.document_id, 1, "teaching")
    binding_data = MaterialBindingInput(
        goal_id=goal.id,
        purpose="teaching",
        expected_binding_revision=0,
        refs=[page.blocks[0].ref],
    )
    forged = binding_data.model_copy(
        update={
            "refs": [page.blocks[0].ref.model_copy(update={"content_digest": "0" * 64})],
        }
    )
    with pytest.raises(BusinessError) as error:
        service.bind(session.token, str(uuid4()), forged)
    assert error.value.code == "stale_version"
    with pytest.raises(BusinessError):
        service.blocks(session.token, version.document_id, 1, "item_review")
    other = workflow.create_session("Other owner")
    with pytest.raises(BusinessError) as error:
        service.blocks(other.token, version.document_id, 1, "reference")
    assert error.value.code == "not_found"
    binding_key = str(uuid4())
    binding = service.bind(session.token, binding_key, binding_data)
    service.revoke(
        session.token,
        version.document_id,
        1,
        DocumentPermissionAction(action="revoke", expected_revision=1),
    )
    with pytest.raises(BusinessError) as error:
        service.bound_blocks(session.token, binding.id, 1)
    assert error.value.code == "source_not_current"
    # Revocation affects current use, not the historical identity of this binding.
    assert service.binding(session.token, binding.id).refs == binding.refs
    assert service.bind(session.token, binding_key, binding_data).refs == binding.refs


def test_lifecycle_intervals_are_configurable_without_changing_permission(
    database, session, material_setup
):
    _, goal, data = material_setup
    service = MaterialWorkflow(
        database,
        Settings(
            material_check_days=5,
            material_review_days=270,
            material_completion_grace_days=45,
        ),
    )
    before = datetime.now(UTC)
    version = service.import_text(session.token, str(uuid4()), data)
    assert before + timedelta(days=4) < version.next_check_at < before + timedelta(days=6)
    refs = [
        block.ref
        for block in service.blocks(session.token, version.document_id, 1, "teaching").blocks
    ]
    binding = service.bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=goal.id,
            purpose="teaching",
            expected_binding_revision=0,
            refs=refs,
            expected_completion_at=before + timedelta(days=300),
        ),
    )
    assert binding.review_due_at == before + timedelta(days=345)
    assert version.permission.use_until is None and version.permission.retain_until is None


@pytest.mark.parametrize("column", ["use_until", "retain_until"])
def test_real_deadlines_independently_stop_use(column, database, session, material_setup):
    service, _, data = material_setup
    version = service.import_text(session.token, str(uuid4()), data)
    with database.transaction() as connection:
        # Column names are this test's closed parameter list, never user input.
        connection.execute(
            f"UPDATE knowledge.document_permissions SET {column}=now()-interval '1 second' "
            "WHERE document_id=%s",
            (version.document_id,),
        )
    with pytest.raises(BusinessError) as error:
        service.blocks(session.token, version.document_id, 1, "reference")
    assert error.value.code == "source_not_current"


def test_legacy_mapping_preserves_original_expiry_revision_and_revocation(
    database, session, material_setup
):
    service, goal, _ = material_setup
    old = KnowledgeWorkflow(database)
    source_data = SourceInput(
        title="Old excerpt",
        source_url="https://example.org/old",
        excerpt="Old note",
    )
    source = old.create(session.token, goal.id, str(uuid4()), source_data)
    expiry = datetime.now(UTC) + timedelta(days=7)
    old.admit(session.token, source.id, AdmitSource(expected_revision=1, valid_until=expiry))
    version = service.import_legacy(session.token, source.id, 1)
    assert version.permission.use_until == expiry
    assert version.provenance == "legacy_excerpt"
    assert service.import_legacy(session.token, source.id, 1) == version
    old.revise(
        session.token,
        source.id,
        SourceRevision(**source_data.model_dump(), expected_revision=1).model_copy(
            update={"excerpt": "A new original"}
        ),
    )
    with pytest.raises(BusinessError) as error:
        service.blocks(session.token, version.document_id, 1, "reference")
    assert error.value.code == "source_not_current"
    assert service.version(session.token, version.document_id, 1).permission.use_until == expiry


def test_http_exact_material_contract_is_read_only_on_get(
    database, workflow, session, material_setup
):
    _, _, data = material_setup
    client = TestClient(create_app(Settings(database_url=database.url)))
    headers = {"Authorization": f"Bearer {session.token}", "Idempotency-Key": str(uuid4())}
    response = client.post("/v1/material-texts", headers=headers, json=data.model_dump(mode="json"))
    assert response.status_code == 201
    document_id = response.json()["document_id"]
    url = f"/v1/documents/{document_id}/versions/1/blocks"
    first = client.get(url, headers=headers)
    assert first.status_code == 200 and len(first.json()["blocks"]) == 4
    assert client.get(url, headers=headers).json() == first.json()
    foreign = workflow.create_session("Other identity")
    assert client.get(url, headers={"Authorization": f"Bearer {foreign.token}"}).status_code == 404
    assert (
        client.post(
            "/v1/material-texts",
            headers=headers,
            json={**data.model_dump(mode="json"), "actor_id": str(uuid4())},
        ).status_code
        == 422
    )
    with database.transaction(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM runtime.runs WHERE actor_id=%s", (session.actor.id,)
            ).fetchone()["n"]
            == 0
        )


def test_material_input_requires_real_permission_and_aware_dates():
    base = {
        "goal_id": str(uuid4()),
        "title": "A",
        "source_url": "https://example.org",
        "text": "A",
        "authorized_use": True,
        "purposes": ["reference"],
    }
    for change in (
        {"authorized_use": False},
        {"use_until": "2027-01-01"},
        {"purposes": ["reference", "reference"]},
        {"text": " \n "},
    ):
        with pytest.raises(ValidationError):
            TextMaterialImport(**{**base, **change})
