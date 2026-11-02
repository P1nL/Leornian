import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import practice, prepare, submit_data
from test_item_supply import document, finish, request_data, run_model
from test_item_supply import supply_setup as supply_setup

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.transfer_contracts import TransferAnswer, TransferRequest
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply_contracts import ChoiceInput
from leornian.shared_kernel.errors import BusinessError


def fail_remediation(workflow, session, setup):
    _, accepted, (supply, _, _, _, _) = setup
    practice(session, setup, wrong=True)
    remediation = workflow.snapshot(session.token).remediations[0]
    supply.remediation(session.token, remediation.id)
    supply.answer(
        session.token,
        accepted.pack_id,
        str(uuid4()),
        ChoiceInput(slot="remediation_1", selected_key="B"),
    )
    return workflow.snapshot(session.token).remediations[0]


@pytest.fixture
def transfer_setup(database, workflow, session, gate_setup):
    remediation = fail_remediation(workflow, session, gate_setup)
    gates, old, setup = gate_setup
    supply, tutor, settings, plan, source = setup
    bank = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    value = document(source)
    for item in value["items"]:
        item["prompt"] = "Different contextual application: " + item["prompt"]
    run_model(tutor, settings, bank.run_id, value)
    finish(database, setup, bank)
    supply.publish(session.token, bank.pack_id)
    return TransferWorkflow(database, settings), remediation, bank, gate_setup


def relation_report(database, transfer_id, verdict="distinct_decision"):
    with database.transaction() as c:
        row = c.execute(
            "SELECT comparisons FROM assessment.transfer_checks WHERE id=%s", (transfer_id,)
        ).fetchone()
    return {
        "comparisons": [
            {**pair, "verdict": verdict, "reason": "Bounded offline relationship fixture."}
            for pair in row["comparisons"]
        ]
    }


def ready_transfer(database, session, setup):
    transfer, remediation, _, (_, _, (_, tutor, settings, _, _)) = setup
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    observed = []
    run_model(
        tutor,
        settings,
        row.relation_run_id,
        relation_report(database, row.id),
        observe=observed.append,
    )
    assert "correct_key" not in json.dumps(observed)
    assert "Private explanation for assessment" not in json.dumps(observed)
    return row


def test_no_published_candidate_has_no_assignment_or_model_run(
    database, workflow, session, gate_setup
):
    remediation = fail_remediation(workflow, session, gate_setup)
    settings = gate_setup[2][2]
    with pytest.raises(BusinessError) as error:
        TransferWorkflow(database, settings).request(
            session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
        )
    assert error.value.code == "no_transfer_candidate"
    assert not workflow.snapshot(session.token).transfers
    assert not workflow.snapshot(session.token).node_progress


def test_new_tutor_evaluation_invalidates_transfer_without_clearing_exposure(
    database, workflow, session, transfer_setup
):
    from leornian.bootstrap.evaluation import EvaluationWorkflow

    transfer, _, _, gate_setup = transfer_setup
    row = ready_transfer(database, session, transfer_setup)
    snapshot = workflow.snapshot(session.token)
    evaluation = snapshot.evaluations[0]
    tutor, settings = gate_setup[2][1:3]
    accepted = EvaluationWorkflow(database, settings).request(session.token, evaluation.id)
    with pytest.raises(BusinessError) as busy:
        transfer.open(session.token, row.id)
    assert busy.value.code == "run_active"
    run_model(
        tutor,
        settings,
        accepted.run_id,
        {
            "recorded_correct": evaluation.correct,
            "explanation": "基于锁定作答补充一种已讲解的情境。",
            "reflection": "在这个情境中判断条件会怎样影响结果？",
        },
    )
    with pytest.raises(BusinessError) as stale:
        transfer.open(session.token, row.id)
    assert stale.value.code == "stale_version"
    view = transfer.view(session.token, row.id)
    assert view.question is None and view.allowed_actions == ["cancel"]
    with database.transaction() as c:
        data = c.execute(
            "SELECT policy_version,comparisons FROM assessment.transfer_checks WHERE id=%s",
            (row.id,),
        ).fetchone()
    assert data["policy_version"] == "concept-transfer.v2"
    assert any(pair["right"] == "teaching_context" for pair in data["comparisons"])


