import json
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_concept_gates import gate_setup as gate_setup
from test_item_supply import supply_setup as supply_setup
from test_python_execution import program
from test_python_execution import python_setup as python_setup
from test_python_practice import complete
from test_python_practice import practice_setup as practice_setup
from test_teaching_delivery import body, drain, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.knowledge import KnowledgeWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.bootstrap.material_consumers import register_node_demand_in
from leornian.bootstrap.materials import MaterialWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.assessment.python_contracts import PythonPracticeSubmission
from leornian.modules.item_bank.exposure import Exposures
from leornian.modules.item_bank.supply import Packs
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.material_contracts import TextMaterialImport
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.composition_delivery_contracts import (
    PrepareCodeReviewComposition,
)
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.evaluation_contracts import EvaluationDocument
from leornian.modules.tutor.evaluations import Evaluations
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def submitted(database, session, practice_setup):
    python, pack, gate, real = practice_setup
    attempt = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()),
        PythonPracticeSubmission(slot="practice_1", code="print(0)"),
    )
    complete(database, session, attempt, real, wrong=True)
    settings = replace(
        gate[2][2], delivery_enabled=True, model_context_tokens=128000,
        model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    with database.transaction() as connection:
        source = Evaluations(connection).receipt_context(session.actor, attempt.id)
        pack_row = Packs(connection).row(session.actor, pack.pack_id)
    return {
        "python": python, "pack": pack,
        "attempt": python.practice_attempt(session.token, attempt.id),
        "settings": settings, "tutor": tutor, "source": source, "real": real,
        "conversation": tutor.conversation(session.token, gate[2][3].goal_id),
        "focus": TeachingFocus(
            kind="attempt", plan_id=pack_row["plan_id"],
            expected_plan_revision=pack_row["plan_revision"], node_key=pack_row["node_key"],
            assessment_receipt_id=attempt.id,
        ),
    }


def arguments():
    return {
        "command_key": "review-the-submitted-program",
        "code_component_id": "submitted",
        "definition": {
            "schema_version": "learning_composition.v2", "title": "Review this submitted program",
            "states": {"code": {"type": "code", "value": ""}},
            "components": [
                {"id": "submitted", "component": "CodeBlock", "props": {
                    "label": "Immutable submitted code", "state": "code",
                }},
                {"id": "review", "component": "ReviewFinding", "props": {
                    "label": "Comments on this submission", "for_component": "submitted",
                }},
                {"id": "boundary", "component": "KeyValueList", "props": {
                    "label": "Review boundary",
                    "entries": [{"name": "Purpose", "value": "Teaching, not a new execution"}],
                }},
            ],
        },
        "findings": [{
            "line": 1, "source_line": "print(0)",
            "content": "The constant output ignores the JSON array. Read and sum its values.",
        }],
    }


def review_provider(settings, args=None, before_check=None, *, select=True):
    calls, prepared = [], []

    def handle(request):
        wire = json.loads(request.content)
        calls.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            payload = json.loads(wire["messages"][-1]["content"])
            assert "submitted_code_review_checks" in payload
            if before_check:
                before_check()
            return httpx.Response(200, json=body(json.dumps(report(payload))))
        if wire["messages"][-1]["role"] == "tool":
            result = json.loads(wire["messages"][-1]["content"])
            prepared.append(result)
            return httpx.Response(200, json=body(json.dumps({
                "text": "The selected submission remains fixed; no new execution was performed.",
                "interaction": {
                    "type": "artifact", "exact_handle": result["candidate"]["id"],
                    "intent": "introduce_only",
                } if result["status"] == "completed" and select else {"type": "none"},
            })))
        return httpx.Response(200, json={
            "choices": [{
                "message": {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "prepare-submitted-code-review", "type": "function",
                    "function": {
                        "name": "prepare_learning_code_review_composition",
                        "arguments": json.dumps(args if args is not None else arguments()),
                    },
                }]},
                "finish_reason": "tool_calls",
            }],
        })

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), calls, prepared


