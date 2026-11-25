import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import relation_document
from test_execution_environments import (
    allowed_work,
    decide,
    release_report,
)
from test_execution_environments import (
    claim as environment_claim,
)
from test_execution_environments import environment_setup as environment_setup
from test_item_supply import finish, run_model
from test_item_supply import supply_setup as supply_setup
from test_program_items import answer_for, environment, item_document
from test_program_practice import owned_claim
from test_transfers import relation_report

from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.program_execution import ProgramWorkflow
from leornian.bootstrap.supply_demand import SupplyWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.gate_contracts import GateRequest
from leornian.modules.assessment.program_contracts import (
    ProgramGateSubmission,
    ProgramPracticeSubmission,
    ProgramTransferSubmission,
)
from leornian.modules.assessment.transfer_contracts import TransferRequest
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import CaseOutput, RunnerReport
from leornian.modules.execution.environment_contracts import EnvironmentRebuildInput
from leornian.modules.item_bank.demand_contracts import SupplyRequest
from leornian.modules.item_bank.supply_contracts import PackRequest
from leornian.shared_kernel.errors import BusinessError


def stdio_document(source, prepared_environment, *, difficulty=None):
    value = item_document(source, environment("python_project"))
    for item in value["items"]:
        item["language"] = "project_stdio"
        item["environment"] = prepared_environment
        item["prompt"] += " Read one JSON integer array from stdin; print the integer result."
        item["tests"] = [
            {"input": json.dumps(case["input"]), "expected": str(case["expected"])}
            for case in item["tests"]
        ]
        item["sample"] = deepcopy(item["tests"][0])
        if difficulty is not None:
            item["difficulty"] = difficulty
            item["prompt"] = "A fresh application with different context: " + item["prompt"]
    return value


def stdio_answer(item, *, wrong=False, changed=False):
    return {**answer_for(item, wrong=wrong, changed=changed), "type": "stdio"}


def controlled_report(database, claim, *, wrong=False, compile_error=False):
    """Supply offline execution facts through the normal owned Runner report contract."""
    with database.transaction() as connection:
        cases = connection.execute(
            "SELECT p.test_cases FROM assessment.program_attempts p "
            "JOIN execution.jobs j ON j.program_input_ref=p.id WHERE j.id=%s",
            (claim.job_id,),
        ).fetchone()["test_cases"]
    return RunnerReport(
        claim_token=claim.claim_token,
        compilation=CaseOutput(
            exit_code=1 if compile_error else 0,
            stdout="",
            stderr="CompileError: fixture failure" if compile_error else "",
            outcome="completed",
        ),
        cases=[
            CaseOutput(
                exit_code=1 if compile_error else 0,
                stdout="" if compile_error else ("incorrect" if wrong else case["expected"] + "\n"),
                stderr="CompileError: fixture failure" if compile_error else "",
                outcome="completed",
            )
            for case in ([] if compile_error else cases)
        ],
    )


def complete_pack(database, session, base, accepted, document):
    supply, tutor, settings, _, _ = base
    run_model(tutor, settings, accepted.run_id, document)
    pack = supply.get(session.token, accepted.pack_id)
    observed = []
    run_model(
        tutor,
        settings,
        pack.pending_run_id,
        {"programs": [
            {"slot": item["slot"], "answer": stdio_answer(item)} for item in document["items"]
        ]},
        observe=observed.append,
    )
    assert '"tests":' not in json.dumps(observed)
    assert '"test_cases":' not in json.dumps(observed)
    assert supply.get(session.token, accepted.pack_id).status == "qualifying"
    for _ in range(5):
        work = owned_claim(database, session)
        assert work is not None and '"expected":' not in work.model_dump_json()
        JourneyWorkflow(database).report(work.job_id, controlled_report(database, work))
    finish(database, base, accepted)
    assert supply.get(session.token, accepted.pack_id).status == "ready"
    return supply.publish(session.token, accepted.pack_id)


@pytest.fixture
def formal_program_setup(database, session, gate_setup, environment_setup):
    gates, _, base = gate_setup
    supply, _, _, plan, source = base
    environments, _ = environment_setup
    demand, work = allowed_work(environments, session)
    assert work.demand_id == demand.id
    release = environments.report(work.job_id, release_report(work))
    prepared = release.environment()
    accepted = supply.submit(
        session.token,
        plan.id,
        str(uuid4()),
        PackRequest(
            expected_plan_revision=1,
            node_key="loops",
            instruction="Bound stdio qualification, practice and independent formal assessment.",
            kind="project_stdio",
            program_environment=prepared,
            automatic=False,
        ),
    )
    document = stdio_document(source, prepared)
    complete_pack(database, session, base, accepted, document)
    try:
        yield SimpleNamespace(
            programs=ProgramWorkflow(database), gates=gates, base=base, accepted=accepted,
            document=document, environment=prepared, environments=environments, demand_id=demand.id,
        )
    finally:
        with database.transaction() as connection:
            for row in connection.execute(
                "SELECT id FROM execution.jobs WHERE actor_id=%s "
                "AND status IN ('queued','running')",
                (session.actor.id,),
            ).fetchall():
                Execution(connection).abandon(row["id"], "test_fixture_closed")


