import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_concept_gates import relation_document, submit_data
from test_item_supply import blind, document, review, run_model, stages
from test_material_consumers import consumer as consumer
from test_material_consumers import draft
from test_material_lifecycle import material_setup as material_setup
from test_material_sources_and_goals import advance_consumer_materials
from test_python_execution import code_document, owned_claim, program, receipt
from test_teaching_delivery import drain, provider

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.automatic_supply import AutomaticSupply
from leornian.bootstrap.concept_gate import ConceptGate
from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.journey import JourneyWorkflow
from leornian.bootstrap.material_consumers import binding_citations
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.modules.assessment.gate_contracts import GateRequest
from leornian.modules.item_bank.python_contracts import PythonPack
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import (
    REVIEW_ROLES,
    SLOTS,
    ChoiceInput,
    PackDocument,
    PackRequest,
    ReviewDocument,
)
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.learning.contracts import LessonRequestInput
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.shared_kernel.errors import BusinessError


def start_pack(consumer, session, *, kind="choice", automatic=False):
    tutor, settings, _, _, _, _, _, _, _ = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    supply = ItemSupply(tutor.database, settings)
    data = PackRequest(
        expected_plan_revision=1, node_key="iteration", instruction="Test this exact node.",
        kind=kind, automatic=automatic,
    )
    key = str(uuid4())
    accepted = supply.submit(session.token, plan.id, key, data)
    assert supply.submit(session.token, plan.id, key, data) == accepted
    return supply, plan, accepted


def pack_context(database, session, accepted):
    with database.transaction() as connection:
        return Packs.material_context(Packs(connection).row(session.actor, accepted.pack_id))


def authored(context, kind="choice"):
    value = (code_document if kind == "python_io" else document)(SimpleNamespace(id=uuid4()))
    for item in value["items"]:
        item["source_refs"] = []
        item["material_citations"] = [context.author_citations[0].model_dump(mode="json")]
    return value


def reviewed(context, passed=True):
    value = review(passed)
    for item in value["items"]:
        item["material_citations"] = [context.review_citations[0].model_dump(mode="json")]
    return value


def finish_pack(consumer, session, supply, accepted, *, fail_role=None):
    tutor, settings, _, _, _, _, _, _, _ = consumer
    context = pack_context(tutor.database, session, accepted)
    observed = {}
    for _ in range(8):
        pending = supply.get(session.token, accepted.pack_id)
        if pending.status in {"ready", "changes_required", "qualifying"}:
            break
        assert pending.pending_run_id is not None
        advance_consumer_materials(tutor.database, session, settings, consumer[4].id)
        role = pending.pending_role
        payload = (
            authored(context) if role == "author"
            else blind() if role == "blind" else reviewed(context, role != fail_role)
        )
        run_model(
            tutor, settings, pending.pending_run_id, payload,
            observe=lambda wire, role=role: observed.update({role: wire}),
        )
    return context, observed


