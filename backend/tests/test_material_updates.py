import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_material_changes import change_input, revise
from test_material_consumers import consumer as consumer
from test_material_consumers import draft
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import prepare
from test_material_processing_retrieval import rag as rag
from test_material_sources_and_goals import advance_consumer_materials
from test_teaching_delivery import drain, provider

from leornian.bootstrap.material_change_reviews import (
    MaterialChangeReviewWorkflow,
    required_review_refs,
)
from leornian.bootstrap.material_changes import MaterialChangeWorkflow
from leornian.bootstrap.material_consumers import binding_citations, ensure_node_binding_in
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.material_updates import MaterialUpdateWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.notifications import NotificationsWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction, MaterialSpan
from leornian.modules.knowledge.materials import digest
from leornian.modules.learning.contracts import LessonRequestInput
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.learning.material_update_contracts import MaterialUpdateDecisionInput
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.platform.model_contracts import ModelConnectionInput, ModelProfileInput
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def update_case(database, session, rag, material_setup, monkeypatch):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    original = prepare(rag, session)
    materials = rag["materials"]
    refs = materials.blocks(
        session.token, original.document_id, original.document_revision, "teaching"
    ).blocks
    binding = materials.bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id,
            purpose="teaching",
            expected_binding_revision=0,
            refs=[block.ref for block in refs],
        ),
    )
    first = materials.version(session.token, original.document_id, original.document_revision)
    candidate = revise(
        session, materials, material_setup[2], first, ORIGINAL.replace("print(x)", "print(x + 1)")
    )
    settings = replace(rag["settings"], model_enabled=True)
    changes = MaterialChangeWorkflow(database)
    report = changes.compare(session.token, str(uuid4()), change_input(binding, candidate))
    return {
        "database": database,
        "settings": settings,
        "rag": rag,
        "materials": materials,
        "original": first,
        "candidate": candidate,
        "binding": binding,
        "changes": changes,
        "report": report,
        "reviews": MaterialChangeReviewWorkflow(database, settings),
        "updates": MaterialUpdateWorkflow(database, settings),
        "notifications": NotificationsWorkflow(database),
    }


def finish_review(case, session, classification="semantic_change"):
    configuration = ModelConfigurationWorkflow(case["database"], case["settings"])
    connection = configuration.create_connection(
        session.token,
        str(uuid4()),
        ModelConnectionInput(
            label="Owned update reviewer",
            protocol="chat_completions",
            base_url="https://update-review.invalid/v1",
            region="owned-test",
            enabled=True,
            api_key="owned-update-review-secret",
        ),
    )
    configuration.save_profile(
        session.token,
        str(uuid4()),
        ModelProfileInput(
            label="Update reviewer",
            connection_id=connection.id,
            model="fixture-update-review",
            operation="chat",
            roles=["material_review.v1"],
            enabled=True,
            allow_private_material=True,
            context_tokens=128_000,
            max_output_tokens=32_768,
        ),
    )
    refs = required_review_refs(case["report"])
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        assert not wire.get("tools")
        assert wire["model"] == "fixture-update-review"
        assert {
            json.dumps(block["ref"], sort_keys=True)
            for block in json.loads(wire["messages"][1]["content"])["blocks"]
        } == {json.dumps(ref.model_dump(mode="json"), sort_keys=True) for ref in refs}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "classification": classification,
                                    "summary": "The changed program prints x + 1 instead of x.",
                                    "reviewed_refs": [
                                        block["reference_key"]
                                        for block in json.loads(wire["messages"][1]["content"])[
                                            "blocks"
                                        ]
                                    ],
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 41},
            },
        )

    review = case["reviews"].get(session.token, case["report"].id)
    case["reviews"].execute(review.id, httpx.MockTransport(handle))
    assert len(sent) == 1
    return case["reviews"].get(session.token, case["report"].id)


def ready_offer(case, session):
    finish_review(case, session)
    updates = case["updates"]
    preparation = updates.get_preparation(session.token, case["report"].id)
    assert preparation is not None
    for _ in range(6):
        updates.execute(preparation.id)
        preparation = updates.get_preparation(session.token, case["report"].id)
        if preparation.offer_id:
            return updates.get(session.token, preparation.offer_id)
        if preparation.job_id:
            job = case["rag"]["intake"].job(session.token, preparation.job_id)
            if job.state != "ready":
                case["rag"]["intake"].execute(job.id, transport=case["rag"]["transport"])
                progressed = case["rag"]["intake"].job(session.token, job.id)
                assert progressed.state not in {
                    "waiting_config", "blocked_unknown", "cancelled",
                }, (progressed.state, progressed.reason_code)
                assert not progressed.issues, (
                    progressed.state, progressed.reason_code, progressed.issues
                )
        if preparation.search_id:
            MaterialSearchWorkflow(case["database"], case["settings"]).execute(
                preparation.search_id, case["rag"]["transport"]
            )
    pytest.fail(f"Update preparation did not create an offer: {preparation}")


