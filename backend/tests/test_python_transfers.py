import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import finish, run_model
from test_item_supply import supply_setup as supply_setup
from test_python_execution import (
    code_document,
    owned_claim,
    prepare_python_gate,
    program,
    publish_python,
    receipt,
    submission,
)
from test_python_execution import python_setup as python_setup
from test_runner import runner as runner
from test_transfers import relation_report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.evaluation import EvaluationWorkflow
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.supply_demand import SupplyWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.contracts import Submission
from leornian.modules.assessment.python_contracts import PythonTraining
from leornian.modules.assessment.transfer_contracts import TransferAnswer, TransferRequest
from leornian.modules.item_bank.demand_contracts import SupplyRequest, SupplyRevision
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply_contracts import SLOTS, PackRequest
from leornian.shared_kernel.errors import BusinessError


def request_data():
    return TransferRequest(expected_plan_revision=1)


def fail_python_remediation(database, session, setup, *, runner=None):
    python, accepted, _ = setup
    publish_python(database, session, setup, runner=runner)
    python.training(session.token, accepted.pack_id)
    origin = None
    for slot in ("practice_1", "practice_2", "remediation_1"):
        if slot == "remediation_1":
            python.training(session.token, accepted.pack_id, remediation=True)
        code = program(slot) if slot == "practice_2" else "print(0)"
        attempt = python.submit_training(
            session.token, accepted.pack_id, str(uuid4()), PythonTraining(slot=slot, code=code)
        )
        claim = owned_claim(database, session, attempt.id)
        JourneyWorkflow(database).report(
            claim.job_id, receipt(database, claim, runner, wrong=slot != "practice_2")
        )
        if slot == "remediation_1":
            origin = attempt
    return origin


def complete_candidate(database, session, setup, accepted, *, runner=None):
    _, _, gate = setup
    supply, tutor, settings, _, source = gate[2]
    value = code_document(source)
    for item in value["items"]:
        item["prompt"] = "Another application fixture: " + item["prompt"]
    run_model(tutor, settings, accepted.run_id, value)
    pack = supply.get(session.token, accepted.pack_id)
    run_model(
        tutor,
        settings,
        pack.pending_run_id,
        {"programs": [{"slot": slot, "code": program(slot)} for slot in SLOTS]},
    )
    for _ in range(5):
        claim = owned_claim(database, session)
        JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, runner))
    finish(database, gate[2], accepted)
    return supply.get(session.token, accepted.pack_id)


def candidate(database, session, setup, *, runner=None):
    _, _, gate = setup
    supply, _, _, plan, _ = gate[2]
    accepted = supply.submit(
        session.token,
        plan.id,
        str(uuid4()),
        PackRequest(
            expected_plan_revision=1,
            node_key="loops",
            instruction="A reviewed fresh code context.",
            kind="python_io",
        ),
    )
    complete_candidate(database, session, setup, accepted, runner=runner)
    return supply.publish(session.token, accepted.pack_id)


@pytest.fixture
def python_transfer_setup(database, session, python_setup):
    origin = fail_python_remediation(database, session, python_setup)
    bank = candidate(database, session, python_setup)
    transfer = TransferWorkflow(database, python_setup[2][2][2])
    return transfer, origin, bank, python_setup


def ready(database, session, setup, *, verdict="distinct_decision"):
    transfer, origin, _, python_setup = setup
    _, tutor, settings, _, _ = python_setup[2][2]
    row = transfer.request(
        session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
    )
    observed = []
    run_model(
        tutor,
        settings,
        row.relation_run_id,
        relation_report(database, row.id, verdict),
        observe=observed.append,
    )
    wire = json.dumps(observed)
    assert '"tests":' not in wire and '"test_cases":' not in wire
    assert '"correct_key":' not in wire and '"explanation": "已锁定程序的训练说明' not in wire
    assert "teaching_context" in wire and "python_io" in wire
    return row


