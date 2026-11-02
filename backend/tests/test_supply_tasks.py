import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_automatic_supply import automatic_request, child, finish_version
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import blind, document, finish, review, run_model, stages
from test_item_supply import supply_setup as supply_setup
from test_python_execution import code_document, owned_claim, program
from test_supply_evaluation import finish_supply, need_supply
from test_transfers import relation_report

from leornian.agent_runtime.contracts import Receipt
from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.automatic_supply import AutomaticSupply
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.transfer_contracts import TransferAnswer, TransferRequest
from leornian.modules.item_bank.demand_contracts import SupplyRequest
from leornian.modules.item_bank.supply_contracts import SLOTS
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.knowledge.contracts import AdmitSource
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError


def test_cancel_old_version_fences_queued_successor_and_preserves_reports(
    database, session, supply_setup
):
    supply, tutor, settings, _, source = supply_setup
    parent = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, parent, "Parent", failed_role="technical")
    AutomaticSupply(database, settings).advance(parent.pack_id)
    successor = child(database, parent.pack_id)
    run_id = supply.get(session.token, successor["id"]).pending_run_id
    supply.cancel_pack(session.token, parent.pack_id)
    calls = []
    run_model(tutor, settings, run_id, document(source), observe=calls.append)
    assert not calls
    assert supply.get(session.token, successor["id"]).status == "cancelled"
    assert supply.get(session.token, parent.pack_id).automation_status == "cancelled"
    assert len([s for s in stages(database, parent.pack_id) if s["result"]]) == 8
    assert AutomaticSupply(database, settings).advance(successor["id"]) == 0


def test_cancel_and_automatic_revision_are_serialized_as_one_task(database, session, supply_setup):
    supply, _, settings, _, _ = supply_setup
    parent = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, parent, "Concurrent", failed_role="security")
    automatic = AutomaticSupply(database, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(automatic.advance, parent.pack_id)
        b = pool.submit(supply.cancel_pack, session.token, parent.pack_id)
        a.result(timeout=15)
        b.result(timeout=15)
    successor = child(database, parent.pack_id)
    if successor:
        assert supply.get(session.token, successor["id"]).status == "cancelled"
    assert automatic.advance(parent.pack_id) == 0


def test_cancel_parent_during_child_call_records_late_fact_without_continuation(
    database, session, supply_setup
):
    supply, tutor, settings, _, source = supply_setup
    parent = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, parent, "Parent", failed_role="technical")
    AutomaticSupply(database, settings).advance(parent.pack_id)
    successor = child(database, parent.pack_id)
    run_id = supply.get(session.token, successor["id"]).pending_run_id

    def response(_):
        supply.cancel_pack(session.token, parent.pack_id)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": json.dumps(document(source))},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(response))).run(run_id)
    with database.transaction() as c:
        call = c.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE run_id=%s", (run_id,)
        ).fetchone()
    assert call == {"status": "result_recorded", "applied": False}
    assert len(stages(database, successor["id"])) == 1


@pytest.mark.parametrize(
    "role,mutation",
    [
        ("author", "missing_slot"),
        ("blind", "missing_slot"),
        ("author", "duplicate_prompt"),
        ("blind", "duplicate_slot"),
    ],
)
def test_known_invalid_author_or_blind_output_is_repaired_beyond_three_steps(
    database, session, supply_setup, role, mutation
):
    supply, tutor, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    if role == "blind":
        run_model(tutor, settings, accepted.run_id, document(source))
    run_id = supply.get(session.token, accepted.pack_id).pending_run_id
    invalid = document(source) if role == "author" else blind()
    if mutation == "missing_slot":
        invalid["items" if role == "author" else "answers"].pop()
    elif mutation == "duplicate_prompt":
        invalid["items"][1]["prompt"] = invalid["items"][0]["prompt"]
    else:
        invalid["answers"][1]["slot"] = invalid["answers"][0]["slot"]
    automatic = AutomaticSupply(database, settings)
    for _ in range(4):
        run_model(tutor, settings, run_id, invalid)
        assert tutor.get(session.token, run_id).status == "failed"
        assert automatic.advance(accepted.pack_id) == 1
    run_model(tutor, settings, run_id, document(source) if role == "author" else blind())
    assert tutor.get(session.token, run_id).status == "succeeded"
    finish(database, supply_setup, accepted)
    automatic.advance(accepted.pack_id)
    assert supply.get(session.token, accepted.pack_id).status == "published"
    with database.transaction() as c:
        calls = c.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE run_id=%s ORDER BY step",
            (run_id,),
        ).fetchall()
    assert len(calls) == 5 and all(c["status"] == "result_recorded" for c in calls)


