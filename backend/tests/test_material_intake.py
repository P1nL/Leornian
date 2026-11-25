from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup

from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.identity.application import Identity
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput, MaterialTextJobInput
from leornian.modules.knowledge.materials import Materials
from leornian.platform.config import Settings
from leornian.platform.relay import relay_materials_once
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def intake_setup(database, session, material_setup):
    _, goal, text = material_setup
    service = MaterialIntakeWorkflow(database, Settings(database_url=database.url))
    data = MaterialDemandInput(
        goal_id=goal.id,
        purpose="teaching",
        language="Python",
        language_version="3.14",
        required_facets=["Iteration over a sequence"],
        optional_facets=["enumerate"],
    )
    demand = service.create_demand(session.token, str(uuid4()), data)
    request = MaterialTextJobInput(expected_demand_revision=1, material=text)
    return service, demand, request, data


def test_demand_is_private_exact_and_replayable(database, workflow, session, intake_setup):
    service, _, _, data = intake_setup
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        demands = list(
            executor.map(lambda _: service.create_demand(session.token, key, data), range(2))
        )
    assert demands[0] == demands[1]
    assert demands[0].scope == "private"
    assert demands[0].language_version == "3.14"
    assert demands[0].consumer_ref == "learner-material-demand:" + str(demands[0].id)
    with pytest.raises(BusinessError) as error:
        service.create_demand(
            session.token, key, data.model_copy(update={"required_facets": ["Different goal"]})
        )
    assert error.value.code == "idempotency_conflict"
    other = workflow.create_session("Other material owner")
    with pytest.raises(BusinessError):
        service.demand(other.token, demands[0].id)
    page = service.demands(session.token, data.goal_id, limit=1)
    rest = service.demands(session.token, data.goal_id, before=page[0].id, limit=1)
    assert len(page) == len(rest) == 1 and page[0].id != rest[0].id


def test_demand_rejects_ambiguous_facets_and_scope(intake_setup):
    _, _, _, data = intake_setup
    for update in (
        {"optional_facets": data.required_facets},
        {"language": "   "},
        {"framework_version": "1.2"},
        {"plan_id": uuid4()},
        {"required_facets": ["same", "same"]},
    ):
        with pytest.raises(ValidationError):
            MaterialDemandInput(**{**data.model_dump(), **update})


def test_text_preparation_deduplicates_and_is_not_a_corpus_release(
    database, session, material_setup, intake_setup
):
    materials, _, _ = material_setup
    service, demand, request, _ = intake_setup
    job = service.submit_text(session.token, demand.id, str(uuid4()), request)
    assert job.state == "queued" and job.document_id is None
    assert len(job.steps) == 1 and ORIGINAL not in job.model_dump_json()
    same = service.submit_text(session.token, demand.id, str(uuid4()), request)
    assert same.id == job.id
    service.execute(job.id)
    prepared = service.job(session.token, job.id)
    assert prepared.state == "waiting_dependency" and prepared.phase == "indexing"
    assert prepared.reason_code == "indexing_pending"
    assert [s.state for s in prepared.steps] == ["queued", "parsing", "waiting_dependency"]
    version = materials.version(session.token, prepared.document_id, prepared.document_revision)
    assert version.processing_state == "parsed"
    assert service.demand(session.token, demand.id).status == "open"
    blocks = materials.blocks(session.token, version.document_id, version.revision, "teaching")
    assert "    print(x)" in next(b.text for b in blocks.blocks if b.kind == "code")
    with database.transaction(snapshot=True) as db:
        row = db.execute(
            "SELECT input_text,request_identity FROM knowledge.material_jobs WHERE id=%s", (job.id,)
        ).fetchone()
        assert row["input_text"] is None and "text" not in row["request_identity"]["material"]
    service.execute(job.id)
    waiting = service.job(session.token, job.id)
    assert waiting.state == "waiting_config"
    assert waiting.reason_code == "model_unavailable"
    assert waiting.document_id == prepared.document_id


def test_same_command_cannot_change_source_or_demand(session, intake_setup):
    service, demand, request, data = intake_setup
    key = str(uuid4())
    service.submit_text(session.token, demand.id, key, request)
    changed = request.model_copy(
        update={"material": request.material.model_copy(update={"text": "Different source"})}
    )
    with pytest.raises(BusinessError) as error:
        service.submit_text(session.token, demand.id, key, changed)
    assert error.value.code == "idempotency_conflict"
    other = service.create_demand(session.token, str(uuid4()), data)
    with pytest.raises(BusinessError):
        service.submit_text(session.token, other.id, key, request)


