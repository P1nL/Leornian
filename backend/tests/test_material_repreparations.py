import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from test_material_changes import change_input, revise
from test_material_consumers import consumer as consumer
from test_material_consumers import draft
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import rag as rag
from test_material_sources_and_goals import advance_consumer_materials
from test_material_updates import decision_data, ready_offer
from test_reviews import review_setup as review_setup
from test_teaching_delivery import drain, provider

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.material_change_reviews import MaterialChangeReviewWorkflow
from leornian.bootstrap.material_changes import MaterialChangeWorkflow
from leornian.bootstrap.material_consumers import binding_citations
from leornian.bootstrap.material_repreparations import MaterialRepreparationWorkflow
from leornian.bootstrap.material_updates import MaterialUpdateWorkflow
from leornian.bootstrap.notifications import NotificationsWorkflow
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.learning.contracts import LessonRequestInput
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.learning.planning import Plans


def lesson_document(citations, *, updated=False):
    return {
        "title": "Iteration",
        "introduction": "Read the sequence.",
        "sections": [{
            "heading": "Loop",
            "explanation": "The loop visits each item and prints the updated expression."
            if updated else "The loop visits each item.",
            "code_example": "for x in items:\n    print(x + 1)"
            if updated else "for x in items:\n    print(x)",
            "source_refs": [],
            "material_citations": [citation.model_dump(mode="json") for citation in citations],
        }],
        "recall_prompts": ["What does each loop iteration visit?"],
    }


@pytest.fixture
def reprepare_case(database, workflow, session, rag, consumer, monkeypatch, request):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    tutor, author_settings, _, materials, goal, original, binding, _, text = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    accepted_lesson = tutor.submit_lesson(
        session.token, plan.id, str(uuid4()),
        LessonRequestInput(
            expected_plan_revision=1, node_key="iteration", instruction="Explain iteration.",
        ),
    )
    advance_consumer_materials(database, session, author_settings, goal.id)
    with database.transaction() as connection:
        bindings = MaterialBindings(connection).for_scope(
            session.actor, goal.id, "lesson", plan_id=plan.id, plan_revision=1,
            node_key="iteration",
        )
    gateway, _, _ = provider(
        author_settings, author=json.dumps(lesson_document(binding_citations(bindings))),
    )
    assert drain(
        tutor, author_settings, accepted_lesson, gateway, session.token,
    ).status == "accepted"
    old_lesson = next(
        lesson for lesson in workflow.snapshot(session.token).lessons if lesson.plan_id == plan.id
    )
    if getattr(request, "param", None) == "missing_lesson":
        text = text.model_copy(update={
            "purposes": [purpose for purpose in text.purposes if purpose != "lesson"],
        })
    candidate = revise(
        session, materials, text, original, ORIGINAL.replace("print(x)", "print(x + 1)"),
    )
    settings = replace(rag["settings"], model_enabled=True)
    changes = MaterialChangeWorkflow(database)
    report = changes.compare(session.token, str(uuid4()), change_input(binding, candidate))
    case = {
        "database": database,
        "settings": settings,
        "rag": rag,
        "materials": materials,
        "original": original,
        "candidate": candidate,
        "binding": binding,
        "changes": changes,
        "report": report,
        "reviews": MaterialChangeReviewWorkflow(database, settings),
        "updates": MaterialUpdateWorkflow(database, settings),
        "notifications": NotificationsWorkflow(database),
        "tutor": tutor,
        "author_settings": author_settings,
        "plan": plan,
        "old_lesson": old_lesson,
        "plan_document": consumer[7],
        "reprepare": MaterialRepreparationWorkflow(database, author_settings),
    }
    case["offer"] = ready_offer(case, session)
    try:
        yield case
    finally:
        with database.transaction() as connection:
            connection.execute(
                "UPDATE learning.material_repreparations SET state='cancelled' "
                "WHERE actor_id=%s AND state NOT IN ('ready','superseded','cancelled')",
                (session.actor.id,),
            )


def count_preparations(case, session):
    with case["database"].transaction(snapshot=True) as connection:
        return connection.execute(
            "SELECT count(*) AS n FROM learning.material_repreparations WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"]


