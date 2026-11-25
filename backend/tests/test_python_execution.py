import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import relation_document
from test_item_supply import finish, run_model
from test_item_supply import supply_setup as supply_setup
from test_runner import runner as runner

from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.python_execution import PythonWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.gate_contracts import GateRequest
from leornian.modules.assessment.python_contracts import PythonGateSubmission, PythonTraining
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import CaseOutput, RunnerReport
from leornian.modules.item_bank.supply_contracts import SLOTS, PackRequest
from leornian.modules.tutor.contracts import TurnInput
from leornian.shared_kernel.errors import BusinessError

EXPRESSIONS = {
    "practice_1": "sum(xs)",
    "practice_2": "sum(1 for x in xs if x > 0)",
    "assessment_1": "sum(abs(x) for x in xs)",
    "assessment_2": "max(xs) if xs else 0",
    "remediation_1": "sum(1 for x in xs if x % 2 == 0)",
}
EXPECTED = {
    "practice_1": [6, 0, -3],
    "practice_2": [3, 0, 1],
    "assessment_1": [6, 0, 7],
    "assessment_2": [3, 0, 2],
    "remediation_1": [1, 0, 2],
}


def program(slot):
    return "import json,sys\nxs=json.load(sys.stdin)\nprint(" + EXPRESSIONS[slot] + ")"


def code_document(source):
    return {
        "items": [
            {
                "slot": slot,
                "language": "python_io",
                "title": "Python " + slot,
                "prompt": "Implement this distinct fixture objective: " + EXPRESSIONS[slot],
                "starter_code": "import json,sys\nxs=json.load(sys.stdin)\nprint(0)",
                "sample": {"input": [1, 2, 3], "expected": EXPECTED[slot][0]},
                "tests": [
                    {"input": value, "expected": expected}
                    for value, expected in zip(
                        [[1, 2, 3], [], [-4, 2, -1]], EXPECTED[slot], strict=True
                    )
                ],
                "difficulty": 1 if slot == "remediation_1" else 2,
                "explanation": "已锁定程序的训练说明 " + slot,
                "source_refs": [{"source_id": str(source.id), "revision": 1}],
            }
            for slot in SLOTS
        ]
    }


def owned_claim(database, session, attempt_id=None, runner_id="fixture"):
    # Scope fixture control to this test's actor; never consume another test's queued execution.
    with database.transaction() as c:
        row = c.execute(
            "SELECT * FROM execution.jobs WHERE actor_id=%s AND status='queued' "
            "AND (%s::uuid IS NULL OR COALESCE(python_input_ref,input_ref)=%s) "
            "ORDER BY created_at,id "
            "LIMIT 1 FOR UPDATE",
            (session.actor.id, attempt_id, attempt_id),
        ).fetchone()
        if row is None:
            return None
        claim_token = uuid4()
        c.execute(
            "UPDATE execution.jobs SET status='running',claim_token=%s,runner_id=%s,"
            "lease_until=now()+interval '90 seconds' WHERE id=%s",
            (claim_token, runner_id, row["id"]),
        )
        return JourneyWorkflow.claim_in(c, {**row, "claim_token": claim_token})


def receipt(database, claim, runner=None, wrong=False):
    if runner:
        cases = [
            CaseOutput.model_validate(runner.execute_case(claim.code, value))
            for value in claim.inputs
        ]
    else:
        with database.transaction() as c:
            row = c.execute(
                "SELECT a.test_cases FROM assessment.python_attempts a JOIN execution.jobs j "
                "ON j.python_input_ref=a.id WHERE j.id=%s",
                (claim.job_id,),
            ).fetchone()
        cases = [
            CaseOutput(
                exit_code=0,
                stdout=json.dumps(0 if wrong else case["expected"]),
                stderr="",
                outcome="completed",
            )
            for case in row["test_cases"]
        ]
    return RunnerReport(claim_token=claim.claim_token, cases=cases)