def train(database, session, setup, *, fail_remediation=False):
    setup.programs.training(session.token, setup.accepted.pack_id)
    origin = None
    for item in setup.document["items"]:
        slot = item["slot"]
        if slot == "remediation_1":
            if not fail_remediation:
                continue
            setup.programs.training(session.token, setup.accepted.pack_id, remediation=True)
        elif slot not in {"practice_1", "practice_2"}:
            continue
        wrong = fail_remediation and slot != "practice_2"
        attempt = setup.programs.submit_practice(
            session.token,
            setup.accepted.pack_id,
            str(uuid4()),
            ProgramPracticeSubmission(slot=slot, answer=stdio_answer(item, wrong=wrong)),
        )
        work = owned_claim(database, session, attempt.id)
        JourneyWorkflow(database).report(
            work.job_id, controlled_report(database, work, wrong=wrong),
        )
        if slot == "remediation_1":
            origin = attempt
    return origin


def prepare_gate(database, session, setup):
    _, tutor, settings, _, _ = setup.base
    gate = setup.gates.request(
        session.token, setup.accepted.pack_id, str(uuid4()),
        GateRequest(expected_plan_revision=1), required_kind="project_stdio",
    )
    observed = []
    run_model(
        tutor, settings, gate.relation_run_id, relation_document(database, gate.id),
        observe=observed.append,
    )
    assert '"tests":' not in json.dumps(observed)
    assert '"test_cases":' not in json.dumps(observed)
    ready = setup.gates.view(session.token, gate.id)
    assert ready.gate.status == "ready" and not ready.questions
    return setup.gates.start(session.token, gate.id)


def gate_submission(setup, *, changed=False):
    return ProgramGateSubmission(programs=[
        {"slot": item["slot"], "answer": stdio_answer(item, changed=changed)}
        for item in setup.document["items"] if item["slot"].startswith("assessment_")
    ])


def evidence_counts(database, session):
    with database.transaction() as connection:
        return {
            name: connection.execute(
                f"SELECT count(*) AS n FROM learning.{name} WHERE actor_id=%s",
                (session.actor.id,),
            ).fetchone()["n"]
            for name in ("execution_evidence", "node_progress", "review_cards")
        }


def test_program_gate_two_reserved_answers_lock_once_and_only_final_pass_is_evidence(
    database, workflow, session, formal_program_setup,
):
    setup = formal_program_setup
    assert evidence_counts(database, session) == {
        "execution_evidence": 0, "node_progress": 0, "review_cards": 0,
    }
    train(database, session, setup)
    assert not workflow.snapshot(session.token).execution_progress
    assert evidence_counts(database, session)["review_cards"] == 0
    opened = prepare_gate(database, session, setup)
    assert len(opened.questions) == 2
    assert all(question.language == "project_stdio" for question in opened.questions)
    assert '"tests":' not in opened.model_dump_json()
    assert '"test_cases":' not in opened.model_dump_json()
    data, key = gate_submission(setup), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: setup.programs.submit_gate(session.token, opened.gate.id, key, data),
            range(2),
        ))
    assert results[0] == results[1] and results[0].gate.status == "submitted"
    for attempted_key, attempted_data in [
        (str(uuid4()), data), (key, gate_submission(setup, changed=True)),
    ]:
        with pytest.raises(BusinessError) as locked:
            setup.programs.submit_gate(
                session.token, opened.gate.id, attempted_key, attempted_data,
            )
        assert locked.value.code == "idempotency_conflict"
    with pytest.raises(ValidationError):
        ProgramGateSubmission(programs=[data.programs[0]])
    with pytest.raises(ValidationError):
        ProgramGateSubmission(programs=[data.programs[0], data.programs[0]])
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id,purpose,slot FROM assessment.program_attempts WHERE gate_id=%s "
            "ORDER BY slot", (opened.gate.id,),
        ).fetchall()
    assert [row["slot"] for row in rows] == ["assessment_1", "assessment_2"]
    assert all(row["purpose"] == "gate" for row in rows)
    for index, row in enumerate(rows):
        work = owned_claim(database, session, row["id"])
        assert '"expected":' not in work.model_dump_json()
        report = controlled_report(database, work)
        JourneyWorkflow(database).report(work.job_id, report)
        JourneyWorkflow(database).report(work.job_id, report)
        assert evidence_counts(database, session)["execution_evidence"] == index
    done = setup.gates.view(session.token, opened.gate.id)
    assert done.gate.status == "passed" and len(done.program_results) == 2
    assert all(result.status == "passed" and result.passed_cases == 3
               for result in done.program_results)
    assert evidence_counts(database, session) == {
        "execution_evidence": 1, "node_progress": 0, "review_cards": 1,
    }
    snapshot = workflow.snapshot(session.token)
    assert snapshot.execution_progress[0].gate_id == opened.gate.id
    assert snapshot.execution_progress[0].policy_version == "program-execution-gate.v1"
    assert not snapshot.node_progress
    assert setup.programs.gate_submission_receipt(session.token, opened.gate.id, key) == done
    assert '"tests":' not in done.model_dump_json()
    assert '"test_cases":' not in done.model_dump_json()