def submit(database, session, setup, *, code=None):
    transfer, _, _, _ = setup
    row = ready(database, session, setup)
    opened = transfer.open(session.token, row.id)
    view = transfer.submit_python(
        session.token,
        row.id,
        str(uuid4()),
        Submission(code=code or program(opened.transfer.candidate_slot)),
    )
    return view, owned_claim(database, session, view.python_attempt.id)


def test_python_successor_is_private_reserved_locked_and_only_unblocks_original_gate(
    database, workflow, session, python_transfer_setup
):
    transfer, origin, bank, setup = python_transfer_setup
    python, _, gate_setup = setup
    row = ready(database, session, python_transfer_setup)
    view = transfer.view(session.token, row.id)
    assert view.transfer.kind == "python_io" and view.question is None
    assert view.transfer.remediation_id is None
    assert view.transfer.python_remediation_id == origin.id
    with pytest.raises(BusinessError):
        python.training(session.token, bank.id)
    opened = transfer.open(session.token, row.id)
    assert opened.question.language == "python_io" and "tests" not in opened.model_dump_json()
    with pytest.raises(BusinessError):
        transfer.submit(session.token, row.id, str(uuid4()), TransferAnswer(selected_key="A"))
    data = Submission(code=program(opened.transfer.candidate_slot))
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        views = list(
            pool.map(lambda _: transfer.submit_python(session.token, row.id, key, data), range(2))
        )
    assert views[0] == views[1] and views[0].transfer.status == "submitted"
    assert views[0].allowed_actions == ["cancel"]
    with pytest.raises(BusinessError):
        python.submit_training(
            session.token,
            bank.id,
            str(uuid4()),
            PythonTraining(slot=opened.transfer.candidate_slot, code=data.code),
        )
    claim = owned_claim(database, session, views[0].python_attempt.id)
    report = receipt(database, claim)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: JourneyWorkflow(database).report(claim.job_id, report), range(2)))
    done = transfer.view(session.token, row.id)
    assert done.transfer.status == "passed" and done.python_attempt.status == "passed"
    assert transfer.submit_python(session.token, row.id, key, data) == done
    with pytest.raises(BusinessError):
        transfer.submit_python(session.token, row.id, str(uuid4()), data)
    snapshot = workflow.snapshot(session.token)
    assert next(a for a in snapshot.python_attempts if a.id == origin.id).status == "not_passed"
    assert not snapshot.execution_progress and not snapshot.node_progress
    assert any(e.source_id == done.python_attempt.id for e in snapshot.evaluations)
    gates, gate = prepare_python_gate(database, session, setup)
    with database.transaction() as c:
        context = c.execute(
            "SELECT context_data FROM assessment.concept_gates WHERE id=%s", (gate.id,)
        ).fetchone()["context_data"]
    assert any(
        entry.get("feedback", {}).get("attempt_id") == str(done.python_attempt.id)
        for entry in context["training_and_exposure"]
    )
    gates.start(session.token, gate.id)
    python.submit_gate(session.token, gate.id, str(uuid4()), submission())
    for _ in range(2):
        gate_claim = owned_claim(database, session)
        JourneyWorkflow(database).report(gate_claim.job_id, receipt(database, gate_claim))
    assert len(workflow.snapshot(session.token).execution_progress) == 1
    assert not workflow.snapshot(session.token).node_progress
    assert gate_setup[0].view(session.token, gate.id).gate.status == "passed"


