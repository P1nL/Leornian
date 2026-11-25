import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_program_items import environment, item_document

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import (
    REVIEW_ROLES,
    SLOTS,
    ChoiceInput,
    PackRequest,
)
from leornian.modules.knowledge.contracts import AdmitSource, SourceInput
from leornian.modules.learning.contracts import GoalInput
from leornian.modules.tutor.contracts import PlanningInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


def run_model(tutor, settings, run_id, value, observe=None):
    def respond(request):
        if observe:
            observe(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": json.dumps(value)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 200},
            },
        )

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(respond))).run(run_id)


@pytest.fixture
def supply_setup(database, workflow, session):
    accepted = workflow.submit(
        session.token, str(uuid4()), GoalInput(title="Python concept checks")
    )
    with database.transaction() as c:
        event = c.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (accepted.job_id,)
        ).fetchone()
    workflow.process_goal(event["event_id"])
    goal = workflow.snapshot(session.token).goals[0]
    settings = Settings(
        delivery_enabled=False,  # Preserve the historical single-stage Runtime regression contract.
        database_url=database.url,
        model_enabled=True,
        model_base_url="https://owned.invalid",
        model_name="offline-owned",
        model_api_key="owned-secret",
    )
    tutor = TutorWorkflow(database, settings)
    knowledge = KnowledgeWorkflow(database)
    source = knowledge.create(
        session.token,
        goal.id,
        str(uuid4()),
        SourceInput(
            title="Owned iteration excerpt",
            source_url="https://owned.invalid/loops",
            excerpt="A Python for loop visits each element. Empty input performs no iterations.",
        ),
    )
    knowledge.admit(
        session.token,
        source.id,
        AdmitSource(
            expected_revision=1,
            valid_until=datetime.now(UTC) + timedelta(days=1),
        ),
    )
    conversation = tutor.conversation(session.token, goal.id)
    planned = tutor.submit_plan(
        session.token,
        conversation.id,
        str(uuid4()),
        PlanningInput(text="Small loop route", expected_revision=0),
    )
    run_model(
        tutor,
        settings,
        planned.run_id,
        {
            "title": "Loop route",
            "summary": "Understand iteration.",
            "assumptions": [],
            "nodes": [
                {
                    "key": "loops",
                    "title": "Loops",
                    "objective": "Explain iteration behavior.",
                    "estimated_minutes": 20,
                    "prerequisite_keys": [],
                    "source_refs": [{"source_id": str(source.id), "revision": 1}],
                }
            ],
        },
    )
    plan = workflow.snapshot(session.token).plans[0]
    tutor.confirm_plan(session.token, plan.id, 1)
    return ItemSupply(database, settings), tutor, settings, plan, source


@pytest.mark.parametrize(
    ("kind", "role"),
    [("sql_query", role) for role in (*REVIEW_ROLES, "author", "blind")]
    + [("python_project", "technical")],
)
def test_execution_role_preserves_public_sample_and_typed_sql_contract(
    database, supply_setup, session, kind, role,
):
    flow, _, _, plan, source = supply_setup
    env = environment(kind)
    accepted = flow.submit(
        session.token,
        plan.id,
        str(uuid4()),
        PackRequest(
            expected_plan_revision=1,
            node_key="loops",
            instruction="One supported execution kind with a public sample.",
            kind=kind,
            program_environment=env,
        ),
    )
    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection)).authenticate(session.token)
        pack = Packs(connection).row(actor, accepted.pack_id)
        pack["document"] = item_document(source, env)
        pack["status"] = (
            "authoring" if role == "author" else "blind_solving" if role == "blind" else "reviewing"
        )
        spec = ItemSupply.role(
            connection, actor, pack, {"role": role, "run_id": accepted.run_id},
        )
    instruction = spec.messages[0]["content"]
    context = json.loads(spec.messages[1]["content"])
    if role in REVIEW_ROLES:
        assert "the exact public sample; the other two cases stay private" in instruction
        assert "not hidden-test disclosure" in instruction
        assert "boundary coverage and remediation alignment" in instruction
        if kind == "sql_query":
            assert "sql-table.v1 stores non-null cells as strings" in instruction
            assert "types matrix and canonical value together" in instruction
            assert context["candidate"]["items"][0]["sample"] in (
                context["candidate"]["items"][0]["tests"]
            )
    elif role == "author":
        assert "the exact public sample and two private cases" in instruction
    else:
        assert "no private datasets/tests" in instruction
        assert "private expected outputs" in instruction
        assert "candidate" not in context
        assert all("tests" not in question for question in context["questions"])


