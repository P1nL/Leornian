import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_item_supply import supply_setup as supply_setup
from test_program_items import table
from test_program_practice import observed_environments as observed_environments
from test_program_practice import owned_claim, publish, receipt, submission
from test_program_practice import program_setup as program_setup
from test_program_runner import runner as runner

from leornian.bootstrap.journey import JourneyWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.program_contracts import (
    ProgramPracticeSubmission,
    ProgramSampleResult,
)
from leornian.modules.assessment.programs import ProgramAssessment
from leornian.modules.execution.contracts import CaseOutput, RunnerReport
from leornian.shared_kernel.errors import BusinessError


def sample_row(index=2, purpose="training"):
    return {
        "sample_case_index": index, "purpose": purpose,
        "comparison_profile": "sql-result-typed.v1",
    }


def outputs(public=None):
    return [
        CaseOutput(
            outcome="completed", exit_code=0, stdout=json.dumps(value),
            stderr="PRIVATE_DIAGNOSTIC_" + str(index),
        )
        for index, value in enumerate([table(-123456), table(-654321), public or table(999)])
    ]


def test_projection_selects_only_the_frozen_sample_not_expected_or_first_case():
    result = ProgramAssessment.public_sample(sample_row(), outputs())
    assert result == {
        "profile": "program-public-sample.v1", "outcome": "completed",
        "exit_code": 0, "output": table(999),
    }

def test_project_actual_integer_stays_exact_beyond_javascript_safe_numbers():
    row = {**sample_row(), "comparison_profile": "python-project-io-result.v1"}
    cases = outputs()
    value = 10 ** 100 + 3
    cases[2] = CaseOutput(
        outcome="completed", exit_code=0, stdout=str(value), stderr="",
    )
    result = ProgramAssessment.public_sample(row, cases)
    assert result["output"] is None and result["integer_text"] == str(value)
    old = ProgramSampleResult(outcome="completed", exit_code=0, output=value)
    assert old.model_dump()["integer_text"] == str(value)


@pytest.mark.parametrize("row,cases", [
    (sample_row(None), outputs()),
    (sample_row(purpose="qualification"), outputs()),
    (sample_row(), outputs()[:1]),
])
def test_legacy_qualification_and_incomplete_reports_have_no_public_projection(row, cases):
    assert ProgramAssessment.public_sample(row, cases) is None


@pytest.mark.parametrize("outcome,exit_code,stdout", [
    ("completed", 0, "PRIVATE_MALFORMED_OUTPUT"),
    ("completed", 0, '{"private":"INVALID_TABLE"}'),
    ("completed", 1, json.dumps(table(999))),
    ("timeout", None, json.dumps(table(999))),
    ("infrastructure_error", None, json.dumps(table(999))),
])
def test_invalid_or_unsuccessful_sample_does_not_expose_raw_output(outcome, exit_code, stdout):
    cases = outputs()
    cases[2] = CaseOutput(
        outcome=outcome, exit_code=exit_code, stdout=stdout, stderr="PRIVATE_RUNTIME_ERROR",
    )
    result = ProgramAssessment.public_sample(sample_row(), cases)
    assert result["outcome"] == outcome and result["exit_code"] == exit_code
    assert result["output"] is None and "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("program_setup", [
    ("sql_query", "sqlite", "sample_last"),
    ("python_project", None, "sample_last"),
], indirect=True)
def test_owner_pins_nonfirst_sample_and_all_public_reads_use_the_same_actual_projection(
    database, session, workflow, program_setup,
):
    programs, accepted, (_, _, settings, _, _), document, _ = program_setup
    publish(database, session, program_setup)
    programs.training(session.token, accepted.pack_id)
    key = str(uuid4())
    attempt = programs.submit_practice(
        session.token, accepted.pack_id, key, submission(document["items"][0]),
    )
    assert attempt.sample_result is None
    with database.transaction() as connection:
        stored = ProgramAssessment(connection).row(session.actor, attempt.id)
        assert stored["sample_case_index"] == 2 and stored["sample_result"] is None
        assert all(
            row["sample_result"] is None for row in ProgramAssessment(connection).for_pack(
                session.actor, accepted.pack_id, "qualification",
            )
        )
    claim = owned_claim(database, session, attempt.id)
    actual = receipt(database, claim)
    cases = list(actual.cases)
    sql = attempt.comparison_profile == "sql-result-typed.v1"
    cases[2] = CaseOutput(
        exit_code=0, outcome="completed", stdout=json.dumps(table(999) if sql else 999),
        stderr="PRIVATE_SAMPLE_DIAGNOSTIC",
    )
    report = RunnerReport(claim_token=claim.claim_token, cases=cases)
    JourneyWorkflow(database).report(claim.job_id, report)
    result = programs.attempt(session.token, attempt.id)
    assert result.status == "not_passed" and result.passed_cases == 2
    if sql:
        assert result.sample_result.output.model_dump() == table(999)
    else:
        assert result.sample_result.output == 999
    assert programs.request(session.token, key) == result
    assert programs.history(session.token, accepted.pack_id, "practice_1").attempts == [result]
    assert workflow.snapshot(session.token).program_attempts == [result]
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + session.token}
    for path in (
        f"/v2/program-practice-attempts/{attempt.id}", "/v2/program-practice-requests/" + key,
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.json()["sample_result"] == result.sample_result.model_dump(mode="json")
        assert all(
            private not in response.text for private in (
                "test_cases", "sample_case_index", "execution_input", "PRIVATE_SAMPLE_DIAGNOSTIC",
            )
        )
    other = workflow.create_session("Different sample reader")
    with pytest.raises(BusinessError, match="not found"):
        programs.attempt(other.token, attempt.id)
    assert not workflow.snapshot(session.token).node_progress


@pytest.mark.skipif(os.environ.get("LEORNIAN_TEST_DOCKER") != "1", reason="Real sample execution")
@pytest.mark.parametrize(
    "program_setup", [("sql_query", "sqlite", "sample_last")], indirect=True,
)
def test_real_runner_actual_public_sample_is_not_its_expected_or_private_outputs(
    database, session, program_setup, runner,
):
    programs, accepted, _, document, _ = program_setup
    publish(database, session, program_setup)
    programs.training(session.token, accepted.pack_id)
    data = submission(document["items"][0]).model_dump(mode="json")
    data["answer"]["query"] = "SELECT COALESCE(SUM(n),0)+37 AS answer FROM records"
    attempt = programs.submit_practice(
        session.token, accepted.pack_id, str(uuid4()),
        ProgramPracticeSubmission.model_validate(data),
    )
    claim = owned_claim(database, session, attempt.id)
    report = receipt(database, claim, runner)
    assert [json.loads(case.stdout)["rows"] for case in report.cases] == [
        [["37"]], [["34"]], [["43"]],
    ]
    JourneyWorkflow(database).report(claim.job_id, report)
    result = programs.attempt(session.token, attempt.id)
    assert result.status == "not_passed" and result.passed_cases == 0
    assert result.sample_result.output.rows == [["43"]]
    assert document["items"][0]["sample"]["expected"]["rows"] == [["6"]]