def decision_data(case, offer, decision="accept_update"):
    return MaterialUpdateDecisionInput(
        decision=decision,
        expected_offer_revision=offer.revision,
        expected_binding_revision=case["binding"].revision,
    )


def notifications(case, session):
    return case["notifications"].list(session.token)


def call_count(case, session):
    with case["database"].transaction(snapshot=True) as connection:
        return connection.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"]


def test_semantic_review_automatically_prepares_one_offer_and_notification(
    database, session, update_case
):
    case = update_case
    offer = ready_offer(case, session)
    preparation = case["updates"].get_preparation(session.token, case["report"].id)
    assert preparation.job_id and preparation.search_id
    job = case["rag"]["intake"].job(session.token, preparation.job_id)
    assert job.state == "ready"
    assert (job.document_id, job.document_revision) == (
        case["candidate"].document_id,
        case["candidate"].revision,
    )
    search = MaterialSearchWorkflow(database, case["settings"])
    selected = search.get(session.token, preparation.search_id)
    selection = search.selection(session.token, selected.selection_id)
    assert selection.coverage.status == "sufficient"
    assert {
        (e.ref.document_id, e.ref.document_revision) for e in selection.evidence
    } == {(case["candidate"].document_id, case["candidate"].revision)}
    notices = notifications(case, session)
    assert len(notices) == 1
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
    before = call_count(case, session)
    for _ in range(2):
        case["updates"].execute(preparation.id)
        assert case["updates"].get(session.token, offer.id) == offer
    assert len(notifications(case, session)) == 1
    assert call_count(case, session) == before
    assert "owned-update-review-secret" not in offer.model_dump_json()
    assert "owned-material-secret" not in notices[0].model_dump_json()
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.document_versions WHERE document_id=%s",
            (case["candidate"].document_id,),
        ).fetchone()["n"] == 2
        assert connection.execute(
            "SELECT count(*) AS n FROM runtime.runs WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"] == 0


@pytest.mark.parametrize("has_origin", [False, True])
def test_update_preparation_preserves_explicit_goals_without_inventing_metadata_facets(
    monkeypatch, has_origin
):
    from types import SimpleNamespace

    from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
    from leornian.modules.knowledge.updates import MaterialUpdates

    binding = SimpleNamespace(
        goal_id=uuid4(), purpose="reference", plan_id=None, plan_revision=None, node_key=None
    )
    origin = MaterialDemandInput(
        goal_id=binding.goal_id, purpose="reference", required_facets=["explicit learner scope"]
    )
    monkeypatch.setattr(
        MaterialUpdates, "origin_demand", lambda *_: origin if has_origin else None
    )
    demand = MaterialUpdateWorkflow.demand_input(None, None, binding, uuid4())
    if has_origin:
        assert demand == origin
    else:
        assert demand.scope_mode == "whole_source" and demand.required_facets == []


