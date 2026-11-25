import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_material_changes import bound, change_input, revise
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup

from leornian.bootstrap.material_change_reviews import (
    MaterialChangeReviewWorkflow,
    required_review_refs,
)
from leornian.bootstrap.material_changes import MaterialChangeWorkflow
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.platform.config import Settings
from leornian.platform.model_contracts import ModelConnectionInput, ModelProfileInput
from leornian.platform.relay import relay_material_change_reviews_once
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def review_case(database, session, material_setup, monkeypatch):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings = Settings(
        database_url=database.url,
        model_configuration_mode="user",
        model_enabled=True,
    )
    materials, text, original, binding = bound(session, material_setup)
    candidate = revise(
        session, materials, text, original, ORIGINAL.replace("print(x)", "print(x + 1)")
    )
    changes = MaterialChangeWorkflow(database)
    data = change_input(binding, candidate)
    key = str(uuid4())
    report = changes.compare(session.token, key, data)
    reviews = MaterialChangeReviewWorkflow(database, settings)

    def configure():
        models = ModelConfigurationWorkflow(database, settings)
        connection = models.create_connection(
            session.token,
            str(uuid4()),
            ModelConnectionInput(
                label="Owned material reviewer",
                protocol="chat_completions",
                base_url="https://material-review.invalid/v1",
                region="owned-test",
                enabled=True,
                api_key="owned-material-review-secret",
            ),
        )
        return models.save_profile(
            session.token,
            str(uuid4()),
            ModelProfileInput(
                label="Material reviewer",
                connection_id=connection.id,
                model="fixture-material-review",
                operation="chat",
                roles=["material_review.v1"],
                enabled=True,
                allow_private_material=True,
                context_tokens=128_000,
                max_output_tokens=32_768,
            ),
        )

    return {
        "settings": settings,
        "materials": materials,
        "text": text,
        "original": original,
        "candidate": candidate,
        "binding": binding,
        "changes": changes,
        "reviews": reviews,
        "report": report,
        "data": data,
        "key": key,
        "configure": configure,
    }


def review_transport(case, *, refs=None, before_receipt=None):
    sent = []
    required = required_review_refs(case["report"])
    verdict = {
        "classification": "semantic_change",
        "summary": "The printed value changes from x to x + 1.",
        "reviewed_refs": [r.model_dump(mode="json") for r in required] if refs is None else refs,
    }

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        assert not wire.get("tools")
        assert wire["model"] == "fixture-material-review"
        content = json.loads(wire["messages"][1]["content"])
        assert {json.dumps(b["ref"], sort_keys=True) for b in content["blocks"]} == {
            json.dumps(r.model_dump(mode="json"), sort_keys=True) for r in required
        }
        if before_receipt:
            before_receipt()
        result = {
            **verdict,
            "reviewed_refs": [
                block["reference_key"] for block in content["blocks"]
            ] if refs is None else refs,
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": json.dumps(result)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 37},
            },
        )

    return httpx.MockTransport(handle), sent


def facts(database, review_id):
    with database.transaction(snapshot=True) as connection:
        return connection.execute(
            "SELECT r.status,r.result,r.error_code,r.operation_id,c.status AS call_status,"
            "c.applied,c.request,c.response_body FROM knowledge.material_change_reviews r "
            "LEFT JOIN runtime.external_calls c ON c.operation_ref=r.operation_id WHERE r.id=%s",
            (review_id,),
        ).fetchone()


def test_compare_registers_one_review_without_creating_a_tutor_run(database, session, review_case):
    case = review_case
    review = case["reviews"].get(session.token, case["report"].id)
    assert review.status == "queued" and review.result is None
    assert case["changes"].compare(session.token, case["key"], case["data"]) == case["report"]
    assert case["changes"].compare(session.token, str(uuid4()), case["data"]) == case["report"]
    unchanged = revise(session, case["materials"], case["text"], case["candidate"], ORIGINAL)
    report = case["changes"].compare(
        session.token, str(uuid4()), change_input(case["binding"], unchanged)
    )
    assert report.classification == "unchanged"
    assert case["reviews"].get(session.token, report.id) is None
    with database.transaction(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM knowledge.material_change_reviews WHERE actor_id=%s",
                (session.actor.id,),
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM runtime.runs WHERE actor_id=%s", (session.actor.id,)
            ).fetchone()["n"]
            == 0
        )


