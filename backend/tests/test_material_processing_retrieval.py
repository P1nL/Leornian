import base64
import io
import json
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_material_files import pdf_bytes
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup
from test_teaching_delivery import drain, provider

from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.bootstrap.material_files import MaterialFilesWorkflow
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.teaching_context import TeachingContext
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.file_contracts import (
    FileMaterialInput,
    MaterialFileJobInput,
    MaterialUploadInput,
)
from leornian.modules.knowledge.file_parser import image_regions, parse_file
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput, MaterialTextJobInput
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.platform.config import Settings
from leornian.platform.material_models import MaterialModelGateway
from leornian.platform.model_contracts import ModelConnectionInput, ModelProfileInput
from leornian.platform.models import MaterialProbeConfiguration
from leornian.platform.relay import relay_material_searches_once
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def rag(database, session, material_setup, monkeypatch, tmp_path):
    monkeypatch.setattr("leornian.platform.model_probes.resolve_destination", lambda *_: "1.1.1.1")
    settings = Settings(
        database_url=database.url,
        model_configuration_mode="user",
        material_storage_dir=str(tmp_path),
    )
    configuration = ModelConfigurationWorkflow(database, settings)
    connection = configuration.create_connection(
        session.token,
        str(uuid4()),
        ModelConnectionInput(
            label="Owned material channel",
            protocol="dashscope",
            base_url="https://dashscope.aliyuncs.com",
            region="cn-beijing",
            enabled=True,
            api_key="owned-material-secret",
        ),
    )
    for operation in ("embedding", "rerank", "ocr"):
        configuration.save_profile(
            session.token,
            str(uuid4()),
            ModelProfileInput(
                label=operation,
                connection_id=connection.id,
                model="fixture-" + operation,
                operation=operation,
                roles=[operation],
                enabled=True,
                allow_private_material=True,
                embedding_dimensions=4,
            ),
        )
    materials, goal, text = material_setup
    intake = MaterialIntakeWorkflow(database, settings)
    demand = intake.create_demand(
        session.token,
        str(uuid4()),
        MaterialDemandInput(
            goal_id=goal.id,
            purpose="teaching",
            language="Python",
            required_facets=["Iteration"],
        ),
    )
    job = intake.submit_text(
        session.token,
        demand.id,
        str(uuid4()),
        MaterialTextJobInput(expected_demand_revision=1, material=text),
    )
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        assert not {"tools", "thinking", "tool_choice"} & wire.keys()
        if wire["model"] in {"fixture-embedding", "different-embedding"}:
            assert all("fixed unrelated connection probe" not in t for t in wire["input"]["texts"])
            body = {
                "output": {
                    "embeddings": [
                        {"text_index": i, "embedding": [1.0, 0.2, 0.3, 0.4] * (
                            2 if wire["model"] == "different-embedding" else 1
                        )}
                        for i in range(len(wire["input"]["texts"]))
                    ]
                }
            }
        elif wire["model"] == "fixture-rerank":
            body = {
                "output": {
                    "results": [
                        {"index": i, "relevance_score": 1 / (i + 1)}
                        for i in range(len(wire["input"]["documents"]))
                    ]
                }
            }
        else:
            assert wire["messages"][0]["content"][0]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
            body = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "# Iteration\n\nUse a sequence.",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        return httpx.Response(200, json={**body, "usage": {"total_tokens": 23}})

    return {
        "intake": intake,
        "demand": demand,
        "job": job,
        "materials": materials,
        "goal": goal,
        "settings": settings,
        "configuration": configuration,
        "connection": connection,
        "transport": httpx.MockTransport(handle),
        "sent": sent,
    }


def prepare(rag, session, job=None):
    job = job or rag["job"]
    for _ in range(20):
        rag["intake"].execute(job.id, transport=rag["transport"])
        state = rag["intake"].job(session.token, job.id)
        if state.state == "ready":
            return state
        assert state.state not in {"waiting_config", "blocked_unknown"}, state
    pytest.fail(f"Owned material did not become usable: {state}")