def request_review(session, submitted, *, key=None, capability=True, focus=None):
    data = TurnInput(
        text="Review the whole program in this selected completed submission.",
        focus=focus or submitted["focus"],
        presentation_capabilities={
            "versions": ["learning_composition.v2"],
            "actions": ["learning_code_review.v1"] if capability else [],
        },
    )
    accepted = submitted["tutor"].submit(
        session.token, submitted["conversation"].id, key or str(uuid4()), data
    )
    return accepted, data


def read_review(database, session, submitted):
    flow = LearningArtifactWorkflow(database)
    summary = flow.list_v2(session.token, submitted["conversation"].id)[0]
    return flow.get_v2(
        session.token, summary.conversation_id, summary.id,
        code_review_capability="learning_code_review.v1",
    )


def review_exposures(database, session):
    with database.transaction() as connection:
        return [
            item for item in Exposures(connection).snapshot(session.actor)[1]
            if ":code-review:" in item["key"]
        ]


def unrelated_material(database, session, submitted):
    return MaterialWorkflow(database).import_text(
        session.token, str(uuid4()), TextMaterialImport(
            goal_id=submitted["conversation"].goal_id,
            title="Unrelated reading", source_url="https://example.org/other",
            text="# Other topic\n\nThis reading is about unrelated string formatting.",
            authorized_use=True, purposes=["reference", "teaching", "indexing"],
        ),
    )


def test_legacy_attempt_keeps_exact_sources_after_unrelated_upload(
    database, session, submitted,
):
    unrelated_material(database, session, submitted)
    accepted, _ = request_review(session, submitted)
    with database.transaction() as connection:
        turn = PgTutorStore(connection).get_turn(
            submitted["conversation"].id, accepted.turn_id,
        )
        assert turn.material_demand_id is None
        assert not Runs(connection).latest(accepted.run_id)
    gateway, calls, _ = review_provider(submitted["settings"])
    assert drain(
        submitted["tutor"], submitted["settings"], accepted, gateway, session.token,
    ).status == "accepted"
    assert len(calls) == 3
    assert read_review(database, session, submitted).review_bindings[0].attempt == (
        submitted["attempt"]
    )


def test_zero_call_legacy_attempt_dependency_recovers_without_rewriting_its_sources(
    database, session, submitted, monkeypatch,
):
    unrelated_material(database, session, submitted)

    def legacy_prepare(connection, actor, conversation, turn, purpose, focus, **_kwargs):
        node = next(
            node for node in Plans(connection).get(actor, focus.plan_id).active.document.nodes
            if node.key == focus.node_key
        )
        return register_node_demand_in(
            connection, actor, conversation.goal_id, focus, purpose,
            f"tutor-turn:{turn.id}:{purpose}", node.objective,
        )

    with monkeypatch.context() as patch:
        patch.setattr("leornian.bootstrap.tutor.prepare_consumer_in", legacy_prepare)
        original_resolver = TutorWorkflow._material_demand

        def old_demand(connection, actor, turn_id, purpose, **_kwargs):
            return MaterialIntake(connection).consumer_demand(
                actor, f"tutor-turn:{turn_id}:{purpose}:semantic-goal.v1",
            )

        patch.setattr(TutorWorkflow, "_material_demand", staticmethod(old_demand))
        accepted, _ = request_review(session, submitted)
        gateway, calls, _ = review_provider(submitted["settings"])
        task = drain(
            submitted["tutor"], submitted["settings"], accepted, gateway, session.token,
        )
        assert task.status == "waiting_dependency" and calls == []
    with database.transaction() as connection:
        intake = MaterialIntake(connection)
        old = intake.consumer_demand(
            session.actor, f"tutor-turn:{accepted.turn_id}:teaching:semantic-goal.v1",
        )
        before = old.model_dump(mode="json")
    submitted["tutor"].resume_delivery(session.token, task.id)
    with database.transaction() as connection:
        turn = PgTutorStore(connection).get_turn(
            submitted["conversation"].id, accepted.turn_id,
        )
        intake = MaterialIntake(connection)
        assert turn.material_demand_id is None
        assert original_resolver(connection, session.actor, turn.id, "teaching") is None
        assert intake.demand(session.actor, old.id).model_dump(mode="json") == before
        assert Runs(connection).latest(accepted.run_id) is None
    gateway, calls, _ = review_provider(submitted["settings"])
    assert drain(
        submitted["tutor"], submitted["settings"], accepted, gateway, session.token,
    ).status == "accepted"
    assert len(calls) == 3