@pytest.mark.parametrize(
    "consumer", [["lesson", "item_author", "item_review"]], indirect=True
)
class TestItemMaterialConsumers:
    def test_material_pending_automatic_pack_resumes_the_same_uncalled_author_run(
        self, database, session, consumer
    ):
        supply, _plan, accepted = start_pack(consumer, session, automatic=True)
        tutor, settings, _, _, goal, _, _, _, _ = consumer
        context = pack_context(database, session, accepted)
        observed = []
        run_model(tutor, settings, accepted.run_id, authored(context), observed.append)
        assert observed == []
        with database.transaction() as connection:
            run = Runs(connection).get(session.actor.id, accepted.run_id)
            assert run.status == "failed" and run.error_code == "material_pending"
            assert Runs(connection).latest(run.id) is None
            turns_before = connection.execute(
                "SELECT count(*) AS n FROM tutor.turns t JOIN tutor.conversations c "
                "ON c.id=t.conversation_id WHERE c.actor_id=%s", (session.actor.id,),
            ).fetchone()["n"]
        advance_consumer_materials(database, session, settings, goal.id)
        assert AutomaticSupply(database, settings).advance(accepted.pack_id) == 1
        pending = supply.get(session.token, accepted.pack_id)
        assert pending.status == "authoring" and pending.pending_run_id == accepted.run_id
        run_model(tutor, settings, accepted.run_id, authored(context), observed.append)
        assert len(observed) == 1
        payload = json.loads(observed[0]["messages"][1]["content"])
        assert payload["material_goal_coverage"]["status"] == "sufficient"
        assert payload["material_citations"] and payload["bound_materials"]
        assert supply.get(session.token, accepted.pack_id).status == "blind_solving"
        assert [row["run_id"] for row in stages(database, accepted.pack_id)][0] == accepted.run_id
        with database.transaction() as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM tutor.turns t JOIN tutor.conversations c "
                "ON c.id=t.conversation_id WHERE c.actor_id=%s", (session.actor.id,),
            ).fetchone()["n"] == turns_before + 1
            assert connection.execute(
                "SELECT count(*) AS n FROM item_bank.packs WHERE actor_id=%s",
                (session.actor.id,),
            ).fetchone()["n"] == 1

    def test_choice_pipeline_scoped_demands_blind_privacy_and_original_gate(
        self, database, workflow, session, consumer
    ):
        supply, plan, accepted = start_pack(consumer, session)
        tutor, settings, _, _, goal, _, planning_binding, _, _ = consumer
        context, observed = finish_pack(consumer, session, supply, accepted)
        assert supply.get(session.token, accepted.pack_id).blind_passed is True
        assert context.origin_citations == binding_citations([planning_binding])
        assert set(observed) == {"author", "blind", *REVIEW_ROLES}
        assert {c.binding_id for c in context.author_citations}.isdisjoint(
            c.binding_id for c in context.review_citations
        )
        for role in ("author", *REVIEW_ROLES):
            payload = json.loads(observed[role]["messages"][1]["content"])
            purpose = "item_author" if role == "author" else "item_review"
            assert payload["material_demand"]["purpose"] == purpose
            assert payload["material_demand"]["language"] is None
            assert payload["material_demand"]["plan_id"] == str(plan.id)
            assert payload["material_demand"]["node_key"] == "iteration"
            assert payload["material_demand"]["scope_mode"] == "teaching_goal"
            assert payload["material_demand"]["required_facets"] == []
            assert payload["material_demand"]["goal_text"] == "Iteration"
            assert payload["material_goal_coverage"]["basis"] == "semantic-goal-evidence.v1"
            assert payload["material_goal_coverage"]["status"] == "sufficient"
            assert {c["purpose"] for c in payload["material_citations"]} == {purpose}
            assert len(payload["bound_materials"]) == len(context.origin_citations)
            assert all(b["ref"]["document_revision"] == 1 for b in payload["bound_materials"])
            assert "selected_key" not in json.dumps(observed[role])
        blind_context = json.loads(observed["blind"]["messages"][1]["content"])
        assert set(blind_context) == {"objective", "node_title", "questions"}
        assert "bound_materials" not in blind_context and "material_demand" not in blind_context
        assert "correct_key" not in json.dumps(blind_context)
        assert "Private explanation" not in json.dumps(blind_context)
        demands = MaterialIntakeWorkflow(database, settings).demands(session.token, goal.id)
        assert {d.consumer_ref for d in demands if d.purpose.startswith("item_")} == {
            f"item-pack:{accepted.pack_id}:{role}:semantic-goal.v1"
            for role in ("author", *REVIEW_ROLES)
        }
        assert supply.publish(session.token, accepted.pack_id).status == "published"
        assert not workflow.snapshot(session.token).node_progress
        practice = supply.practice(session.token, accepted.pack_id)
        assert all(q.material_citations == context.author_citations[:1] for q in practice.questions)
        assert all(not q.source_refs for q in practice.questions)
        for slot in ("practice_1", "practice_2"):
            key = str(uuid4())
            data = ChoiceInput(slot=slot, selected_key="A")
            result = supply.answer(session.token, accepted.pack_id, key, data)
            assert result.correct
            assert supply.answer(session.token, accepted.pack_id, key, data) == result
        assert not workflow.snapshot(session.token).node_progress

        attempt_turn = tutor.submit(
            session.token, consumer[2].id, str(uuid4()), TurnInput(
                text="Explain this exact recorded answer.",
                focus=TeachingFocus(
                    kind="attempt", plan_id=plan.id, expected_plan_revision=1,
                    node_key="iteration", assessment_receipt_id=result.id,
                ),
            ),
        )
        question = next(q for q in practice.questions if q.slot == result.slot)
        with database.transaction() as connection:
            turn = PgTutorStore(connection).get_turn(consumer[2].id, attempt_turn.turn_id)
            demand = MaterialIntake(connection).demand(session.actor, turn.material_demand_id)
            assert demand.goal_text == question.title + "\n" + question.prompt
            assert demand.consumer_ref.endswith(":attempt-source.v1:semantic-goal.v1")
        gateway, sent, _ = provider(settings, author="Explain the fixed public task and receipt.")
        assert drain(
            tutor, settings, attempt_turn, gateway, session.token,
        ).status == "waiting_dependency"
        assert sent == []
        advance_consumer_materials(database, session, settings, goal.id)
        tutor.resume_delivery(session.token, attempt_turn.delivery_task_id)
        assert drain(
            tutor, settings, attempt_turn, gateway, session.token,
        ).status == "accepted"
        assert len(sent) == 2
        payload = json.loads(
            sent[0]["messages"][1]["content"].removeprefix("Learning context (data): ")
        )
        assert payload["material_goal_coverage"]["status"] == "sufficient"
        assert payload["material_citations"]

        lesson_turn = tutor.submit_lesson(
            session.token, plan.id, str(uuid4()),
            LessonRequestInput(
                expected_plan_revision=1, node_key="iteration", instruction="Explain iteration."
            ),
        )
        advance_consumer_materials(database, session, settings, goal.id)
        with database.transaction() as connection:
            citations = binding_citations(MaterialBindings(connection).for_scope(
                session.actor, goal.id, "lesson", plan_id=plan.id,
                plan_revision=1, node_key="iteration",
            ))
        lesson = {
            "title": "Iteration", "introduction": "Visit sequence elements.",
            "sections": [{
                "heading": "Loop", "explanation": "The loop visits elements.",
                "code_example": "", "source_refs": [],
                "material_citations": [c.model_dump(mode="json") for c in citations],
            }], "recall_prompts": ["What is visited?"],
        }
        gateway, _, _ = provider(settings, author=json.dumps(lesson))
        assert drain(tutor, settings, lesson_turn, gateway, session.token).status == "accepted"
        # Exercise the original complete relation owner, without batch-protocol fixture shortcuts.
        gates = ConceptGate(database, replace(settings, delivery_enabled=False))
        gate = gates.request(
            session.token, accepted.pack_id, str(uuid4()), GateRequest(expected_plan_revision=1)
        )
        run_model(tutor, settings, gate.relation_run_id, relation_document(database, gate.id))
        assert gates.start(session.token, gate.id).gate.status == "in_progress"
        result = gates.submit(session.token, gate.id, str(uuid4()), submit_data())
        assert result.gate.status == "passed"
        assert workflow.snapshot(session.token).node_progress[0].evidence_gate_id == gate.id

    @pytest.mark.parametrize("kind", ["choice", "python_io"])
    @pytest.mark.parametrize("change", ["binding", "revision", "purpose", "span", "digest"])
    def test_author_owner_rejects_unsupplied_exact_citations(
        self, database, session, consumer, kind, change
    ):
        supply, _, accepted = start_pack(consumer, session, kind=kind)
        context = pack_context(database, session, accepted)
        value = authored(context, kind)
        citation = value["items"][0]["material_citations"][0]
        if change == "binding":
            citation["binding_id"] = str(uuid4())
        elif change == "revision":
            citation["binding_revision"] += 1
        elif change == "purpose":
            citation["purpose"] = "item_review"
        elif change == "span":
            citation["ref"]["span"]["end"] += 1
        else:
            citation["ref"]["content_digest"] = "0" * 64
        parsed = (PythonPack if kind == "python_io" else PackDocument).model_validate(value)
        with pytest.raises(BusinessError, match="unbound"):
            with database.transaction() as connection:
                row = Packs(connection).row(session.actor, accepted.pack_id)
                Packs(connection).record_author(row, accepted.run_id, parsed)
        assert supply.get(session.token, accepted.pack_id).item_count == 0

    def test_review_owner_rejects_author_authority_missing_or_forged_references(
        self, database, session, consumer
    ):
        _, _, accepted = start_pack(consumer, session)
        context = pack_context(database, session, accepted)
        bad = reviewed(context)
        values = [review(), copy.deepcopy(bad), copy.deepcopy(bad)]
        values[1]["items"][0]["material_citations"] = [
            context.author_citations[0].model_dump(mode="json")
        ]
        values[2]["items"][0]["material_citations"][0]["ref"]["content_digest"] = "0" * 64
        for value in values:
            with pytest.raises(BusinessError, match="exact supplied"):
                with database.transaction() as connection:
                    row = Packs(connection).row(session.actor, accepted.pack_id)
                    Packs(connection).record_review(
                        row, accepted.run_id, ReviewDocument.model_validate(value)
                    )
        assert stages(database, accepted.pack_id)[0]["result"] is None

    def test_reference_repair_cannot_turn_a_negative_review_into_an_approval(
        self, database, session, consumer
    ):
        supply, _, accepted = start_pack(consumer, session)
        tutor, settings, _, _, goal, _, _, _, _ = consumer
        context = pack_context(database, session, accepted)
        advance_consumer_materials(database, session, settings, goal.id)
        run_model(tutor, settings, accepted.run_id, authored(context))
        run_model(
            tutor, settings, supply.get(session.token, accepted.pack_id).pending_run_id, blind()
        )
        pending = supply.get(session.token, accepted.pack_id)
        assert pending.pending_role == "curriculum"
        advance_consumer_materials(database, session, settings, goal.id)
        run_model(tutor, settings, pending.pending_run_id, review(False))
        assert supply.get(session.token, accepted.pack_id).status == "failed"
        demands_before = MaterialIntakeWorkflow(database, settings).demands(session.token, goal.id)
        repaired = supply.repair_stage(session.token, accepted.pack_id)
        run_model(tutor, settings, repaired.pending_run_id, reviewed(context, passed=True))
        failed = supply.get(session.token, accepted.pack_id)
        assert failed.status == "failed"
        with database.transaction() as connection:
            assert Runs(connection).get(
                session.actor.id, failed.pending_run_id
            ).error_code == "review_verdict_changed"
        assert MaterialIntakeWorkflow(database, settings).demands(
            session.token, goal.id
        ) == demands_before

    def test_document_and_binding_heads_cannot_retarget_a_queued_pack(
        self, database, session, consumer
    ):
        supply, plan, accepted = start_pack(consumer, session)
        tutor, settings, _, materials, goal, version, _, _, text = consumer
        context = pack_context(database, session, accepted)
        newer = materials.import_text(
            session.token, str(uuid4()),
            text.model_copy(update={
                "document_id": version.document_id, "expected_revision": 1,
                "text": "# New unrelated head\n\nNEVER_RETARGET_THE_QUEUED_PACK",
            }),
        )
        refs = [
            b.ref for b in materials.blocks(
                session.token, newer.document_id, newer.revision, "item_author"
            ).blocks
        ]
        materials.bind(
            session.token, str(uuid4()),
            MaterialBindingInput(
                goal_id=goal.id, plan_id=plan.id, plan_revision=1, node_key="iteration",
                purpose="item_author", expected_binding_revision=1, refs=refs,
            ),
        )
        advance_consumer_materials(database, session, settings, goal.id)
        observed = []
        run_model(tutor, settings, accepted.run_id, authored(context), observed.append)
        assert supply.get(session.token, accepted.pack_id).status == "blind_solving"
        payload = json.loads(observed[0]["messages"][1]["content"])
        assert all(b["ref"]["document_revision"] == 1 for b in payload["bound_materials"])
        assert "NEVER_RETARGET" not in json.dumps(payload)
        assert pack_context(database, session, accepted) == context

    def test_late_model_receipt_is_recorded_but_not_applied_after_material_revocation(
        self, database, session, consumer
    ):
        supply, _, accepted = start_pack(consumer, session)
        tutor, settings, _, materials, goal, version, _, _, _ = consumer
        context = pack_context(database, session, accepted)
        advance_consumer_materials(database, session, settings, goal.id)
        observed = []

        def revoke(wire):
            observed.append(wire)
            materials.revoke(
                session.token, version.document_id, 1,
                DocumentPermissionAction(expected_revision=1, action="revoke"),
            )

        run_model(tutor, settings, accepted.run_id, authored(context), revoke)
        assert supply.get(session.token, accepted.pack_id).item_count == 0
        assert stages(database, accepted.pack_id)[0]["result"] is None
        with database.transaction() as connection:
            call = Runs(connection).latest(accepted.run_id)
            assert call.status == "result_recorded" and not call.applied
        run_model(tutor, settings, accepted.run_id, authored(context), observed.append)
        assert len(observed) == 1

    def test_automatic_revision_preserves_exact_context_and_starts_new_author_demand(
        self, database, session, consumer
    ):
        supply, _, accepted = start_pack(consumer, session, automatic=True)
        tutor, settings, _, _, goal, _, _, _, _ = consumer
        context, _ = finish_pack(consumer, session, supply, accepted, fail_role="technical")
        assert supply.get(session.token, accepted.pack_id).status == "changes_required"
        assert AutomaticSupply(database, settings).advance(accepted.pack_id) == 1
        with database.transaction() as connection:
            child = connection.execute(
                "SELECT * FROM item_bank.packs WHERE predecessor_id=%s", (accepted.pack_id,)
            ).fetchone()
            assert child and Packs.material_context(child) == context
            assert child["document"] is None and child["status"] == "authoring"
        demands = MaterialIntakeWorkflow(database, settings).demands(session.token, goal.id)
        assert any(
            d.consumer_ref == f"item-pack:{child['id']}:author:semantic-goal.v1" for d in demands
        )
        assert pack_context(tutor.database, session, accepted) == context

    def test_python_blind_and_qualification_keep_private_tests_on_original_owner_chain(
        self, database, session, consumer
    ):
        supply, _, accepted = start_pack(consumer, session, kind="python_io")
        tutor, settings, _, _, goal, _, _, _, _ = consumer
        context = pack_context(database, session, accepted)
        advance_consumer_materials(database, session, settings, goal.id)
        run_model(tutor, settings, accepted.run_id, authored(context, "python_io"))
        observed = []
        run_model(
            tutor, settings, supply.get(session.token, accepted.pack_id).pending_run_id,
            {"programs": [{"slot": slot, "code": program(slot)} for slot in SLOTS]},
            observed.append,
        )
        questions = json.loads(observed[0]["messages"][1]["content"])["questions"]
        assert all("tests" not in q and "explanation" not in q for q in questions)
        assert all(q["material_citations"] for q in questions)
        assert supply.get(session.token, accepted.pack_id).status == "qualifying"
        # These are protocol receipts, not real Docker or semantic-quality acceptance.
        for _ in range(5):
            claim = owned_claim(database, session)
            assert claim is not None and "expected" not in claim.model_dump_json()
            JourneyWorkflow(database).report(claim.job_id, receipt(database, claim))
        finish_pack(consumer, session, supply, accepted)
        assert supply.publish(session.token, accepted.pack_id).status == "published"


@pytest.mark.parametrize(
    "consumer", [["lesson", "item_author"], ["lesson", "item_review"]], indirect=True
)
def test_planning_permission_does_not_grant_both_item_role_purposes(
    database, session, consumer
):
    tutor, settings, _, _, goal, _, _, _, _ = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    with pytest.raises(BusinessError, match="not allowed"):
        ItemSupply(database, settings).submit(
            session.token, plan.id, str(uuid4()),
            PackRequest(
                expected_plan_revision=1, node_key="iteration", instruction="Scoped only."
            ),
        )
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM item_bank.packs WHERE actor_id=%s", (session.actor.id,)
        ).fetchone()["n"] == 0
        assert not MaterialBindings(connection).for_scope(
            session.actor, goal.id, "item_author", plan_id=plan.id,
            plan_revision=1, node_key="iteration",
        )