def test_wrong_python_successor_never_unblocks_gate_or_allows_a_training_route_retake(
    database, workflow, session, python_transfer_setup
):
    transfer, origin, bank, setup = python_transfer_setup
    view, claim = submit(database, session, python_transfer_setup, code="print(0)")
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, wrong=True))
    done = transfer.view(session.token, view.transfer.id)
    assert done.transfer.status == "not_passed"
    assert done.python_attempt.passed_cases < 3
    with pytest.raises(BusinessError):
        prepare_python_gate(database, session, setup)
    with pytest.raises(BusinessError):
        transfer.request(
            session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
        )
    with pytest.raises(BusinessError):
        setup[0].submit_training(
            session.token,
            bank.id,
            str(uuid4()),
            PythonTraining(
                slot=done.transfer.candidate_slot, code=program(done.transfer.candidate_slot)
            ),
        )
    assert not workflow.snapshot(session.token).execution_progress


@pytest.mark.parametrize("change", ["cancel", "expired", "source", "teaching", "session"])
def test_late_or_stale_code_successor_keeps_runner_fact_without_eligibility_or_rerun(
    database, workflow, session, python_transfer_setup, change
):
    transfer, origin, bank, setup = python_transfer_setup
    view, claim = submit(database, session, python_transfer_setup)
    report = receipt(database, claim)
    if change == "cancel":
        transfer.cancel(session.token, view.transfer.id)
    elif change == "expired":
        with database.transaction() as c:
            c.execute(
                "UPDATE execution.jobs SET lease_until=now()-interval '1 second' WHERE id=%s",
                (claim.job_id,),
            )
        JourneyWorkflow(database).expire_executions()
    elif change == "source":
        KnowledgeWorkflow(database).revoke(session.token, setup[2][2][4].id, 1)
    elif change == "teaching":
        evaluation = next(
            e for e in workflow.snapshot(session.token).evaluations if e.source_id == origin.id
        )
        tutor, settings = setup[2][2][1:3]
        accepted = EvaluationWorkflow(database, settings).request(session.token, evaluation.id)
        run_model(
            tutor,
            settings,
            accepted.run_id,
            {
                "recorded_correct": False,
                "explanation": "新增解释了这份程序的循环逻辑。",
                "reflection": "再分析另一个情境。",
            },
        )
    else:
        with database.transaction() as c:
            c.execute(
                "UPDATE identity.sessions SET revoked_at=now() WHERE actor_id=%s",
                (session.actor.id,),
            )
    JourneyWorkflow(database).report(claim.job_id, report)
    JourneyWorkflow(database).report(claim.job_id, report)
    with database.transaction() as c:
        row = c.execute(
            "SELECT * FROM assessment.transfer_checks WHERE id=%s", (view.transfer.id,)
        ).fetchone()
        result = c.execute(
            "SELECT * FROM assessment.python_attempts WHERE id=%s", (view.python_attempt.id,)
        ).fetchone()
        jobs = c.execute(
            "SELECT report FROM execution.jobs WHERE python_input_ref=%s", (view.python_attempt.id,)
        ).fetchall()
        evidence = c.execute(
            "SELECT 1 FROM learning.execution_evidence WHERE actor_id=%s", (session.actor.id,)
        ).fetchone()
    assert row["status"] == ("cancelled" if change == "cancel" else "error")
    assert result["status"] == "error" and not evidence
    assert len(jobs) == 1 and (
        jobs[0]["report"].get("cases") or jobs[0]["report"].get("late_receipt")
    )
    if change != "session":
        with pytest.raises(BusinessError):
            transfer.request(
                session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
            )
        with pytest.raises(BusinessError):
            setup[0].training(session.token, bank.id)


def test_code_successor_without_eligible_inventory_creates_no_half_assignment(
    database, workflow, session, python_setup
):
    origin = fail_python_remediation(database, session, python_setup)
    service = TransferWorkflow(database, python_setup[2][2][2])
    with pytest.raises(BusinessError) as missing:
        service.request(
            session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
        )
    assert missing.value.code == "no_transfer_candidate"  # Existing choice pack cannot substitute.
    assert not workflow.snapshot(session.token).transfers
    with pytest.raises(BusinessError):
        service.request(session.token, origin.id, str(uuid4()), request_data())