def test_inferred_update_scope_repair_preserves_failed_preparation_and_exact_binding(
    database, session, update_case
):
    from leornian.modules.identity.application import Identity
    from leornian.modules.knowledge.intake import MaterialIntake
    from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
    from leornian.modules.knowledge.updates import MaterialUpdates

    case = update_case
    case["binding"] = case["materials"].bind(
        session.token, str(uuid4()), MaterialBindingInput(
            goal_id=case["binding"].goal_id, purpose="reference",
            expected_binding_revision=0, refs=case["binding"].refs,
        ),
    )
    case["report"] = case["changes"].compare(
        session.token, str(uuid4()), change_input(case["binding"], case["candidate"])
    )
    finish_review(case, session)
    updates = case["updates"]
    preparation = updates.get_preparation(session.token, case["report"].id)
    with database.transaction() as connection:
        intake = MaterialIntake(connection)
        old = intake.ensure_consumer_demand(
            session.actor, "material-update:" + str(preparation.id),
            MaterialDemandInput(
                goal_id=case["binding"].goal_id, purpose=case["binding"].purpose,
                required_facets=["Outdated source edition title"],
            ),
        )
        failed = intake.prepare_revision(
            session.actor, Identity.digest(session.token), old.id,
            case["candidate"].document_id, case["candidate"].revision,
        )
        intake.transition(
            failed.id, "waiting_dependency", "validating", reason="coverage_gap",
            issues=old.required_facets,
        )
        MaterialUpdates(connection).transition(
            preparation.id, "waiting_dependency", "automatic_repair_exhausted",
            demand_id=old.id, job_id=failed.id,
        )
    repaired = updates.repair_inferred_scope(session.token, case["report"].id)
    assert repaired.job_id != failed.id and repaired.demand_id != old.id
    intake_flow = case["rag"]["intake"]
    preserved = intake_flow.job(session.token, failed.id)
    assert preserved.state == "cancelled" and preserved.reason_code == "inferred_scope_replaced"
    assert intake_flow.demand(session.token, old.id) == old
    assert intake_flow.demand(session.token, repaired.demand_id).scope_mode == "whole_source"
    for _ in range(8):
        updates.execute(preparation.id)
        current = updates.get_preparation(session.token, case["report"].id)
        if current.offer_id:
            break
        intake_flow.execute(current.job_id, transport=case["rag"]["transport"])
        if current.search_id:
            MaterialSearchWorkflow(database, case["settings"]).execute(
                current.search_id, case["rag"]["transport"]
            )
    assert current.offer_id is not None
    offer = updates.get(session.token, current.offer_id)
    assert all(ref.document_revision == case["candidate"].revision for ref in offer.candidate_refs)
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
    with pytest.raises(BusinessError, match="No unresolved inferred"):
        updates.repair_inferred_scope(session.token, case["report"].id)


@pytest.mark.parametrize("classification", ["editorial_equivalent", "uncertain"])
def test_non_semantic_or_incomplete_review_never_creates_an_update(
    session, update_case, classification
):
    case = update_case
    assert case["updates"].get_preparation(session.token, case["report"].id) is None
    review = finish_review(case, session, classification)
    assert review.result.classification == classification
    assert case["updates"].get_preparation(session.token, case["report"].id) is None
    assert notifications(case, session) == []
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]


def test_notification_read_later_and_keep_preserve_the_current_binding(session, update_case):
    case = update_case
    offer = ready_offer(case, session)
    notice = notifications(case, session)[0]
    before = call_count(case, session)
    case["notifications"].read(session.token, notice.id)
    later = case["updates"].decide(
        session.token, offer.id, str(uuid4()), decision_data(case, offer, "decide_later")
    )
    assert later.successor_binding_id is None
    current = case["updates"].get(session.token, offer.id)
    kept = case["updates"].decide(
        session.token,
        offer.id,
        str(uuid4()),
        decision_data(case, current, "keep_current_for_track"),
    )
    assert kept.successor_binding_id is None
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
    assert call_count(case, session) == before
    with pytest.raises(BusinessError):
        current = case["updates"].get(session.token, offer.id)
        case["updates"].decide(
            session.token, offer.id, str(uuid4()), decision_data(case, current)
        )


def test_identical_new_revision_keeps_the_same_offer_but_new_content_notifies_again(
    session, update_case, material_setup
):
    case = update_case
    first = ready_offer(case, session)
    case["updates"].decide(
        session.token,
        first.id,
        str(uuid4()),
        decision_data(case, first, "keep_current_for_track"),
    )
    for expected_revision, content in (
        (3, ORIGINAL.replace("print(x)", "print(x + 1)")),
        (4, ORIGINAL.replace("print(x)", "print(x + 2)")),
    ):
        case["candidate"] = revise(
            session, case["materials"], material_setup[2], case["candidate"], content
        )
        assert case["candidate"].revision == expected_revision
        case["report"] = case["changes"].compare(
            session.token,
            str(uuid4()),
            change_input(case["binding"], case["candidate"]),
        )
        current = ready_offer(case, session)
        if expected_revision == 3:
            assert current.id == first.id and current.candidate_revision == 2
            assert len(notifications(case, session)) == 1
            assert notifications(case, session)[0].state == "kept_current"
        else:
            assert current.id != first.id and current.candidate_revision == 4
            notices = notifications(case, session)
            assert len(notices) == 2
            assert {notice.state for notice in notices} == {"unread", "kept_current"}
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]