def request_data(*, automatic=False, **overrides):
    return PackRequest(
        expected_plan_revision=1,
        node_key="loops",
        instruction="Keep choices concise.",
        automatic=automatic,
        **overrides,
    )


def document(source):
    return {
        "items": [
            {
                "slot": slot,
                "title": f"Concept {index}",
                "prompt": f"Iteration decision in scenario {index}: which behavior occurs?",
                "difficulty": 1 if slot == "remediation_1" else 2,
                "options": [{"key": key, "text": f"{slot} option {key}"} for key in "ABCD"],
                "source_refs": [{"source_id": str(source.id), "revision": 1}],
                "correct_key": "A",
                "explanation": f"Private explanation for {slot}.",
            }
            for index, slot in enumerate(SLOTS)
        ]
    }


def blind():
    return {"answers": [{"slot": slot, "selected_key": "A"} for slot in SLOTS]}


def review(passed=True):
    return {
        "items": [
            {
                "slot": slot,
                "verdict": "pass" if passed else "revise",
                "reason": "Checked against the supplied objective and exact semantics.",
            }
            for slot in SLOTS
        ],
        "assessment_independence": "supported" if passed else "revise",
        "relationship_reason": "Different contexts require different decisions without clues.",
    }


def stages(database, pack_id):
    with database.transaction() as c:
        return c.execute(
            "SELECT * FROM item_bank.stages WHERE pack_id=%s ORDER BY created_at", (pack_id,)
        ).fetchall()


def finish(database, setup, accepted, fail_role=None, observe=None):
    _, tutor, settings, _, source = setup
    for _ in range(8):
        pending = [s for s in stages(database, accepted.pack_id) if s["result"] is None]
        if not pending:
            break
        stage = pending[0]
        value = (
            document(source)
            if stage["role"] == "author"
            else (blind() if stage["role"] == "blind" else review(stage["role"] != fail_role))
        )
        run_model(
            tutor,
            settings,
            stage["run_id"],
            value,
            (lambda request, role=stage["role"]: observe(role, request)) if observe else None,
        )


