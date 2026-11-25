import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import relation_document
from test_item_supply import blind, document, finish, request_data, review, run_model, stages
from test_item_supply import supply_setup as supply_setup
from test_python_execution import code_document, owned_claim, program, receipt
from test_runner import runner as runner
from test_supply_evaluation import finish_supply, need_supply

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.automatic_supply import AutomaticSupply
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.modules.assessment.gate_contracts import GateRequest
from leornian.modules.item_bank.demand_contracts import SupplyRequest
from leornian.modules.item_bank.supply_contracts import REVIEW_ROLES, SLOTS, ChoiceInput
from leornian.modules.tutor.contracts import PlanningInput, TurnInput
from leornian.shared_kernel.errors import BusinessError


def automatic_request(session, setup, **overrides):
    supply, _, _, plan, _ = setup
    return supply.submit(
        session.token, plan.id, str(uuid4()), request_data(automatic=True, **overrides)
    )


def finish_version(database, setup, accepted, label, *, failed_role=None):
    _, tutor, settings, _, source = setup
    value = document(source)
    for item in value["items"]:
        item["prompt"] = label + ": " + item["prompt"]
    run_model(tutor, settings, accepted.run_id, value)
    finish(database, setup, accepted, fail_role=failed_role)


def child(database, pack_id):
    with database.transaction() as c:
        return c.execute(
            "SELECT * FROM item_bank.packs WHERE predecessor_id=%s", (pack_id,)
        ).fetchone()


def test_automatic_pack_publishes_without_exposing_questions_or_writing_progress(
    database, workflow, session, supply_setup
):
    supply, _, settings, _, _ = supply_setup
    accepted = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, accepted, "Initial")
    assert supply.get(session.token, accepted.pack_id).status == "ready"
    automatic = AutomaticSupply(database, settings)
    assert automatic.advance(accepted.pack_id) == 1
    assert supply.get(session.token, accepted.pack_id).status == "published"
    assert automatic.advance(accepted.pack_id) == 0
    snapshot = workflow.snapshot(session.token)
    assert snapshot.packs[0].automatic
    assert "automation_session_digest" not in snapshot.model_dump_json()
    assert "correct_key" not in snapshot.model_dump_json()
    assert not snapshot.node_progress and not snapshot.choice_results
    with database.transaction() as c:
        assert not c.execute(
            "SELECT 1 FROM item_bank.exposure_facts WHERE actor_id=%s", (session.actor.id,)
        ).fetchone()
        assert (
            c.execute(
                "SELECT count(*) AS n FROM item_bank.stages WHERE pack_id=%s", (accepted.pack_id,)
            ).fetchone()["n"]
            == 8
        )


@pytest.mark.parametrize("published", [False, True])
def test_successor_route_keeps_published_supply_complete_but_cannot_publish_old_ready_pack(
    database, session, supply_setup, published,
):
    supply, tutor, settings, plan, _ = supply_setup
    accepted = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, accepted, "Original route")
    automatic = AutomaticSupply(database, settings)
    if published:
        assert automatic.advance(accepted.pack_id) == 1
    conversation = tutor.conversation(session.token, plan.goal_id)
    successor = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(
            text="Reprepare the route from the accepted material update.", expected_revision=1,
        ),
    )
    value = plan.latest.document.model_dump(mode="json")
    value["summary"] = "Use the accepted successor material."
    run_model(tutor, settings, successor.run_id, value)
    tutor.confirm_plan(session.token, plan.id, 2)

    assert automatic.advance(accepted.pack_id) == 0
    current = supply.get(session.token, accepted.pack_id)
    assert current.status == ("published" if published else "ready")
    assert current.automation_status == ("completed" if published else "waiting")
    assert current.automation_reason == (None if published else "stale_version")
    assert len(current.reviewed_roles) == len(REVIEW_ROLES)
    assert child(database, accepted.pack_id) is None
    if published:
        with pytest.raises(BusinessError, match="current confirmed plan"):
            supply.practice(session.token, accepted.pack_id)