def test_accept_is_concurrent_idempotent_and_preserves_exact_history(
    database, session, update_case
):
    case = update_case
    offer = ready_offer(case, session)
    data, key = decision_data(case, offer), str(uuid4())
    before = call_count(case, session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: case["updates"].decide(session.token, offer.id, key, data), range(2)
            )
        )
    assert results[0] == results[1]
    saved = results[0]
    assert saved.successor_binding_id == case["binding"].id
    assert saved.successor_binding_revision == case["binding"].revision + 1
    current = case["materials"].binding(session.token, case["binding"].id)
    assert current.revision == saved.successor_binding_revision
    assert {ref.document_revision for ref in current.refs} == {case["candidate"].revision}
    assert case["materials"].binding(
        session.token, case["binding"].id, case["binding"].revision
    ) == case["binding"]
    assert case["materials"].version(
        session.token, case["original"].document_id, case["original"].revision
    ) == case["original"]
    assert case["changes"].get(session.token, case["report"].id) == case["report"]
    assert case["updates"].get(session.token, offer.id) == offer
    notice = notifications(case, session)[0]
    assert notice.state == "accepted"
    assert case["notifications"].read(session.token, notice.id).state == "accepted"
    assert call_count(case, session) == before
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM learning.material_binding_revisions WHERE binding_id=%s",
            (case["binding"].id,),
        ).fetchone()["n"] == 2
    with pytest.raises(BusinessError):
        case["updates"].decide(session.token, offer.id, str(uuid4()), data)


@pytest.mark.parametrize("revision", [1, 2])
def test_accept_rechecks_both_versions_live_permission(session, update_case, revision):
    case = update_case
    offer = ready_offer(case, session)
    before = call_count(case, session)
    case["materials"].revoke(
        session.token,
        case["candidate"].document_id,
        revision,
        DocumentPermissionAction(action="revoke", expected_revision=1),
    )
    with pytest.raises(BusinessError):
        case["updates"].decide(
            session.token, offer.id, str(uuid4()), decision_data(case, offer)
        )
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
    assert call_count(case, session) == before


def test_accept_rejects_a_changed_binding_without_rebasing(session, update_case):
    case = update_case
    offer = ready_offer(case, session)
    changed = case["materials"].bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=case["binding"].goal_id,
            purpose=case["binding"].purpose,
            expected_binding_revision=case["binding"].revision,
            refs=case["binding"].refs,
        ),
    )
    with pytest.raises(BusinessError):
        case["updates"].decide(
            session.token, offer.id, str(uuid4()), decision_data(case, offer)
        )
    assert case["materials"].binding(session.token, changed.id) == changed


def test_update_and_notification_are_isolated_from_another_actor(
    workflow, session, update_case
):
    case = update_case
    offer = ready_offer(case, session)
    notice = notifications(case, session)[0]
    other = workflow.create_session("Other update learner")
    assert notifications(case, other) == []
    for read in (
        lambda: case["updates"].get(other.token, offer.id),
        lambda: case["updates"].get_preparation(other.token, case["report"].id),
        lambda: case["notifications"].read(other.token, notice.id),
        lambda: case["updates"].decide(
            other.token, offer.id, str(uuid4()), decision_data(case, offer)
        ),
    ):
        with pytest.raises(BusinessError):
            read()
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]


def test_partial_changed_block_waits_instead_of_guessing_a_wider_successor(
    session, update_case
):
    case = update_case
    page = case["materials"].blocks(
        session.token, case["original"].document_id, case["original"].revision, "teaching"
    )
    code = page.blocks[2]
    start = code.ref.span.start + code.text.index("print(x)")
    partial = code.ref.model_copy(
        update={
            "span": MaterialSpan(start=start, end=start + len("print(x)")),
            "content_digest": digest("print(x)"),
        }
    )
    binding = case["materials"].bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=case["binding"].goal_id,
            purpose=case["binding"].purpose,
            expected_binding_revision=case["binding"].revision,
            refs=[partial],
        ),
    )
    case["binding"] = binding
    case["report"] = case["changes"].compare(
        session.token, str(uuid4()), change_input(binding, case["candidate"])
    )
    finish_review(case, session)
    preparation = case["updates"].get_preparation(session.token, case["report"].id)
    assert preparation is not None
    case["updates"].execute(preparation.id)
    current = case["updates"].get_preparation(session.token, case["report"].id)
    assert current.status == "waiting_dependency"
    assert current.offer_id is None and notifications(case, session) == []
    assert case["materials"].binding(session.token, binding.id) == binding