def test_pack_full_pipeline_public_only_blind_and_private_assessment(
    database,
    workflow,
    session,
    supply_setup,
):
    supply, tutor, _, plan, _ = supply_setup
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(
            pool.map(
                lambda _: supply.submit(session.token, plan.id, key, request_data()),
                range(2),
            )
        )
    assert accepted[0] == accepted[1]
    accepted = accepted[0]
    with pytest.raises(BusinessError):
        supply.publish(session.token, accepted.pack_id)

    observed = {}

    def observe(role, request):
        assert "tools" not in request
        observed[role] = request

    finish(database, supply_setup, accepted, observe=observe)
    assert set(observed) == {"author", "blind", *REVIEW_ROLES}
    blind_payload = json.dumps(observed["blind"])
    assert "correct_key" not in blind_payload and "Private explanation" not in blind_payload
    assert "previous_document" not in blind_payload and "review_feedback" not in blind_payload
    blind_context = json.loads(observed["blind"]["messages"][-1]["content"])
    assert set(blind_context) == {"objective", "node_title", "questions"}
    for role in ("author", *REVIEW_ROLES):
        context = json.loads(observed[role]["messages"][-1]["content"])
        assert context["requested_item_kind"] == "choice"
        assert context["learner_instruction"] == request_data().instruction
    for role in REVIEW_ROLES:
        assert "review_feedback" not in json.dumps(observed[role])
        assert "selected_key" not in json.dumps(observed[role])
        instruction = observed[role]["messages"][0]["content"]
        assert "not a request for every artifact or format" in instruction
        assert "never waives correctness" in instruction
    assert supply.get(session.token, accepted.pack_id).status == "ready"
    assert len(supply.get(session.token, accepted.pack_id).passed_roles) == 6
    published = supply.publish(session.token, accepted.pack_id)
    assert published.status == "published"
    assert supply.publish(session.token, accepted.pack_id) == published
    assert supply.submit(session.token, plan.id, key, request_data()) == accepted
    practice = supply.practice(session.token, accepted.pack_id)
    assert [q.slot for q in practice.questions] == ["practice_1", "practice_2"]
    assert "correct_key" not in practice.model_dump_json()
    assert "assessment_1" not in practice.model_dump_json()
    answer = ChoiceInput(slot="practice_1", selected_key="B")
    answer_key = str(uuid4())
    wrong = supply.answer(session.token, accepted.pack_id, answer_key, answer)
    assert not wrong.correct and wrong.explanation
    assert supply.answer(session.token, accepted.pack_id, answer_key, answer) == wrong
    with pytest.raises(BusinessError) as error:
        supply.answer(
            session.token,
            accepted.pack_id,
            str(uuid4()),
            ChoiceInput(slot="practice_1", selected_key="A"),
        )
    assert error.value.code == "idempotency_conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        second_key = str(uuid4())
        seconds = list(
            pool.map(
                lambda _: supply.answer(
                    session.token,
                    accepted.pack_id,
                    second_key,
                    ChoiceInput(slot="practice_2", selected_key="A"),
                ),
                range(2),
            )
        )
    assert seconds[0] == seconds[1] and seconds[0].correct
    snapshot = workflow.snapshot(session.token)
    assert len(snapshot.choice_results) == 2 and not snapshot.tracks and not snapshot.attempts
    assert "correct_key" not in snapshot.model_dump_json()
    assert "Private explanation for assessment" not in snapshot.model_dump_json()
    assert tutor.get(session.token, accepted.run_id).status == "succeeded"


def test_question_bank_projects_generation_without_opening_private_or_practice_items(
    database, session, workflow, supply_setup,
):
    supply, tutor, settings, plan, source = supply_setup
    headers = {"Authorization": "Bearer " + session.token}
    client = TestClient(create_app(settings))
    index = f"/v1/plans/{plan.id}/question-bank"
    assert client.get(index, headers=headers).json() == [{
        "node_key": "loops", "plan_revision": 1, "title": "Loops", "position": 1, "packs": [],
    }]
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    path = f"/v1/packs/{accepted.pack_id}/generation"
    other = {"Authorization": "Bearer " + workflow.create_session("Another learner").token}
    assert client.get(path, headers=other).status_code == 404
    assert client.get(index, headers=other).status_code == 404
    pending = client.get(path, headers=headers).json()
    assert [(stage["role"], stage["status"]) for stage in pending["stages"]] == [
        ("author", "queued"),
    ]
    run_model(tutor, settings, accepted.run_id, {
        **document(source), "public_notes": ["从本节目标选取考点。", "private draft"],
    })
    run_model(tutor, settings, stages(database, accepted.pack_id)[-1]["run_id"], {
        **blind(), "public_notes": ["按公开题面独立作答。"],
    })
    checked = review(False)
    checked["items"][0]["reason"] = "Unreleased key and hidden tests must not be displayed."
    run_model(tutor, settings, stages(database, accepted.pack_id)[-1]["run_id"], {
        **checked, "public_notes": ["核对题目是否用到尚未学习的知识。"],
    })
    finish(database, supply_setup, accepted)
    directory = client.get(index, headers=headers).json()
    assert [pack["id"] for pack in directory[0]["packs"]] == [str(accepted.pack_id)]
    response = client.get(path, headers=headers)
    report = response.json()
    assert report["status"] == "changes_required" and report["published_at"] is None
    assert [stage["role"] for stage in report["stages"]] == ["author", "blind", *REVIEW_ROLES]
    author, solver, curriculum = report["stages"][:3]
    assert author["public_notes"] == ["从本节目标选取考点。"] and author["item_count"] == 5
    assert solver["blind_passed"] and solver["public_notes"] == ["按公开题面独立作答。"]
    assert curriculum["decisions"] == dict.fromkeys(SLOTS, "revise")
    assert curriculum["public_notes"] == ["核对题目是否用到尚未学习的知识。"]
    assert report["stages"][-1]["public_notes"] == []
    for private in (
        "private draft", "Unreleased key", "Private explanation", "selected_key", "correct_key",
        "Iteration decision", "relationship_reason", "reasoning_content",
    ):
        assert private not in response.text
    with database.transaction(snapshot=True) as connection:
        assert not connection.execute(
            "SELECT 1 FROM item_bank.exposures WHERE pack_id=%s", (accepted.pack_id,),
        ).fetchone()