def test_real_inputs_are_indexed_and_hybrid_selection_is_bound_and_consumed(database, session, rag):
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.material_jobs SET published_at=now() WHERE id=%s", (rag["job"].id,),
        )
    job = prepare(rag, session)
    assert job.document_revision == 1
    assert len(rag["sent"]) == 1
    assert any("    print(x)" in t for t in rag["sent"][0]["input"]["texts"])
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT published_at FROM knowledge.material_jobs WHERE id=%s", (job.id,),
        ).fetchone()["published_at"] is None
    searches = MaterialSearchWorkflow(database, rag["settings"])
    data = MaterialSearchInput(
        demand_id=rag["demand"].id,
        expected_demand_revision=1,
        query="Iteration print items",
    )
    key = str(uuid4())
    request = searches.submit(session.token, key, data)
    assert searches.submit(session.token, str(uuid4()), data).id == request.id
    searches.execute(request.id, rag["transport"])
    ready = searches.get(session.token, request.id)
    assert ready.status == "ready", ready
    selection = searches.selection(session.token, ready.selection_id)
    assert selection.mode == "hybrid" and selection.coverage.status == "sufficient"
    assert selection.coverage.semantic_quality == "not_certified"
    assert all(e.ref.selection_id == selection.id for e in selection.evidence)
    assert rag["sent"][1]["parameters"]["text_type"] == "query"
    assert rag["sent"][2]["parameters"]["return_documents"] is False
    binding = rag["materials"].bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id,
            purpose="teaching",
            expected_binding_revision=0,
            refs=[e.ref for e in selection.evidence],
        ),
    )
    blocks = rag["materials"].bound_blocks(session.token, binding.id, binding.revision).blocks
    assert all(ORIGINAL[b.ref.span.start : b.ref.span.end] == b.text for b in blocks)
    tutor = TutorWorkflow(database, rag["settings"])
    conversation = tutor.conversation(session.token, rag["goal"].id)
    with database.transaction() as connection:
        context, manifest = TeachingContext.build(
            connection, session.actor, conversation, TeachingFocus()
        )
    assert context["bound_materials"][0]["binding_id"] == str(binding.id)
    assert manifest["material_bindings"][0]["revision"] == binding.revision
    assert "owned-material-secret" not in selection.model_dump_json()
    searches.execute(request.id, rag["transport"])
    assert searches.get(session.token, request.id) == ready and len(rag["sent"]) == 3
    with pytest.raises(BusinessError, match="key changed"):
        searches.submit(session.token, key, data.model_copy(update={"query": "different"}))
    with database.transaction(snapshot=True) as connection:
        facts = connection.execute(
            "SELECT status,applied,usage FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchall()
    assert len(facts) == 3 and all(f["status"] == "result_recorded" and f["applied"] for f in facts)


def test_explicit_lexical_mode_does_not_call_models_and_get_is_read_only(session, rag):
    prepare(rag, session)
    searches = MaterialSearchWorkflow(rag["intake"].database, rag["settings"])
    job = searches.submit(
        session.token,
        str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id,
            expected_demand_revision=1,
            query="Iteration",
            mode="lexical",
        ),
    )
    searches.execute(job.id, rag["transport"])
    client = TestClient(create_app(rag["settings"]))
    headers = {"Authorization": "Bearer " + session.token}
    result = client.get(f"/v1/material-searches/{job.id}", headers=headers)
    assert result.status_code == 200 and result.json()["status"] == "ready"
    selection = client.get(
        "/v1/material-selections/" + result.json()["selection_id"], headers=headers
    )
    assert selection.status_code == 200 and selection.json()["mode"] == "lexical"
    assert len(rag["sent"]) == 1


def test_unknown_material_embedding_is_not_resent_after_redelivery_or_key_rotation(
    database, session, rag
):
    intake, job = rag["intake"], rag["job"]
    intake.execute(job.id)
    sent = []

    def timeout(request):
        sent.append(request)
        raise httpx.ReadTimeout("The request may have reached the model.")

    transport = httpx.MockTransport(timeout)
    intake.execute(job.id, transport)
    assert intake.job(session.token, job.id).state == "blocked_unknown"
    from leornian.platform.model_contracts import ModelConnectionPatch

    rag["configuration"].patch_connection(
        session.token,
        rag["connection"].id,
        ModelConnectionPatch(expected_revision=1, api_key="rotated-material-secret"),
    )
    intake.execute(job.id, transport)
    assert len(sent) == 1
    with database.transaction(snapshot=True) as connection:
        facts = connection.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchall()
    assert facts == [{"status": "unknown", "applied": False}]