@pytest.fixture
def python_setup(database, session, gate_setup):
    supply, tutor, settings, plan, source = gate_setup[2]
    accepted = supply.submit(
        session.token,
        plan.id,
        str(uuid4()),
        PackRequest(
            expected_plan_revision=1,
            node_key="loops",
            instruction="Five Python IO tasks.",
            kind="python_io",
            automatic=False,
        ),
    )
    run_model(tutor, settings, accepted.run_id, code_document(source))
    pack = supply.get(session.token, accepted.pack_id)
    observed = []
    run_model(
        tutor,
        settings,
        pack.pending_run_id,
        {"programs": [{"slot": slot, "code": program(slot)} for slot in SLOTS]},
        observe=observed.append,
    )
    context = json.loads(observed[0]["messages"][1]["content"])
    assert all("tests" not in q and "explanation" not in q for q in context["questions"])
    assert supply.get(session.token, pack.id).status == "qualifying"
    try:
        yield PythonWorkflow(database), accepted, gate_setup
    finally:
        with database.transaction() as c:
            rows = c.execute(
                "SELECT id FROM execution.jobs WHERE actor_id=%s "
                "AND status IN ('queued','running')",
                (session.actor.id,),
            ).fetchall()
            for row in rows:
                Execution(c).abandon(row["id"], "test_fixture_closed")


def publish_python(database, session, setup, *, runner=None):
    _, accepted, gate_setup = setup
    supply = gate_setup[2][0]
    for _ in range(5):
        claim = owned_claim(database, session)
        assert "expected" not in claim.model_dump_json()
        JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, runner))
    finish(database, gate_setup[2], accepted)
    assert supply.get(session.token, accepted.pack_id).status == "ready"
    return supply.publish(session.token, accepted.pack_id)


def train(database, session, setup, *, wrong=False, runner=None):
    python, accepted, _ = setup
    python.training(session.token, accepted.pack_id)
    for slot in ("practice_1", "practice_2"):
        attempt = python.submit_training(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            PythonTraining(slot=slot, code=program(slot)),
        )
        claim = owned_claim(database, session, attempt.id)
        JourneyWorkflow(database).report(
            claim.job_id, receipt(database, claim, runner, wrong=wrong and slot == "practice_1")
        )


def prepare_python_gate(database, session, setup):
    _, accepted, (gates, _, (_, tutor, settings, _, _)) = setup
    row = gates.request(
        session.token,
        accepted.pack_id,
        str(uuid4()),
        GateRequest(expected_plan_revision=1),
        required_kind="python_io",
    )
    observed = []
    run_model(
        tutor,
        settings,
        row.relation_run_id,
        relation_document(database, row.id),
        observe=observed.append,
    )
    assert '"tests":' not in json.dumps(observed)
    assert gates.view(session.token, row.id).questions == []
    return gates, row


def submission():
    return PythonGateSubmission(
        programs=[
            {"slot": slot, "code": program(slot)} for slot in ("assessment_1", "assessment_2")
        ]
    )


def test_python_published_only_after_actual_blind_execution_and_all_six_reviews(
    database, workflow, session, python_setup
):
    _, accepted, gate_setup = python_setup
    supply = gate_setup[2][0]
    with pytest.raises(BusinessError):
        supply.publish(session.token, accepted.pack_id)
    assert not workflow.snapshot(
        session.token
    ).python_attempts  # Private qualification stays private.
    pack = publish_python(database, session, python_setup)
    assert pack.kind == "python_io" and pack.blind_passed and len(pack.passed_roles) == 6
    with pytest.raises(BusinessError):
        supply.practice(session.token, pack.id)  # No single-choice route on code artifacts.