@pytest.mark.parametrize("failure", ["compile_error", "revoke", "replacement"])
def test_program_gate_failed_or_stale_environment_never_creates_mastery(
    database, session, formal_program_setup, failure,
):
    setup = formal_program_setup
    train(database, session, setup)
    opened = prepare_gate(database, session, setup)
    setup.programs.submit_gate(
        session.token, opened.gate.id, str(uuid4()), gate_submission(setup),
    )
    works = [owned_claim(database, session), owned_claim(database, session)]
    assert all(work is not None for work in works)
    reports = [
        controlled_report(database, work, compile_error=failure == "compile_error")
        for work in works
    ]
    current = next(
        demand for demand in setup.environments.snapshot(session.token).demands
        if demand.id == setup.demand_id
    )
    if failure == "revoke":
        decide(setup.environments, session, current, "revoke")
    elif failure == "replacement":
        setup.environments.rebuild(
            session.token, current.id, str(uuid4()),
            EnvironmentRebuildInput(
                expected_requirement_revision=current.requirement_revision,
                expected_decision_revision=current.decision_revision,
            ),
        )
        work = environment_claim(setup.environments)
        assert work.demand_id == current.id
        replacement = setup.environments.report(work.job_id, release_report(work, "2"))
        assert str(replacement.id) != setup.environment["environment_release_id"]
    for work, report in zip(works, reports, strict=True):
        JourneyWorkflow(database).report(work.job_id, report)
    assert evidence_counts(database, session) == {
        "execution_evidence": 0, "node_progress": 0, "review_cards": 0,
    }
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT status,error_code FROM assessment.program_attempts WHERE gate_id=%s",
            (opened.gate.id,),
        ).fetchall()
        gate = connection.execute(
            "SELECT status FROM assessment.concept_gates WHERE id=%s", (opened.gate.id,),
        ).fetchone()
        receipts = connection.execute(
            "SELECT count(*) AS n FROM execution.jobs WHERE id=ANY(%s) AND report IS NOT NULL",
            ([work.job_id for work in works],),
        ).fetchone()["n"]
    assert len(rows) == 2 and all(row["status"] != "passed" for row in rows)
    assert gate["status"] == ("not_passed" if failure == "compile_error" else "blocked")
    if failure != "compile_error":
        assert all(row["status"] == "error" and row["error_code"] for row in rows)
    assert receipts == 2


