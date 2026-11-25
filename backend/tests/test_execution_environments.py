from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from leornian.bootstrap.execution_environments import ExecutionEnvironmentWorkflow
from leornian.modules.execution.environment_contracts import (
    EngineObservationInput,
    EnvironmentDecisionInput,
    EnvironmentDemandInput,
    EnvironmentPreparationClaimInput,
    EnvironmentPreparationProgress,
    EnvironmentPreparationReport,
    EnvironmentRebuildInput,
)
from leornian.modules.execution.environment_recipes import RECIPES, recipe
from leornian.modules.execution.environments import Environments
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def environment_setup(database, session):
    service = ExecutionEnvironmentWorkflow(database)
    yield service, session
    with database.transaction() as connection:
        connection.execute(
            "UPDATE execution.environment_preparation_jobs SET status='cancelled' "
            "WHERE actor_id=%s AND status IN ('queued','waiting_engine','preparing','verifying')",
            (session.actor.id,),
        )


def request(service, session, recipe_id="python-flask.v1", revision=0, key=None):
    return service.request(
        session.token,
        key or str(uuid4()),
        EnvironmentDemandInput(recipe_id=recipe_id, expected_requirement_revision=revision),
    )


def decide(service, session, demand, value="allow", key=None):
    return service.decide(
        session.token,
        demand.id,
        key or str(uuid4()),
        EnvironmentDecisionInput(
            expected_requirement_revision=demand.requirement_revision,
            expected_decision_revision=demand.decision_revision,
            decision=value,
        ),
    )


def ready_engine(service):
    service.observe_engine(
        EngineObservationInput(
            runner_id="offline-environment-test",
            status="ready",
            version="29.8.0",
            operating_system="linux",
            detail="Offline lifecycle fixture, not a Docker receipt.",
        )
    )


def claim(service):
    return service.claim(EnvironmentPreparationClaimInput(runner_id="offline-environment-test"))


def release_report(work, digit="1"):
    return EnvironmentPreparationReport(
        claim_token=work.claim_token,
        outcome="ready",
        runtime_version="3.12.12",
        image_id="sha256:" + digit * 64,
        image_ids={"runtime": "sha256:" + digit * 64},
        toolchains={"python": "3.12.12"},
        verification={"isolated": True, "smoke": True},
    )


def allowed_work(service, session):
    ready_engine(service)
    demand = request(service, session)
    decide(service, session, demand)
    return demand, claim(service)


def test_no_preparation_before_allow_and_defer_decline_preserve_the_requirement(environment_setup):
    service, session = environment_setup
    ready_engine(service)
    demand = request(service, session)
    assert claim(service) is None
    for value, status in [("defer", "deferred"), ("decline", "declined")]:
        decide(service, session, demand, value)
        demand = service.snapshot(session.token).demands[0]
        assert demand.status == status
        assert demand.requirement_revision == 1 and demand.release is None
        assert claim(service) is None


def test_allow_prepares_exact_release_and_revoke_gates_future_consumption(
    environment_setup,
    database,
):
    service, session = environment_setup
    demand, work = allowed_work(service, session)
    assert work.demand_id == demand.id
    assert service.progress(
        work.job_id,
        EnvironmentPreparationProgress(
            claim_token=work.claim_token,
            phase="verifying",
        ),
    ) == {"allowed": True}
    release = service.report(work.job_id, release_report(work))
    assert release.environment()["environment_release_id"] == str(release.id)
    with database.transaction() as connection:
        assert (
            Environments(connection)
            .require_release(
                session.actor,
                release.id,
                profile="project-stdio.v1",
                language="python",
            )
            .id
            == release.id
        )
    current = service.snapshot(session.token).demands[0]
    decide(service, session, current, "revoke")
    with database.transaction() as connection, pytest.raises(BusinessError) as error:
        Environments(connection).require_release(
            session.actor,
            release.id,
            profile="project-stdio.v1",
            language="python",
        )
    assert error.value.code == "precondition_failed"
    assert service.snapshot(session.token).demands[0].release.id == release.id


def test_old_decision_receipt_is_read_only_after_revoke_and_key_body_is_exact(
    environment_setup,
    database,
):
    service, session = environment_setup
    demand = request(service, session)
    key = str(uuid4())
    data = EnvironmentDecisionInput(
        expected_requirement_revision=1,
        expected_decision_revision=0,
        decision="allow",
    )
    first = service.decide(session.token, demand.id, key, data)
    current = service.snapshot(session.token).demands[0]
    decide(service, session, current, "revoke")
    assert service.decision_receipt(session.token, demand.id, key) == first
    assert service.decide(session.token, demand.id, key, data) == first
    assert service.snapshot(session.token).demands[0].status == "revoked"
    with pytest.raises(BusinessError) as error:
        service.decide(session.token, demand.id, key, data.model_copy(update={"decision": "defer"}))
    assert error.value.code == "idempotency_conflict"
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM execution.environment_preparation_jobs "
                "WHERE demand_id=%s",
                (demand.id,),
            ).fetchone()["n"]
            == 1
        )


def test_requirement_expansion_waits_for_new_consent_and_preserves_original_request_receipt(
    environment_setup,
):
    service, session = environment_setup
    key = str(uuid4())
    original = request(service, session, recipe_id="python-standard.v1", key=key)
    decide(service, session, original)
    expanded = request(service, session, recipe_id="python-flask.v1", revision=1)
    assert expanded.id == original.id and expanded.requirement_revision == 2
    assert expanded.status == "waiting_authorization" and expanded.decision is None
    assert service.request_receipt(session.token, key) == original
    assert request(service, session, recipe_id="python-standard.v1", key=key) == original
    ready_engine(service)
    assert claim(service) is None


