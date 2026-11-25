import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_concept_gates import gate_setup as gate_setup
from test_dynamic_plans import document, run
from test_dynamic_plans import setup_planner as setup_planner
from test_generated_lessons import execute, lesson_document
from test_item_supply import supply_setup as supply_setup
from test_python_execution import program
from test_python_execution import python_setup as python_setup
from test_python_practice import complete
from test_python_practice import practice_setup as practice_setup

from leornian.bootstrap.teaching_context import TeachingContext
from leornian.bootstrap.teaching_memory import TeachingMemory, encoded_size
from leornian.modules.assessment.python_contracts import PythonPracticeSubmission
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.supply import Packs
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.knowledge.contracts import SourceInput
from leornian.modules.learning.contracts import LessonRequestInput
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.application import Tutor
from leornian.modules.tutor.contracts import PlanningInput, TeachingFocus
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.modules.tutor.route_requirements import RouteRequirementChange, RouteRequirements
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def memory_setup(database, session, setup_planner):
    tutor, settings, conversation = setup_planner
    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection)).authenticate(session.token)
        knowledge = Knowledge(connection)
        sources = []
        for name in ("earlier", "current"):
            source, _ = knowledge.create(
                actor, conversation.goal_id, str(uuid4()),
                SourceInput(
                    title=name, source_url=f"https://owned.invalid/{name}",
                    excerpt="Use pathlib.Path.iterdir for read-only path iteration.",
                ),
            )
            knowledge.admit(actor, source.id, 1, datetime.now(UTC) + timedelta(days=1))
            sources.append(source)
    route = document(sources=[{"source_id": str(sources[0].id), "revision": 1}])
    route["nodes"][1]["source_refs"] = [{"source_id": str(sources[1].id), "revision": 1}]
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Teach a two-node project.", expected_revision=0),
    )
    run(setup_planner, accepted.run_id, route)
    with database.transaction() as connection:
        plan = Plans(connection).for_goal(actor, conversation.goal_id)
    tutor.confirm_plan(session.token, plan.id, 1)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="organizer",
    )
    return SimpleNamespace(
        database=database, tutor=tutor, settings=settings, conversation=conversation,
        actor=actor, plan=plan, sources=sources, focus=focus,
    )


def save_turn(state, *, node="paths", text="I can list files.", reply="Use Path.iterdir.",
              complete=True, revision=1, at=None):
    with state.database.transaction() as connection:
        store = PgTutorStore(connection)
        turn, _ = store.request_turn(state.conversation.id, str(uuid4()), text)
        store.bind_focus(turn.id, TeachingFocus(
            kind="node", plan_id=state.plan.id, expected_plan_revision=revision, node_key=node,
        ))
        if complete:
            store.complete(turn.id, reply)
        if at is not None:
            connection.execute(
                "UPDATE tutor.turns SET created_at=%s,completed_at=%s WHERE id=%s",
                (at, at if complete else None, turn.id),
            )
        return turn.id


def build(state, **kwargs):
    with state.database.transaction() as connection:
        return TeachingMemory.build_in(
            connection, state.actor, state.conversation, state.focus, **kwargs,
        )


def test_old_cross_node_deliveries_and_quoted_self_report_rebuild_without_mastery(memory_setup):
    state = memory_setup
    old = save_turn(state, text="Use snake_case names.", reply="Iterate with Path.iterdir().")
    save_turn(state, reply="UNDELIVERED CANDIDATE", complete=False)
    save_turn(state, reply="DIFFERENT REVISION", revision=2)
    with state.database.transaction() as connection:
        requirements = RouteRequirements(connection)
        snapshot = {"revision": 0, "learner_messages": [
            {"turn_id": str(old), "text": "Use snake_case names."},
        ]}
        requirements.accept(state.conversation.id, old, snapshot, [
            RouteRequirementChange(
                key="preferences", value="snake_case names", source_turn_id=old,
                source_quote="Use snake_case names.",
            ),
        ])
        context, manifest = TeachingContext.build(
            connection, state.actor, state.conversation, state.focus,
        )
    memory = context["learning_memory"]
    assert memory["delivered_teaching"][0]["node_key"] == "paths"
    assert memory["delivered_teaching"][0]["extracts"][0]["turn_id"] == str(old)
    assert memory["learner_stated"]["facts"]["preferences"]["source_quote"]["text"] == (
        "Use snake_case names."
    )
    assert memory["learner_messages"][0]["kind"] == "learner_self_report"
    assert all(
        dimension["status"] == "unobserved" for dimension in memory["assessment"]["dimensions"]
    )
    assert memory["project_state"]["submissions"] == []
    assert "UNDELIVERED" not in json.dumps(memory)
    assert "DIFFERENT REVISION" not in json.dumps(memory)
    assert manifest["learning_memory"]["turn_ids"] == [str(old)]