def test_successor_keeps_other_documents_and_does_not_follow_the_document_head(
    session, update_case, material_setup
):
    case = update_case
    other = case["materials"].import_text(
        session.token,
        str(uuid4()),
        material_setup[2].model_copy(
            update={"title": "Stable extra context", "text": "Keep the original context."}
        ),
    )
    extra = case["materials"].blocks(
        session.token, other.document_id, other.revision, "teaching"
    ).blocks[0].ref
    binding = case["materials"].bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=case["binding"].goal_id,
            purpose=case["binding"].purpose,
            expected_binding_revision=case["binding"].revision,
            refs=[*case["binding"].refs, extra],
        ),
    )
    case["binding"] = binding
    case["report"] = case["changes"].compare(
        session.token, str(uuid4()), change_input(binding, case["candidate"])
    )
    offer = ready_offer(case, session)
    third = revise(
        session,
        case["materials"],
        material_setup[2],
        case["candidate"],
        ORIGINAL.replace("print(x)", "print(x + 2)"),
    )
    assert third.revision == 3
    saved = case["updates"].decide(
        session.token, offer.id, str(uuid4()), decision_data(case, offer)
    )
    successor = case["materials"].binding(session.token, saved.successor_binding_id)
    assert extra in successor.refs
    assert {
        ref.document_revision
        for ref in successor.refs
        if ref.document_id == case["candidate"].document_id
    } == {2}
    assert case["materials"].binding(session.token, binding.id, binding.revision) == binding