def test_review_failure_keeps_all_six_reports_then_allows_one_real_revision(
    database,
    session,
    supply_setup,
):
    supply, _, _, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    finish(database, supply_setup, accepted, fail_role="technical")
    summary = supply.get(session.token, accepted.pack_id)
    assert summary.status == "changes_required" and len(summary.reviewed_roles) == 6
    with pytest.raises(BusinessError):
        supply.publish(session.token, accepted.pack_id)
    revised = supply.submit(
        session.token, plan.id, str(uuid4()), request_data(predecessor_id=accepted.pack_id)
    )
    assert supply.get(session.token, revised.pack_id).revision == 2
    with pytest.raises(BusinessError):
        supply.submit(
            session.token, plan.id, str(uuid4()), request_data(predecessor_id=accepted.pack_id)
        )
    _, tutor, settings, _, _ = supply_setup
    run_model(tutor, settings, revised.run_id, document(source))
    assert tutor.get(session.token, revised.run_id).error_code == "invalid_item_output"
    assert supply.get(session.token, accepted.pack_id).status == "changes_required"
    assert all(s["result"] for s in stages(database, accepted.pack_id))


@pytest.mark.parametrize(
    "mutation", ["missing_slot", "duplicate_prompt", "duplicate_options", "unknown_source"]
)
def test_invalid_author_receipt_never_becomes_a_pack(
    database,
    session,
    supply_setup,
    mutation,
):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    value = document(source)
    if mutation == "missing_slot":
        value["items"].pop()
    elif mutation == "duplicate_prompt":
        value["items"][1]["prompt"] = value["items"][0]["prompt"]
    elif mutation == "duplicate_options":
        value["items"][1]["options"] = value["items"][0]["options"]
    else:
        value["items"][0]["source_refs"][0]["source_id"] = str(uuid4())
    run_model(tutor, settings, accepted.run_id, value)
    assert tutor.get(session.token, accepted.run_id).error_code == "invalid_item_output"
    assert supply.get(session.token, accepted.pack_id).status == "failed"
    with database.transaction() as c:
        call = c.execute(
            "SELECT * FROM runtime.external_calls WHERE run_id=%s", (accepted.run_id,)
        ).fetchone()
        assert call["response_body"] and call["status"] == "result_recorded" and not call["applied"]
    assert len(stages(database, accepted.pack_id)) == 1