def test_exact_transfer_is_private_until_open_once_scored_and_not_mastery(
    database, workflow, session, transfer_setup
):
    transfer, remediation, bank, gate_setup = transfer_setup
    gates, old, (supply, _, _, _, _) = gate_setup
    row = ready_transfer(database, session, transfer_setup)
    view = transfer.view(session.token, row.id)
    assert view.transfer.status == "ready" and view.question is None and view.result is None
    assert view.transfer.candidate_pack_id == bank.pack_id
    with pytest.raises(BusinessError):
        supply.practice(session.token, bank.pack_id)
    opened = transfer.open(session.token, row.id)
    assert opened.question.slot == opened.transfer.candidate_slot
    with pytest.raises(BusinessError):
        supply.answer(
            session.token,
            bank.pack_id,
            str(uuid4()),
            ChoiceInput(slot=opened.question.slot, selected_key="A"),
        )
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: transfer.submit(
                    session.token, row.id, key, TransferAnswer(selected_key="A")
                ),
                range(2),
            )
        )
    assert results[0] == results[1] and results[0].transfer.status == "passed"
    with pytest.raises(BusinessError):
        transfer.submit(session.token, row.id, str(uuid4()), TransferAnswer(selected_key="B"))
    snapshot = workflow.snapshot(session.token)
    original = next(item for item in snapshot.remediations if item.id == remediation.id)
    assert original.status == "not_passed" and original.transfer_required
    assert not snapshot.node_progress
    # Concept results already lock pack/slot globally: completed transfers retain
    # the existing ordinary read path, unlike a second code-submission purpose.
    assert len(supply.practice(session.token, bank.pack_id).questions) == 2
    reviewed_gate = prepare(database, session, gate_setup)
    with database.transaction() as c:
        context = c.execute(
            "SELECT context_data FROM assessment.concept_gates WHERE id=%s", (reviewed_gate.id,)
        ).fetchone()["context_data"]
    assert any(
        item.get("feedback")
        for item in context["training_and_exposure"]
        if item["key"].startswith("seen:" + str(bank.pack_id))
    )
    gates.start(session.token, reviewed_gate.id)
    assert (
        gates.submit(session.token, reviewed_gate.id, str(uuid4()), submit_data()).gate.status
        == "passed"
    )
    assert len(workflow.snapshot(session.token).node_progress) == 1


def test_wrong_transfer_locks_exact_successor_and_still_blocks_original_gate(
    database, workflow, session, transfer_setup
):
    transfer, remediation, _, gate_setup = transfer_setup
    row = ready_transfer(database, session, transfer_setup)
    transfer.open(session.token, row.id)
    failed = transfer.submit(session.token, row.id, str(uuid4()), TransferAnswer(selected_key="B"))
    assert failed.transfer.status == "not_passed" and failed.result.explanation
    with pytest.raises(BusinessError):
        transfer.request(
            session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
        )
    with pytest.raises(BusinessError):
        prepare(database, session, gate_setup)
    assert not workflow.snapshot(session.token).node_progress


@pytest.mark.parametrize("failure", ["uncertain", "answer_leakage", "missing_pair"])
def test_unqualified_candidates_never_open_or_reroll(database, session, transfer_setup, failure):
    transfer, remediation, _, (_, _, (_, tutor, settings, _, _)) = transfer_setup
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    report = relation_report(
        database, row.id, "distinct_decision" if failure == "missing_pair" else failure
    )
    if failure == "missing_pair":
        report["comparisons"].pop()
    run_model(tutor, settings, row.relation_run_id, report)
    view = transfer.view(session.token, row.id)
    assert view.transfer.status == "blocked" and view.question is None
    with pytest.raises(BusinessError):
        transfer.open(session.token, row.id)
    with pytest.raises(BusinessError) as error:
        transfer.request(
            session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
        )
    assert error.value.code == "no_transfer_candidate"


def test_source_change_invalidates_the_bound_successor(database, session, transfer_setup):
    transfer, _, bank, (_, _, (_, _, _, _, source)) = transfer_setup
    row = ready_transfer(database, session, transfer_setup)
    KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    with pytest.raises(BusinessError):
        transfer.open(session.token, row.id)
    assert transfer.view(session.token, row.id).blocked_reason == "source_not_current"


def test_unknown_transfer_relation_does_not_resend_and_cancels_together(
    database, session, transfer_setup
):
    transfer, remediation, _, (_, _, (_, tutor, settings, _, _)) = transfer_setup
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("Owned transfer timeout")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(row.relation_run_id)
    loop.run(row.relation_run_id)
    assert len(requests) == 1
    assert tutor.get(session.token, row.relation_run_id).status == "blocked_unknown"
    assert transfer.cancel(session.token, row.id).transfer.status == "cancelled"
    assert tutor.get(session.token, row.relation_run_id).status == "cancelled"


