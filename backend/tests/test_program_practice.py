import json
import os
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_item_supply import finish, run_model
from test_item_supply import supply_setup as supply_setup
from test_program_items import answer_for, environment, item_document
from test_program_runner import runner as runner

from leornian.bootstrap.automatic_supply import AutomaticSupply
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.program_execution import ProgramWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.gate_contracts import GateRequest
from leornian.modules.assessment.program_contracts import ProgramPracticeSubmission
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.execution.application import Execution
from leornian.modules.execution.contracts import CaseOutput, RunnerReport
from leornian.modules.item_bank.supply_contracts import PackRequest
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture(scope="module")
def observed_environments(request):
    if os.environ.get("LEORNIAN_TEST_DOCKER") == "1":
        return request.getfixturevalue("runner").program_environments()
    return [environment("python_project")] + [
        environment("sql_query", dialect) for dialect in ("sqlite", "postgresql", "mysql")
    ]


@pytest.fixture
def program_setup(database, session, supply_setup, observed_environments, request):
    parameters = getattr(request, "param", ("sql_query", "sqlite"))
    kind, dialect = parameters[:2]
    expected = environment(kind, dialect)
    env = next(
        (
            value
            for value in observed_environments
            if value["profile"] == expected["profile"]
            and value.get("dialect") == expected.get("dialect")
        ),
        None,
    )
    if env is None:
        pytest.skip("The selected real local program image is not prepared.")
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(
        session.token,
        plan.id,
        str(uuid4()),
        PackRequest(
            expected_plan_revision=1,
            node_key="loops",
            instruction="Bound local program practice.",
            kind=kind,
            program_environment=env,
            automatic=False,
        ),
    )
    document = item_document(source, env)
    if len(parameters) == 3 and parameters[2] == "sample_last":
        for item in document["items"]:
            item["tests"] = item["tests"][1:] + item["tests"][:1]
    run_model(tutor, settings, accepted.run_id, document)
    pack = supply.get(session.token, accepted.pack_id)
    observed = []
    run_model(
        tutor,
        settings,
        pack.pending_run_id,
        {
            "programs": [
                {"slot": item["slot"], "answer": answer_for(item)} for item in document["items"]
            ],
        },
        observe=observed.append,
    )
    assert supply.get(session.token, accepted.pack_id).status == "qualifying"
    context = json.loads(observed[0]["messages"][1]["content"])
    assert all("tests" not in item and "explanation" not in item for item in context["questions"])
    assert "materials" not in context and "candidate" not in context
    try:
        yield ProgramWorkflow(database), accepted, supply_setup, document, env
    finally:
        with database.transaction() as connection:
            for row in connection.execute(
                "SELECT id FROM execution.jobs WHERE actor_id=%s "
                "AND status IN ('queued','running')",
                (session.actor.id,),
            ).fetchall():
                Execution(connection).abandon(row["id"], "test_fixture_closed")


def owned_claim(database, session, attempt_id=None):
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM execution.jobs WHERE actor_id=%s AND status='queued' "
            "AND program_input_ref IS NOT NULL "
            "AND (%s::uuid IS NULL OR program_input_ref=%s) ORDER BY created_at,id "
            "LIMIT 1 FOR UPDATE",
            (session.actor.id, attempt_id, attempt_id),
        ).fetchone()
        if row is None:
            return None
        token = uuid4()
        connection.execute(
            "UPDATE execution.jobs SET status='running',claim_token=%s,runner_id='owned-program',"
            "lease_until=now()+interval '300 seconds' WHERE id=%s",
            (token, row["id"]),
        )
        return JourneyWorkflow.claim_in(connection, {**row, "claim_token": token})