def test_blind_mismatch_denies_publication_without_skipping_review(database, session, supply_setup):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    run_model(tutor, settings, accepted.run_id, document(source))
    blind_run = next(s for s in stages(database, accepted.pack_id) if s["role"] == "blind")
    answers = blind()
    answers["answers"][0]["selected_key"] = "C"
    run_model(tutor, settings, blind_run["run_id"], answers)
    finish(database, supply_setup, accepted)
    summary = supply.get(session.token, accepted.pack_id)
    assert summary.blind_passed is False and len(summary.passed_roles) == 6
    assert summary.status == "changes_required"


def test_unknown_stage_is_not_resent_and_cancellation_stops_successors(
    database,
    session,
    supply_setup,
):
    supply, tutor, settings, plan, _ = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    seen = []

    def timeout(request):
        seen.append(request)
        raise httpx.ReadTimeout("owned transport")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(accepted.run_id)
    loop.run(accepted.run_id)
    assert len(seen) == 1 and tutor.get(session.token, accepted.run_id).status == "blocked_unknown"
    assert supply.get(session.token, accepted.pack_id).status == "authoring"
    tutor.cancel(session.token, accepted.run_id)
    assert supply.get(session.token, accepted.pack_id).status == "cancelled"
    assert len(stages(database, accepted.pack_id)) == 1


def test_source_revocation_blocks_dispatch_and_published_open(database, session, supply_setup):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    finish(database, supply_setup, accepted)
    supply.publish(session.token, accepted.pack_id)
    KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    with pytest.raises(BusinessError) as error:
        supply.practice(session.token, accepted.pack_id)
    assert error.value.code == "source_not_current"
    assert supply.get(session.token, accepted.pack_id).status == "published"


def test_http_ownership_hidden_fields_and_forbidden_assessment(session, workflow, supply_setup):
    supply, _, settings, plan, _ = supply_setup
    other = workflow.create_session("Other actor")
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
    response = client.post(
        f"/v1/plans/{plan.id}/pack-requests",
        headers=headers,
        json=request_data().model_dump(mode="json"),
    )
    assert response.status_code == 202
    pack_id = response.json()["pack_id"]
    summary = client.get("/v1/packs/" + pack_id, headers=headers)
    assert summary.status_code == 200 and "document" not in summary.json()
    assert (
        client.get(
            "/v1/packs/" + pack_id, headers={"Authorization": "Bearer " + other.token}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/packs/" + pack_id + "/answers",
            headers=headers,
            json={"slot": "assessment_1", "selected_key": "A"},
        ).status_code
        == 422
    )
    assert client.post("/v1/packs/" + pack_id + "/publish", headers=headers).status_code == 409


def test_missing_review_is_not_eligible(database, session, supply_setup):
    supply, _, _, plan, _ = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    with database.transaction() as c:
        packs = Packs(c)
        assert not packs.eligible(packs.row(session.actor, accepted.pack_id))
        packs.status(accepted.pack_id, "ready")
    with pytest.raises(BusinessError):
        supply.publish(session.token, accepted.pack_id)