def test_unrelated_upload_does_not_restore_revoked_attempt_source(database, session, submitted):
    unrelated_material(database, session, submitted)
    source = submitted["source"]["context_data"]["question"]["source_refs"][0]
    KnowledgeWorkflow(database).revoke(
        session.token, UUID(source["source_id"]), source["revision"],
    )
    with pytest.raises(BusinessError, match="Source revision|source"):
        request_review(session, submitted)
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT 1 FROM knowledge.document_versions WHERE legacy_source_id=%s",
            (UUID(source["source_id"]),),
        ).fetchone() is None


@pytest.mark.parametrize("existing", ["prepared", "unknown", "explicit"])
def test_attempt_scope_keeps_existing_calls_and_explicit_material_demand(
    database, session, submitted, existing,
):
    accepted, _ = request_review(session, submitted)
    with database.transaction() as connection:
        intake = MaterialIntake(connection)
        data = MaterialDemandInput(
            goal_id=submitted["conversation"].goal_id,
            plan_id=submitted["focus"].plan_id, plan_revision=1,
            node_key=submitted["focus"].node_key, purpose="teaching",
            scope_mode="teaching_goal", goal_text="The previously frozen material objective.",
        )
        if existing == "explicit":
            demand = intake.create_demand(session.actor, str(uuid4()), data)
            PgTutorStore(connection).bind_material_demand(accepted.turn_id, demand.id)
        else:
            demand = intake.ensure_consumer_demand(
                session.actor, f"tutor-turn:{accepted.turn_id}:teaching:semantic-goal.v1", data,
            )
            runs = Runs(connection)
            call = runs.prepare(accepted.run_id, "https://owned.invalid/v1", {"model": "offline"})
            if existing == "unknown":
                assert runs.dispatch(call.id)
                runs.record(call.id, unknown=True)
                runs.finish(accepted.run_id, "blocked_unknown", "external_result_unknown")
        assert TutorWorkflow._material_demand(
            connection, session.actor, accepted.turn_id, "teaching",
        ) == demand
        if existing != "explicit":
            assert Runs(connection).latest(accepted.run_id).status == existing