def test_negative_review_creates_one_changed_successor_and_automatically_publishes(
    database, session, supply_setup
):
    supply, tutor, settings, _, _ = supply_setup
    accepted = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, accepted, "Initial", failed_role="technical")
    automatic = AutomaticSupply(database, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: automatic.advance(accepted.pack_id), range(2))) == [0, 1]
    successor = child(database, accepted.pack_id)
    assert successor["revision"] == 2 and successor["automatic"]
    summary = supply.get(session.token, successor["id"])
    observed = []
    value = document(supply_setup[4])
    for item in value["items"]:
        item["prompt"] = "Changed real decision: " + item["prompt"]
    run_model(tutor, settings, summary.pending_run_id, value, observe=observed.append)
    author_context = json.loads(observed[0]["messages"][1]["content"])
    assert len(author_context["review_feedback"]) == 6
    assert author_context["revision_scope"] == {
        "predecessor_id": str(accepted.pack_id), "automatic": True,
        "instruction_inherited": True, "predecessor_published": False,
    }
    assert "Preserve sound, unaffected slots" in observed[0]["messages"][0]["content"]
    assert (
        not next(
            r["report"] for r in author_context["review_feedback"] if r["role"] == "technical"
        )["assessment_independence"]
        == "supported"
    )
    finish(database, supply_setup, SimpleNamespace(pack_id=successor["id"]))
    automatic.advance(successor["id"])
    assert supply.get(session.token, successor["id"]).status == "published"
    parent = supply.get(session.token, accepted.pack_id)
    assert parent.status == "changes_required" and len(parent.reviewed_roles) == 6
    assert child(database, successor["id"]) is None


def test_fifth_version_completes_same_task_without_a_revision_count_stop(
    database, session, supply_setup
):
    supply, _, settings, _, _ = supply_setup
    automatic = AutomaticSupply(database, settings)
    accepted = automatic_request(session, supply_setup)
    current = accepted
    task_id = supply.get(session.token, accepted.pack_id).supply_task_id
    for revision in range(1, 6):
        finish_version(
            database,
            supply_setup,
            current,
            f"Revision {revision}",
            failed_role="adversarial" if revision < 5 else None,
        )
        automatic.advance(current.pack_id)
        summary = supply.get(session.token, current.pack_id)
        assert summary.revision == revision
        assert summary.supply_task_id == task_id
        if revision < 5:
            assert summary.status == "changes_required"
            successor = child(database, current.pack_id)
            summary = supply.get(session.token, successor["id"])
            current = SimpleNamespace(pack_id=successor["id"], run_id=summary.pending_run_id)
    assert summary.status == "published" and summary.automation_status == "completed"
    assert summary.automation_error is None
    assert automatic.advance(current.pack_id) == 0
    assert child(database, current.pack_id) is None
    with database.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM item_bank.packs WHERE actor_id=%s",
                (session.actor.id,),
            ).fetchone()["n"]
            == 5
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM runtime.external_calls c JOIN runtime.runs r "
                "ON r.id=c.run_id WHERE r.actor_id=%s AND r.policy_version LIKE %s",
                (session.actor.id, "item_%"),
            ).fetchone()["n"]
            == 40
        )
        assert (
            c.execute(
                "SELECT strategy FROM item_bank.supply_tasks WHERE id=%s", (task_id,)
            ).fetchone()["strategy"]
            == "redesign_decisions"
        )


@pytest.mark.parametrize("revocation", ["session", "source"])
def test_current_authority_is_rechecked_before_automatic_publication(
    database, session, supply_setup, revocation
):
    supply, _, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, accepted, "Initial")
    if revocation == "session":
        with database.transaction() as c:
            c.execute(
                "UPDATE identity.sessions SET revoked_at=now() WHERE actor_id=%s",
                (session.actor.id,),
            )
    else:
        KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    AutomaticSupply(database, settings).advance(accepted.pack_id)
    with database.transaction() as c:
        row = c.execute("SELECT * FROM item_bank.packs WHERE id=%s", (accepted.pack_id,)).fetchone()
    assert row["status"] == "ready" and row["published_at"] is None
    with database.transaction() as c:
        task = c.execute(
            "SELECT * FROM item_bank.supply_tasks WHERE head_pack_id=%s", (accepted.pack_id,)
        ).fetchone()
    assert task["status"] == "waiting"
    assert task["reason"] == ("unauthorized" if revocation == "session" else "source_not_current")