def test_cancellation_during_material_call_keeps_receipt_but_does_not_apply(database, session, rag):
    intake, job = rag["intake"], rag["job"]
    intake.execute(job.id)

    def cancel(request):
        intake.cancel(session.token, job.id)
        count = len(json.loads(request.content)["input"]["texts"])
        return httpx.Response(
            200,
            json={
                "output": {
                    "embeddings": [
                        {"text_index": i, "embedding": [1, 0, 0, 0]} for i in range(count)
                    ]
                }
            },
        )

    intake.execute(job.id, httpx.MockTransport(cancel))
    assert intake.job(session.token, job.id).state == "cancelled"
    with database.transaction(snapshot=True) as connection:
        fact = connection.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()
        vectors = connection.execute(
            "SELECT 1 FROM knowledge.material_chunks c JOIN knowledge.material_index_builds b "
            "ON b.id=c.build_id WHERE b.actor_id=%s AND c.embedding IS NOT NULL",
            (session.actor.id,),
        ).fetchall()
    assert fact == {"status": "result_recorded", "applied": False} and not vectors


def test_search_rejects_revoked_and_foreign_material_without_exposing_text(
    database, session, workflow, rag
):
    job = prepare(rag, session)
    searches = MaterialSearchWorkflow(database, rag["settings"])
    data = MaterialSearchInput(
        demand_id=rag["demand"].id, expected_demand_revision=1, query="Iteration"
    )
    other = workflow.create_session("Other material reader")
    with pytest.raises(BusinessError):
        searches.submit(other.token, str(uuid4()), data)
    request = searches.submit(session.token, str(uuid4()), data)
    rag["materials"].revoke(
        session.token,
        job.document_id,
        job.document_revision,
        DocumentPermissionAction(expected_revision=1, action="revoke"),
    )
    searches.execute(request.id, rag["transport"])
    state = searches.get(session.token, request.id)
    assert state.status == "waiting_dependency" and state.selection_id is None
    assert len(rag["sent"]) == 1


def test_pdf_ocr_uses_actual_isolated_page_image_and_appends_derived_version(session, rag):
    files = MaterialFilesWorkflow(rag["intake"].database, rag["settings"])
    content = pdf_bytes([None])
    upload = files.reserve(
        session.token,
        rag["demand"].id,
        str(uuid4()),
        MaterialUploadInput(
            expected_demand_revision=1,
            byte_size=len(content),
            content_digest=sha256(content).hexdigest(),
            material=FileMaterialInput(
                goal_id=rag["goal"].id,
                title="Scan",
                format="pdf",
                authorized_use=True,
                purposes=["reference", "teaching", "indexing"],
            ),
        ),
    )
    files.store_content(session.token, upload.id, content)
    job = files.submit(
        session.token,
        rag["demand"].id,
        str(uuid4()),
        MaterialFileJobInput(expected_demand_revision=1, upload_id=upload.id),
    )
    rag["intake"].execute(job.id)
    parsed = rag["intake"].job(session.token, job.id)
    assert parsed.phase == "ocr"
    ready = prepare(rag, session, job)
    assert ready.document_revision == 2
    original = rag["materials"].version(session.token, ready.document_id, 1)
    derived = rag["materials"].version(session.token, ready.document_id, 2)
    assert original.processing_state == "partial" and original.pages[0].requires_ocr
    assert derived.pages[0].method == "ocr" and derived.upload_id == upload.id
    assert files.original(session.token, upload.id, "reference") == content


@pytest.mark.parametrize("legacy", [False, True])
def test_image_ocr_uses_frozen_regions_when_partition_policy_changes(
    session, rag, monkeypatch, legacy,
):
    content = io.BytesIO()
    Image.new("RGB", (1191, 1684), "white").save(content, format="PNG")
    content = content.getvalue()
    if legacy:
        parsed = parse_file(content, "png")
        template = parsed["pages"][0]
        parsed["pages"] = [
            {**template, "number": number, "region": region}
            for number, region in enumerate(image_regions(1191, 1684), 1)
        ]
        parsed["parser_version"] = "image-original.v1"
        monkeypatch.setattr("leornian.bootstrap.material_intake.extract_file", lambda *_: parsed)
    files = MaterialFilesWorkflow(rag["intake"].database, rag["settings"])
    upload = files.reserve(
        session.token, rag["demand"].id, str(uuid4()),
        MaterialUploadInput(
            expected_demand_revision=1,
            byte_size=len(content),
            content_digest=sha256(content).hexdigest(),
            material=FileMaterialInput(
                goal_id=rag["goal"].id,
                title="Frozen source image",
                format="png",
                authorized_use=True,
                purposes=["reference", "teaching", "indexing"],
            ),
        ),
    )
    files.store_content(session.token, upload.id, content)
    job = files.submit(
        session.token, rag["demand"].id, str(uuid4()),
        MaterialFileJobInput(expected_demand_revision=1, upload_id=upload.id),
    )
    rag["intake"].execute(job.id)
    original = rag["materials"].version(
        session.token, rag["intake"].job(session.token, job.id).document_id, 1,
    )
    ready = prepare(rag, session, job)
    derived = rag["materials"].version(session.token, ready.document_id, 2)
    assert ready.document_revision == 2
    assert [page.region for page in derived.pages] == [page.region for page in original.pages]
    assert len(original.pages) == (4 if legacy else 1)
    images = []
    for wire in rag["sent"]:
        if wire["model"] != "fixture-ocr":
            continue
        image_url = wire["messages"][0]["content"][0]["image_url"]["url"]
        with Image.open(io.BytesIO(base64.b64decode(image_url.split(",", 1)[1]))) as image:
            images.append(image.size)
    assert images == [
        (page.region[2] - page.region[0], page.region[3] - page.region[1])
        for page in original.pages
    ]
    assert files.original(session.token, upload.id, "reference") == content


