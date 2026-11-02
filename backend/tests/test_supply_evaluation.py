import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import practice
from test_item_supply import document, finish, run_model
from test_item_supply import supply_setup as supply_setup
from test_transfers import fail_remediation, relation_report

from leornian.bootstrap.evaluation import EvaluationWorkflow
from leornian.bootstrap.supply_demand import SupplyWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.transfer_contracts import TransferAnswer, TransferRequest
from leornian.modules.item_bank.demand_contracts import SupplyRequest, SupplyRevision
from leornian.modules.item_bank.supply_contracts import PackRequest
from leornian.modules.tutor.contracts import TurnInput
from leornian.shared_kernel.errors import BusinessError


def need_supply(database, workflow, session, gate_setup):
    remediation = fail_remediation(workflow, session, gate_setup)
    return SupplyWorkflow(database, gate_setup[2][2]), remediation


def demand_request():
    return SupplyRequest(
        expected_plan_revision=1, instruction="补充不同情境的基础循环练习。", automatic=False
    )


def finish_supply(database, session, gate_setup, demand, *, fail_role=None):
    supply, tutor, settings, _, source = gate_setup[2]
    value = document(source)
    for item in value["items"]:
        item["prompt"] = "Fresh supply situation: " + item["prompt"]
    run_model(tutor, settings, demand.pack.pending_run_id, value)
    finish(database, gate_setup[2], SimpleNamespace(pack_id=demand.pack.id), fail_role=fail_role)
    return supply


def test_demand_idempotent_full_pipeline_explicit_publication_exact_successor(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: demands.request(session.token, remediation.id, key, demand_request()),
                range(2),
            )
        )
    demand = results[0]
    assert results[0] == results[1]
    assert demand.allowed_difficulties == [1, 2] and demand.pack.revision == 1
    supply = finish_supply(database, session, gate_setup, demand)
    snapshot = workflow.snapshot(session.token)
    assert snapshot.supply_demands[0].pack.status == "ready"
    assert not snapshot.transfers and not snapshot.node_progress
    transfer = TransferWorkflow(database, gate_setup[2][2])
    with pytest.raises(BusinessError) as error:
        transfer.request(
            session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
        )
    assert error.value.code == "no_transfer_candidate"
    supply.publish(session.token, demand.pack.id)
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    observed = []
    run_model(
        gate_setup[2][1],
        gate_setup[2][2],
        row.relation_run_id,
        relation_report(database, row.id),
        observe=observed.append,
    )
    view = transfer.open(session.token, row.id)
    assert view.transfer.candidate_pack_id == demand.pack.id
    transfer.submit(session.token, row.id, str(uuid4()), TransferAnswer(selected_key="A"))
    snapshot = workflow.snapshot(session.token)
    assert len([e for e in snapshot.evaluations if e.source_kind == "transfer"]) == 1
    assert not snapshot.node_progress and "correct_key" not in json.dumps(observed)
    with pytest.raises(BusinessError):
        demands.request(session.token, remediation.id, str(uuid4()), demand_request())