def test_automatic_unknown_never_resends_and_cancellation_stops_the_chain(
    database, session, supply_setup
):
    supply, tutor, settings, _, _ = supply_setup
    accepted = automatic_request(session, supply_setup)
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("Owned automatic supply timeout")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(accepted.run_id)
    automatic = AutomaticSupply(database, settings)
    assert automatic.advance(accepted.pack_id) == 0
    loop.run(accepted.run_id)
    assert len(calls) == 1 and tutor.get(session.token, accepted.run_id).status == "blocked_unknown"
    supply.cancel_pack(session.token, accepted.pack_id)
    assert automatic.advance(accepted.pack_id) == 0
    assert supply.get(session.token, accepted.pack_id).status == "cancelled"
    assert len(stages(database, accepted.pack_id)) == 1


@pytest.mark.parametrize("second_invalid", [False, True])
def test_automatic_format_correction_reuses_one_step_and_preserves_raw(
    database, session, supply_setup, second_invalid
):
    supply, tutor, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    run_model(tutor, settings, accepted.run_id, document(source))
    summary = supply.get(session.token, accepted.pack_id)
    run_model(tutor, settings, summary.pending_run_id, blind())
    summary = supply.get(session.token, accepted.pack_id)
    review_run = summary.pending_run_id
    invalid = review()
    invalid["relationship_reason"] = "x" * 901
    run_model(tutor, settings, review_run, invalid)
    automatic = AutomaticSupply(database, settings)
    assert automatic.advance(accepted.pack_id) == 1
    run_model(tutor, settings, review_run, invalid if second_invalid else review())
    if second_invalid:
        automatic.advance(accepted.pack_id)
        run_model(tutor, settings, review_run, review())
        finish(database, supply_setup, accepted)
        automatic.advance(accepted.pack_id)
        assert supply.get(session.token, accepted.pack_id).status == "published"
    else:
        finish(database, supply_setup, accepted)
        automatic.advance(accepted.pack_id)
        assert supply.get(session.token, accepted.pack_id).status == "published"
    with database.transaction() as c:
        calls = c.execute(
            "SELECT * FROM runtime.external_calls WHERE run_id=%s ORDER BY step",
            (review_run,),
        ).fetchall()
    assert len(calls) == (3 if second_invalid else 2)
    assert "x" * 901 in calls[0]["response_body"]
    automatic.advance(accepted.pack_id)
    assert child(database, accepted.pack_id) is None


def finish_python(database, session, setup, *, runner=None, foreground=False):
    supply, tutor, settings, _, source = setup
    accepted = automatic_request(session, setup, kind="python_io")
    run_model(tutor, settings, accepted.run_id, code_document(source))
    summary = supply.get(session.token, accepted.pack_id)
    run_model(
        tutor,
        settings,
        summary.pending_run_id,
        {"programs": [{"slot": slot, "code": program(slot)} for slot in SLOTS]},
    )
    active = None
    if foreground:
        conversation = tutor.conversation(session.token, setup[3].goal_id)
        active = tutor.submit(
            session.token, conversation.id, str(uuid4()), TurnInput(text="先处理我的问题。")
        )
    for _ in range(5):
        claim = owned_claim(database, session)
        JourneyWorkflow(database).report(claim.job_id, receipt(database, claim, runner))
    automatic = AutomaticSupply(database, settings)
    if active:
        assert supply.get(session.token, accepted.pack_id).pending_run_id is None
        assert automatic.advance(accepted.pack_id) == 0
        tutor.cancel(session.token, active.run_id)
        assert automatic.advance(accepted.pack_id) == 1
    finish(database, setup, accepted)
    assert automatic.advance(accepted.pack_id) == 1
    published = supply.get(session.token, accepted.pack_id)
    assert published.status == "published" and published.blind_passed
    assert len(published.passed_roles) == len(REVIEW_ROLES)
    return accepted


