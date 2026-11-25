from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup

from leornian.bootstrap.material_changes import MaterialChangeWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.change_contracts import MaterialChangeInput
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


def bound(session, material_setup, *, select=None):
    service, goal, text = material_setup
    version = service.import_text(session.token, str(uuid4()), text)
    blocks = service.blocks(session.token, version.document_id, 1, "teaching").blocks
    refs = [b.ref for b in blocks] if select is None else select(blocks)
    binding = service.bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=goal.id, purpose="teaching", expected_binding_revision=0, refs=refs
        ),
    )
    return service, text, version, binding


def change_input(binding, version):
    return MaterialChangeInput(
        binding_id=binding.id,
        expected_binding_revision=binding.revision,
        document_id=version.document_id,
        candidate_revision=version.revision,
    )


def revise(session, service, text, version, content):
    return service.import_text(
        session.token,
        str(uuid4()),
        text.model_copy(
            update={
                "document_id": version.document_id,
                "expected_revision": version.revision,
                "text": content,
            }
        ),
    )


def test_cumulative_comparison_keeps_old_binding_and_deduplicates(
    database, session, material_setup
):
    service, text, v1, binding = bound(session, material_setup)
    v2 = revise(session, service, text, v1, ORIGINAL.replace("print(x)", "print(x + 1)"))
    v3 = revise(session, service, text, v2, ORIGINAL.replace("print(x)", "print(x + 2)"))
    changes = MaterialChangeWorkflow(database)
    data = change_input(binding, v3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(
            pool.map(lambda _: changes.compare(session.token, str(uuid4()), data), range(2))
        )
    report = reports[0]
    assert report == reports[1]
    assert (report.baseline_revision, report.candidate_revision) == (1, 3)
    assert report.classification == "uncertain" and report.state == "waiting_dependency"
    assert report.semantic_quality == "not_certified"
    assert len(report.unchanged_blocks) == 3
    assert len(report.affected_refs) == 1
    assert len(report.affected_context_refs) == 3
    assert len(report.added_or_changed_blocks) == len(report.removed_or_changed_blocks) == 1
    assert service.binding(session.token, binding.id) == binding
    assert (
        service.bound_blocks(session.token, binding.id, 1)
        .blocks[2]
        .text.endswith("print(x)\n```\n")
    )
    with database.transaction(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM knowledge.material_change_checks WHERE actor_id=%s",
                (session.actor.id,),
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM runtime.external_calls WHERE actor_id=%s",
                (session.actor.id,),
            ).fetchone()["n"]
            == 0
        )


def test_unchanged_and_partial_span_relocation_are_exact(database, session, material_setup):
    from leornian.modules.knowledge.material_contracts import MaterialSpan
    from leornian.modules.knowledge.materials import digest

    def selected(blocks):
        block = blocks[2]
        start = block.text.index("print(x)")
        return [
            block.ref.model_copy(
                update={
                    "span": MaterialSpan(
                        start=block.ref.span.start + start, end=block.ref.span.start + start + 8
                    ),
                    "content_digest": digest("print(x)"),
                }
            )
        ]

    service, text, v1, binding = bound(session, material_setup, select=selected)
    v2 = revise(session, service, text, v1, ORIGINAL)
    changes = MaterialChangeWorkflow(database)
    unchanged = changes.compare(session.token, str(uuid4()), change_input(binding, v2))
    assert unchanged.state == "no_content_change" and unchanged.reason_code is None
    v3 = revise(session, service, text, v2, ORIGINAL.replace("中文教材：", "教材原文：中文教材："))
    report = changes.compare(session.token, str(uuid4()), change_input(binding, v3))
    assert not report.affected_refs
    assert report.affected_context_refs == binding.refs
    relocated = report.relocated_refs[0]
    assert relocated.candidate.span.start > relocated.baseline.span.start
    assert relocated.candidate.selection_id is None
    with database.transaction() as connection:
        from leornian.modules.knowledge.materials import Materials

        blocks = Materials(connection).read_refs(
            session.actor, binding.goal_id, binding.purpose, [relocated.candidate]
        )
    assert blocks[0].text == "print(x)"


def test_change_check_permission_scope_stale_and_http_replay(
    database, workflow, session, material_setup
):
    service, text, v1, binding = bound(session, material_setup)
    v2 = revise(session, service, text, v1, ORIGINAL.replace("| 1 |", "| 2 |"))
    data = change_input(binding, v2)
    key = str(uuid4())
    with TestClient(create_app(Settings(database_url=database.url))) as client:
        headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": key}
        response = client.post(
            "/v1/material-change-checks", headers=headers, json=data.model_dump(mode="json")
        )
        assert response.status_code == 201, response.text
        report = response.json()
        assert (
            client.get("/v1/material-change-checks/" + report["id"], headers=headers).json()
            == report
        )
        other = workflow.create_session("Another learner")
        assert (
            client.get(
                "/v1/material-change-checks/" + report["id"],
                headers={"Authorization": "Bearer " + other.token},
            ).status_code
            == 404
        )
    changes = MaterialChangeWorkflow(database)
    service.bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=binding.goal_id,
            purpose="teaching",
            expected_binding_revision=1,
            refs=binding.refs,
        ),
    )
    assert str(changes.compare(session.token, key, data).id) == report["id"]
    with pytest.raises(BusinessError) as error:
        changes.compare(session.token, str(uuid4()), data)
    assert error.value.code == "stale_version"
    service.revoke(
        session.token,
        v2.document_id,
        v2.revision,
        DocumentPermissionAction(expected_revision=1, action="revoke"),
    )
    with pytest.raises(BusinessError) as error:
        changes.compare(session.token, key, data)
    assert error.value.code == "source_not_current"