def test_blind_exit_zero_with_wrong_output_never_publishes(database, session, python_setup):
    _, accepted, gate_setup = python_setup
    journey = JourneyWorkflow(database)
    for index in range(5):
        claim = owned_claim(database, session)
        journey.report(claim.job_id, receipt(database, claim, wrong=index == 0))
    finish(database, gate_setup[2], accepted)
    pack = gate_setup[2][0].get(session.token, accepted.pack_id)
    assert pack.status == "changes_required" and not pack.blind_passed
    with pytest.raises(BusinessError):
        gate_setup[2][0].publish(session.token, pack.id)


def test_python_gate_two_programs_locked_atomic_scoring_and_scoped_evidence(
    database, workflow, session, python_setup
):
    python, accepted, _ = python_setup
    publish_python(database, session, python_setup)
    train(database, session, python_setup)
    gates, gate = prepare_python_gate(database, session, python_setup)
    opened = gates.start(session.token, gate.id)
    assert len(opened.questions) == 2 and "tests" not in opened.model_dump_json()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        views = list(
            pool.map(
                lambda _: python.submit_gate(session.token, gate.id, key, submission()), range(2)
            )
        )
    assert views[0] == views[1] and views[0].gate.status == "submitted"
    first = owned_claim(database, session)
    JourneyWorkflow(database).report(first.job_id, receipt(database, first))
    snapshot = workflow.snapshot(session.token)
    assert all(
        a.status == "queued" and a.feedback is None
        for a in snapshot.python_attempts
        if a.gate_id == gate.id
    )
    assert not snapshot.execution_progress and not snapshot.node_progress
    with database.transaction() as c:
        actual = c.execute(
            "SELECT public_content FROM item_bank.exposure_facts WHERE actor_id=%s "
            "AND pack_id=%s AND slot='practice_1' AND kind='feedback'",
            (session.actor.id, accepted.pack_id),
        ).fetchone()["public_content"]["feedback"]
    delivered = next(
        a
        for a in snapshot.python_attempts
        if a.pack_id == accepted.pack_id and a.slot == "practice_1"
    )
    assert actual["explanation"] == delivered.feedback
    assert "已锁定程序的训练说明" not in actual["explanation"]
    with pytest.raises(BusinessError):
        python.training(session.token, accepted.pack_id)
    second = owned_claim(database, session)
    report = receipt(database, second)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: JourneyWorkflow(database).report(second.job_id, report), range(2)))
    snapshot = workflow.snapshot(session.token)
    assert gates.view(session.token, gate.id).gate.status == "passed"
    assert len(snapshot.execution_progress) == 1 and not snapshot.node_progress
    assert snapshot.execution_progress[0].policy_version == "python-io-gate.v1"
    assert len([a for a in snapshot.python_attempts if a.gate_id == gate.id]) == 2
    assert python.submit_gate(session.token, gate.id, key, submission()).gate.status == "passed"
    with pytest.raises(BusinessError):
        gates.request(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            GateRequest(expected_plan_revision=1),
            required_kind="python_io",
        )


