from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_item_supply import supply_setup as supply_setup
from test_program_practice import observed_environments as observed_environments
from test_program_practice import (
    owned_claim,
    publish,
    receipt,
    submission,
)
from test_program_practice import program_setup as program_setup
from test_program_runner import runner as runner

from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.modules.tutor.evaluations import Evaluations


def test_program_result_rolls_back_with_original_public_feedback_owner(
    database, session, workflow, program_setup, monkeypatch,
):
    programs, accepted, _, document, _ = program_setup
    publish(database, session, program_setup)
    programs.training(session.token, accepted.pack_id)
    attempt = programs.submit_practice(
        session.token, accepted.pack_id, str(uuid4()), submission(document["items"][0]),
    )
    claim = owned_claim(database, session, attempt.id)
    report = receipt(database, claim)
    original = Evaluations.enqueue

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Original evaluation storage unavailable.")

    monkeypatch.setattr(Evaluations, "enqueue", unavailable)
    with pytest.raises(RuntimeError):
        JourneyWorkflow(database).report(claim.job_id, report)
    pending = programs.attempt(session.token, attempt.id)
    assert pending.status == "queued" and pending.sample_result is None
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status,report FROM execution.jobs WHERE id=%s", (claim.job_id,),
        ).fetchone()
        assert row["status"] == "running" and row["report"] is None
    monkeypatch.setattr(Evaluations, "enqueue", original)
    JourneyWorkflow(database).report(claim.job_id, report)
    JourneyWorkflow(database).report(claim.job_id, report)
    result = programs.attempt(session.token, attempt.id)
    assert result.status == "passed" and result.sample_result is not None
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.evaluations WHERE source_id=%s", (attempt.id,),
        ).fetchone()["n"] == 1
    assert not workflow.snapshot(session.token).node_progress


def test_material_revocation_after_claim_keeps_receipt_without_applying_grade(
    database, session, program_setup,
):
    programs, accepted, (_, _, _, _, source), document, _ = program_setup
    publish(database, session, program_setup)
    programs.training(session.token, accepted.pack_id)
    attempt = programs.submit_practice(
        session.token, accepted.pack_id, str(uuid4()), submission(document["items"][0]),
    )
    claim = owned_claim(database, session, attempt.id)
    report = receipt(database, claim)
    KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    JourneyWorkflow(database).report(claim.job_id, report)
    result = programs.attempt(session.token, attempt.id)
    assert result.status == "error" and result.passed_cases == 0
    assert result.error_code == "source_not_current"
    assert result.sample_result is None
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT report FROM execution.jobs WHERE id=%s", (claim.job_id,),
        ).fetchone()
        assert row["report"]["cases"]


def test_concurrent_same_command_has_one_attempt_and_one_original_queue_job(
    database, session, program_setup,
):
    programs, accepted, _, document, _ = program_setup
    publish(database, session, program_setup)
    programs.training(session.token, accepted.pack_id)
    key = str(uuid4())
    data = submission(document["items"][0])
    with ThreadPoolExecutor(max_workers=2) as workers:
        rows = list(workers.map(
            lambda _index: programs.submit_practice(
                session.token, accepted.pack_id, key, data,
            ), range(2),
        ))
    assert rows[0].id == rows[1].id
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM execution.jobs WHERE program_input_ref=%s", (rows[0].id,),
        ).fetchone()["n"] == 1