def test_delivered_lesson_uses_actual_document_instead_of_saved_notice(memory_setup, session):
    state = memory_setup
    accepted = state.tutor.submit_lesson(
        session.token, state.plan.id, str(uuid4()),
        LessonRequestInput(
            expected_plan_revision=1, node_key="paths", instruction="Show an actual path example.",
        ),
    )
    execute(state.tutor, state.settings, accepted.run_id, lesson_document(state.sources[0]))
    memory, manifest = build(state)
    extracts = memory["delivered_teaching"][0]["extracts"]
    lesson = next(item for item in extracts if item["kind"] == "lesson")
    assert lesson["lesson_id"] in manifest["lesson_ids"]
    assert lesson["sections"][0]["heading"] == "Iterate over directory children"
    assert 'Path(".").iterdir()' in lesson["sections"][0]["code_example"]["text"]
    assert "First inspect entries" in lesson["excerpt"]["text"]
    assert memory["assessment"]["total_receipts"] == 0
    next_lesson = state.tutor.submit_lesson(
        session.token, state.plan.id, str(uuid4()),
        LessonRequestInput(
            expected_plan_revision=1, node_key="organizer", instruction="Continue the project.",
        ),
    )
    sent = execute(
        state.tutor, state.settings, next_lesson.run_id, lesson_document(state.sources[1]),
    )
    next_context = json.loads(sent[0]["messages"][1]["content"])
    assert next_context["learning_memory"]["delivered_teaching"][0]["extracts"][0]["lesson_id"] == (
        lesson["lesson_id"]
    )


def test_branch_and_request_boundary_do_not_pull_mainline_or_later_delivery(memory_setup):
    state = memory_setup
    at = datetime.now(UTC) - timedelta(minutes=3)
    old = save_turn(state, reply="BEFORE REQUEST", at=at)
    current = save_turn(state, node="organizer", complete=False, at=at + timedelta(minutes=1))
    save_turn(state, reply="AFTER REQUEST", at=at + timedelta(minutes=2))
    memory, manifest = build(state, before_turn_id=current)
    assert manifest["turn_ids"] == [str(old)]
    assert "AFTER REQUEST" not in json.dumps(memory)
    branch, _ = build(state, branch_id=uuid4(), before_turn_id=current)
    assert branch["delivered_teaching"] == [] and branch["learner_messages"] == []
    with state.database.transaction() as connection:
        with pytest.raises(BusinessError, match="conversation not found"):
            TeachingMemory.build_in(
                connection, state.actor,
                state.conversation.model_copy(update={"id": uuid4()}), state.focus,
            )


def test_revoked_old_source_is_removed_and_frozen_origin_cannot_publish(memory_setup):
    state = memory_setup
    save_turn(state, reply="PROTECTED EARLIER TEXT")
    _, frozen = build(state)
    with state.database.transaction() as connection:
        Knowledge(connection).revoke(state.actor, state.sources[0].id, 1)
    memory, manifest = build(state)
    assert memory["delivered_teaching"] == []
    assert memory["omissions"]["unavailable_nodes"] == 1
    assert "PROTECTED EARLIER TEXT" not in json.dumps(memory)
    assert manifest["turn_ids"] == []
    with state.database.transaction() as connection:
        with pytest.raises(BusinessError) as error:
            TeachingMemory.require_current_in(
                connection, state.actor, state.conversation.goal_id, frozen,
            )
        assert error.value.code == "source_not_current"


def test_large_history_fits_budget_and_retains_exact_references(memory_setup):
    state = memory_setup
    for index in range(12):
        save_turn(state, text=f"Question {index}: " + "query " * 300,
                  reply=f"Delivered {index}: " + "pathlib " * 700)
    memory, manifest = build(state, max_chars=6000)
    assert encoded_size(memory) <= 6000
    assert memory["delivered_teaching"][0]["delivered_count"] == 12
    assert len(manifest["turn_ids"]) == 2
    assert all(
        item["excerpt"]["truncated"] and item["excerpt"]["start"] == 0
        for item in memory["delivered_teaching"][0]["extracts"]
    )


def test_actual_submitted_code_and_failed_result_obey_the_request_boundary(
    database, session, practice_setup,
):
    python, pack, _, real = practice_setup
    with database.transaction() as connection:
        actor = Identity(PgIdentityStore(connection)).authenticate(session.token)
        owned = Packs(connection).row(actor, pack.pack_id)
        plan = Plans(connection).get(actor, owned["plan_id"])
        conversation = Tutor(PgTutorStore(connection)).conversation(actor, plan.goal_id)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key=owned["node_key"],
    )
    state = SimpleNamespace(
        database=database, actor=actor, conversation=conversation, focus=focus, plan=plan,
    )
    before = save_turn(
        state, node=focus.node_key, text="Continue after my submitted code.", complete=False,
    )
    first = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()),
        PythonPracticeSubmission(slot="practice_1", code="print(0)"),
    )
    complete(database, session, first, real, wrong=True)
    memory, manifest = build(state)
    assert memory["project_state"]["submissions"][0]["answer"]["code"]["text"] == "print(0)"
    assert memory["project_state"]["submissions"][0]["source_receipt"] == str(first.id)
    assert memory["unresolved"][0]["outcome"] == "not_passed"
    assert str(first.id) in manifest["receipt_ids"]
    assert "test_cases" not in json.dumps(memory)
    assert "assessment_1" not in json.dumps(memory)
    frozen, frozen_manifest = build(state, before_turn_id=before)
    assert frozen["assessment"]["total_receipts"] == 0
    assert frozen["project_state"]["submissions"] == []
    assert frozen_manifest["receipt_ids"] == [] and frozen_manifest["submission_ids"] == []
    corrected = python.submit_practice(
        session.token, pack.pack_id, str(uuid4()),
        PythonPracticeSubmission(
            slot="practice_1", code=program("practice_1"), previous_attempt_id=first.id,
        ),
    )
    complete(database, session, corrected, real)
    updated, _ = build(state)
    assert updated["project_state"]["submissions"][0]["source_receipt"] == str(corrected.id)
    assert updated["project_state"]["submissions"][0]["answer"]["code"]["text"] == (
        program("practice_1")
    )
    assert updated["assessment"]["total_receipts"] == 2
    assert not any(issue["source_receipt"] == str(first.id) for issue in updated["unresolved"])