def test_repeated_format_repair_never_changes_a_negative_review_to_clearance(
    database, session, supply_setup
):
    supply, tutor, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    run_model(tutor, settings, accepted.run_id, document(source))
    run_model(tutor, settings, supply.get(session.token, accepted.pack_id).pending_run_id, blind())
    run_id = supply.get(session.token, accepted.pack_id).pending_run_id
    invalid = review(False)
    invalid["relationship_reason"] = "x" * 901
    automatic = AutomaticSupply(database, settings)
    for _ in range(4):
        run_model(tutor, settings, run_id, invalid)
        automatic.advance(accepted.pack_id)
    run_model(tutor, settings, run_id, review(True))
    assert tutor.get(session.token, run_id).error_code == "review_verdict_changed"
    automatic.advance(accepted.pack_id)
    run_model(tutor, settings, run_id, review(False))
    finish(database, supply_setup, accepted)
    assert supply.get(session.token, accepted.pack_id).status == "changes_required"
    assert supply.get(session.token, accepted.pack_id).published_at is None


def test_source_wait_recovers_same_task_without_a_new_root(database, session, supply_setup):
    from datetime import UTC, datetime, timedelta

    supply, _, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    finish_version(database, supply_setup, accepted, "Restore")
    knowledge = KnowledgeWorkflow(database)
    knowledge.revoke(session.token, source.id, 1)
    automatic = AutomaticSupply(database, settings)
    automatic.advance(accepted.pack_id)
    assert supply.get(session.token, accepted.pack_id).automation_status == "waiting"
    knowledge.admit(
        session.token,
        source.id,
        AdmitSource(expected_revision=1, valid_until=datetime.now(UTC) + timedelta(days=1)),
    )
    automatic.advance(accepted.pack_id)
    summary = supply.get(session.token, accepted.pack_id)
    assert summary.status == "published" and summary.automation_status == "completed"
    assert child(database, accepted.pack_id) is None


def test_missing_supply_prepares_transfer_without_opening_or_progress(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(
        session.token,
        remediation.id,
        str(uuid4()),
        SupplyRequest(expected_plan_revision=1, instruction="New independently useful contexts."),
    )
    finish_supply(database, session, gate_setup, demand)
    supply, tutor, settings, _, _ = gate_setup[2]
    automatic = AutomaticSupply(database, settings)
    assert automatic.advance(demand.pack.id) == 1
    assert supply.get(session.token, demand.pack.id).automation_status == "running"
    assert automatic.advance(demand.pack.id) == 1
    transfer = workflow.snapshot(session.token).transfers[0]
    assert transfer.status == "preparing"
    assert automatic.advance(demand.pack.id) == 0
    assert supply.get(session.token, demand.pack.id).automation_action == "check_transfer"
    assert supply.get(session.token, demand.pack.id).automation_status == "running"
    run_model(tutor, settings, transfer.relation_run_id, relation_report(database, transfer.id))
    automatic.advance(demand.pack.id)
    assert supply.get(session.token, demand.pack.id).automation_status == "completed"
    snapshot = workflow.snapshot(session.token)
    assert snapshot.transfers[0].status == "ready" and snapshot.transfers[0].opened_at is None
    assert not snapshot.node_progress
    with database.transaction() as c:
        assert not c.execute(
            "SELECT 1 FROM item_bank.exposure_facts WHERE actor_id=%s AND pack_id=%s",
            (session.actor.id, demand.pack.id),
        ).fetchone()


def test_cancel_published_supply_does_not_unpublish_or_start_transfer(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(
        session.token,
        remediation.id,
        str(uuid4()),
        SupplyRequest(expected_plan_revision=1, instruction="Qualified successor supply."),
    )
    finish_supply(database, session, gate_setup, demand)
    supply, _, settings, _, _ = gate_setup[2]
    automatic = AutomaticSupply(database, settings)
    automatic.advance(demand.pack.id)
    result = supply.cancel_pack(session.token, demand.pack.id)
    assert result.status == "published" and result.automation_status == "cancelled"
    assert automatic.advance(demand.pack.id) == 0
    assert not workflow.snapshot(session.token).transfers
    with pytest.raises(BusinessError) as error:
        supply.resume_automation(session.token, demand.pack.id)
    assert error.value.code == "supply_cancelled"


def test_restarted_coordinator_consumes_only_a_complete_late_receipt_not_unknown(
    database, session, supply_setup
):
    supply, tutor, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    gateway = ChatCompletionsGateway(settings)
    call = tutor.prepare(
        lease,
        gateway.endpoint,
        gateway.request(role.messages, require_tool=False, allowed_tools=(), json_output=True),
    )
    assert tutor.dispatch(lease, call.id)
    tutor.block_unknown(lease)
    assert AutomaticSupply(database, settings).advance(accepted.pack_id) == 0
    tutor.record(
        call.id,
        Receipt(
            http_status=200,
            body=json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(document(source)),
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
            ),
        ),
    )
    assert AutomaticSupply(database, settings).advance(accepted.pack_id) == 1
    observed = []
    run_model(tutor, settings, accepted.run_id, {}, observe=observed.append)
    assert not observed
    assert supply.get(session.token, accepted.pack_id).status == "blind_solving"
    with database.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM runtime.external_calls WHERE run_id=%s",
                (accepted.run_id,),
            ).fetchone()["n"]
            == 1
        )