@pytest.mark.parametrize("operation", ["embedding", "rerank"])
def test_normal_material_protocol_rejects_incomplete_or_nonfinite_outputs(operation):
    gateway = MaterialModelGateway(
        MaterialProbeConfiguration(
            base_url="https://dashscope.aliyuncs.com",
            protocol="dashscope",
            operation=operation,
            model="fixture",
            dimensions=4,
            timeout=30,
            local_endpoint=False,
            api_key="not-sent",
        )
    )
    wire, _ = gateway.request(texts=["one", "two", "three"], query="Which?")
    broken = (
        {"output": {"embeddings": [{"text_index": 0, "embedding": [float("nan")] * 4}]}}
        if operation == "embedding"
        else {"output": {"results": [{"index": 0, "relevance_score": 0.5}]}}
    )
    with pytest.raises(ModelProtocolError):
        gateway.result(json.dumps(broken), wire)


def test_relay_wakes_search_without_creating_or_dispatching_external_call(database, session, rag):
    job = MaterialSearchWorkflow(database, rag["settings"]).submit(
        session.token,
        str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id, expected_demand_revision=1, query="Iteration"
        ),
    )
    published = []
    relay_material_searches_once(database, published.append)
    assert job.id in published and not rag["sent"]


def test_profile_change_does_not_mix_index_spaces_or_silently_downgrade(session, rag):
    prepare(rag, session)
    rag["configuration"].save_profile(
        session.token,
        str(uuid4()),
        ModelProfileInput(
            label="New embedding space",
            connection_id=rag["connection"].id,
            model="different-embedding",
            operation="embedding",
            roles=["embedding"],
            embedding_dimensions=8,
            enabled=True,
            allow_private_material=True,
        ),
    )
    searches = MaterialSearchWorkflow(rag["intake"].database, rag["settings"])
    job = searches.submit(
        session.token,
        str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id,
            expected_demand_revision=1,
            query="Iteration",
        ),
    )
    searches.execute(job.id, rag["transport"])
    result = searches.get(session.token, job.id)
    assert result.status == "waiting_dependency" and result.error_code == "index_rebuild_pending"
    assert result.selection_id is None and len(rag["sent"]) == 2
    searches.execute(job.id, rag["transport"])
    assert searches.get(session.token, job.id).status == "ready"
    assert len(rag["sent"]) == 4
    with searches.database.transaction(snapshot=True) as connection:
        spaces = connection.execute(
            "SELECT b.space,array_length(c.embedding,1) AS dimensions "
            "FROM knowledge.material_index_builds b "
            "JOIN knowledge.material_chunks c ON c.build_id=b.id WHERE b.actor_id=%s "
            "AND c.embedding IS NOT NULL",
            (session.actor.id,),
        ).fetchall()
    assert {r["dimensions"] for r in spaces} == {4, 8}
    assert all(r["space"]["dimensions"] == r["dimensions"] for r in spaces)
    assert rag["intake"].job(session.token, rag["job"].id).state == "ready"