def test_complete_review_uses_owned_profile_and_preserves_original_binding(
    database, session, review_case
):
    case = review_case
    case["configure"]()
    review = case["reviews"].get(session.token, case["report"].id)
    transport, sent = review_transport(case)
    case["reviews"].execute(review.id, transport)
    saved = case["reviews"].get(session.token, case["report"].id)
    assert saved.status == "reviewed" and saved.error_code is None
    assert saved.result.classification == "semantic_change"
    assert set(r.model_dump_json() for r in saved.result.reviewed_refs) == set(
        r.model_dump_json() for r in required_review_refs(case["report"])
    )
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
    assert facts(database, review.id)["applied"] is True
    case["reviews"].execute(review.id, transport)
    assert len(sent) == 1
    with TestClient(create_app(case["settings"])) as client:
        response = client.get(
            f"/v1/material-change-checks/{case['report'].id}/review",
            headers={"Authorization": "Bearer " + session.token},
        )
    assert response.status_code == 200 and response.json()["status"] == "reviewed"
    assert "owned-material-review-secret" not in response.text
    with database.transaction(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM runtime.runs WHERE actor_id=%s", (session.actor.id,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.parametrize("legacy", [True, False])
def test_segmented_context_repair_preserves_receipts_and_cannot_retry_real_uncertainty(
    database, session, workflow, review_case, monkeypatch, legacy
):
    case = review_case
    case["configure"]()
    reviews = case["reviews"]
    original_request = reviews.request

    def segmented_request(gateway, report, blocks, *, segmented=False):
        if not segmented:
            raise BusinessError("precondition_failed", "Force the durable-part path.")
        return original_request(gateway, report, blocks, segmented=True)

    monkeypatch.setattr(reviews, "request", segmented_request)
    original_role = MaterialChangeReviewWorkflow.role

    def legacy_role(report, blocks, *, segmented=False):
        role = original_role(report, blocks, segmented=segmented)
        content = json.loads(role.messages[1]["content"])
        content.pop("comparison_scope")
        role.messages[1]["content"] = json.dumps(content)
        return role

    if legacy:
        monkeypatch.setattr(MaterialChangeReviewWorkflow, "role", staticmethod(legacy_role))
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        content = json.loads(wire["messages"][1]["content"])
        sent.append(content)
        classification = (
            "semantic_change" if legacy and len(sent) > 1 else "uncertain"
        )
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": json.dumps({
                "classification": classification, "summary": "Exact changed content comparison.",
                "reviewed_refs": [block["reference_key"] for block in content["blocks"]],
            })}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 37},
        })

    review = reviews.get(session.token, case["report"].id)
    transport = httpx.MockTransport(handle)
    reviews.execute(review.id, transport)
    assert reviews.get(session.token, case["report"].id).error_code == "change_review_uncertain"
    with database.transaction(snapshot=True) as connection:
        before = connection.execute(
            "SELECT c.id,c.status,c.applied,c.request,c.response_body "
            "FROM runtime.external_calls c JOIN knowledge.material_change_review_parts p "
            "ON p.operation_id=c.operation_ref WHERE p.review_id=%s", (review.id,),
        ).fetchone()
    if not legacy:
        with pytest.raises(BusinessError, match="retain uncertainty"):
            reviews.repair_context(session.token, case["report"].id)
        reviews.execute(review.id, transport)
        assert len(sent) == 1
        return

    other = workflow.create_session("Other comparison repair actor")
    with pytest.raises(BusinessError, match="not found"):
        reviews.repair_context(other.token, case["report"].id)
    monkeypatch.setattr(MaterialChangeReviewWorkflow, "role", staticmethod(original_role))
    queued = reviews.repair_context(session.token, case["report"].id)
    assert queued.status == "queued" and queued.result is None
    reviews.execute(review.id, transport)
    saved = reviews.get(session.token, case["report"].id)
    assert saved.status == "reviewed" and saved.result.classification == "semantic_change"
    assert len(sent) == 2 and sent[1]["comparison_scope"]["basis"] == "exact-document-diff.v1"
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT id,status,applied,request,response_body "
            "FROM runtime.external_calls WHERE id=%s",
            (before["id"],),
        ).fetchone() == before
        current = connection.execute(
            "SELECT c.context_manifest FROM runtime.external_calls c "
            "JOIN knowledge.material_change_review_parts p ON p.operation_id=c.operation_ref "
            "WHERE p.review_id=%s", (review.id,),
        ).fetchone()
    assert current["context_manifest"]["previous_call_id"] == str(before["id"])
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
    with pytest.raises(BusinessError, match="completed legacy"):
        reviews.repair_context(session.token, case["report"].id)
    assert len(sent) == 2