def test_revision_has_new_document_new_blind_and_new_six_role_reports(
    database,
    session,
    supply_setup,
):
    supply, tutor, settings, plan, source = supply_setup
    first = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    finish(database, supply_setup, first, fail_role="ambiguity")
    child = supply.submit(
        session.token, plan.id, str(uuid4()), request_data(predecessor_id=first.pack_id)
    )
    value = document(source)
    value["items"][2]["prompt"] = "Changed task: diagnose which counter update is outside the loop."
    run_model(tutor, settings, child.run_id, value)
    with database.transaction() as connection:
        parent_document = connection.execute(
            "SELECT document FROM item_bank.packs WHERE id=%s", (first.pack_id,),
        ).fetchone()["document"]
    observed = {}

    def observe(role, request):
        context = json.loads(request["messages"][-1]["content"])
        observed[role] = context
        if role in REVIEW_ROLES:
            assert context["revision_baseline"] == {
                "pack_id": str(first.pack_id), "revision": 1, "kind": "choice",
                "document": parent_document,
            }
            assert context["revision_scope"] == {
                "predecessor_id": str(first.pack_id), "automatic": False,
                "instruction_inherited": True, "predecessor_published": False,
            }
            assert "not itself learner exposure" in request["messages"][0]["content"]
            assert "not the revision baseline" in request["messages"][0]["content"]
            assert "review_feedback" not in context and "blind_validation" not in context
        else:
            assert role == "blind"
            assert "revision_baseline" not in context and "previous_document" not in context
            assert "revision_scope" not in context

    finish(database, supply_setup, child, observe=observe)
    assert set(observed) == {"blind", *REVIEW_ROLES}
    assert supply.get(session.token, child.pack_id).status == "ready"
    assert supply.get(session.token, first.pack_id).status == "changes_required"
    parent_ids = {s["run_id"] for s in stages(database, first.pack_id)}
    child_ids = {s["run_id"] for s in stages(database, child.pack_id)}
    assert len(child_ids) == 8 and parent_ids.isdisjoint(child_ids)
    assert supply.publish(session.token, child.pack_id).status == "published"


def test_source_revocation_after_prepare_prevents_request_dispatch(database, session, supply_setup):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    lease = tutor.claim(accepted.run_id)
    role = tutor.context(lease)
    gateway = ChatCompletionsGateway(settings)
    call = tutor.prepare(
        lease,
        gateway.endpoint,
        gateway.request(role.messages, require_tool=False, allowed_tools=(), json_output=True),
    )
    KnowledgeWorkflow(database).revoke(session.token, source.id, 1)
    assert not tutor.dispatch(lease, call.id)
    assert tutor.get(session.token, accepted.run_id).error_code == "source_not_current"
    with database.transaction() as c:
        saved = c.execute(
            "SELECT status,dispatched_at FROM runtime.external_calls WHERE id=%s", (call.id,)
        ).fetchone()
    assert saved["status"] == "not_sent" and saved["dispatched_at"] is None


def test_late_receipt_after_cancellation_never_schedules_blind(database, session, supply_setup):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())

    def cancel(request):
        tutor.cancel(session.token, accepted.run_id)
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

    AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(cancel))).run(
        accepted.run_id,
    )
    assert supply.get(session.token, accepted.pack_id).status == "cancelled"
    assert len(stages(database, accepted.pack_id)) == 1
    with database.transaction() as c:
        receipt = c.execute(
            "SELECT status,applied FROM runtime.external_calls WHERE run_id=%s", (accepted.run_id,)
        ).fetchone()
    assert receipt["status"] == "result_recorded" and not receipt["applied"]


@pytest.mark.parametrize("changed_verdict", [False, True])
def test_explicit_review_format_correction_preserves_old_receipt_and_verdicts(
    database,
    session,
    supply_setup,
    changed_verdict,
):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    run_model(tutor, settings, accepted.run_id, document(source))
    for stage in stages(database, accepted.pack_id):
        if stage["role"] == "blind":
            run_model(tutor, settings, stage["run_id"], blind())
    stage = next(s for s in stages(database, accepted.pack_id) if s["role"] == "curriculum")
    invalid = review(passed=False)
    invalid["relationship_reason"] = "x" * 901
    run_model(tutor, settings, stage["run_id"], invalid)
    assert tutor.get(session.token, stage["run_id"]).error_code == "invalid_item_output"
    assert supply.get(session.token, accepted.pack_id).status == "failed"
    corrected = supply.correct_review_format(session.token, accepted.pack_id)
    assert corrected.status == "reviewing" and corrected.pending_run_id == stage["run_id"]
    assert supply.correct_review_format(session.token, accepted.pack_id) == corrected
    run_model(tutor, settings, stage["run_id"], review(passed=changed_verdict))
    with database.transaction() as c:
        calls = c.execute(
            "SELECT * FROM runtime.external_calls WHERE run_id=%s ORDER BY step", (stage["run_id"],)
        ).fetchall()
        report = Packs(c).stage(stage["run_id"])
    assert len(calls) == 2 and "x" * 901 in calls[0]["response_body"]
    assert calls[0]["applied"] and calls[0]["status"] == "result_recorded"
    if changed_verdict:
        assert report["result"] is None
        assert tutor.get(session.token, stage["run_id"]).error_code == "review_verdict_changed"
        assert supply.get(session.token, accepted.pack_id).status == "failed"
    else:
        assert report["result"]["assessment_independence"] == "revise"
        assert all(item["verdict"] == "revise" for item in report["result"]["items"])
        assert tutor.get(session.token, stage["run_id"]).status == "succeeded"
        assert supply.get(session.token, accepted.pack_id).status == "reviewing"


