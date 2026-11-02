import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from test_concept_gates import gate_setup as gate_setup
from test_concept_gates import practice
from test_item_supply import supply_setup as supply_setup
from test_transfers import transfer_setup as transfer_setup

from leornian.agent_runtime.gateway import ChatCompletionsGateway, ModelProtocolError
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.relation_batches import RelationBatches
from leornian.bootstrap.transfer import TransferWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.assessment.gate_contracts import GateRelations, GateRequest
from leornian.modules.assessment.transfer_contracts import TransferRequest
from leornian.modules.identity.application import Identity
from leornian.shared_kernel.errors import BusinessError


@pytest.mark.parametrize("cross_risk", [False, True])
def test_full_history_beyond_32_is_reviewed_in_persisted_batches(
    database, session, gate_setup, cross_risk
):
    _, pack, (_, old_tutor, settings, plan, _) = gate_setup
    practice(session, gate_setup)
    conversation = old_tutor.conversation(session.token, plan.goal_id)
    ids = []
    with database.transaction() as connection:
        for index in range(40):
            turn_id = uuid4()
            ids.append(str(turn_id))
            connection.execute(
                "INSERT INTO tutor.turns(id,conversation_id,idempotency_key,user_text,"
                "assistant_text,purpose,completed_at) VALUES(%s,%s,%s,%s,%s,'teaching',now())",
                (
                    turn_id,
                    conversation.id,
                    str(uuid4()),
                    f"Earlier question {index}",
                    "An actual earlier explanation. " + "Facts " * 150,
                ),
            )
    settings = replace(
        settings, delivery_enabled=True, model_context_tokens=128000, model_max_output_tokens=32768
    )
    gates = ConceptGate(database, settings)
    tutor = TutorWorkflow(database, settings)
    gate = gates.request(
        session.token, pack.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    sent = []

    def handle(request):
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        sent.append(payload)
        final = "reviewed_raw_summaries" in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "comparisons": [
                                        {
                                            **pair,
                                            "verdict": "uncertain"
                                            if cross_risk and final
                                            else "distinct_decision",
                                            "reason": "Cross-fragment risk."
                                            if cross_risk and final
                                            else "Different decision.",
                                        }
                                        for pair in payload["required_comparisons"]
                                    ],
                                    "exposure_summary": (
                                        "Inspected the identified raw teaching fragment."
                                    ),
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            },
        )

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    for _ in range(80):  # Test timeout only, not an application task limit.
        AgentLoop(tutor, gateway).run(gate.relation_run_id)
        if tutor.get(session.token, gate.relation_run_id).status != "queued":
            break
    with database.transaction() as connection:
        stored = connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE id=%s", (gate.id,)
        ).fetchone()
        calls = connection.execute(
            "SELECT count(*) n FROM runtime.external_calls WHERE run_id=%s",
            (gate.relation_run_id,),
        ).fetchone()["n"]
    assert len(stored["relation_parts"]) == len(sent) == calls > 3
    raw = "".join(
        p["context"]["learning_context"]["serialized_fragment"]
        for p in sent
        if "learning_context" in p["context"]
    )
    assert raw == json.dumps(
        stored["context_data"]["learning_context"], ensure_ascii=False, indent=2
    )
    assert all(turn_id in raw for turn_id in ids)
    assert sent[-1]["coverage"] == ["cross_batch_risk"]
    assert stored["status"] == ("blocked" if cross_risk else "ready")
    expected = {(p["left"], p["right"]) for p in stored["comparisons"]}
    assert {(p["left"], p["right"]) for p in stored["relation_report"]["comparisons"]} == expected


def test_transfer_batch_format_repair_keeps_only_current_batch_verdicts(
    database, session, transfer_setup
):
    _, remediation, _, (_, _, (_, old_tutor, settings, plan, _)) = transfer_setup
    conversation = old_tutor.conversation(session.token, plan.goal_id)
    with database.transaction() as connection:
        for index in range(40):
            connection.execute(
                "INSERT INTO tutor.turns(id,conversation_id,idempotency_key,user_text,"
                "assistant_text,purpose,completed_at) VALUES(%s,%s,%s,%s,%s,'teaching',now())",
                (uuid4(), conversation.id, str(uuid4()), f"Context {index}", "A fact. " * 150),
            )
    settings = replace(
        settings, delivery_enabled=True, model_context_tokens=128000, model_max_output_tokens=32768
    )
    transfer = TransferWorkflow(database, settings)
    tutor = TutorWorkflow(database, settings)
    row = transfer.request(
        session.token, remediation.id, str(uuid4()), TransferRequest(expected_plan_revision=1)
    )
    bad_batch = None
    malformed_sent = False
    sent = []

    def handle(request):
        nonlocal bad_batch, malformed_sent
        messages = json.loads(request.content)["messages"]
        payload = next(
            json.loads(m["content"])
            for m in messages
            if m["role"] == "user" and m["content"].startswith('{"context":')
        )
        sent.append(payload)
        if bad_batch is None and "teaching_context" in payload["context"]:
            bad_batch = payload["batch_index"]
        checks = [
            {
                **pair,
                "verdict": "uncertain"
                if payload["batch_index"] == bad_batch and i == 0
                else "distinct_decision",
                "reason": "Actual fragment relationship.",
            }
            for i, pair in enumerate(payload["required_comparisons"])
        ]
        if payload["batch_index"] == bad_batch and not malformed_sent:
            malformed_sent = True
            checks[0]["reason"] = "x" * 181
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "comparisons": checks,
                                    "exposure_summary": "Inspected raw context.",
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            },
        )

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    repairs = 0
    for _ in range(80):
        AgentLoop(tutor, gateway).run(row.relation_run_id)
        state = tutor.get(session.token, row.relation_run_id)
        if state.status == "failed":
            assert state.error_code == "invalid_transfer_output"
            transfer.repair_digest(Identity.digest(session.token), row.id)
            repairs += 1
        elif state.status != "queued":
            assert state.status == "succeeded"
            break
    else:
        pytest.fail("Owned transfer fixture did not finish")
    with database.transaction() as connection:
        stored = connection.execute(
            "SELECT * FROM assessment.transfer_checks WHERE id=%s", (row.id,)
        ).fetchone()
    assert repairs == 1 and len(stored["relation_parts"]) == len(sent) - 1 > 3
    assert stored["status"] == "ready"
    assert any(p["verdict"] == "uncertain" for p in stored["relation_report"]["comparisons"])