def test_transfer_http_ownership_extra_fields_and_atomic_feedback(
    database, workflow, session, transfer_setup, monkeypatch
):
    transfer, _, bank, (_, _, (_, _, settings, _, _)) = transfer_setup
    row = ready_transfer(database, session, transfer_setup)
    client = TestClient(create_app(settings))
    other = workflow.create_session("Other learner")
    path = f"/v1/transfers/{row.id}"
    assert client.get(path, headers={"Authorization": "Bearer " + other.token}).status_code == 404
    forged = client.post(
        path + "/submissions",
        headers={"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())},
        json={"selected_key": "A", "candidate_pack_id": str(bank.pack_id), "passed": True},
    )
    assert forged.status_code == 422
    transfer.open(session.token, row.id)
    record = Exposures.record

    def fail_feedback(self, actor, pack_id, question, feedback=None):
        if feedback is not None:
            raise RuntimeError("Offline rollback check")
        return record(self, actor, pack_id, question, feedback)

    monkeypatch.setattr(Exposures, "record", fail_feedback)
    with pytest.raises(RuntimeError):
        transfer.submit(session.token, row.id, str(uuid4()), TransferAnswer(selected_key="A"))
    view = transfer.view(session.token, row.id)
    assert view.transfer.status == "opened" and view.result is None
    assert not [
        r for r in workflow.snapshot(session.token).choice_results if r.pack_id == bank.pack_id
    ]


def test_server_selects_the_second_candidate_only_after_complete_pair_coverage(
    database, session, transfer_setup
):
    transfer, remediation, _, (_, _, (_, tutor, settings, _, _)) = transfer_setup
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    report = relation_report(database, row.id)
    first_key = report["comparisons"][0]["left"]
    for pair in report["comparisons"]:
        if pair["left"] == first_key:
            pair["verdict"] = "uncertain"
    run_model(tutor, settings, row.relation_run_id, report)
    view = transfer.view(session.token, row.id)
    assert view.transfer.status == "ready" and view.question is None
    assert view.transfer.candidate_slot == "practice_2"


def test_new_actual_exposure_blocks_open_without_erasing_the_relation_report(
    database, session, transfer_setup
):
    from leornian.modules.item_bank.supply import Packs

    transfer, _, bank, _ = transfer_setup
    row = ready_transfer(database, session, transfer_setup)
    with database.transaction() as c:
        item = Packs(c).transfer_material(session.actor, bank.pack_id, "practice_2")
        Exposures(c).record(session.actor, bank.pack_id, item)
    assert transfer.view(session.token, row.id).blocked_reason == "stale_version"
    with pytest.raises(BusinessError):
        transfer.open(session.token, row.id)
    with database.transaction() as c:
        assert c.execute(
            "SELECT relation_report FROM assessment.transfer_checks WHERE id=%s",
            (row.id,),
        ).fetchone()["relation_report"]


def test_late_transfer_receipt_survives_cancellation_without_assigning_a_question(
    database, session, transfer_setup
):
    transfer, remediation, _, (_, _, (_, tutor, settings, _, _)) = transfer_setup
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    report = relation_report(database, row.id)

    def respond(request):
        transfer.cancel(session.token, row.id)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": json.dumps(report)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(respond))).run(
        row.relation_run_id
    )
    view = transfer.view(session.token, row.id)
    assert view.transfer.status == "cancelled" and view.question is None
    assert view.transfer.candidate_pack_id is None
    with database.transaction() as c:
        receipt = c.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE run_id=%s",
            (row.relation_run_id,),
        ).fetchone()
    assert receipt["status"] == "result_recorded" and not receipt["applied"]


def test_published_but_too_hard_items_do_not_enter_transfer_review(
    database, workflow, session, gate_setup
):
    remediation = fail_remediation(workflow, session, gate_setup)
    _, _, setup = gate_setup
    supply, tutor, settings, plan, source = setup
    bank = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    value = document(source)
    for item in value["items"]:
        item["prompt"] = "Fresh but too difficult: " + item["prompt"]
        if item["slot"].startswith("practice_"):
            item["difficulty"] = 5
    run_model(tutor, settings, bank.run_id, value)
    finish(database, setup, bank)
    supply.publish(session.token, bank.pack_id)
    with pytest.raises(BusinessError) as error:
        TransferWorkflow(database, settings).request(
            session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
        )
    assert error.value.code == "no_transfer_candidate"
    assert not workflow.snapshot(session.token).transfers