def test_review_uses_original_receipt_checked_delivery_and_atomic_assistance(
    database, workflow, session, submitted
):
    legacy = EvaluationDocument(
        recorded_correct=False, explanation="Original immutable commentary.", reflection="Why?"
    )
    with database.transaction() as connection:
        evaluations = Evaluations(connection)
        evaluations.record(evaluations.row(session.actor, submitted["source"]["id"]), legacy)
    key = str(uuid4())
    accepted, data = request_review(session, submitted, key=key)
    with database.transaction() as connection:
        frozen = Runs(connection).lock(accepted.run_id)["tool_contracts"]
        assert frozen["prepare_learning_code_review_composition"] == 1
        assert "request_learning_practice_supply" not in frozen
        assert "prepare_learning_response_composition" not in frozen

    def before_check():
        assert not review_exposures(database, session)
        assert not LearningArtifactWorkflow(database).list_v2(
            session.token, submitted["conversation"].id
        )

    gateway, calls, prepared = review_provider(submitted["settings"], before_check=before_check)
    task = drain(submitted["tutor"], submitted["settings"], accepted, gateway, session.token)
    assert task.status == "accepted" and len(calls) == 3
    view = read_review(database, session, submitted)
    assert not view.component_bindings
    assert [
        binding.model_dump(mode="json", exclude_none=True) for binding in view.review_bindings
    ] == prepared[0]["candidate"]["review_bindings"]
    binding = view.review_bindings[0]
    assert binding.attempt == submitted["attempt"] and not binding.recorded_correct
    assert binding.findings[0].source_line == "print(0)"
    code = view.presentation.definition.states["code"]
    assert code.read_only and code.value == submitted["attempt"].code
    exposures = review_exposures(database, session)
    assert len(exposures) == 1
    assert exposures[0]["feedback"]["attempt"]["id"] == str(submitted["attempt"].id)
    assert not workflow.snapshot(session.token).node_progress
    with database.transaction() as connection:
        evaluations = Evaluations(connection)
        assert evaluations.row(session.actor, submitted["source"]["id"])["document"] == (
            legacy.model_dump(mode="json")
        )
    assert "test_cases" not in json.dumps(calls)
    assert submitted["tutor"].submit(
        session.token, view.conversation_id, key, data
    ) == accepted
    assert read_review(database, session, submitted).review_bindings == view.review_bindings
    assert review_exposures(database, session) == exposures


@pytest.mark.parametrize("change", ["wrong-line", "wrong-quote", "replacement-code"])
def test_review_rejects_wrong_code_and_line_anchors_without_exposure(
    database, session, submitted, change
):
    args = arguments()
    if change == "wrong-line":
        args["findings"][0]["line"] = 2
    elif change == "wrong-quote":
        args["findings"][0]["source_line"] = "print(sum(values))"
    else:
        args["definition"]["states"]["code"]["value"] = "print(sum(values))"
    accepted, _ = request_review(session, submitted)
    gateway, _, prepared = review_provider(submitted["settings"], args)
    task = drain(submitted["tutor"], submitted["settings"], accepted, gateway, session.token)
    assert task.status == "accepted"
    assert prepared[0]["status"] == "waiting_dependency"
    assert not review_exposures(database, session)
    assert not LearningArtifactWorkflow(database).list_v2(
        session.token, submitted["conversation"].id
    )


def test_new_attempt_does_not_rebase_review_and_older_readers_cannot_consume_new_feedback(
    database, workflow, session, submitted
):
    accepted, _ = request_review(session, submitted)
    gateway, _, _ = review_provider(submitted["settings"])
    assert drain(
        submitted["tutor"], submitted["settings"], accepted, gateway, session.token
    ).status == "accepted"
    view = read_review(database, session, submitted)
    second = submitted["python"].submit_practice(
        session.token, submitted["pack"].pack_id, str(uuid4()),
        PythonPracticeSubmission(
            slot="practice_1", code=program("practice_1"),
            previous_attempt_id=submitted["attempt"].id,
        ),
    )
    complete(database, session, second, submitted["real"])
    restored = read_review(database, session, submitted)
    assert restored.review_bindings == view.review_bindings
    assert restored.content_ref == view.content_ref
    assert restored.review_bindings[0].attempt.id != second.id
    client = TestClient(create_app(submitted["settings"]))
    path = f"/v2/conversations/{view.conversation_id}/learning-artifacts/{view.id}"
    headers = {"Authorization": "Bearer " + session.token}
    assert client.get(path, headers=headers).status_code == 409
    assert client.get(
        path + "?code_review_capability=learning_code_review.v1", headers=headers
    ).status_code == 200
    other = workflow.create_session("Other reviewer")
    assert client.get(
        path + "?code_review_capability=learning_code_review.v1",
        headers={"Authorization": "Bearer " + other.token},
    ).status_code == 404