def accept(case, session, *, key=None):
    return case["updates"].decide(
        session.token, case["offer"].id, key or str(uuid4()), decision_data(case, case["offer"]),
    )


def advance(case, session, decision):
    with case["database"].transaction() as connection:
        connection.execute(
            "UPDATE learning.material_repreparations SET next_action_at=now() "
            "WHERE actor_id=%s AND decision_id=%s",
            (session.actor.id, decision.id),
        )
    case["reprepare"].reconcile_once()
    return {
        row.kind: row for row in case["reprepare"].list(session.token, decision.id)
    }


def prepare_successor_plan(case, session, decision):
    rows = advance(case, session, decision)
    pending = rows["plan"]
    assert pending.state == "running" and pending.run_id and pending.delivery_task_id
    advance_consumer_materials(
        case["database"], session, case["author_settings"], case["plan"].goal_id,
    )
    successor = case["materials"].binding(
        session.token, decision.successor_binding_id, decision.successor_binding_revision,
    )
    document = deepcopy(case["plan_document"])
    document["summary"] = "Read the updated iteration expression."
    document["nodes"][0]["material_citations"] = [
        citation.model_dump(mode="json") for citation in binding_citations([successor])
    ]
    gateway, calls, _ = provider(case["author_settings"], author=json.dumps(document))
    assert drain(
        case["tutor"], case["author_settings"], pending, gateway, session.token,
    ).status == "accepted"
    rows = advance(case, session, decision)
    if rows["lesson"].state == "waiting_dependency":
        rows = advance(case, session, decision)
    assert rows["plan"].state == "ready" and rows["plan"].output_plan_revision == 2
    return rows, calls


def test_only_first_accept_enqueues_and_replay_or_read_never_repairs_missing_jobs(
    session, reprepare_case,
):
    case = reprepare_case
    assert count_preparations(case, session) == 0
    case["updates"].get(session.token, case["offer"].id)
    later = case["updates"].decide(
        session.token, case["offer"].id, str(uuid4()),
        decision_data(case, case["offer"], "decide_later"),
    )
    assert later.decision == "decide_later" and count_preparations(case, session) == 0
    key = str(uuid4())
    decision = accept(case, session, key=key)
    rows = case["reprepare"].list(session.token, decision.id)
    assert len(rows) == 2 and {row.kind for row in rows} == {"plan", "lesson"}
    assert all(row.state == "queued" and row.run_id is None for row in rows)
    assert accept(case, session, key=key) == decision
    assert case["reprepare"].list(session.token, decision.id) == rows
    with case["database"].transaction() as connection:
        connection.execute(
            "DELETE FROM learning.material_repreparations WHERE decision_id=%s",
            (decision.id,),
        )
    assert case["updates"].decision_receipt(session.token, case["offer"].id, key) == decision
    case["updates"].get(session.token, case["offer"].id)
    assert accept(case, session, key=key) == decision
    assert case["reprepare"].list(session.token, decision.id) == []
    assert count_preparations(case, session) == 0