@pytest.mark.parametrize("failure", ["uncertain", "missing_pair"])
def test_python_relation_never_leaks_tests_or_rechecks_used_candidates(
    database, workflow, session, python_transfer_setup, failure
):
    transfer, origin, _, setup = python_transfer_setup
    tutor, settings = setup[2][2][1:3]
    row = transfer.request(
        session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
    )
    report = relation_report(
        database, row.id, "uncertain" if failure == "uncertain" else "distinct_decision"
    )
    if failure == "missing_pair":
        report["comparisons"].pop()
    run_model(tutor, settings, row.relation_run_id, report)
    view = transfer.view(session.token, row.id)
    assert view.transfer.status == "blocked" and view.question is None
    with pytest.raises(BusinessError) as missing:
        transfer.request(
            session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
        )
    assert missing.value.code == "no_transfer_candidate"
    assert not workflow.snapshot(session.token).execution_progress


def test_code_relation_unknown_is_not_resent_or_replaced_by_a_new_key(
    database, session, python_transfer_setup
):
    transfer, origin, _, setup = python_transfer_setup
    tutor, settings = setup[2][2][1:3]
    row = transfer.request(
        session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
    )
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("Owned Python transfer timeout")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(row.relation_run_id)
    loop.run(row.relation_run_id)
    assert len(calls) == 1
    assert tutor.get(session.token, row.relation_run_id).status == "blocked_unknown"
    with pytest.raises(BusinessError):
        transfer.request(
            session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
        )
    transfer.cancel(session.token, row.id)
    assert tutor.get(session.token, row.relation_run_id).status == "cancelled"


def test_code_completion_feedback_evaluation_and_runner_receipt_roll_back_together(
    database, workflow, session, python_transfer_setup, monkeypatch
):
    transfer, _, _, _ = python_transfer_setup
    view, claim = submit(database, session, python_transfer_setup)
    report = receipt(database, claim)
    original = Exposures.record

    def unavailable(self, actor, pack_id, question, feedback=None):
        if feedback is not None:
            raise RuntimeError("Feedback storage unavailable")
        return original(self, actor, pack_id, question, feedback)

    monkeypatch.setattr(Exposures, "record", unavailable)
    with pytest.raises(RuntimeError):
        JourneyWorkflow(database).report(claim.job_id, report)
    assert transfer.view(session.token, view.transfer.id).transfer.status == "submitted"
    snapshot = workflow.snapshot(session.token)
    assert (
        next(a for a in snapshot.python_attempts if a.id == view.python_attempt.id).status
        == "queued"
    )
    assert not any(e.source_id == view.python_attempt.id for e in snapshot.evaluations)
    monkeypatch.setattr(Exposures, "record", original)
    JourneyWorkflow(database).report(claim.job_id, report)  # Receipt replay, not code re-execution.
    assert transfer.view(session.token, view.transfer.id).transfer.status == "passed"


def test_python_supply_reuses_quality_pipeline_and_publishes_before_exact_selection(
    database, workflow, session, python_setup
):
    origin = fail_python_remediation(database, session, python_setup)
    settings = python_setup[2][2][2]
    supply = SupplyWorkflow(database, settings)
    data = SupplyRequest(
        expected_plan_revision=1, instruction="用另一种情境检查代码迁移。", automatic=False
    )
    key = str(uuid4())
    demand = supply.request(session.token, origin.id, key, data, required_kind="python_io")
    assert supply.request(session.token, origin.id, key, data, required_kind="python_io") == demand
    assert demand.remediation_id is None and demand.python_remediation_id == origin.id
    assert demand.kind == demand.pack.kind == "python_io" and demand.allowed_difficulties == [1, 2]
    accepted = SimpleNamespace(pack_id=demand.pack.id, run_id=demand.pack.pending_run_id)
    complete_candidate(database, session, python_setup, accepted)
    transfer = TransferWorkflow(database, settings)
    with pytest.raises(BusinessError):
        transfer.request(
            session.token, origin.id, str(uuid4()), request_data(), required_kind="python_io"
        )
    python_setup[2][2][0].publish(session.token, demand.pack.id)
    row = ready(
        database, session, (transfer, origin, demand.pack, python_setup), verdict="uncertain"
    )
    child = supply.revise(
        session.token,
        demand.id,
        SupplyRevision(
            expected_pack_revision=1,
            instruction="按照实际关系失败修订代码题情境。",
            transfer_feedback_id=row.id,
        ),
    )
    assert child.pack.kind == "python_io" and child.pack.revision == 2
    assert child.pack.supply_demand_id == demand.id and not child.pack.reviewed_roles
    assert child.pack.transfer_feedback_id == row.id
    with pytest.raises(BusinessError):
        supply.request(session.token, origin.id, str(uuid4()), data, required_kind="python_io")
    assert not workflow.snapshot(session.token).execution_progress