def test_failed_execution_training_requires_exact_lower_remediation(
    database, session, python_setup
):
    python, accepted, gate_setup = python_setup
    publish_python(database, session, python_setup)
    train(database, session, python_setup, wrong=True)
    gates = gate_setup[0]
    with pytest.raises(BusinessError):
        gates.request(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            GateRequest(expected_plan_revision=1),
            required_kind="python_io",
        )
    items = python.training(session.token, accepted.pack_id, remediation=True)
    assert [i.slot for i in items] == ["remediation_1"]
    attempt = python.submit_training(
        session.token,
        accepted.pack_id,
        str(uuid4()),
        PythonTraining(slot="remediation_1", code=program("remediation_1")),
    )
    claim = owned_claim(database, session, attempt.id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    prepare_python_gate(database, session, python_setup)


def test_python_gate_cancel_and_late_receipts_never_apply_progress(
    database, workflow, session, python_setup
):
    python, _, _ = python_setup
    publish_python(database, session, python_setup)
    train(database, session, python_setup)
    gates, gate = prepare_python_gate(database, session, python_setup)
    gates.start(session.token, gate.id)
    python.submit_gate(session.token, gate.id, str(uuid4()), submission())
    claim = owned_claim(database, session)
    gates.cancel(session.token, gate.id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    assert gates.view(session.token, gate.id).gate.status == "cancelled"
    assert not workflow.snapshot(session.token).execution_progress
    with database.transaction() as c:
        assert c.execute(
            "SELECT report FROM execution.jobs WHERE id=%s", (claim.job_id,)
        ).fetchone()["report"]["cases"]


def test_expired_python_qualification_keeps_late_receipt_without_review_or_rerun(
    database, workflow, session, python_setup
):
    _, accepted, gate_setup = python_setup
    claim = owned_claim(database, session)
    with database.transaction() as c:
        c.execute(
            "UPDATE execution.jobs SET lease_until=now()-interval '1 second' WHERE id=%s",
            (claim.job_id,),
        )
    JourneyWorkflow(database).expire_executions()
    report = receipt(database, claim)
    JourneyWorkflow(database).report(claim.job_id, report)
    JourneyWorkflow(database).report(claim.job_id, report)
    assert gate_setup[2][0].get(session.token, accepted.pack_id).status == "failed"
    assert not workflow.snapshot(session.token).execution_progress
    with database.transaction() as c:
        stored = c.execute(
            "SELECT report FROM execution.jobs WHERE id=%s", (claim.job_id,)
        ).fetchone()["report"]
    assert stored["late_receipt"] == report.model_dump(mode="json")


def test_qualification_continuation_does_not_preempt_an_active_user_turn(
    database, session, python_setup
):
    python, accepted, (_, _, (_, tutor, _, plan, _)) = python_setup
    conversation = tutor.conversation(session.token, plan.goal_id)
    active = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="先回答我的问题")
    )
    for _ in range(5):
        claim = owned_claim(database, session)
        JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    pack = python_setup[2][2][0].get(session.token, accepted.pack_id)
    assert pack.status == "reviewing" and pack.pending_run_id is None
    tutor.cancel(session.token, active.run_id)
    resumed = python.continue_review(session.token, pack.id)
    assert resumed.pending_role == "curriculum"
    assert python.continue_review(session.token, pack.id) == resumed


def test_http_private_cases_ownership_and_forbidden_client_grades(
    database, workflow, session, python_setup
):
    _, accepted, (_, _, (_, _, settings, _, _)) = python_setup
    publish_python(database, session, python_setup)
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + session.token}
    response = client.get(f"/v1/packs/{accepted.pack_id}/execution-practice", headers=headers)
    assert response.status_code == 200 and "tests" not in response.text
    other = workflow.create_session("Different code learner")
    assert (
        client.get(
            f"/v1/packs/{accepted.pack_id}/execution-practice",
            headers={
                "Authorization": "Bearer " + other.token,
            },
        ).status_code
        == 404
    )
    headers["Idempotency-Key"] = str(uuid4())
    assert (
        client.post(
            f"/v1/packs/{accepted.pack_id}/execution-submissions",
            headers=headers,
            json={
                "slot": "practice_1",
                "code": "print(1)",
                "passed": True,
            },
        ).status_code
        == 422
    )


@pytest.mark.skipif(
    os.environ.get("LEORNIAN_TEST_DOCKER") != "1",
    reason="Explicit real Docker execution acceptance",
)
def test_real_docker_blind_training_and_dynamic_execution_gate(
    database, workflow, session, python_setup, runner
):
    python, _, _ = python_setup
    publish_python(database, session, python_setup, runner=runner)
    train(database, session, python_setup, runner=runner)
    gates, gate = prepare_python_gate(database, session, python_setup)
    gates.start(session.token, gate.id)
    python.submit_gate(session.token, gate.id, str(uuid4()), submission())
    for _ in range(2):
        claim = owned_claim(database, session)
        JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, runner=runner))
    assert gates.view(session.token, gate.id).gate.status == "passed"
    assert len(workflow.snapshot(session.token).execution_progress) == 1