def test_dual_compare_and_swap_rejects_stale_decisions(environment_setup):
    service, session = environment_setup
    demand = request(service, session)

    def submit(value):
        try:
            return decide(service, session, demand, value).decision
        except BusinessError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        result = list(workers.map(submit, ["allow", "defer"]))
    assert result.count("stale_version") == 1


def test_revoked_and_expired_installation_receipts_never_publish_a_release(
    environment_setup,
    database,
):
    service, session = environment_setup
    demand, work = allowed_work(service, session)
    current = service.snapshot(session.token).demands[0]
    decide(service, session, current, "revoke")
    assert service.report(work.job_id, release_report(work)) is None
    assert service.report(work.job_id, release_report(work)) is None
    with pytest.raises(BusinessError) as error:
        service.report(work.job_id, release_report(work, "2"))
    assert error.value.code == "idempotency_conflict"
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status,late_report FROM execution.environment_preparation_jobs WHERE id=%s",
            (work.job_id,),
        ).fetchone()
        assert row["status"] == "cancelled" and row["late_report"]["outcome"] == "ready"
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM execution.environment_releases WHERE demand_id=%s",
                (demand.id,),
            ).fetchone()["n"]
            == 0
        )


def test_preparation_unknown_keeps_original_claim_and_only_explicit_rebuild_queues_new_work(
    environment_setup,
    database,
):
    service, session = environment_setup
    demand, work = allowed_work(service, session)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE execution.environment_preparation_jobs "
            "SET lease_until=now()-interval '1 second'"
            " WHERE id=%s",
            (work.job_id,),
        )
    service.expire()
    current = service.snapshot(session.token).demands[0]
    assert current.status == "blocked_unknown"
    assert claim(service) is None
    assert service.report(work.job_id, release_report(work)) is None
    key = str(uuid4())
    body = EnvironmentRebuildInput(
        expected_requirement_revision=current.requirement_revision,
        expected_decision_revision=current.decision_revision,
    )
    receipt = service.rebuild(session.token, demand.id, key, body)
    assert service.rebuild_receipt(session.token, demand.id, key) == receipt
    assert service.rebuild(session.token, demand.id, key, body) == receipt
    assert claim(service).job_id != work.job_id


def test_other_actor_cannot_read_receipts_use_release_or_decide_foreign_requirement(
    environment_setup,
    workflow,
    database,
):
    service, session = environment_setup
    demand, work = allowed_work(service, session)
    release = service.report(work.job_id, release_report(work))
    other = workflow.create_session("Separate environment owner")
    with pytest.raises(BusinessError) as error:
        service.decide(
            other.token,
            demand.id,
            str(uuid4()),
            EnvironmentDecisionInput(
                expected_requirement_revision=1,
                expected_decision_revision=1,
                decision="revoke",
            ),
        )
    assert error.value.code == "not_found"
    with database.transaction() as connection, pytest.raises(BusinessError) as error:
        Environments(connection).require_release(
            other.actor,
            release.id,
            profile="project-stdio.v1",
            language="python",
        )
    assert error.value.code == "not_found"


def test_managed_base_is_automatically_queued_and_audits_its_actual_authority(
    environment_setup, database,
):
    service, session = environment_setup
    demand = request(service, session, "typescript-standard.v1")
    assert demand.decision == "allow" and demand.decision_revision == 1
    assert demand.status == "queued"
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM execution.environment_install_decisions WHERE demand_id=%s",
            (demand.id,),
        ).fetchone()
        decision = Environments._decision(row)
        assert decision.authorization_basis == "managed_base"
        assert row["command"]["authorization_basis"] == "managed_base"
    again = request(service, session, "typescript-standard.v1")
    assert again.decision_revision == 1
    decide(service, session, again, "revoke")
    stopped = request(service, session, "typescript-standard.v1")
    assert stopped.status == "revoked" and stopped.decision_revision == 2


def test_managed_base_never_replaces_unknown_preparation_with_an_updated_recipe(
    environment_setup, database, monkeypatch,
):
    service, session = environment_setup
    ready_engine(service)
    demand = request(service, session, "typescript-standard.v1")
    work = claim(service)
    assert work.demand_id == demand.id
    with database.transaction() as connection:
        connection.execute(
            "UPDATE execution.environment_preparation_jobs "
            "SET lease_until=now()-interval '1 second' "
            "WHERE id=%s", (work.job_id,),
        )
    service.expire()
    assert request(service, session, "typescript-standard.v1").status == "blocked_unknown"
    maintained = recipe("typescript-standard.v1")
    monkeypatch.setitem(RECIPES, maintained.requirement.recipe_id, replace(
        maintained, requirement=maintained.requirement.model_copy(update={
            "dependency_lock": [*maintained.requirement.dependency_lock, "new-tooling==1"],
        }),
    ))
    with pytest.raises(BusinessError) as error:
        request(service, session, "typescript-standard.v1", revision=1)
    assert error.value.code == "precondition_failed"
    current = service.snapshot(session.token).demands[0]
    assert current.requirement_revision == 1 and current.status == "blocked_unknown"
    assert claim(service) is None
