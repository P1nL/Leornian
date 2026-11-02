import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_item_supply import (
    document,
    finish,
    request_data,
    run_model,
)
from test_item_supply import (
    supply_setup as supply_setup,
)

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.gate_contracts import GateRequest, GateSubmission
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import ChoiceInput
from leornian.modules.learning.contracts import LessonRequestInput
from leornian.modules.learning.progress import Progress
from leornian.modules.tutor.contracts import TurnInput
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def gate_setup(database, session, supply_setup):
    supply, tutor, settings, plan, source = supply_setup
    lesson = tutor.submit_lesson(
        session.token,
        plan.id,
        str(uuid4()),
        LessonRequestInput(
            expected_plan_revision=1,
            node_key="loops",
            instruction="Teach one loop idea.",
        ),
    )
    run_model(
        tutor,
        settings,
        lesson.run_id,
        {
            "title": "Loops",
            "introduction": "Understand iteration.",
            "sections": [
                {
                    "heading": "Visit elements",
                    "explanation": "Each element is visited once.",
                    "code_example": "",
                    "source_refs": [{"source_id": str(source.id), "revision": 1}],
                }
            ],
            "recall_prompts": ["What happens for no elements?"],
        },
    )
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    finish(database, supply_setup, accepted)
    supply.publish(session.token, accepted.pack_id)
    return ConceptGate(database, settings), accepted, supply_setup


def practice(session, setup, wrong=False):
    _, accepted, (supply, _, _, _, _) = setup
    supply.practice(session.token, accepted.pack_id)
    for slot in ("practice_1", "practice_2"):
        supply.answer(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            ChoiceInput(
                slot=slot,
                selected_key="B" if wrong and slot == "practice_1" else "A",
            ),
        )


def relation_document(database, gate_id, verdict="distinct_decision"):
    with database.transaction() as c:
        row = c.execute(
            "SELECT comparisons FROM assessment.concept_gates WHERE id=%s", (gate_id,)
        ).fetchone()
    return {
        "comparisons": [
            {**pair, "verdict": verdict, "reason": "Different decision; actual content inspected."}
            for pair in row["comparisons"]
        ]
    }


def prepare(database, session, setup, verdict="distinct_decision", observe=None):
    gates, accepted, (_, tutor, settings, _, _) = setup
    summary = gates.request(
        session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    run_model(
        tutor,
        settings,
        summary.relation_run_id,
        relation_document(database, summary.id, verdict),
        observe=observe,
    )
    return summary


def submit_data(wrong=False):
    return GateSubmission(
        answers=[
            {"slot": "assessment_1", "selected_key": "A"},
            {"slot": "assessment_2", "selected_key": "B" if wrong else "A"},
        ]
    )


def test_concept_gate_hidden_until_start_and_atomic_completion(
    database,
    workflow,
    session,
    gate_setup,
):
    gates, accepted, (supply, _, _, _, _) = gate_setup
    practice(session, gate_setup)
    observed = []
    summary = prepare(database, session, gate_setup, observe=observed.append)
    assert "correct_key" not in json.dumps(observed)
    assert "Private explanation for practice" in json.dumps(observed)
    assert "Private explanation for assessment" not in json.dumps(observed)
    ready = gates.view(session.token, summary.id)
    assert ready.gate.status == "ready" and ready.questions == [] and ready.results == []
    assert "start" in ready.allowed_actions
    assert not workflow.snapshot(session.token).node_progress
    first = gates.start(session.token, summary.id)
    assert first.gate.status == "in_progress" and len(first.questions) == 2
    assert not first.results and "submit" in first.allowed_actions
    assert "correct_key" not in first.model_dump_json()
    assert gates.start(session.token, summary.id) == first
    assert not workflow.snapshot(session.token).node_progress
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: gates.submit(session.token, summary.id, key, submit_data()),
                range(2),
            )
        )
    assert responses[0] == responses[1]
    assert responses[0].gate.status == "passed" and all(r.correct for r in responses[0].results)
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.node_progress) == 1
    assert snapshot.node_progress[0].evidence_gate_id == summary.id
    assert not snapshot.attempts and not snapshot.tracks
    with database.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM learning.concept_evidence WHERE gate_id=%s",
                (summary.id,),
            ).fetchone()["n"]
            == 1
        )
    with pytest.raises(BusinessError) as error:
        gates.submit(session.token, summary.id, str(uuid4()), submit_data(True))
    assert error.value.code == "idempotency_conflict"
    with pytest.raises(BusinessError):
        gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )


def test_practice_error_opens_distinct_remediation_and_never_grants_mastery(
    database,
    workflow,
    session,
    gate_setup,
):
    gates, accepted, (supply, _, _, _, _) = gate_setup
    with pytest.raises(BusinessError):
        supply.answer(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            ChoiceInput(slot="remediation_1", selected_key="A"),
        )
    practice(session, gate_setup, wrong=True)
    remediation = workflow.snapshot(session.token).remediations[0]
    with pytest.raises(BusinessError):
        gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )
    question = supply.remediation(session.token, remediation.id)
    assert question.slot == "remediation_1"
    assert question.difficulty <= 2 and "correct_key" not in question.model_dump_json()
    result = supply.answer(
        session.token,
        accepted.pack_id,
        str(uuid4()),
        ChoiceInput(slot="remediation_1", selected_key="A"),
    )
    assert result.correct and not workflow.snapshot(session.token).node_progress
    assert workflow.snapshot(session.token).remediations[0].status == "passed"
    summary = prepare(database, session, gate_setup)
    assert gates.view(session.token, summary.id).gate.status == "ready"
    with database.transaction() as c:
        context = c.execute(
            "SELECT exposures FROM assessment.concept_gates WHERE id=%s", (summary.id,)
        ).fetchone()["exposures"]
    assert any(item["key"].endswith(":remediation_1") and item.get("feedback") for item in context)


def test_remediation_failure_is_locked_and_requires_new_transfer(
    workflow,
    session,
    gate_setup,
):
    gates, accepted, (supply, _, _, _, _) = gate_setup
    practice(session, gate_setup, wrong=True)
    remediation = workflow.snapshot(session.token).remediations[0]
    supply.remediation(session.token, remediation.id)
    supply.answer(
        session.token,
        accepted.pack_id,
        str(uuid4()),
        ChoiceInput(slot="remediation_1", selected_key="B"),
    )
    receipt = workflow.snapshot(session.token).remediations[0]
    assert receipt.status == "not_passed" and receipt.transfer_required
    with pytest.raises(BusinessError):
        supply.answer(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            ChoiceInput(slot="remediation_1", selected_key="A"),
        )
    with pytest.raises(BusinessError):
        gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )
    assert not workflow.snapshot(session.token).node_progress


@pytest.mark.parametrize("verdict", ["answer_leakage", "uncertain"])
def test_relationships_must_all_pass_before_assessment_is_exposed(
    database,
    session,
    gate_setup,
    verdict,
):
    gates, _, _ = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup, verdict=verdict)
    view = gates.view(session.token, summary.id)
    assert view.gate.status == "blocked" and view.gate.error_code == "assessment_not_independent"
    assert not view.questions
    with pytest.raises(BusinessError):
        gates.start(session.token, summary.id)