def prepare_missing_transfer(database, workflow, session, gate_setup):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(
        session.token,
        remediation.id,
        str(uuid4()),
        SupplyRequest(expected_plan_revision=1, instruction="Different contextual decisions."),
    )
    finish_supply(database, session, gate_setup, demand)
    supply, tutor, settings, _, _ = gate_setup[2]
    automatic = AutomaticSupply(database, settings)
    automatic.advance(demand.pack.id)
    automatic.advance(demand.pack.id)
    return demand, workflow.snapshot(session.token).transfers[0], automatic, supply, tutor, settings


def test_failed_transfer_quality_creates_a_new_version_then_completes_delivery(
    database, workflow, session, gate_setup
):
    demand, transfer, automatic, supply, tutor, settings = prepare_missing_transfer(
        database, workflow, session, gate_setup
    )
    run_model(
        tutor,
        settings,
        transfer.relation_run_id,
        relation_report(database, transfer.id, "uncertain"),
    )
    assert automatic.advance(demand.pack.id) == 1
    successor = child(database, demand.pack.id)
    assert successor["transfer_feedback_id"] == transfer.id
    summary = supply.get(session.token, successor["id"])
    from types import SimpleNamespace

    finish_version(
        database,
        gate_setup[2],
        SimpleNamespace(pack_id=successor["id"], run_id=summary.pending_run_id),
        "Redesigned successor",
    )
    automatic.advance(successor["id"])
    automatic.advance(successor["id"])
    latest = next(t for t in workflow.snapshot(session.token).transfers if t.id != transfer.id)
    run_model(tutor, settings, latest.relation_run_id, relation_report(database, latest.id))
    automatic.advance(successor["id"])
    assert supply.get(session.token, successor["id"]).automation_status == "completed"
    assert supply.get(session.token, demand.pack.id).status == "published"
    with database.transaction() as c:
        previous = c.execute(
            "SELECT status,relation_report FROM assessment.transfer_checks WHERE id=%s",
            (transfer.id,),
        ).fetchone()
    assert previous["status"] == "blocked" and previous["relation_report"]


def test_transfer_format_recovery_preserves_full_pair_verdicts_across_many_steps(
    database, workflow, session, gate_setup
):
    demand, transfer, automatic, supply, tutor, settings = prepare_missing_transfer(
        database, workflow, session, gate_setup
    )
    invalid = relation_report(database, transfer.id)
    invalid["comparisons"][0]["reason"] = "x" * 181
    for _ in range(4):
        run_model(tutor, settings, transfer.relation_run_id, invalid)
        assert automatic.advance(demand.pack.id) == 1
    run_model(tutor, settings, transfer.relation_run_id, relation_report(database, transfer.id))
    automatic.advance(demand.pack.id)
    assert supply.get(session.token, demand.pack.id).automation_status == "completed"
    with database.transaction() as c:
        calls = c.execute(
            "SELECT response_body FROM runtime.external_calls WHERE run_id=%s ORDER BY step",
            (transfer.relation_run_id,),
        ).fetchall()
    assert len(calls) == 5 and "x" * 181 in calls[0]["response_body"]