def test_preparation_rechecks_scope_and_real_deadlines(workflow, session, intake_setup):
    service, demand, request, _ = intake_setup
    other = workflow.create_session("Foreign candidate")
    with pytest.raises(BusinessError):
        service.submit_text(other.token, demand.id, str(uuid4()), request)
    for changed in (
        request.model_copy(update={"expected_demand_revision": 2}),
        request.model_copy(
            update={"material": request.material.model_copy(update={"goal_id": uuid4()})}
        ),
        request.model_copy(
            update={"material": request.material.model_copy(update={"purposes": ["reference"]})}
        ),
        request.model_copy(
            update={
                "material": request.material.model_copy(
                    update={
                        "use_until": datetime.now(UTC) - timedelta(seconds=1),
                    }
                )
            }
        ),
    ):
        with pytest.raises(BusinessError):
            service.submit_text(session.token, demand.id, str(uuid4()), changed)


def test_markdown_failure_changes_parser_without_rewriting_original(
    database, session, material_setup, intake_setup
):
    materials, _, _ = material_setup
    service, demand, request, _ = intake_setup
    original = "```python\nfor value in values:\n    print(value)\n"
    request = request.model_copy(
        update={
            "material": request.material.model_copy(update={"text": original}),
        }
    )
    with pytest.raises(BusinessError):
        materials.import_text(session.token, str(uuid4()), request.material)
    job = service.submit_text(session.token, demand.id, str(uuid4()), request)
    service.execute(job.id)
    result = service.job(session.token, job.id)
    assert result.phase == "checking" and result.issues == ["markdown_fence_incomplete"]
    version = materials.version(session.token, result.document_id, result.document_revision)
    assert version.parser_version == "exact-text.markdown-fallback.v1"
    with database.transaction(snapshot=True) as db:
        stored = db.execute(
            "SELECT original_text FROM knowledge.document_versions WHERE document_id=%s",
            (result.document_id,),
        ).fetchone()
        assert stored["original_text"] == original


def test_worker_loss_resumes_only_deterministic_parsing(
    database, session, intake_setup, monkeypatch
):
    service, demand, request, _ = intake_setup
    job = service.submit_text(session.token, demand.id, str(uuid4()), request)
    with monkeypatch.context() as patch:

        def crash(*_args, **_kwargs):
            raise RuntimeError("test worker loss before parse commit")

        patch.setattr(Materials, "import_text", crash)
        with pytest.raises(RuntimeError):
            service.execute(job.id)
    assert service.job(session.token, job.id).state == "parsing"
    service.execute(job.id)
    assert service.job(session.token, job.id).state == "parsing"
    with database.transaction() as db:
        db.execute(
            "UPDATE knowledge.material_jobs SET lease_until=now()-interval '1 second' WHERE id=%s",
            (job.id,),
        )
    MaterialIntakeWorkflow(database, service.settings).execute(job.id)
    result = service.job(session.token, job.id)
    assert result.document_id is not None
    assert [s.state for s in result.steps].count("parsing") == 2


def test_cancel_fences_claimed_result_and_preserves_steps(
    database, session, intake_setup, monkeypatch
):
    service, demand, request, _ = intake_setup
    key = str(uuid4())
    job = service.submit_text(session.token, demand.id, key, request)
    claimed = service._claim(job.id)
    cancelled = service.cancel(session.token, job.id)
    assert cancelled.state == "cancelled" and len(cancelled.steps) == 3
    monkeypatch.setattr(service, "_claim", lambda _: claimed)
    service.execute(job.id)
    assert service.job(session.token, job.id).document_id is None
    assert service.submit_text(session.token, demand.id, key, request).state == "cancelled"
    with database.transaction(snapshot=True) as db:
        assert (
            db.execute(
                "SELECT input_text FROM knowledge.material_jobs WHERE id=%s", (job.id,)
            ).fetchone()["input_text"]
            is None
        )