def test_relation_missing_pair_is_known_failure_no_automatic_repair(database, session, gate_setup):
    gates, accepted, (_, tutor, settings, _, _) = gate_setup
    practice(session, gate_setup)
    summary = gates.request(
        session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    report = relation_document(database, summary.id)
    report["comparisons"].pop()
    run_model(tutor, settings, summary.relation_run_id, report)
    assert gates.view(session.token, summary.id).gate.status == "blocked"
    assert tutor.get(session.token, summary.relation_run_id).error_code == "invalid_gate_output"
    assert not gates.view(session.token, summary.id).questions


def test_new_exposure_invalidates_ready_gate_and_preserves_report(database, session, gate_setup):
    gates, accepted, (supply, _, _, _, _) = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup)
    with database.transaction() as c:
        item = Packs(c).published_document(session.actor, accepted.pack_id).items[-1]
        Exposures(c).record(session.actor, accepted.pack_id, item)
    view = gates.view(session.token, summary.id)
    assert view.blocked_reason == "stale_version" and view.allowed_actions == ["cancel"]
    with pytest.raises(BusinessError):
        gates.start(session.token, summary.id)
    with database.transaction() as c:
        assert c.execute(
            "SELECT relation_report FROM assessment.concept_gates WHERE id=%s", (summary.id,)
        ).fetchone()["relation_report"]
    assert supply.get(session.token, accepted.pack_id).status == "published"


def test_gate_cancellation_and_late_relation_response_never_expose_questions(
    database,
    session,
    gate_setup,
):
    gates, accepted, (_, tutor, settings, _, _) = gate_setup
    practice(session, gate_setup)
    summary = gates.request(
        session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    report = relation_document(database, summary.id)

    def respond(request):
        gates.cancel(session.token, summary.id)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": json.dumps(report)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(respond))).run(
        summary.relation_run_id,
    )
    assert gates.view(session.token, summary.id).gate.status == "cancelled"
    assert not gates.view(session.token, summary.id).questions
    with database.transaction() as c:
        receipt = c.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE run_id=%s",
            (summary.relation_run_id,),
        ).fetchone()
    assert receipt["status"] == "result_recorded" and not receipt["applied"]


def test_failed_gate_does_not_write_completion_and_cannot_be_reused(
    database,
    workflow,
    session,
    gate_setup,
):
    gates, accepted, _ = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup)
    gates.start(session.token, summary.id)
    result = gates.submit(session.token, summary.id, str(uuid4()), submit_data(wrong=True))
    assert result.gate.status == "not_passed"
    assert not workflow.snapshot(session.token).node_progress
    with pytest.raises(BusinessError):
        gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )


def test_exam_rejects_tutor_and_training_commands(database, session, gate_setup):
    gates, accepted, (supply, tutor, _, plan, _) = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup)
    gates.start(session.token, summary.id)
    conversation = tutor.conversation(session.token, plan.goal_id)
    with pytest.raises(BusinessError):
        tutor.submit(session.token, conversation.id, str(uuid4()), TurnInput(text="Give answers"))
    with pytest.raises(BusinessError):
        supply.practice(session.token, accepted.pack_id)
    gates.cancel(session.token, summary.id)
    assert supply.practice(session.token, accepted.pack_id).questions
    with pytest.raises(BusinessError):
        gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )


def test_source_revocation_after_start_prevents_grading_not_historical_reads(
    database,
    workflow,
    session,
    gate_setup,
):
    gates, _, (_, _, _, _, source) = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup)
    gates.start(session.token, summary.id)
    KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    with pytest.raises(BusinessError):
        gates.submit(session.token, summary.id, str(uuid4()), submit_data())
    assert gates.view(session.token, summary.id).allowed_actions == ["cancel"]
    assert not workflow.snapshot(session.token).node_progress


def test_http_ownership_atomic_payload_and_no_answers_before_submission(
    database,
    workflow,
    session,
    gate_setup,
):
    gates, _, (_, _, settings, _, _) = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup)
    client = TestClient(create_app(settings))
    other = workflow.create_session("Unrelated actor")
    path = "/v1/concept-gates/" + str(summary.id)
    assert client.get(path, headers={"Authorization": "Bearer " + other.token}).status_code == 404
    headers = {"Authorization": "Bearer " + session.token}
    ready = client.get(path, headers=headers)
    assert ready.status_code == 200 and ready.json()["questions"] == []
    started = client.post(path + "/start", headers=headers)
    assert started.status_code == 200 and len(started.json()["questions"]) == 2
    assert (
        "correct_key" not in started.text
        and "Private explanation for assessment" not in started.text
    )
    headers["Idempotency-Key"] = str(uuid4())
    assert (
        client.post(
            path + "/submissions",
            headers=headers,
            json={
                "answers": [{"slot": "assessment_1", "selected_key": "A"}],
            },
        ).status_code
        == 422
    )
    assert gates.view(session.token, summary.id).gate.status == "in_progress"
    assert (
        client.post(
            path + "/submissions", headers=headers, json=submit_data().model_dump(mode="json")
        ).json()["gate"]["status"]
        == "passed"
    )