def test_actual_runner_claim_route_dispatches_python_without_private_expected(
    database, session, python_setup, monkeypatch
):
    _, _, (_, _, (_, _, settings, _, _)) = python_setup
    # Only queue selection is fixture-scoped. HTTP auth, claim_in authorization and
    # the public/private response contract still use the actual implementations.
    # Old invalid queue rows may legitimately make the unscoped production poll return None.
    monkeypatch.setattr(
        JourneyWorkflow,
        "claim",
        lambda _self, runner_id, program_environments=(): owned_claim(
            database, session, runner_id=runner_id,
        ),
    )
    client = TestClient(create_app(replace(settings, runner_token="fixture-controller-token")))
    denied = client.post(
        "/internal/executions/claim",
        json={"runner_id": "fixture"},
        headers={"Authorization": "Bearer " + session.token},
    )
    assert denied.status_code == 401
    response = client.post(
        "/internal/executions/claim",
        json={"runner_id": "fixture"},
        headers={"Authorization": "Bearer fixture-controller-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"job_id", "claim_token", "code", "inputs"}
    assert len(data["inputs"]) == 3 and "expected" not in response.text


def test_cancelled_qualification_is_not_restarted_by_queued_execution(
    database, session, python_setup
):
    _, accepted, gate_setup = python_setup
    supply = gate_setup[2][0]
    supply.cancel_pack(session.token, accepted.pack_id)
    assert owned_claim(database, session) is None
    assert supply.get(session.token, accepted.pack_id).status == "cancelled"
    assert supply.get(session.token, accepted.pack_id).pending_run_id is None


def test_python_completion_rolls_back_with_both_scores_and_replays_same_receipt(
    database, workflow, session, python_setup, monkeypatch
):
    from leornian.modules.learning.progress import Progress

    python, _, _ = python_setup
    publish_python(database, session, python_setup)
    train(database, session, python_setup)
    gates, gate = prepare_python_gate(database, session, python_setup)
    gates.start(session.token, gate.id)
    python.submit_gate(session.token, gate.id, str(uuid4()), submission())
    first = owned_claim(database, session)
    JourneyWorkflow(database).report(first.job_id, receipt(database, first))
    second = owned_claim(database, session)
    report = receipt(database, second)
    original = Progress.apply_python

    def unavailable(*_):
        raise RuntimeError("learning storage failed")

    monkeypatch.setattr(Progress, "apply_python", unavailable)
    with pytest.raises(RuntimeError):
        JourneyWorkflow(database).report(second.job_id, report)
    assert gates.view(session.token, gate.id).gate.status == "submitted"
    assert not workflow.snapshot(session.token).execution_progress
    monkeypatch.setattr(Progress, "apply_python", original)
    JourneyWorkflow(database).report(second.job_id, report)
    assert gates.view(session.token, gate.id).gate.status == "passed"
    assert len(workflow.snapshot(session.token).execution_progress) == 1


def test_source_revocation_after_execution_claim_preserves_receipts_but_not_progress(
    database, workflow, session, python_setup
):
    python, _, (_, _, (_, _, _, _, source)) = python_setup
    publish_python(database, session, python_setup)
    train(database, session, python_setup)
    gates, gate = prepare_python_gate(database, session, python_setup)
    gates.start(session.token, gate.id)
    python.submit_gate(session.token, gate.id, str(uuid4()), submission())
    claims = [owned_claim(database, session) for _ in range(2)]
    KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    for claim in claims:
        JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    assert gates.view(session.token, gate.id).gate.status == "not_passed"
    assert not workflow.snapshot(session.token).execution_progress
    with database.transaction() as c:
        for claim in claims:
            assert c.execute(
                "SELECT report FROM execution.jobs WHERE id=%s", (claim.job_id,)
            ).fetchone()["report"]["cases"]