def test_old_lease_cannot_replace_new_workers_state(database, session, intake_setup):
    service, demand, request, _ = intake_setup
    job = service.submit_text(session.token, demand.id, str(uuid4()), request)
    _, _, old = service._claim(job.id)
    with database.transaction() as db:
        db.execute(
            "UPDATE knowledge.material_jobs SET lease_until=now()-interval '1 second' WHERE id=%s",
            (job.id,),
        )
    _, _, current = service._claim(job.id)
    service._wait(job.id, "source_not_current", old)
    with database.transaction(snapshot=True) as db:
        row = db.execute(
            "SELECT state,lease_token,input_text FROM knowledge.material_jobs WHERE id=%s",
            (job.id,),
        ).fetchone()
    assert row["state"] == "parsing" and row["lease_token"] == current
    assert row["input_text"] == request.material.text
    service.cancel(session.token, job.id)


def test_expired_retention_clears_queued_input_not_history(database, session, intake_setup):
    service, demand, request, _ = intake_setup
    job = service.submit_text(session.token, demand.id, str(uuid4()), request)
    with database.transaction() as db:
        db.execute(
            "UPDATE knowledge.material_jobs SET retain_until=now()-interval '1 second' WHERE id=%s",
            (job.id,),
        )
    assert service.expire_retained_inputs() >= 1
    result = service.job(session.token, job.id)
    assert result.state == "cancelled" and result.reason_code == "material_retention_expired"
    assert len(result.steps) == 2
    service.execute(job.id)
    assert service.job(session.token, job.id).document_id is None


def test_revoked_session_prevents_parsing_and_discards_transient_text(
    database, session, intake_setup
):
    service, demand, request, _ = intake_setup
    job = service.submit_text(session.token, demand.id, str(uuid4()), request)
    with database.transaction() as db:
        db.execute(
            "UPDATE identity.sessions SET revoked_at=now() WHERE token_digest=%s",
            (Identity.digest(session.token),),
        )
    service.execute(job.id)
    with database.transaction(snapshot=True) as db:
        row = db.execute(
            "SELECT state,reason_code,input_text,document_id "
            "FROM knowledge.material_jobs WHERE id=%s",
            (job.id,),
        ).fetchone()
    assert row == {
        "state": "waiting_dependency",
        "reason_code": "unauthorized",
        "input_text": None,
        "document_id": None,
    }


def test_relay_filters_future_jobs_before_limiting(database, session, intake_setup):
    service, demand, request, _ = intake_setup
    first = service.submit_text(session.token, demand.id, str(uuid4()), request)
    with database.transaction() as db:
        db.execute(
            "UPDATE knowledge.material_jobs SET next_run_at=now()+interval '1 day' WHERE id=%s",
            (first.id,),
        )
    second = service.submit_text(
        session.token,
        demand.id,
        str(uuid4()),
        request.model_copy(
            update={"material": request.material.model_copy(update={"text": "Next"})}
        ),
    )
    sent = []
    with database.transaction() as db:
        # SKIP LOCKED excludes other actors' retained queues from this relay batch.
        db.execute(
            "SELECT id FROM knowledge.material_jobs WHERE actor_id<>%s FOR UPDATE",
            (session.actor.id,),
        ).fetchall()
        relay_materials_once(database, sent.append)
    assert second.id in sent and first.id not in sent
    service.cancel(session.token, first.id)
    service.cancel(session.token, second.id)


def test_backend_readiness_requires_the_material_job_migration(database, monkeypatch):
    assert database.ready()
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {"ok": False}
    monkeypatch.setattr(database, "transaction", lambda: nullcontext(connection))
    assert not database.ready()
    assert "version = '0066'" in connection.execute.call_args.args[0]


def test_api_returns_durable_task_and_reads_do_not_parse(database, session, intake_setup):
    service, demand, request, _ = intake_setup
    with TestClient(create_app(service.settings)) as client:
        headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
        submitted = client.post(
            f"/v1/material-demands/{demand.id}/texts",
            headers=headers,
            json=request.model_dump(mode="json"),
        )
        assert submitted.status_code == 202
        job = submitted.json()
        assert job["state"] == "queued" and ORIGINAL not in submitted.text
        read = client.get(f"/v1/material-jobs/{job['id']}", headers=headers)
        assert read.status_code == 200 and read.json()["state"] == "queued"
        assert (
            client.get(
                f"/v1/material-demands/{demand.id}/jobs",
                headers=headers,
            ).json()[0]["id"]
            == job["id"]
        )
        assert (
            client.post(
                f"/v1/material-jobs/{job['id']}/cancel",
                headers=headers,
            ).json()["state"]
            == "cancelled"
        )