def test_completion_failure_rolls_back_grade_feedback_and_evidence(
    database,
    workflow,
    session,
    gate_setup,
    monkeypatch,
):
    gates, _, _ = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup)
    gates.start(session.token, summary.id)
    with database.transaction() as c:
        before = Exposures(c).revision(session.actor)

    def fail(_self, _actor, _completion):
        raise RuntimeError("Owned transaction fault")

    with monkeypatch.context() as patch:
        patch.setattr(Progress, "apply", fail)
        with pytest.raises(RuntimeError):
            gates.submit(session.token, summary.id, "same-transaction-key", submit_data())
    assert gates.view(session.token, summary.id).gate.status == "in_progress"
    assert not workflow.snapshot(session.token).node_progress
    with database.transaction() as c:
        assert Exposures(c).revision(session.actor) == before
    assert (
        gates.submit(session.token, summary.id, "same-transaction-key", submit_data()).gate.status
        == "passed"
    )


def test_unknown_relation_never_resends_and_cancels_as_one_business_action(
    database,
    session,
    gate_setup,
):
    gates, accepted, (_, tutor, settings, _, _) = gate_setup
    practice(session, gate_setup)
    summary = gates.request(
        session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    seen = []

    def timeout(request):
        seen.append(request)
        raise httpx.ReadTimeout("Owned relation timeout")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(summary.relation_run_id)
    loop.run(summary.relation_run_id)
    assert len(seen) == 1
    assert tutor.get(session.token, summary.relation_run_id).status == "blocked_unknown"
    assert gates.cancel(session.token, summary.id).gate.status == "cancelled"
    assert tutor.get(session.token, summary.relation_run_id).status == "cancelled"


def test_new_teaching_context_invalidates_ready_relation_report(
    database,
    session,
    gate_setup,
):
    gates, _, (_, tutor, _, plan, _) = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup)
    conversation = tutor.conversation(session.token, plan.goal_id)
    turn = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain loops")
    )
    from leornian.agent_runtime.repository import Runs
    from leornian.modules.tutor.application import Tutor
    from leornian.modules.tutor.infrastructure import PgTutorStore

    with database.transaction() as c:
        Tutor(PgTutorStore(c)).complete(turn.turn_id, "A new example may change independence.")
        Runs(c).finish(turn.run_id, "succeeded")
    assert gates.view(session.token, summary.id).blocked_reason == "stale_version"
    with pytest.raises(BusinessError):
        gates.start(session.token, summary.id)


def test_prerequisites_are_checked_by_learning_owner(database, session, gate_setup):
    _, _, (_, _, _, plan, _) = gate_setup
    from leornian.modules.learning.contracts import PlanNode

    node = PlanNode(
        key="next",
        title="Next",
        objective="Apply loops",
        estimated_minutes=10,
        prerequisite_keys=["loops"],
        source_refs=[],
    )
    with database.transaction() as c:
        with pytest.raises(BusinessError):
            Progress(c).require_prerequisites(session.actor, plan.id, 1, node)


def test_previous_assessment_exposure_cannot_be_reset_by_a_new_request_key(
    database,
    session,
    gate_setup,
):
    gates, accepted, _ = gate_setup
    practice(session, gate_setup)
    with database.transaction() as c:
        material = Packs(c).assessment_materials(session.actor, accepted.pack_id)[0]
        Exposures(c).record(session.actor, accepted.pack_id, material)
    with pytest.raises(BusinessError) as error:
        gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )
    assert error.value.code == "precondition_failed"