def test_retention_purges_vectors_and_material_call_content_but_keeps_call_facts(
    database, session, rag
):
    job = prepare(rag, session)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.document_permissions SET retain_until=now()-interval '1 second' "
            "WHERE document_id=%s AND document_revision=%s",
            (job.document_id, job.document_revision),
        )
        connection.execute(
            "UPDATE knowledge.material_jobs SET retain_until=now()-interval '1 second' WHERE id=%s",
            (job.id,),
        )
    rag["intake"].expire_retained_inputs()
    with database.transaction(snapshot=True) as connection:
        chunks = connection.execute(
            "SELECT c.text,c.embedding,c.lexemes FROM knowledge.material_chunks c "
            "JOIN knowledge.material_index_builds b ON b.id=c.build_id WHERE b.actor_id=%s",
            (session.actor.id,),
        ).fetchall()
        calls = connection.execute(
            "SELECT status,request,response_body,usage FROM runtime.external_calls "
            "WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchall()
    assert chunks and all(c == {"text": None, "embedding": None, "lexemes": None} for c in chunks)
    assert len(calls) == 1 and calls[0]["status"] == "result_recorded"
    assert calls[0]["response_body"] is None and calls[0]["request"]["content_purged"]
    assert calls[0]["usage"]["total_tokens"] == 23


def test_selected_material_reaches_byok_tutor_and_accepted_reply_freezes_binding(
    database, session, rag, monkeypatch
):
    from test_material_sources_and_goals import advance_consumer_materials, configure_goal_models

    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    prepare(rag, session)
    searches = MaterialSearchWorkflow(database, rag["settings"])
    search = searches.submit(
        session.token,
        str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id,
            expected_demand_revision=1,
            query="Iteration",
            mode="lexical",
        ),
    )
    searches.execute(search.id, rag["transport"])
    selection = searches.selection(
        session.token, searches.get(session.token, search.id).selection_id
    )
    binding = rag["materials"].bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id,
            purpose="teaching",
            expected_binding_revision=0,
            refs=[e.ref for e in selection.evidence],
        ),
    )
    rag["configuration"].save_profile(
        session.token,
        str(uuid4()),
        ModelProfileInput(
            label="Owned teaching",
            connection_id=rag["connection"].id,
            model="fixture-chat",
            operation="chat",
            roles=["tutor.v1", "delivery_review.v1"],
            enabled=True,
            allow_private_material=True,
            context_tokens=128000,
            max_output_tokens=32768,
        ),
    )
    configure_goal_models(database, session, rag["settings"])
    tutor = TutorWorkflow(database, rag["settings"])
    conversation = tutor.conversation(session.token, rag["goal"].id)
    accepted = tutor.submit(
        session.token,
        conversation.id,
        str(uuid4()),
        TurnInput(text="Explain the selected Iteration material with its exact citation."),
    )
    advance_consumer_materials(database, session, rag["settings"], rag["goal"].id)
    gateway, sent, _ = provider(rag["settings"], author="Iteration visits the selected sequence.")
    completed = drain(tutor, rag["settings"], accepted, gateway, session.token)
    assert completed.status == "accepted"
    context = json.loads(sent[0]["messages"][1]["content"].split("(data): ", 1)[1])
    assert context["bound_materials"][0]["blocks"][0]["ref"]["selection_id"] == str(selection.id)
    with database.transaction(snapshot=True) as connection:
        task = connection.execute(
            "SELECT context_manifest FROM tutor.delivery_tasks WHERE id=%s",
            (accepted.delivery_task_id,),
        ).fetchone()
    frozen = task["context_manifest"]["material_bindings"][0]
    assert frozen["id"] == str(binding.id) and frozen["revision"] == binding.revision


def test_no_embedding_channel_still_allows_explicit_chinese_lexical_search(session, rag):
    rag["configuration"].save_profile(
        session.token,
        str(uuid4()),
        ModelProfileInput(
            label="Disabled embedding",
            connection_id=rag["connection"].id,
            model="fixture-embedding",
            operation="embedding",
            roles=["embedding"],
            embedding_dimensions=4,
            enabled=False,
            allow_private_material=True,
        ),
    )
    rag["intake"].execute(rag["job"].id)
    rag["intake"].execute(rag["job"].id, rag["transport"])
    assert rag["intake"].job(session.token, rag["job"].id).state == "waiting_config"
    searches = MaterialSearchWorkflow(rag["intake"].database, rag["settings"])
    data = MaterialSearchInput(
        demand_id=rag["demand"].id,
        expected_demand_revision=1,
        query="\u4e2d\u6587\u6559\u6750",
        mode="lexical",
    )
    job = searches.submit(session.token, str(uuid4()), data)
    searches.execute(job.id, rag["transport"])
    selection = searches.selection(session.token, searches.get(session.token, job.id).selection_id)
    assert selection.mode == "lexical"
    assert any("\u4e2d\u6587\u6559\u6750" in e.text for e in selection.evidence)
    assert selection.coverage.status == "insufficient"
    hybrid = searches.submit(
        session.token, str(uuid4()), data.model_copy(update={"mode": "hybrid"})
    )
    searches.execute(hybrid.id, rag["transport"])
    assert searches.get(session.token, hybrid.id).status == "waiting_config"
    assert not rag["sent"]