def receipt(database, claim, real=None, *, wrong=False, infrastructure=False):
    if real is not None:
        program = claim.program.model_dump(mode="json")
        outputs = (
            real.execute_sql(program)
            if program["profile"] == "sql-query.v1"
            else real.execute_project(program)
        )
        return RunnerReport(claim_token=claim.claim_token, cases=outputs)
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM assessment.program_attempts WHERE id="
            "(SELECT program_input_ref FROM execution.jobs WHERE id=%s)",
            (claim.job_id,),
        ).fetchone()
    values = []
    for case in row["test_cases"]:
        actual = deepcopy(case["expected"])
        if wrong:
            actual = (
                0
                if type(actual) is int
                else {
                    **actual,
                    "rows": [["0"]],
                    "types": [["integer"]],
                }
            )
        values.append(
            CaseOutput(
                exit_code=None if infrastructure else 0,
                stdout=json.dumps(actual),
                stderr="",
                outcome="infrastructure_error" if infrastructure else "completed",
            )
        )
    return RunnerReport(claim_token=claim.claim_token, cases=values)


def publish(database, session, setup, real=None, *, wrong=False):
    _, accepted, base, _, _ = setup
    supply = base[0]
    for _ in range(5):
        claim = owned_claim(database, session)
        assert claim is not None and '"expected":' not in claim.model_dump_json()
        JourneyWorkflow(database).report(
            claim.job_id,
            receipt(database, claim, real, wrong=wrong),
        )
    finish(database, base, accepted)
    if not wrong:
        assert supply.get(session.token, accepted.pack_id).status == "ready"
        return supply.publish(session.token, accepted.pack_id)
    return supply.get(session.token, accepted.pack_id)


def submission(item, *, wrong=False, parent=None, retry=False, changed=False):
    return ProgramPracticeSubmission(
        slot=item["slot"],
        answer=answer_for(item, wrong=wrong, changed=changed),
        previous_attempt_id=parent,
        retry=retry,
    )


@pytest.mark.skipif(
    os.environ.get("LEORNIAN_TEST_DOCKER") != "1", reason="Real Docker profile test"
)
@pytest.mark.parametrize(
    "program_setup",
    [
        ("sql_query", "sqlite"),
        ("sql_query", "postgresql"),
        ("sql_query", "mysql"),
        ("python_project", None),
    ],
    indirect=True,
)
def test_real_program_qualification_six_reviews_publication_and_original_assessment(
    database,
    session,
    workflow,
    program_setup,
    runner,
):
    programs, accepted, (supply, _, settings, _, _), document, _ = program_setup
    with pytest.raises(BusinessError):
        supply.publish(session.token, accepted.pack_id)
    published = publish(database, session, program_setup, runner)
    assert published.blind_passed is True and len(published.passed_roles) == 6
    public = programs.training(session.token, accepted.pack_id)
    assert len(public) == 2 and all("tests" not in value.model_dump() for value in public)
    attempt = programs.submit_practice(
        session.token,
        accepted.pack_id,
        str(uuid4()),
        submission(document["items"][0]),
    )
    claim = owned_claim(database, session, attempt.id)
    report = receipt(database, claim, runner)
    assert all(case.outcome == "completed" and case.exit_code == 0 for case in report.cases), report
    journey = JourneyWorkflow(database)
    journey.report(claim.job_id, report)
    journey.report(claim.job_id, report)
    result = programs.attempt(session.token, attempt.id)
    assert result.status == "passed" and result.passed_cases == 3
    assert "test_cases" not in result.model_dump_json()
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.node_progress and not snapshot.execution_progress
    assert [value.id for value in snapshot.program_attempts] == [attempt.id]
    with pytest.raises(BusinessError):
        ConceptGate(database, settings).request(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            GateRequest(expected_plan_revision=1),
        )


def test_wrong_blind_output_never_publishes_even_when_every_review_fixture_approves(
    database,
    session,
    program_setup,
):
    result = publish(database, session, program_setup, wrong=True)
    assert result.status == "changes_required" and result.blind_passed is False
    with pytest.raises(BusinessError):
        program_setup[2][0].publish(session.token, result.id)