def test_successor_route_requires_confirmation_before_exact_lesson_and_preserves_history(
    database, workflow, session, reprepare_case, review_setup,
):
    case = reprepare_case
    assert review_setup[1].track_id
    before = workflow.snapshot(session.token)
    assert before.attempts and before.attempts[0].status == "passed"
    with database.transaction(snapshot=True) as connection:
        old_plan = Plans(connection).get(session.actor, case["plan"].id)
    decision = accept(case, session)
    rows, calls = prepare_successor_plan(case, session, decision)
    assert len(calls) == 2
    assert rows["lesson"].state == "waiting_confirmation" and rows["lesson"].run_id is None
    with database.transaction(snapshot=True) as connection:
        current = Plans(connection).get(session.actor, case["plan"].id)
    assert current.latest.revision == 2 and current.active.revision == 1
    assert current.active == old_plan.active
    for _ in range(2):
        assert advance(case, session, decision)["lesson"].state == "waiting_confirmation"
    case["tutor"].confirm_plan(session.token, current.id, 2)
    rows = advance(case, session, decision)
    pending = rows["lesson"]
    assert pending.state == "running" and pending.run_id and pending.delivery_task_id
    advance_consumer_materials(database, session, case["author_settings"], case["plan"].goal_id)
    with database.transaction() as connection:
        bindings = MaterialBindings(connection).for_scope(
            session.actor, current.goal_id, "lesson", plan_id=current.id, plan_revision=2,
            node_key="iteration",
        )
    assert bindings and all(
        ref.document_revision == case["candidate"].revision
        for binding in bindings for ref in binding.refs
    )
    gateway, lesson_calls, _ = provider(
        case["author_settings"],
        author=json.dumps(lesson_document(binding_citations(bindings), updated=True)),
    )
    assert drain(
        case["tutor"], case["author_settings"], pending, gateway, session.token,
    ).status == "accepted"
    rows = advance(case, session, decision)
    assert rows["lesson"].state == "ready" and rows["lesson"].output_lesson_id
    assert len(lesson_calls) == 2
    after = workflow.snapshot(session.token)
    assert next(lesson for lesson in after.lessons
                if lesson.id == case["old_lesson"].id) == case["old_lesson"]
    new_lesson = next(
        lesson for lesson in after.lessons if lesson.id == rows["lesson"].output_lesson_id
    )
    assert new_lesson.plan_revision == 2 and new_lesson.node_key == "iteration"
    assert after.attempts == before.attempts and after.reviews == before.reviews
    assert after.node_progress == before.node_progress
    assert after.execution_progress == before.execution_progress
    assert count_preparations(case, session) == 2
    assert advance(case, session, decision) == rows


def test_unknown_original_repreparation_never_creates_a_second_run_or_provider_attempt(
    database, session, reprepare_case,
):
    case = reprepare_case
    decision = accept(case, session)
    rows = advance(case, session, decision)
    pending = rows["plan"]
    advance_consumer_materials(database, session, case["author_settings"], case["plan"].goal_id)
    sent = []

    def lost(request):
        sent.append(request)
        raise httpx.ReadTimeout("Owned original preparation receipt is unknown", request=request)

    loop = AgentLoop(
        case["tutor"],
        ChatCompletionsGateway(case["author_settings"], httpx.MockTransport(lost)),
    )
    loop.run(pending.run_id)
    assert case["tutor"].get(session.token, pending.run_id).status == "blocked_unknown"
    for _ in range(2):
        rows = advance(case, session, decision)
        loop.run(pending.run_id)
        assert rows["plan"].state == "waiting_receipt"
        assert rows["plan"].run_id == pending.run_id
        assert rows["plan"].delivery_task_id == pending.delivery_task_id
    assert len(sent) == 1
    with database.transaction() as connection:
        external = connection.execute(
            "SELECT status FROM runtime.external_calls WHERE run_id=%s", (pending.run_id,),
        ).fetchall()
        rows = connection.execute(
            "SELECT run_id FROM learning.material_repreparations WHERE decision_id=%s "
            "AND run_id IS NOT NULL", (decision.id,),
        ).fetchall()
    assert len(external) == 1 and external[0]["status"] == "unknown"
    assert [row["run_id"] for row in rows] == [pending.run_id]


@pytest.mark.parametrize("reprepare_case", ["revoke", "missing_lesson"], indirect=True)
def test_repreparation_waits_for_actual_permission_instead_of_bypassing_it(
    session, reprepare_case, request,
):
    case = reprepare_case
    decision = accept(case, session)
    if request.node.callspec.params["reprepare_case"] == "revoke":
        case["materials"].revoke(
            session.token, case["candidate"].document_id, case["candidate"].revision,
            DocumentPermissionAction(expected_revision=1, action="revoke"),
        )
        rows = advance(case, session, decision)
        assert rows["plan"].state == "waiting_dependency" and rows["plan"].reason
        assert all(row.run_id is None and row.delivery_task_id is None for row in rows.values())
    else:
        rows, _ = prepare_successor_plan(case, session, decision)
        case["tutor"].confirm_plan(session.token, case["plan"].id, 2)
        rows = advance(case, session, decision)
        assert rows["lesson"].state == "waiting_dependency" and rows["lesson"].reason
        assert rows["lesson"].run_id is None and rows["lesson"].delivery_task_id is None