def test_format_correction_can_continue_after_second_schema_failure(
    database, session, supply_setup
):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    run_model(tutor, settings, accepted.run_id, document(source))
    stage = next(s for s in stages(database, accepted.pack_id) if s["role"] == "blind")
    run_model(tutor, settings, stage["run_id"], blind())
    stage = next(s for s in stages(database, accepted.pack_id) if s["role"] == "curriculum")
    invalid = review()
    invalid["items"][0]["reason"] = "x" * 601
    run_model(tutor, settings, stage["run_id"], invalid)
    supply.correct_review_format(session.token, accepted.pack_id)
    run_model(tutor, settings, stage["run_id"], invalid)
    supply.correct_review_format(session.token, accepted.pack_id)
    run_model(tutor, settings, stage["run_id"], review())
    with database.transaction() as c:
        calls = c.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE run_id=%s", (stage["run_id"],)
        ).fetchone()
    assert calls["n"] == 3


def test_schema_correction_is_not_available_for_missing_review_slots(
    database,
    session,
    supply_setup,
):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    run_model(tutor, settings, accepted.run_id, document(source))
    stage = next(s for s in stages(database, accepted.pack_id) if s["role"] == "blind")
    run_model(tutor, settings, stage["run_id"], blind())
    stage = next(s for s in stages(database, accepted.pack_id) if s["role"] == "curriculum")
    invalid = review()
    invalid["items"].pop()
    run_model(tutor, settings, stage["run_id"], invalid)
    with pytest.raises(BusinessError):
        supply.correct_review_format(session.token, accepted.pack_id)


def test_unknown_format_correction_is_never_resent(database, session, supply_setup):
    supply, tutor, settings, plan, source = supply_setup
    accepted = supply.submit(session.token, plan.id, str(uuid4()), request_data())
    run_model(tutor, settings, accepted.run_id, document(source))
    stage = next(s for s in stages(database, accepted.pack_id) if s["role"] == "blind")
    run_model(tutor, settings, stage["run_id"], blind())
    stage = next(s for s in stages(database, accepted.pack_id) if s["role"] == "curriculum")
    invalid = review()
    invalid["relationship_reason"] = "x" * 901
    run_model(tutor, settings, stage["run_id"], invalid)
    supply.correct_review_format(session.token, accepted.pack_id)
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("Owned correction transport")

    loop = AgentLoop(tutor, ChatCompletionsGateway(settings, httpx.MockTransport(timeout)))
    loop.run(stage["run_id"])
    loop.run(stage["run_id"])
    assert len(requests) == 1
    assert tutor.get(session.token, stage["run_id"]).status == "blocked_unknown"
    with pytest.raises(BusinessError):
        supply.correct_review_format(session.token, accepted.pack_id)
    with database.transaction() as c:
        calls = c.execute(
            "SELECT status FROM runtime.external_calls WHERE run_id=%s ORDER BY step",
            (stage["run_id"],),
        ).fetchall()
    assert [row["status"] for row in calls] == ["result_recorded", "unknown"]