def test_http_capability_negotiation_private_cases_and_request_recovery(
    database,
    session,
    program_setup,
):
    programs, accepted, (supply, _, settings, _, _), document, env = program_setup
    publish(database, session, program_setup)
    settings = replace(settings, runner_token="owned-program-runner")
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + session.token}
    control = {"Authorization": "Bearer " + settings.runner_token}
    assert (
        client.get(f"/v2/packs/{accepted.pack_id}/program-practice", headers=headers).status_code
        == 200
    )
    data = submission(document["items"][0])
    key = str(uuid4())
    response = client.post(
        f"/v2/packs/{accepted.pack_id}/program-submissions",
        headers={**headers, "Idempotency-Key": key},
        json=data.model_dump(mode="json"),
    )
    assert response.status_code == 202, response.text
    attempt_id = response.json()["id"]
    assert (
        client.get("/v2/program-practice-requests/" + key, headers=headers).json()["id"]
        == attempt_id
    )
    assert (
        client.post(
            "/internal/executions/claim",
            headers=headers,
            json={"runner_id": "learner"},
        ).status_code
        == 401
    )
    # This dedicated database has no pre-existing/native jobs; fixtures close their own queues.
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM execution.jobs WHERE status='queued' AND actor_id<>%s",
                (session.actor.id,),
            ).fetchone()["n"]
            == 0
        )
    assert (
        client.post(
            "/internal/executions/claim",
            headers=control,
            json={"runner_id": "old"},
        ).json()
        is None
    )
    unsupported = {**env, "runtime_version": "999.0"}
    assert (
        client.post(
            "/internal/executions/claim",
            headers=control,
            json={
                "runner_id": "wrong-version",
                "program_environments": [unsupported],
            },
        ).json()
        is None
    )
    claim = client.post(
        "/internal/executions/claim",
        headers=control,
        json={
            "runner_id": "capable",
            "program_environments": [env],
        },
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["program"]["runtime_version"] == env["runtime_version"]
    assert '"expected":' not in claim.text
    assert set(claim.json()) == {"job_id", "claim_token", "program"}
    assert (
        client.post(
            f"/v2/program-practice-attempts/{attempt_id}/cancel", headers=headers
        ).status_code
        == 200
    )
    with database.transaction() as connection:
        private = ProgramAssessment(connection).for_pack(
            session.actor, accepted.pack_id, "qualification"
        )
    assert (
        client.get(
            "/v2/program-practice-attempts/" + str(private[0]["id"]),
            headers=headers,
        ).status_code
        == 404
    )
    assert "tests" not in supply.get(session.token, accepted.pack_id).model_dump()
    assert programs.attempt(session.token, attempt_id).status == "error"


@pytest.mark.parametrize("program_setup", [("python_project", None)], indirect=True)
def test_project_multi_attempt_protection_cancel_retry_and_late_receipt_isolation(
    database,
    session,
    workflow,
    program_setup,
):
    programs, accepted, _, document, _ = program_setup
    publish(database, session, program_setup)
    programs.training(session.token, accepted.pack_id)
    item = document["items"][0]
    invalid_data = submission(item).model_dump(mode="json")
    invalid_data["answer"]["files"][0]["content"] = "print(6)"
    invalid = ProgramPracticeSubmission.model_validate(invalid_data)
    with pytest.raises(BusinessError, match="Read-only"):
        programs.submit_practice(session.token, accepted.pack_id, str(uuid4()), invalid)
    first_data = submission(item, wrong=True)
    first = programs.submit_practice(session.token, accepted.pack_id, "first", first_data)
    assert (
        programs.submit_practice(session.token, accepted.pack_id, "first", first_data).id
        == first.id
    )
    old_claim = owned_claim(database, session, first.id)
    old_report = receipt(database, old_claim, wrong=True)
    programs.cancel(session.token, first.id)
    assert programs.attempt(session.token, first.id).error_code == "learner_cancelled"
    retry_data = submission(item, wrong=True, parent=first.id, retry=True)
    second = programs.submit_practice(session.token, accepted.pack_id, "retry", retry_data)
    JourneyWorkflow(database).report(old_claim.job_id, old_report)
    assert programs.attempt(session.token, second.id).status == "queued"
    claim = owned_claim(database, session, second.id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, wrong=True))
    second_result = programs.attempt(session.token, second.id)
    assert second_result.status == "not_passed"
    third = programs.submit_practice(
        session.token,
        accepted.pack_id,
        "revision",
        submission(item, parent=second.id, changed=True),
    )
    claim = owned_claim(database, session, third.id)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
    assert programs.attempt(session.token, third.id).status == "passed"
    assert programs.attempt(session.token, second.id) == second_result
    with pytest.raises(BusinessError):
        programs.submit_practice(session.token, accepted.pack_id, str(uuid4()), submission(item))
    history = programs.history(session.token, accepted.pack_id, "practice_1", limit=1)
    assert history.latest_attempt_id == third.id and history.next_before == third.id
    assert [value.id for value in history.attempts] == [third.id]
    assert not workflow.snapshot(session.token).node_progress