def test_changed_teaching_context_invalidates_assignment_and_reauthors_in_same_task(
    database, workflow, session, gate_setup
):
    from leornian.bootstrap.evaluation import EvaluationWorkflow

    demand, transfer, automatic, supply, tutor, settings = prepare_missing_transfer(
        database, workflow, session, gate_setup
    )
    run_model(tutor, settings, transfer.relation_run_id, relation_report(database, transfer.id))
    automatic.advance(demand.pack.id)
    evaluation = workflow.snapshot(session.token).evaluations[0]
    accepted = EvaluationWorkflow(database, settings).request(session.token, evaluation.id)
    run_model(
        tutor,
        settings,
        accepted.run_id,
        {
            "recorded_correct": evaluation.correct,
            "explanation": "新增的讲评已经解释了一个具体解法。",
            "reflection": "另一个情境为什么需要不同决策？",
        },
    )
    assert automatic.advance(demand.pack.id) == 1
    successor = child(database, demand.pack.id)
    assert successor and successor["revision"] == 2
    with database.transaction() as c:
        old = c.execute(
            "SELECT status,error_code,relation_report FROM assessment.transfer_checks WHERE id=%s",
            (transfer.id,),
        ).fetchone()
    assert old["status"] == "blocked" and old["error_code"] == "stale_version"
    assert old["relation_report"]
    assert supply.get(session.token, successor["id"]).supply_task_id == demand.pack.supply_task_id


def test_known_provider_auth_rejection_waits_for_explicit_configuration_recovery(
    database, session, supply_setup
):
    supply, tutor, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    observed = []

    def rejected(request):
        observed.append(request)
        return httpx.Response(401, json={"error": "Owned authentication rejection"})

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(rejected))).run(
        accepted.run_id
    )
    automatic = AutomaticSupply(database, settings)
    for _ in range(3):
        assert automatic.advance(accepted.pack_id) == 0
    assert len(observed) == 1
    assert supply.get(session.token, accepted.pack_id).automation_status == "waiting"
    supply.resume_automation(session.token, accepted.pack_id)
    assert automatic.advance(accepted.pack_id) == 1
    run_model(tutor, settings, accepted.run_id, document(source))
    assert tutor.get(session.token, accepted.run_id).status == "succeeded"
    with database.transaction() as c:
        statuses = c.execute(
            "SELECT status FROM runtime.external_calls WHERE run_id=%s ORDER BY step",
            (accepted.run_id,),
        ).fetchall()
    assert statuses == [{"status": "failed_known"}, {"status": "result_recorded"}]


def test_manual_selection_racing_automatic_delivery_is_reused_without_duplicate_runs(
    database, workflow, session, gate_setup
):
    demands, remediation = need_supply(database, workflow, session, gate_setup)
    demand = demands.request(
        session.token,
        remediation.id,
        str(uuid4()),
        SupplyRequest(expected_plan_revision=1, instruction="A useful independent successor."),
    )
    finish_supply(database, session, gate_setup, demand)
    supply, tutor, settings, _, _ = gate_setup[2]
    automatic = AutomaticSupply(database, settings)
    automatic.advance(demand.pack.id)
    transfer = TransferWorkflow(database, settings).request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    run_model(tutor, settings, transfer.relation_run_id, relation_report(database, transfer.id))
    assert automatic.advance(demand.pack.id) == 0
    assert supply.get(session.token, demand.pack.id).automation_status == "completed"
    assert len(workflow.snapshot(session.token).transfers) == 1


def test_task_fence_alone_preserves_inflight_unknown_before_cleanup_can_run(
    database, session, supply_setup
):
    _, tutor, settings, _, _ = supply_setup
    accepted = automatic_request(session, supply_setup)
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    gateway = ChatCompletionsGateway(settings)
    call = tutor.prepare(
        lease,
        gateway.endpoint,
        gateway.request(role.messages, require_tool=False, allowed_tools=(), json_output=True),
    )
    assert tutor.dispatch(lease, call.id)
    with database.transaction() as c:
        SupplyTasks(c).cancel(session.actor, accepted.pack_id)
    assert tutor.context(lease) is None
    with database.transaction() as c:
        fact = c.execute(
            "SELECT status FROM runtime.external_calls WHERE id=%s", (call.id,)
        ).fetchone()
    assert fact["status"] == "unknown"
    assert tutor.get(session.token, accepted.run_id).status == "cancelled"


def test_stopping_generation_does_not_revoke_an_already_opened_learner_successor(
    database, workflow, session, gate_setup
):
    demand, transfer, automatic, supply, tutor, settings = prepare_missing_transfer(
        database, workflow, session, gate_setup
    )
    run_model(tutor, settings, transfer.relation_run_id, relation_report(database, transfer.id))
    automatic.advance(demand.pack.id)
    transfers = TransferWorkflow(database, settings)
    transfers.open(session.token, transfer.id)
    supply.cancel_pack(session.token, demand.pack.id)
    result = transfers.submit(
        session.token, transfer.id, str(uuid4()), TransferAnswer(selected_key="A")
    )
    assert result.transfer.status == "passed"
    assert not workflow.snapshot(session.token).node_progress