def test_supply_rejects_existing_published_inventory_and_has_no_half_demand(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    supply, tutor, settings, plan, source = gate_setup[2]
    accepted = supply.submit(
        session.token,
        plan.id,
        str(uuid4()),
        PackRequest(expected_plan_revision=1, node_key="loops", instruction="New context."),
    )
    value = document(source)
    for item in value["items"]:
        item["prompt"] = "Inventory contextual decision: " + item["prompt"]
    run_model(tutor, settings, accepted.run_id, value)
    finish(database, gate_setup[2], accepted)
    supply.publish(session.token, accepted.pack_id)
    with pytest.raises(BusinessError):
        demands.request(session.token, remediation.id, str(uuid4()), demand_request())
    assert not workflow.snapshot(session.token).supply_demands


def test_supply_revision_uses_actual_failed_transfer_report_without_new_root(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(session.token, remediation.id, str(uuid4()), demand_request())
    finish_supply(database, session, gate_setup, demand).publish(session.token, demand.pack.id)
    transfer = TransferWorkflow(database, gate_setup[2][2])
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    run_model(
        gate_setup[2][1],
        gate_setup[2][2],
        row.relation_run_id,
        relation_report(database, row.id, verdict="uncertain"),
    )
    child = demands.revise(
        session.token,
        demand.id,
        SupplyRevision(
            expected_pack_revision=1,
            instruction="纠正这份关系报告指出的同情境问题。",
            transfer_feedback_id=row.id,
        ),
    )
    assert child.pack.revision == 2 and child.pack.predecessor_id == demand.pack.id
    assert child.pack.supply_demand_id == demand.id
    assert child.pack.transfer_feedback_id == row.id and child.pack.reviewed_roles == []
    with database.transaction() as c:
        feedback = c.execute(
            "SELECT transfer_feedback FROM item_bank.packs WHERE id=%s", (child.pack.id,)
        ).fetchone()["transfer_feedback"]
    assert feedback["report"]["comparisons"]
    assert workflow.snapshot(session.token).remediations[0].status == "not_passed"


def test_supply_revision_keeps_demand_and_rechecks_all_roles(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(session.token, remediation.id, str(uuid4()), demand_request())
    finish_supply(database, session, gate_setup, demand, fail_role="difficulty")
    data = SupplyRevision(expected_pack_revision=1, instruction="修正审核发现，保留不同情境。")
    child = demands.revise(session.token, demand.id, data)
    assert demands.revise(session.token, demand.id, data) == child
    assert child.pack.revision == 2 and child.pack.supply_demand_id == demand.id
    assert child.pack.reviewed_roles == [] and child.pack.blind_passed is None
    assert child.pack.predecessor_id == demand.pack.id
    with pytest.raises(BusinessError):
        demands.request(session.token, remediation.id, str(uuid4()), demand_request())


def test_supply_rejects_author_wrong_difficulty_and_does_not_publish(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(session.token, remediation.id, str(uuid4()), demand_request())
    value = document(gate_setup[2][4])
    for item in value["items"]:
        item["prompt"] = "Not a duplicate: " + item["prompt"]
        if item["slot"].startswith("practice"):
            item["difficulty"] = 5
    run_model(gate_setup[2][1], gate_setup[2][2], demand.pack.pending_run_id, value)
    assert workflow.snapshot(session.token).supply_demands[0].pack.status == "failed"
    assert not workflow.snapshot(session.token).transfers


def test_evaluation_exact_receipt_once_public_only_and_no_score_mutation(
    database, workflow, session, gate_setup
):
    practice(session, gate_setup, wrong=True)
    _, _, (_, tutor, settings, _, _) = gate_setup
    evaluation = next(e for e in workflow.snapshot(session.token).evaluations if not e.correct)
    service = EvaluationWorkflow(database, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(pool.map(lambda _: service.request(session.token, evaluation.id), range(2)))
    assert accepted[0] == accepted[1]
    observed = []
    run_model(
        tutor,
        settings,
        accepted[0].run_id,
        {
            "recorded_correct": False,
            "explanation": "这次作答不正确，应区分循环体与退出条件。",
            "reflection": "没有元素时循环体会执行吗？",
        },
        observe=observed.append,
    )
    snapshot = workflow.snapshot(session.token)
    current = next(e for e in snapshot.evaluations if e.id == evaluation.id)
    assert current.document and not current.document.recorded_correct
    assert service.request(session.token, evaluation.id) == accepted[0]
    wire = json.dumps(observed)
    assert "correct_key" not in wire and "assessment_1" not in wire
    assert "Private explanation for assessment" not in wire
    assert not snapshot.node_progress
    assert len([t for c in snapshot.turns for t in c.turns if t.purpose == "evaluation"]) == 1


def test_evaluation_cannot_override_locked_score_or_preempt_foreground(
    database, workflow, session, gate_setup
):
    practice(session, gate_setup, wrong=True)
    _, _, (_, tutor, settings, _, _) = gate_setup
    evaluation = next(e for e in workflow.snapshot(session.token).evaluations if not e.correct)
    service = EvaluationWorkflow(database, settings)
    conversation = tutor.conversation(session.token, workflow.snapshot(session.token).goals[0].id)
    active = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="我有新问题")
    )
    with pytest.raises(BusinessError) as error:
        service.request(session.token, evaluation.id)
    assert error.value.code == "run_active"
    assert (
        next(
            e for e in workflow.snapshot(session.token).evaluations if e.id == evaluation.id
        ).run_id
        is None
    )
    tutor.cancel(session.token, active.run_id)
    accepted = service.request(session.token, evaluation.id)
    run_model(
        tutor,
        settings,
        accepted.run_id,
        {
            "recorded_correct": True,
            "explanation": "Forged pass.",
            "reflection": "Done?",
        },
    )
    snapshot = workflow.snapshot(session.token)
    assert tutor.get(session.token, accepted.run_id).error_code == "invalid_evaluation_output"
    assert next(e for e in snapshot.evaluations if e.id == evaluation.id).document is None
    assert not next(r for r in snapshot.choice_results if r.id == evaluation.source_id).correct


def test_supply_and_evaluation_http_ownership_and_no_client_gold(
    database, workflow, session, gate_setup
):
    _, remediation = need_supply(database, workflow, session, gate_setup)
    client = TestClient(create_app(gate_setup[2][2]))
    other = workflow.create_session("Not the owner")
    headers = {"Authorization": "Bearer " + other.token, "Idempotency-Key": str(uuid4())}
    response = client.post(
        f"/v1/remediations/{remediation.id}/supply-requests",
        headers=headers,
        json=demand_request().model_dump(),
    )
    assert response.status_code == 404
    evaluation = workflow.snapshot(session.token).evaluations[0]
    assert client.post(f"/v1/evaluations/{evaluation.id}/run", headers=headers).status_code == 404
    assert not workflow.snapshot(session.token).supply_demands