def test_cancelled_review_keeps_preparation_unpublished_and_does_not_expose_comments(
    database, session, submitted
):
    accepted, _ = request_review(session, submitted)
    gateway, _, _ = review_provider(
        submitted["settings"],
        before_check=lambda: submitted["tutor"].cancel(session.token, accepted.run_id),
    )
    task = drain(submitted["tutor"], submitted["settings"], accepted, gateway, session.token)
    assert task.status == "cancelled"
    assert not review_exposures(database, session)
    assert not LearningArtifactWorkflow(database).list_v2(
        session.token, submitted["conversation"].id
    )
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT quality_call_id FROM tutor.learning_presentations WHERE prepared_run_id=%s",
            (accepted.run_id,),
        ).fetchone()["quality_call_id"] is None


def test_old_frozen_runs_do_not_gain_review_tool_and_replay_cannot_change_support(
    database, session, submitted
):
    key = str(uuid4())
    accepted, _ = request_review(session, submitted, key=key, capability=False)
    with database.transaction() as connection:
        assert "prepare_learning_code_review_composition" not in Runs(connection).lock(
            accepted.run_id
        )["tool_contracts"]
    with pytest.raises(BusinessError, match="submitted-review support"):
        request_review(session, submitted, key=key)
    submitted["tutor"].cancel(session.token, accepted.run_id)
    value = arguments()
    value["recorded_correct"] = True
    with pytest.raises(ValueError):
        PrepareCodeReviewComposition.model_validate(value)


def test_unselected_preparation_never_becomes_delivered_assistance(database, session, submitted):
    accepted, _ = request_review(session, submitted)
    gateway, _, prepared = review_provider(submitted["settings"], select=False)
    task = drain(submitted["tutor"], submitted["settings"], accepted, gateway, session.token)
    assert task.status == "accepted" and prepared[0]["status"] == "completed"
    assert not review_exposures(database, session)
    assert not LearningArtifactWorkflow(database).list_v2(
        session.token, submitted["conversation"].id
    )
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT quality_call_id FROM tutor.learning_presentations WHERE prepared_run_id=%s",
            (accepted.run_id,),
        ).fetchone()["quality_call_id"] is None


@pytest.mark.parametrize("source", ["pending", "qualification"])
def test_review_never_opens_pending_or_private_qualification_code(
    database, session, submitted, source
):
    if source == "pending":
        receipt_id = submitted["python"].submit_practice(
            session.token, submitted["pack"].pack_id, str(uuid4()),
            PythonPracticeSubmission(slot="practice_2", code="print(0)"),
        ).id
    else:
        with database.transaction() as connection:
            receipt_id = connection.execute(
                "SELECT id FROM assessment.python_attempts "
                "WHERE pack_id=%s AND purpose='qualification' LIMIT 1",
                (submitted["pack"].pack_id,),
            ).fetchone()["id"]
    with pytest.raises(BusinessError, match="already-public feedback"):
        request_review(
            session, submitted,
            focus=submitted["focus"].model_copy(update={"assessment_receipt_id": receipt_id}),
        )
    assert not review_exposures(database, session)


def test_review_read_rechecks_original_material_permission_without_rebasing(
    database, session, submitted
):
    accepted, _ = request_review(session, submitted)
    gateway, _, _ = review_provider(submitted["settings"])
    assert drain(
        submitted["tutor"], submitted["settings"], accepted, gateway, session.token
    ).status == "accepted"
    original = read_review(database, session, submitted)
    source = submitted["source"]["context_data"]["question"]["source_refs"][0]
    KnowledgeWorkflow(database).revoke(
        session.token, UUID(source["source_id"]), source["revision"]
    )
    with pytest.raises(BusinessError):
        read_review(database, session, submitted)
    assert LearningArtifactWorkflow(database).list_v2(
        session.token, original.conversation_id
    )[0].id == original.id
    assert len(review_exposures(database, session)) == 1