def test_old_candidate_tools_skip_new_programs_without_permission_upgrade(
    database,
    session,
    program_setup,
):
    _, accepted, (_, tutor, _, plan, _), _, _ = program_setup
    publish(database, session, program_setup)
    conversation = tutor.conversation(session.token, plan.goal_id)
    with database.transaction() as connection:
        result = LearningArtifactWorkflow.candidates_in(
            connection,
            session.actor,
            conversation.id,
            TeachingFocus(kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="loops"),
        )
    assert result["items"] == []


def test_expired_qualification_records_late_facts_without_review_or_automatic_retry(
    database,
    session,
    program_setup,
):
    programs, accepted, (supply, _, _, _, _), _, _ = program_setup
    claim = owned_claim(database, session)
    report = receipt(database, claim)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE execution.jobs SET lease_until=now()-interval '1 second' WHERE id=%s",
            (claim.job_id,),
        )
    programs.expire_executions()
    JourneyWorkflow(database).report(claim.job_id, report)
    assert supply.get(session.token, accepted.pack_id).status == "failed"
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM execution.jobs WHERE id=%s", (claim.job_id,)
        ).fetchone()
        assert row["status"] == "expired" and "late_receipt" in row["report"]
        assert not connection.execute(
            "SELECT 1 FROM item_bank.stages WHERE pack_id=%s AND role='curriculum'",
            (accepted.pack_id,),
        ).fetchone()


def test_environment_failure_waits_instead_of_generating_another_paid_author(
    database,
    session,
    supply_setup,
):
    supply, tutor, settings, plan, source = supply_setup
    env = environment()
    accepted = supply.submit(
        session.token,
        plan.id,
        str(uuid4()),
        PackRequest(
            expected_plan_revision=1,
            node_key="loops",
            instruction="Bound environment.",
            kind="sql_query",
            program_environment=env,
            automatic=True,
        ),
    )
    document = item_document(source, env)
    run_model(tutor, settings, accepted.run_id, document)
    pack = supply.get(session.token, accepted.pack_id)
    run_model(
        tutor,
        settings,
        pack.pending_run_id,
        {
            "programs": [
                {"slot": item["slot"], "answer": answer_for(item)} for item in document["items"]
            ],
        },
    )
    claim = owned_claim(database, session)
    JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, infrastructure=True))
    assert (
        supply.get(session.token, accepted.pack_id).automation_error
        == "program_environment_unavailable"
    )
    assert AutomaticSupply(database, settings).advance(accepted.pack_id) == 0
    result = supply.get(session.token, accepted.pack_id)
    assert (
        result.automation_status == "waiting"
        and result.automation_reason == "program_environment_unavailable"
    )
    supply.cancel_pack(session.token, accepted.pack_id)
    with database.transaction() as connection:
        for row in connection.execute(
            "SELECT id FROM execution.jobs WHERE actor_id=%s AND status='queued'",
            (session.actor.id,),
        ).fetchall():
            Execution(connection).abandon(row["id"], "test_fixture_closed")