def test_partial_negative_review_cannot_be_washed_to_pass_while_filling_missing_slot(
    database, session, supply_setup
):
    supply, tutor, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    run_model(tutor, settings, accepted.run_id, document(source))
    run_model(tutor, settings, supply.get(session.token, accepted.pack_id).pending_run_id, blind())
    run_id = supply.get(session.token, accepted.pack_id).pending_run_id
    partial = review(False)
    partial["items"].pop()
    run_model(tutor, settings, run_id, partial)
    automatic = AutomaticSupply(database, settings)
    automatic.advance(accepted.pack_id)
    run_model(tutor, settings, run_id, review(True))
    assert tutor.get(session.token, run_id).error_code == "review_verdict_changed"
    automatic.advance(accepted.pack_id)
    run_model(tutor, settings, run_id, review(False))
    finish(database, supply_setup, accepted)
    assert supply.get(session.token, accepted.pack_id).status == "changes_required"


def test_conflicting_review_decisions_reauthor_instead_of_retrying_for_clearance(
    database, session, supply_setup
):
    supply, tutor, settings, _, source = supply_setup
    accepted = automatic_request(session, supply_setup)
    run_model(tutor, settings, accepted.run_id, document(source))
    run_model(tutor, settings, supply.get(session.token, accepted.pack_id).pending_run_id, blind())
    run_id = supply.get(session.token, accepted.pack_id).pending_run_id
    conflicting = review(False)
    conflicting["items"].append({**conflicting["items"][0], "verdict": "pass"})
    run_model(tutor, settings, run_id, conflicting)
    automatic = AutomaticSupply(database, settings)
    automatic.advance(accepted.pack_id)
    assert tutor.get(session.token, run_id).error_code == "conflicting_review_verdicts"
    assert automatic.advance(accepted.pack_id) == 1
    assert child(database, accepted.pack_id)["revision"] == 2
    with database.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM runtime.external_calls WHERE run_id=%s", (run_id,)
            ).fetchone()["n"]
            == 1
        )


def test_task_http_controls_keep_ownership_and_private_authority_out_of_dtos(
    database, workflow, session, supply_setup
):
    _, _, settings, _, _ = supply_setup
    accepted = automatic_request(session, supply_setup)
    client = TestClient(create_app(settings))
    other = workflow.create_session("Not the task owner")
    for action in ("cancel", "automation-resume"):
        response = client.post(
            f"/v1/packs/{accepted.pack_id}/{action}",
            headers={"Authorization": "Bearer " + other.token},
        )
        assert response.status_code == 404
    response = client.post(
        f"/v1/packs/{accepted.pack_id}/cancel",
        headers={"Authorization": "Bearer " + session.token},
    )
    assert response.status_code == 200 and response.json()["automation_status"] == "cancelled"
    assert "session_digest" not in response.text and "repair_base_messages" not in response.text


def test_runner_waits_for_task_before_taking_plan_lock(
    database, session, supply_setup, monkeypatch
):
    supply, tutor, settings, plan, source = supply_setup
    accepted = automatic_request(session, supply_setup, kind="python_io")
    run_model(tutor, settings, accepted.run_id, code_document(source))
    run_model(
        tutor,
        settings,
        supply.get(session.token, accepted.pack_id).pending_run_id,
        {"programs": [{"slot": slot, "code": program(slot)} for slot in SLOTS]},
    )
    task_id = supply.get(session.token, accepted.pack_id).supply_task_id
    reached = Event()
    original = SupplyTasks.require_current

    def observe(store, actor, pack_id):
        reached.set()
        return original(store, actor, pack_id)

    monkeypatch.setattr(SupplyTasks, "require_current", observe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.transaction() as c:
            SupplyTasks(c).lock(session.actor, task_id)
            pending = pool.submit(owned_claim, database, session)
            assert reached.wait(10)
            c.execute("SET LOCAL lock_timeout='2s'")
            # If Runner held plan -> task, this would deadlock with the coordinator.
            Plans(c).get(session.actor, plan.id, lock=True)
        assert pending.result(timeout=15) is not None
    supply.cancel_pack(session.token, accepted.pack_id)