@pytest.mark.parametrize(
    ("extra_verdict", "cancel_before_resume"),
    [("distinct_decision", False), ("uncertain", False), ("distinct_decision", True)],
)
def test_known_gate_batch_receipt_recovery_retains_extra_facts_without_resending(
    database, session, gate_setup, monkeypatch, extra_verdict, cancel_before_resume
):
    _, pack, (_, _, settings, _, _) = gate_setup
    practice(session, gate_setup)
    settings = replace(
        settings, delivery_enabled=True, model_context_tokens=128000, model_max_output_tokens=32768
    )
    monkeypatch.setattr(RelationBatches, "working_tokens", 1000)
    gates = ConceptGate(database, settings)
    tutor = TutorWorkflow(database, settings)
    gate = gates.request(
        session.token, pack.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    with database.transaction() as connection:
        stored = connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE id=%s", (gate.id,)
        ).fetchone()
    all_pairs = stored["comparisons"]
    sent = []

    def handle(request):
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        sent.append(payload["batch_index"])
        checks = [
            {**pair, "verdict": "distinct_decision", "reason": "Actual distinct decision."}
            for pair in payload["required_comparisons"]
        ]
        extra = next(pair for pair in all_pairs if pair not in payload["required_comparisons"])
        checks.append({**extra, "verdict": extra_verdict, "reason": "Additional actual-pair fact."})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "comparisons": checks,
                                    "exposure_summary": "Reviewed raw fragment.",
                                }
                            ),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            },
        )

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    # Reproduce the former parser's rejection, preserving its exact completed receipt.
    with monkeypatch.context() as patch:

        def former_parser(*args, **kwargs):
            raise ModelProtocolError("invalid_relation_batch")

        patch.setattr(RelationBatches, "consume", former_parser)
        AgentLoop(tutor, gateway).run(gate.relation_run_id)
    state = tutor.get(session.token, gate.relation_run_id)
    assert state.status == "failed" and state.can_resume
    assert gates.view(session.token, gate.id).questions == []
    with database.transaction() as connection:
        first = connection.execute(
            "SELECT * FROM runtime.external_calls WHERE run_id=%s ORDER BY step LIMIT 1",
            (gate.relation_run_id,),
        ).fetchone()
    if cancel_before_resume:
        gates.cancel(session.token, gate.id)
        assert not tutor.get(session.token, gate.relation_run_id).can_resume
        with pytest.raises(BusinessError):
            tutor.resume(session.token, gate.relation_run_id)
        assert sent == [0]
        return
    tutor.resume(session.token, gate.relation_run_id)
    for _ in range(40):
        AgentLoop(tutor, gateway).run(gate.relation_run_id)
        if tutor.get(session.token, gate.relation_run_id).status != "queued":
            break
    else:
        pytest.fail("Recorded Gate review did not finish.")
    with database.transaction() as connection:
        stored = connection.execute(
            "SELECT * FROM assessment.concept_gates WHERE id=%s", (gate.id,)
        ).fetchone()
        receipt = connection.execute(
            "SELECT * FROM runtime.external_calls WHERE id=%s", (first["id"],)
        ).fetchone()
    assert receipt["response_body"] == first["response_body"] and receipt["applied"]
    assert sent == list(range(len(sent)))  # The rejected call was consumed, never sent twice.
    assert len(stored["relation_parts"]) == len(sent)
    assert gates.view(session.token, gate.id).questions == []
    if extra_verdict == "uncertain":
        assert stored["status"] == "blocked" and sent == [0]
        assert any(
            pair["verdict"] == "uncertain" for pair in stored["relation_report"]["comparisons"]
        )
    else:
        assert stored["status"] == "ready"
        assert len(stored["relation_parts"]) == len(RelationBatches.batches(stored))
        assert stored["relation_parts"][-1]["coverage"] == ["cross_batch_risk"]


@pytest.mark.parametrize("invalid", ["missing", "unrelated"])
def test_relation_batches_still_reject_missing_or_unrelated_pairs(monkeypatch, invalid):
    pair = {"left": "assessment_1", "right": "learning_context"}
    monkeypatch.setattr(RelationBatches, "batches", lambda row: [{"required_comparisons": [pair]}])
    row = {"relation_parts": [], "comparisons": [pair]}
    checks = [
        {
            **({"left": "assessment_2", "right": "other"} if invalid == "missing" else pair),
            "verdict": "distinct_decision",
            "reason": "A decision.",
        }
    ]
    if invalid == "unrelated":
        checks.append(
            {"left": "unknown", "right": "other", "verdict": "uncertain", "reason": "Unknown."}
        )
    with pytest.raises(ModelProtocolError, match="invalid_relation_batch"):
        RelationBatches.consume(
            None, row, GateRelations(comparisons=checks, exposure_summary="Raw."), "gate"
        )