def test_cross_pack_actual_feedback_is_a_required_relationship_comparison(
    database,
    session,
    gate_setup,
):
    gates, accepted, setup = gate_setup
    supply, tutor, settings, plan, source = setup
    practice(session, gate_setup)
    other = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    value = document(source)
    for item in value["items"]:
        item["prompt"] = "Different prior context: " + item["prompt"]
    run_model(tutor, settings, other.run_id, value)
    finish(database, setup, other)
    supply.publish(session.token, other.pack_id)
    supply.practice(session.token, other.pack_id)
    supply.answer(
        session.token, other.pack_id, str(uuid4()), ChoiceInput(slot="practice_1", selected_key="A")
    )
    summary = gates.request(
        session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    with database.transaction() as c:
        row = c.execute(
            "SELECT context_data,comparisons FROM assessment.concept_gates WHERE id=%s",
            (summary.id,),
        ).fetchone()
    key = "seen:" + str(other.pack_id) + ":practice_1"
    entry = next(
        item for item in row["context_data"]["training_and_exposure"] if item["key"] == key
    )
    assert entry["feedback"]["explanation"] == "Private explanation for practice_1."
    assert {(pair["left"], pair["right"]) for pair in row["comparisons"]} >= {
        ("assessment_1", key),
        ("assessment_2", key),
    }


@pytest.mark.parametrize("verdict", ["answer_leakage", "uncertain"])
def test_same_materials_cannot_reroll_a_negative_report(database, session, gate_setup, verdict):
    gates, accepted, _ = gate_setup
    practice(session, gate_setup)
    summary = prepare(database, session, gate_setup, verdict=verdict)
    with pytest.raises(BusinessError) as error:
        gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )
    assert error.value.code == "assessment_not_independent"
    assert gates.view(session.token, summary.id).gate.status == "blocked"
    with database.transaction() as c:
        row = c.execute(
            "SELECT count(*) AS n FROM assessment.concept_gates WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()
        original = c.execute(
            "SELECT idempotency_key,completed_at FROM assessment.concept_gates WHERE id=%s",
            (summary.id,),
        ).fetchone()
    assert row["n"] == 1 and original["completed_at"]
    assert (
        gates.request(
            session.token,
            accepted.pack_id,
            original["idempotency_key"],
            GateRequest(expected_plan_revision=1),
        ).id
        == summary.id
    )


def test_changed_exposure_allows_new_review_without_erasing_the_old_report(
    database, session, gate_setup
):
    gates, accepted, (_, tutor, settings, _, _) = gate_setup
    practice(session, gate_setup)
    original = prepare(database, session, gate_setup, verdict="answer_leakage")
    with database.transaction() as c:
        item = Packs(c).published_document(session.actor, accepted.pack_id).items[-1]
        Exposures(c).record(session.actor, accepted.pack_id, item)
    current = gates.request(
        session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
    )
    assert current.id != original.id
    run_model(tutor, settings, current.relation_run_id, relation_document(database, current.id))
    assert gates.view(session.token, current.id).gate.status == "ready"
    assert gates.view(session.token, original.id).gate.status == "blocked"


def test_gate_feedback_creates_one_new_fully_reviewed_version(
    database, workflow, session, gate_setup
):
    gates, accepted, setup = gate_setup
    supply, tutor, settings, plan, source = setup
    practice(session, gate_setup)
    rejected = prepare(database, session, gate_setup, verdict="answer_leakage")
    data = request_data(predecessor_id=accepted.pack_id, gate_feedback_id=rejected.id)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        children = list(
            pool.map(lambda _: supply.submit(session.token, plan.id, key, data), range(2))
        )
    assert children[0] == children[1]
    child = children[0]
    with pytest.raises(BusinessError):
        supply.submit(session.token, plan.id, str(uuid4()), data)
    with pytest.raises(BusinessError) as conflict:
        supply.submit(
            session.token,
            plan.id,
            key,
            request_data(predecessor_id=accepted.pack_id, gate_feedback_id=uuid4()),
        )
    assert conflict.value.code == "idempotency_conflict"
    new_doc = document(source)
    for item in new_doc["items"]:
        item["prompt"] = "New context for the revised question: " + item["prompt"]
    captured = []
    run_model(tutor, settings, child.run_id, new_doc, observe=captured.append)
    author_context = json.loads(captured[0]["messages"][-1]["content"])
    feedback = author_context["gate_feedback"]
    assert feedback["gate_id"] == str(rejected.id)
    assert feedback["relation_report"]["comparisons"][0]["verdict"] == "answer_leakage"
    assert feedback["reviewed_context"]["learning_context"]["saved_lessons"]
    assert any(item.get("feedback") for item in feedback["actual_exposures"])
    observed = {}
    finish(database, setup, child, observe=lambda role, request: observed.update({role: request}))
    assert set(observed) == {
        "blind",
        "curriculum",
        "difficulty",
        "technical",
        "ambiguity",
        "security",
        "adversarial",
    }
    assert all("gate_feedback" not in json.dumps(request) for request in observed.values())
    ready = supply.get(session.token, child.pack_id)
    assert ready.status == "ready" and ready.revision == 2
    assert ready.predecessor_id == accepted.pack_id and ready.gate_feedback_id == rejected.id
    assert supply.get(session.token, accepted.pack_id).status == "published"
    assert gates.view(session.token, rejected.id).gate.status == "blocked"
    snapshot = workflow.snapshot(session.token).model_dump_json()
    assert "answer_leakage" not in snapshot and "reviewed_context" not in snapshot
    assert "Private explanation for assessment" not in snapshot
    assert not workflow.snapshot(session.token).node_progress
    assert supply.publish(session.token, child.pack_id).status == "published"
    assert supply.submit(session.token, plan.id, key, data) == child
    with database.transaction() as c:
        assert Exposures(c).revision(session.actor) == 4


def test_published_revision_needs_exact_negative_gate_without_a_version_count_limit(
    database, workflow, session, gate_setup
):
    gates, accepted, (supply, _, settings, plan, _) = gate_setup
    practice(session, gate_setup)
    ready = prepare(database, session, gate_setup)
    with pytest.raises(BusinessError):
        supply.submit(
            session.token,
            plan.id,
            str(uuid4()),
            request_data(predecessor_id=accepted.pack_id, gate_feedback_id=ready.id),
        )
    gates.cancel(session.token, ready.id)
    rejected = prepare(database, session, gate_setup, verdict="uncertain")
    other = workflow.create_session("Cannot use another learner's report")
    with database.transaction() as c:
        with pytest.raises(BusinessError) as ownership:
            from leornian.modules.assessment.gates import Gates

            Gates(c).revision_feedback(other.actor, rejected.id, accepted.pack_id)
    assert ownership.value.code == "not_found"
    with database.transaction() as c:
        c.execute("UPDATE item_bank.packs SET revision=3 WHERE id=%s", (accepted.pack_id,))
    client = TestClient(create_app(settings))
    response = client.post(
        f"/v1/plans/{plan.id}/pack-requests",
        headers={"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())},
        json=request_data(predecessor_id=accepted.pack_id, gate_feedback_id=rejected.id).model_dump(
            mode="json"
        ),
    )
    assert response.status_code == 202
    with database.transaction() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM item_bank.packs WHERE predecessor_id=%s",
                (accepted.pack_id,),
            ).fetchone()["n"]
            == 1
        )
        child = c.execute(
            "SELECT revision,gate_feedback_id FROM item_bank.packs WHERE predecessor_id=%s",
            (accepted.pack_id,),
        ).fetchone()
    assert child["revision"] == 4 and child["gate_feedback_id"] == rejected.id