def test_python_automation_resumes_after_foreground_without_a_manual_continue_action(
    database, session, supply_setup
):
    finish_python(database, session, supply_setup, foreground=True)


@pytest.mark.skipif(os.environ.get("LEORNIAN_TEST_DOCKER") != "1", reason="Real Docker opt-in")
def test_real_docker_automatic_qualification_six_reviews_and_publication(
    database, session, supply_setup, runner
):
    finish_python(database, session, supply_setup, runner=runner)


def test_automatic_missing_question_supply_keeps_the_demand_and_publishes(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(
        session.token,
        remediation.id,
        str(uuid4()),
        SupplyRequest(expected_plan_revision=1, instruction="不同情境的基础循环练习。"),
    )
    assert demand.pack.automatic
    finish_supply(database, session, gate_setup, demand, fail_role="difficulty")
    automatic = AutomaticSupply(database, gate_setup[2][2])
    automatic.advance(demand.pack.id)
    successor = child(database, demand.pack.id)
    assert successor["supply_demand_id"] == demand.id and successor["revision"] == 2
    summary = gate_setup[2][0].get(session.token, successor["id"])
    finish_version(
        database,
        gate_setup[2],
        SimpleNamespace(pack_id=successor["id"], run_id=summary.pending_run_id),
        "New supply",
    )
    automatic.advance(successor["id"])
    latest = workflow.snapshot(session.token).supply_demands[0]
    assert latest.id == demand.id and latest.pack.status == "published"
    assert not workflow.snapshot(session.token).node_progress


def test_actual_gate_quality_failure_automatically_revises_the_exact_published_pack(
    database, session, gate_setup
):
    gates, _, setup = gate_setup
    supply, tutor, settings, _, _ = setup
    accepted = automatic_request(session, setup)
    finish_version(database, setup, accepted, "Independent auto pack")
    automatic = AutomaticSupply(database, settings)
    automatic.advance(accepted.pack_id)
    supply.practice(session.token, accepted.pack_id)
    for slot in ("practice_1", "practice_2"):
        supply.answer(
            session.token, accepted.pack_id, str(uuid4()), ChoiceInput(slot=slot, selected_key="A")
        )
    gate = gates.request(
        session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    run_model(
        tutor,
        settings,
        gate.relation_run_id,
        relation_document(database, gate.id, "answer_leakage"),
    )
    assert gates.view(session.token, gate.id).gate.status == "blocked"
    assert automatic.advance(accepted.pack_id) == 1
    successor = child(database, accepted.pack_id)
    assert successor["gate_feedback_id"] == gate.id and successor["revision"] == 2
    assert supply.get(session.token, accepted.pack_id).status == "published"
    assert gates.view(session.token, gate.id).questions == []
    assert automatic.advance(accepted.pack_id) == 0


def test_manual_history_stays_manual_and_revision_replay_inherits_the_parent_policy(
    database, session, supply_setup
):
    supply, _, settings, plan, _ = supply_setup
    parent = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    finish_version(database, supply_setup, parent, "Legacy", failed_role="difficulty")
    automatic = AutomaticSupply(database, settings)
    assert automatic.advance(parent.pack_id) == 0
    assert child(database, parent.pack_id) is None
    key = str(uuid4())
    # The new default does not silently take over an existing manual chain.
    data = request_data(predecessor_id=parent.pack_id, automatic=True)
    successor = supply.submit(session.token, plan.id, key, data)
    assert not supply.get(session.token, successor.pack_id).automatic
    assert supply.submit(session.token, plan.id, key, data) == successor
    assert automatic.advance(successor.pack_id) == 0