def test_accept_marks_real_plan_and_derived_lesson_dependencies_without_overwriting_them(
    database, workflow, session, rag, consumer, monkeypatch
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    tutor, author_settings, _, materials, goal, original, binding, _, text = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    lesson_turn = tutor.submit_lesson(
        session.token,
        plan.id,
        str(uuid4()),
        LessonRequestInput(
            expected_plan_revision=1, node_key="iteration", instruction="Explain iteration."
        ),
    )
    advance_consumer_materials(database, session, author_settings, goal.id)
    with database.transaction() as connection:
        lesson_bindings = MaterialBindings(connection).for_scope(
            session.actor,
            goal.id,
            "lesson",
            plan_id=plan.id,
            plan_revision=1,
            node_key="iteration",
        )
    assert len(lesson_bindings) == 1 and lesson_bindings[0].id != binding.id
    citations = binding_citations(lesson_bindings)
    lesson_document = {
        "title": "Iteration",
        "introduction": "Read the sequence.",
        "sections": [
            {
                "heading": "Loop",
                "explanation": "The loop visits each item.",
                "code_example": "for x in items:\n    print(x)",
                "source_refs": [],
                "material_citations": [c.model_dump(mode="json") for c in citations],
            }
        ],
        "recall_prompts": ["What does each loop iteration visit?"],
    }
    gateway, _, _ = provider(author_settings, author=json.dumps(lesson_document))
    assert drain(tutor, author_settings, lesson_turn, gateway, session.token).status == "accepted"
    saved_lesson = workflow.snapshot(session.token).lessons[0]
    with database.transaction(snapshot=True) as connection:
        saved_plan = Plans(connection).get(session.actor, plan.id)
    candidate = revise(
        session, materials, text, original, ORIGINAL.replace("print(x)", "print(x + 1)")
    )
    settings = replace(rag["settings"], model_enabled=True)
    changes = MaterialChangeWorkflow(database)
    report = changes.compare(session.token, str(uuid4()), change_input(binding, candidate))
    case = {
        "database": database,
        "settings": settings,
        "rag": rag,
        "materials": materials,
        "original": original,
        "candidate": candidate,
        "binding": binding,
        "changes": changes,
        "report": report,
        "reviews": MaterialChangeReviewWorkflow(database, settings),
        "updates": MaterialUpdateWorkflow(database, settings),
        "notifications": NotificationsWorkflow(database),
    }
    offer = ready_offer(case, session)
    assert offer.migration_cost == "dependent_content_requires_reprepare"
    assert {(item.kind, item.id) for item in offer.impact.dependencies} == {
        ("plan", saved_plan.id),
        ("lesson", saved_lesson.id),
    }
    notice = notifications(case, session)[0]
    assert notice.payload.affected_plan_count == notice.payload.affected_lesson_count == 1
    accepted = case["updates"].decide(
        session.token, offer.id, str(uuid4()), decision_data(case, offer)
    )
    assert accepted.requires_reprepare == offer.impact.dependencies
    assert workflow.snapshot(session.token).lessons[0] == saved_lesson
    with database.transaction(snapshot=True) as connection:
        assert Plans(connection).get(session.actor, plan.id) == saved_plan
        marker = connection.execute(
            "SELECT state FROM learning.material_update_migrations WHERE decision_id=%s",
            (accepted.id,),
        ).fetchone()
    assert marker["state"] == "requires_reprepare"
    assert case["materials"].binding(session.token, binding.id, binding.revision) == binding


def test_update_api_reads_and_decision_replay_use_the_same_owned_receipt(
    workflow, session, update_case
):
    case = update_case
    offer = ready_offer(case, session)
    headers = {"Authorization": "Bearer " + session.token}
    with TestClient(create_app(case["settings"])) as client:
        response = client.get(f"/v1/material-update-offers/{offer.id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(offer.id)
        assert client.get(f"/v1/material-update-offers/{offer.id}").status_code == 401
        preparation = client.get(
            f"/v1/material-change-checks/{case['report'].id}/preparation", headers=headers
        )
        assert preparation.status_code == 200
        assert preparation.json()["offer_id"] == str(offer.id)
        notices = client.get("/v1/notifications", headers=headers)
        assert notices.status_code == 200 and len(notices.json()) == 1
        notice_id = notices.json()[0]["id"]
        read = client.post(f"/v1/notifications/{notice_id}/read", headers=headers)
        assert read.status_code == 200 and read.json()["state"] == "read"
        assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
        command_headers = {**headers, "Idempotency-Key": str(uuid4())}
        body = decision_data(case, offer).model_dump(mode="json")
        before = call_count(case, session)
        path = f"/v1/material-update-offers/{offer.id}/decisions"
        accepted = client.post(path, headers=command_headers, json=body)
        replayed = client.post(path, headers=command_headers, json=body)
        assert accepted.status_code == replayed.status_code == 201
        assert accepted.json() == replayed.json()
        assert accepted.json()["successor_binding_revision"] == case["binding"].revision + 1
        assert call_count(case, session) == before
        assert client.get(
            f"/v1/material-update-offers/{offer.id}", headers=headers
        ).status_code == 200
        receipt_path = path + "/" + command_headers["Idempotency-Key"]
        receipt = client.get(receipt_path, headers=headers)
        assert receipt.status_code == 200 and receipt.json() == accepted.json()
        assert client.get(path + "/" + str(uuid4()), headers=headers).status_code == 404
        wrong_offer = f"/v1/material-update-offers/{uuid4()}/decisions/"
        assert client.get(
            wrong_offer + command_headers["Idempotency-Key"], headers=headers
        ).status_code == 404
        other = workflow.create_session("Other receipt learner")
        assert client.get(
            receipt_path, headers={"Authorization": "Bearer " + other.token}
        ).status_code == 404
        case["materials"].revoke(
            session.token,
            case["candidate"].document_id,
            case["candidate"].revision,
            DocumentPermissionAction(action="revoke", expected_revision=1),
        )
        after_revocation = client.get(receipt_path, headers=headers)
        assert after_revocation.status_code == 200
        assert after_revocation.json() == accepted.json()
        assert "summary" not in after_revocation.json()
        assert call_count(case, session) == before


def test_retention_clears_automatic_update_text_but_preserves_owned_receipt_metadata(
    database, session, update_case
):
    case = update_case
    offer = ready_offer(case, session)
    key = str(uuid4())
    accepted = case["updates"].decide(
        session.token, offer.id, key, decision_data(case, offer)
    )
    successor = case["materials"].binding(session.token, accepted.successor_binding_id)
    preparation = case["updates"].get_preparation(session.token, case["report"].id)
    with database.transaction() as connection:
        command = connection.execute(
            "SELECT search_id FROM knowledge.material_search_commands "
            "WHERE actor_id=%s AND command_key=%s",
            (session.actor.id, "material-update:" + str(preparation.id)),
        ).fetchone()
        assert command["search_id"] == preparation.search_id
        before_search = connection.execute(
            "SELECT request->>'query' AS query FROM knowledge.material_searches WHERE id=%s",
            (preparation.search_id,),
        ).fetchone()
        assert before_search["query"]
        operations = connection.execute(
            "SELECT operation_id AS id FROM knowledge.material_change_reviews WHERE check_id=%s "
            "UNION SELECT id FROM knowledge.material_operations WHERE job_id=%s "
            "UNION SELECT id FROM knowledge.material_search_operations WHERE search_id=%s",
            (case["report"].id, preparation.job_id, preparation.search_id),
        ).fetchall()
        assert len(operations) >= 2
        connection.execute(
            "UPDATE knowledge.material_update_preparations SET search_id=NULL WHERE id=%s",
            (preparation.id,),
        )
        connection.execute(
            "UPDATE knowledge.document_permissions SET retain_until=now()-interval '1 second' "
            "WHERE document_id=%s AND document_revision=%s",
            (case["candidate"].document_id, case["candidate"].revision),
        )
    case["rag"]["intake"].expire_retained_inputs()
    with database.transaction(snapshot=True) as connection:
        current = connection.execute(
            "SELECT status,error_code FROM knowledge.material_update_preparations WHERE id=%s",
            (preparation.id,),
        ).fetchone()
        assert current["status"] == "cancelled"
        assert current["error_code"] == "material_retention_expired"
        search = connection.execute(
            "SELECT request->>'query' AS query,status FROM knowledge.material_searches WHERE id=%s",
            (preparation.search_id,),
        ).fetchone()
        assert search["query"] is None and search["status"] == "cancelled"
        demand = connection.execute(
            "SELECT status,specification FROM knowledge.material_demands WHERE id=%s",
            (preparation.demand_id,),
        ).fetchone()
        assert demand["status"] == "cancelled"
        assert demand["specification"]["required_facets"] == []
        assert demand["specification"]["optional_facets"] == []
        selections = connection.execute(
            "SELECT query,facets,coverage FROM knowledge.material_selections WHERE demand_id=%s",
            (preparation.demand_id,),
        ).fetchall()
        assert selections
        for selected in selections:
            assert selected["query"] is None and selected["facets"] == []
            assert selected["coverage"]["status"] == "unavailable"
            assert selected["coverage"]["required"] == []
            assert selected["coverage"]["missing_facets"] == []
        review = connection.execute(
            "SELECT result FROM knowledge.material_change_reviews WHERE check_id=%s",
            (case["report"].id,),
        ).fetchone()
        assert review["result"] is None
        calls = connection.execute(
            "SELECT request,response_body,status,applied FROM runtime.external_calls "
            "WHERE operation_ref=ANY(%s)",
            ([operation["id"] for operation in operations],),
        ).fetchall()
        assert len(calls) == len(operations)
        for call in calls:
            assert call["request"]["content_purged"] is True
            assert "input" not in call["request"] and "messages" not in call["request"]
            assert call["response_body"] is None
            assert call["status"] == "result_recorded" and call["applied"] is True
    assert case["updates"].decision_receipt(session.token, offer.id, key) == accepted
    assert case["materials"].binding(session.token, successor.id) == successor
    notice = notifications(case, session)[0]
    assert notice.state == "accepted" and notice.offer_id == offer.id
    with pytest.raises(BusinessError):
        case["updates"].get(session.token, offer.id)


def test_node_consumer_follows_only_an_explicitly_accepted_scoped_successor(
    database, workflow, session, rag, consumer, monkeypatch
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    tutor, author_settings, _, materials, goal, original, _, _, text = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    lesson_turn = tutor.submit_lesson(
        session.token,
        plan.id,
        str(uuid4()),
        LessonRequestInput(
            expected_plan_revision=1, node_key="iteration", instruction="Explain iteration."
        ),
    )
    advance_consumer_materials(database, session, author_settings, goal.id)
    with database.transaction() as connection:
        binding = MaterialBindings(connection).for_scope(
            session.actor,
            goal.id,
            "lesson",
            plan_id=plan.id,
            plan_revision=1,
            node_key="iteration",
        )[0]
    lesson_document = {
        "title": "Iteration",
        "introduction": "Read the sequence.",
        "sections": [
            {
                "heading": "Loop",
                "explanation": "The loop visits each item.",
                "code_example": "for x in items:\n    print(x)",
                "source_refs": [],
                "material_citations": [
                    citation.model_dump(mode="json") for citation in binding_citations([binding])
                ],
            }
        ],
        "recall_prompts": ["What does each loop iteration visit?"],
    }
    gateway, _, _ = provider(author_settings, author=json.dumps(lesson_document))
    assert drain(tutor, author_settings, lesson_turn, gateway, session.token).status == "accepted"
    saved_lesson = workflow.snapshot(session.token).lessons[0]
    with database.transaction(snapshot=True) as connection:
        saved_plan = Plans(connection).get(session.actor, plan.id)
    candidate = revise(
        session, materials, text, original, ORIGINAL.replace("print(x)", "print(x + 1)")
    )
    settings = replace(rag["settings"], model_enabled=True)
    changes = MaterialChangeWorkflow(database)
    report = changes.compare(session.token, str(uuid4()), change_input(binding, candidate))
    case = {
        "database": database,
        "settings": settings,
        "rag": rag,
        "materials": materials,
        "original": original,
        "candidate": candidate,
        "binding": binding,
        "changes": changes,
        "report": report,
        "reviews": MaterialChangeReviewWorkflow(database, settings),
        "updates": MaterialUpdateWorkflow(database, settings),
        "notifications": NotificationsWorkflow(database),
    }
    offer = ready_offer(case, session)
    accepted = case["updates"].decide(
        session.token, offer.id, str(uuid4()), decision_data(case, offer)
    )
    successor = materials.binding(session.token, accepted.successor_binding_id)
    focus = TeachingFocus(
        kind="node",
        plan_id=plan.id,
        expected_plan_revision=1,
        node_key="iteration",
        lesson_id=saved_lesson.id,
    )
    with database.transaction() as connection:
        node = saved_plan.active.document.nodes[0]
        resumed = ensure_node_binding_in(
            connection, session.actor, goal.id, focus, node, "lesson"
        )
    assert resumed == [successor]
    assert {ref.document_revision for ref in successor.refs} == {candidate.revision}
    assert workflow.snapshot(session.token).lessons[0] == saved_lesson
    with database.transaction(snapshot=True) as connection:
        assert Plans(connection).get(session.actor, plan.id) == saved_plan
    manual = materials.bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=goal.id,
            purpose="lesson",
            plan_id=plan.id,
            plan_revision=1,
            node_key="iteration",
            expected_binding_revision=successor.revision,
            refs=successor.refs[:1],
        ),
    )
    with database.transaction() as connection, pytest.raises(BusinessError) as failure:
        ensure_node_binding_in(connection, session.actor, goal.id, focus, node, "lesson")
    assert failure.value.code == "stale_version"
    assert materials.binding(session.token, manual.id) == manual
    assert materials.binding(session.token, binding.id, binding.revision) == binding


def test_historical_review_resumes_only_on_a_new_compare_key_without_reissuing_calls(
    database, session, update_case
):
    case = update_case
    reviewed = finish_review(case, session)
    assert reviewed.status == "reviewed" and reviewed.result.classification == "semantic_change"
    preparation = case["updates"].get_preparation(session.token, case["report"].id)
    assert preparation.status == "queued"
    assert preparation.job_id is preparation.search_id is preparation.offer_id is None
    with database.transaction() as connection:
        command = connection.execute(
            "SELECT command_key FROM knowledge.material_change_commands "
            "WHERE actor_id=%s AND check_id=%s",
            (session.actor.id, case["report"].id),
        ).fetchone()
        previous_call = connection.execute(
            "SELECT c.id,c.status,c.applied,c.request,c.response_body "
            "FROM runtime.external_calls c JOIN knowledge.material_change_reviews r "
            "ON r.operation_id=c.operation_ref WHERE r.id=%s",
            (reviewed.id,),
        ).fetchone()
        assert previous_call["status"] == "result_recorded" and previous_call["applied"] is True
        removed = connection.execute(
            "DELETE FROM knowledge.material_update_preparations WHERE id=%s "
            "AND status='queued' AND job_id IS NULL AND search_id IS NULL AND offer_id IS NULL "
            "RETURNING id",
            (preparation.id,),
        ).fetchone()
        assert removed["id"] == preparation.id
    before_calls = call_count(case, session)
    data = change_input(case["binding"], case["candidate"])
    assert case["changes"].get(session.token, case["report"].id) == case["report"]
    assert case["reviews"].get(session.token, case["report"].id) == reviewed
    assert case["updates"].get_preparation(session.token, case["report"].id) is None
    assert case["changes"].compare(session.token, command["command_key"], data) == case["report"]
    assert case["updates"].get_preparation(session.token, case["report"].id) is None
    keys = [str(uuid4()), str(uuid4())]
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(
            pool.map(lambda key: case["changes"].compare(session.token, key, data), keys)
        )
    assert reports == [case["report"], case["report"]]
    assert case["changes"].compare(session.token, keys[0], data) == case["report"]
    resumed = case["updates"].get_preparation(session.token, case["report"].id)
    assert resumed.status == "queued" and resumed.id != preparation.id
    assert resumed.job_id is resumed.search_id is resumed.offer_id is None
    assert case["reviews"].get(session.token, case["report"].id) == reviewed
    assert case["materials"].binding(session.token, case["binding"].id) == case["binding"]
    assert notifications(case, session) == [] and call_count(case, session) == before_calls
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.material_update_preparations WHERE check_id=%s",
            (case["report"].id,),
        ).fetchone()["n"] == 1
        current_call = connection.execute(
            "SELECT id,status,applied,request,response_body "
            "FROM runtime.external_calls WHERE id=%s",
            (previous_call["id"],),
        ).fetchone()
    assert current_call == previous_call