def test_reference_output_repair_keeps_the_failed_legacy_receipt(database, session, review_case):
    from leornian.agent_runtime.gateway import ChatCompletionsGateway
    from leornian.agent_runtime.repository import Runs
    from leornian.modules.knowledge.change_contracts import MaterialChangeVerdict
    from leornian.modules.knowledge.materials import Materials
    from leornian.modules.knowledge.review_parts import MaterialReviewParts
    from leornian.platform.models import UserModels

    case = review_case
    case["configure"]()
    reviews = case["reviews"]
    review = reviews.get(session.token, case["report"].id)
    with database.transaction() as connection:
        blocks = Materials(connection).read_refs(
            session.actor, case["report"].goal_id, case["report"].purpose,
            required_review_refs(case["report"]),
        )
        parts = MaterialReviewParts(connection)
        parts.save(review.id, [[(block, block.ref) for block in blocks]])
        part = parts.pending(review.id)
        models = UserModels(connection, case["settings"])
        binding = models.binding(session.actor, "material_review.v1")
        gateway = ChatCompletionsGateway(models.resolve_chat(session.actor, binding))
        request, policy = reviews.request(gateway, case["report"], blocks, segmented=True)
        content = json.loads(request["messages"][1]["content"])
        content["result_schema"] = MaterialChangeVerdict.model_json_schema()
        for block in content["blocks"]:
            block.pop("reference_key")
        request["messages"][1]["content"] = json.dumps(content)
        operation_id = uuid4()
        old = Runs(connection).prepare_operation(
            session.actor.id, operation_id, gateway.endpoint, request, policy, {
                "model_binding": binding, "check_id": str(case["report"].id),
                "review_id": str(review.id), "part_id": str(part["id"]),
                "required_refs": part["refs"],
            },
        )
        connection.execute(
            "UPDATE knowledge.material_change_review_parts SET operation_id=%s WHERE id=%s",
            (operation_id, part["id"]),
        )
    sent = []

    def handle(request):
        content = json.loads(json.loads(request.content)["messages"][1]["content"])
        sent.append(content)
        selected = [block.get("reference_key", block["ref"]) for block in content["blocks"]]
        if len(sent) == 1:
            selected.append(selected[0])
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": json.dumps({
                "classification": "semantic_change", "summary": "Teaching content changed.",
                "reviewed_refs": selected,
            })}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 37},
        })

    transport = httpx.MockTransport(handle)
    reviews.execute(review.id, transport)
    assert reviews.get(session.token, case["report"].id).error_code == "incomplete_change_review"
    with database.transaction(snapshot=True) as connection:
        original = Runs(connection).operation(operation_id)
    assert original.status == "result_recorded" and not original.applied
    reviews.repair_reference_output(session.token, case["report"].id)
    reviews.execute(review.id, transport)
    saved = reviews.get(session.token, case["report"].id)
    assert saved.status == "reviewed" and saved.result.classification == "semantic_change"
    assert len(sent) == 2
    with database.transaction(snapshot=True) as connection:
        preserved = Runs(connection).operation(operation_id)
        current = connection.execute(
            "SELECT c.context_manifest FROM runtime.external_calls c "
            "JOIN knowledge.material_change_review_parts p ON p.operation_id=c.operation_ref "
            "WHERE p.review_id=%s", (review.id,),
        ).fetchone()
    assert preserved.response_body == original.response_body and preserved.request == old.request
    assert preserved.status == "result_recorded" and preserved.applied
    assert current["context_manifest"]["previous_call_id"] == str(old.id)
    with pytest.raises(BusinessError, match="No known legacy"):
        reviews.repair_reference_output(session.token, case["report"].id)


def test_unknown_change_review_redelivery_never_reissues_the_request(
    database, session, review_case
):
    case = review_case
    case["configure"]()
    review = case["reviews"].get(session.token, case["report"].id)
    dispatched = []

    def unknown(request):
        dispatched.append(request)
        raise httpx.ReadTimeout(
            "The original request may have reached the provider.", request=request
        )

    transport = httpx.MockTransport(unknown)
    case["reviews"].execute(review.id, transport)
    assert case["reviews"].get(session.token, case["report"].id).status == "blocked_unknown"
    case["reviews"].execute(review.id, transport)
    assert len(dispatched) == 1
    row = facts(database, review.id)
    assert row["call_status"] == "unknown" and row["applied"] is False
    assert row["result"] is None