def test_code_transfer_http_current_origin_ownership_and_server_only_scoring(
    database, workflow, session, python_transfer_setup
):
    transfer, origin, bank, setup = python_transfer_setup
    settings = setup[2][2][2]
    client = TestClient(create_app(settings))
    other = workflow.create_session("Different code transfer learner")
    path = f"/v1/python-attempts/{origin.id}/transfer-requests"
    headers = {"Authorization": "Bearer " + other.token, "Idempotency-Key": str(uuid4())}
    assert client.post(path, headers=headers, json=request_data().model_dump()).status_code == 404
    headers["Authorization"] = "Bearer " + session.token
    accepted = client.post(path, headers=headers, json=request_data().model_dump())
    assert accepted.status_code == 202 and accepted.json()["kind"] == "python_io"
    row = transfer.view(session.token, accepted.json()["id"]).transfer
    run_model(setup[2][2][1], settings, row.relation_run_id, relation_report(database, row.id))
    path = f"/v1/transfers/{row.id}"
    assert client.get(path, headers=headers).json()["question"] is None
    assert client.post(path + "/open", headers=headers).status_code == 200
    response = client.post(
        path + "/execution-submissions",
        headers=headers,
        json={
            "code": program("practice_1"),
            "passed": True,
            "pack_id": str(bank.id),
        },
    )
    assert response.status_code == 422
    response = client.post(
        path + "/execution-submissions", headers=headers, json={"code": program("practice_1")}
    )
    assert response.status_code == 202 and response.json()["transfer"]["status"] == "submitted"
    assert "test_cases" not in response.text and '"tests":' not in response.text


@pytest.mark.skipif(
    os.environ.get("LEORNIAN_TEST_DOCKER") != "1",
    reason="Explicit real Docker code transfer acceptance",
)
def test_real_docker_failed_remediation_fresh_successor_then_formal_gate(
    database, workflow, session, python_setup, runner
):
    origin = fail_python_remediation(database, session, python_setup, runner=runner)
    bank = candidate(database, session, python_setup, runner=runner)
    transfer = TransferWorkflow(database, python_setup[2][2][2])
    view, claim = submit(database, session, (transfer, origin, bank, python_setup))
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, runner))
    done = transfer.view(session.token, view.transfer.id)
    assert done.transfer.status == "passed" and done.python_attempt.passed_cases == 3
    assert not workflow.snapshot(session.token).execution_progress
    gates, gate = prepare_python_gate(database, session, python_setup)
    gates.start(session.token, gate.id)
    python_setup[0].submit_gate(session.token, gate.id, str(uuid4()), submission())
    for _ in range(2):
        gate_claim = owned_claim(database, session)
        JourneyWorkflow(database).report(gate_claim.job_id, receipt(database, gate_claim, runner))
    assert gates.view(session.token, gate.id).gate.status == "passed"
    assert len(workflow.snapshot(session.token).execution_progress) == 1
    assert not workflow.snapshot(session.token).node_progress