@pytest.mark.parametrize("difficulty", [1, 2], ids=["lower", "equal"])
def test_program_transfer_preserves_kind_environment_and_never_substitutes_for_gate(
    database, workflow, session, formal_program_setup, difficulty,
):
    setup = formal_program_setup
    origin = train(database, session, setup, fail_remediation=True)
    supply, tutor, settings, _, source = setup.base
    transfer = TransferWorkflow(database, settings)
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + session.token}
    request_key, supply_key = str(uuid4()), str(uuid4())

    def facts():
        with database.transaction(snapshot=True) as connection:
            counts = {
                table: connection.execute(
                    f"SELECT count(*) AS n FROM {table} WHERE actor_id=%s", (session.actor.id,),
                ).fetchone()["n"]
                for table in (
                    "assessment.transfer_checks", "item_bank.supply_demands",
                    "assessment.program_attempts", "execution.jobs", "runtime.runs",
                )
            }
            counts["external_calls"] = connection.execute(
                "SELECT count(*) AS n FROM runtime.external_calls c "
                "JOIN runtime.runs r ON r.id=c.run_id WHERE r.actor_id=%s", (session.actor.id,),
            ).fetchone()["n"]
        return counts

    before = facts()
    assert client.get(f"/v1/transfer-requests/{request_key}", headers=headers).status_code == 404
    assert client.get(f"/v1/supply-requests/{supply_key}", headers=headers).status_code == 404
    assert facts() == before
    with pytest.raises(BusinessError) as missing:
        transfer.request_program(
            session.token, origin.id, str(uuid4()), TransferRequest(expected_plan_revision=1),
        )
    assert missing.value.code == "no_transfer_candidate"
    demand = SupplyWorkflow(database, settings).request_program(
        session.token, origin.id, supply_key,
        SupplyRequest(
            expected_plan_revision=1, instruction="Different context at equal/lower difficulty.",
            automatic=False,
        ),
    )
    assert demand.kind == "project_stdio" and set(demand.allowed_difficulties) == {1, 2}
    assert demand.program_remediation_id == origin.id
    assert demand.pack.kind == "project_stdio"
    assert demand.pack.program_environment.model_dump(mode="json") == setup.environment
    before = facts()
    assert client.get(
        f"/v1/supply-requests/{supply_key}", headers=headers,
    ).json() == demand.model_dump(mode="json")
    assert client.get(
        f"/v1/supply-demands/{demand.id}", headers=headers,
    ).json() == demand.model_dump(mode="json")
    assert facts() == before
    accepted = SimpleNamespace(pack_id=demand.pack.id, run_id=demand.pack.pending_run_id)
    candidate = stdio_document(source, setup.environment, difficulty=difficulty)
    complete_pack(database, session, setup.base, accepted, candidate)
    row = transfer.request_program(
        session.token, origin.id, request_key, TransferRequest(expected_plan_revision=1),
    )
    before = facts()
    assert client.get(
        f"/v1/transfer-requests/{request_key}", headers=headers,
    ).json() == row.model_dump(mode="json")
    assert client.get(
        f"/v1/transfer-requests/{uuid4()}", headers=headers,
    ).status_code == 404
    assert client.get(
        f"/v1/transfers/{row.id}/opening", headers=headers,
    ).status_code == 404
    assert facts() == before
    observed = []
    run_model(
        tutor, settings, row.relation_run_id, relation_report(database, row.id),
        observe=observed.append,
    )
    assert '"tests":' not in json.dumps(observed)
    assert '"test_cases":' not in json.dumps(observed)
    assert transfer.view(session.token, row.id).question is None
    opened = transfer.open(session.token, row.id)
    before = facts()
    assert client.get(
        f"/v1/transfers/{row.id}/opening", headers=headers,
    ).json() == opened.model_dump(mode="json")
    assert client.get(
        f"/v1/transfers/{row.id}/submissions/{uuid4()}", headers=headers,
    ).status_code == 404
    assert client.get(
        f"/v1/transfers/{row.id}/cancellation", headers=headers,
    ).status_code == 404
    assert facts() == before
    assert opened.question.language == "project_stdio"
    assert opened.question.difficulty == difficulty
    assert opened.question.environment.model_dump(mode="json") == setup.environment
    candidate_item = next(
        item for item in candidate["items"] if item["slot"] == opened.transfer.candidate_slot
    )
    data, key = ProgramTransferSubmission(answer=stdio_answer(candidate_item)), str(uuid4())
    queued = transfer.submit_program(session.token, row.id, key, data)
    assert queued.transfer.status == "submitted" and queued.program_attempt.status == "queued"
    work = owned_claim(database, session, queued.program_attempt.id)
    JourneyWorkflow(database).report(work.job_id, controlled_report(database, work))
    done = transfer.view(session.token, row.id)
    assert done.transfer.status == "passed" and done.program_attempt.status == "passed"
    before = facts()
    assert client.get(
        f"/v1/transfers/{row.id}/submissions/{key}", headers=headers,
    ).json() == done.model_dump(mode="json")
    assert client.get(
        f"/v1/transfers/{row.id}/submissions/{uuid4()}", headers=headers,
    ).status_code == 404
    assert facts() == before
    assert transfer.submit_program(session.token, row.id, key, data) == done
    with pytest.raises(BusinessError) as locked:
        transfer.submit_program(session.token, row.id, str(uuid4()), data)
    assert locked.value.code == "idempotency_conflict"
    assert '"tests":' not in done.model_dump_json()
    assert '"test_cases":' not in done.model_dump_json()
    assert evidence_counts(database, session) == {
        "execution_evidence": 0, "node_progress": 0, "review_cards": 0,
    }
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.execution_progress and not snapshot.node_progress
    with database.transaction() as connection:
        original = connection.execute(
            "SELECT status FROM assessment.program_attempts WHERE id=%s", (origin.id,),
        ).fetchone()
    assert original["status"] == "not_passed"
    assert prepare_gate(database, session, setup).gate.status == "in_progress"
    client.close()