def test_missing_owned_profile_waits_then_uses_new_configuration(session, review_case):
    case = review_case
    review = case["reviews"].get(session.token, case["report"].id)
    transport, sent = review_transport(case)
    case["reviews"].execute(review.id, transport)
    assert case["reviews"].get(session.token, case["report"].id).status == "waiting_config"
    assert not sent
    case["configure"]()
    case["reviews"].execute(review.id, transport)
    assert case["reviews"].get(session.token, case["report"].id).status == "reviewed"
    assert len(sent) == 1


@pytest.mark.parametrize("interruption", ["cancel", "revoke", "replace_binding"])
def test_late_complete_review_receipt_is_saved_without_applying(
    database, session, review_case, interruption
):
    case = review_case
    case["configure"]()
    review = case["reviews"].get(session.token, case["report"].id)

    def interrupt():
        if interruption == "cancel":
            case["reviews"].cancel(session.token, case["report"].id)
        elif interruption == "revoke":
            case["materials"].revoke(
                session.token,
                case["candidate"].document_id,
                case["candidate"].revision,
                DocumentPermissionAction(expected_revision=1, action="revoke"),
            )
        else:
            case["materials"].bind(
                session.token,
                str(uuid4()),
                MaterialBindingInput(
                    goal_id=case["binding"].goal_id,
                    purpose=case["binding"].purpose,
                    expected_binding_revision=case["binding"].revision,
                    refs=case["binding"].refs,
                ),
            )

    transport, sent = review_transport(case, before_receipt=interrupt)
    case["reviews"].execute(review.id, transport)
    row = facts(database, review.id)
    assert row["call_status"] == "result_recorded"
    assert row["response_body"] and row["applied"] is False
    assert row["result"] is None
    assert row["status"] == ("cancelled" if interruption == "cancel" else "waiting_dependency")
    assert len(sent) == 1


def test_incomplete_reference_coverage_cannot_be_applied(database, session, review_case):
    case = review_case
    case["configure"]()
    review = case["reviews"].get(session.token, case["report"].id)
    required = required_review_refs(case["report"])
    assert len(required) > 1
    transport, sent = review_transport(
        case, refs=[r.model_dump(mode="json") for r in required[:-1]]
    )
    case["reviews"].execute(review.id, transport)
    row = facts(database, review.id)
    assert row["status"] == "waiting_dependency"
    assert row["error_code"] == "incomplete_change_review"
    assert row["call_status"] == "result_recorded" and row["applied"] is False
    assert row["result"] is None
    case["reviews"].execute(review.id, transport)
    assert len(sent) == 1


def test_expired_material_retention_purges_review_result_and_operation_content(
    database, session, review_case
):
    case = review_case
    case["configure"]()
    review = case["reviews"].get(session.token, case["report"].id)
    transport, _ = review_transport(case)
    case["reviews"].execute(review.id, transport)
    assert facts(database, review.id)["result"]
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.document_permissions SET retain_until=now()-interval '1 second' "
            "WHERE document_id=%s AND document_revision=%s",
            (case["candidate"].document_id, case["candidate"].revision),
        )
    MaterialIntakeWorkflow(database, case["settings"]).expire_retained_inputs()
    row = facts(database, review.id)
    assert row["result"] is None
    assert row["response_body"] is None
    assert row["request"] == {"model": "fixture-material-review", "content_purged": True}
    assert row["applied"] is True


def test_relay_skips_dependency_terminal_and_active_lease_reviews(database, session, review_case):
    case = review_case
    current = case["candidate"]
    reviews = []
    for ordinal in range(5):
        current = revise(
            session,
            case["materials"],
            case["text"],
            current,
            ORIGINAL + f"\n\nA distinct reviewed addition {ordinal}.\n",
        )
        report = case["changes"].compare(
            session.token, str(uuid4()), change_input(case["binding"], current)
        )
        reviews.append(case["reviews"].get(session.token, report.id))
    statuses = ["queued", "processing", "waiting_dependency", "reviewed", "cancelled"]
    with database.transaction() as connection:
        for review, status in zip(reviews, statuses, strict=True):
            connection.execute(
                "UPDATE knowledge.material_change_reviews SET status=%s,"
                "lease_until=now()+interval '1 hour',next_run_at=now()-interval '1 second',"
                "published_at=NULL WHERE id=%s",
                (status, review.id),
            )
    published = []
    relay_material_change_reviews_once(database, published.append)
    own_ids = {review.id for review in reviews}
    assert own_ids & set(published) == {reviews[0].id}
