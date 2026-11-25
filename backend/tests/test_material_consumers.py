import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_material_lifecycle import material_setup as material_setup
from test_material_sources_and_goals import advance_consumer_materials, configure_goal_models
from test_teaching_delivery import drain, provider

from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.material_consumers import binding_citations
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.teaching_delivery import TeachingDelivery
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction, MaterialSpan
from leornian.modules.knowledge.materials import digest
from leornian.modules.learning.contracts import LessonRequestInput, LessonSection
from leornian.modules.learning.material_contracts import MaterialBindingInput, MaterialCitation
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.tutor.contracts import PlanningInput, TeachingFocus, TurnInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError


@pytest.fixture
def consumer(database, session, material_setup, request, monkeypatch):
    materials, goal, text = material_setup
    purposes = getattr(request, "param", True)
    if purposes:
        text = text.model_copy(update={
            "purposes": [*text.purposes, *(["lesson"] if purposes is True else purposes)]
        })
    version = materials.import_text(session.token, str(uuid4()), text)
    refs = [
        b.ref for b in materials.blocks(
            session.token, version.document_id, version.revision, "planning"
        ).blocks
    ]
    binding = materials.bind(
        session.token, str(uuid4()),
        MaterialBindingInput(
            goal_id=goal.id, purpose="planning", expected_binding_revision=0, refs=refs
        ),
    )
    settings = Settings(
        database_url=database.url, delivery_enabled=True, model_enabled=True,
        model_base_url="https://owned.invalid/v1", model_name="offline-owned",
        model_api_key="offline-consumer-fixture",
        model_context_tokens=128000, model_max_output_tokens=32768,
    )
    monkeypatch.setattr("leornian.platform.model_probes.resolve_destination", lambda *_: "1.1.1.1")
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    configure_goal_models(database, session, settings, material_roles=True)
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, goal.id)
    document = {
        "title": "Iteration", "summary": "Read and print a sequence.", "assumptions": [],
        "nodes": [{
            "key": "iteration", "title": "Iteration", "objective": "Iteration",
            "estimated_minutes": 30, "prerequisite_keys": [], "source_refs": [],
            "material_citations": [
                c.model_dump(mode="json") for c in binding_citations([binding])
            ],
        }],
    }
    return tutor, settings, conversation, materials, goal, version, binding, document, text


def draft(consumer, session):
    tutor, settings, conversation, _, _, _, _, document, _ = consumer
    accepted = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Teach iteration.", expected_revision=0),
    )
    advance_consumer_materials(tutor.database, session, settings, conversation.goal_id)
    gateway, sent, _ = provider(settings, author=json.dumps(document))
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    with tutor.database.transaction() as connection:
        from leornian.modules.learning.planning import Plans

        plan = Plans(connection).for_goal(session.actor, conversation.goal_id)
    return plan, accepted, sent


def test_plan_and_lesson_consume_exact_material_citations_with_automatic_demands(
    database, workflow, session, consumer
):
    tutor, settings, conversation, _, goal, _, planning_binding, _, _ = consumer
    plan, accepted, sent = draft(consumer, session)
    assert len(sent) == 2
    assert not plan.latest.sources
    assert plan.latest.document.nodes[0].material_citations == binding_citations([planning_binding])
    intake = MaterialIntakeWorkflow(database, settings)
    demands = intake.demands(session.token, goal.id)
    planning_demand = next(demand for demand in demands if demand.purpose == "planning")
    assert planning_demand.consumer_ref == (
        f"tutor-turn:{accepted.turn_id}:planning:semantic-goal.v1"
    )
    assert planning_demand.language is None
    assert planning_demand.scope_mode == "teaching_goal"
    assert planning_demand.required_facets == [] and planning_demand.goal_text == goal.title
    author_context = json.loads(sent[0]["messages"][1]["content"])
    assert author_context["material_demand"]["id"] == str(planning_demand.id)
    assert author_context["material_citations"] == [
        c.model_dump(mode="json") for c in binding_citations([planning_binding])
    ]
    tutor.confirm_plan(session.token, plan.id, 1)
    data = LessonRequestInput(
        expected_plan_revision=1, node_key="iteration", instruction="Explain iteration."
    )
    key = str(uuid4())
    lesson_turn = tutor.submit_lesson(session.token, plan.id, key, data)
    assert tutor.submit_lesson(session.token, plan.id, key, data) == lesson_turn
    advance_consumer_materials(database, session, settings, goal.id)
    with database.transaction() as connection:
        bindings = MaterialBindings(connection).for_scope(
            session.actor, goal.id, "lesson", plan_id=plan.id, plan_revision=1,
            node_key="iteration",
        )
    assert len(bindings) == 1 and bindings[0].id != planning_binding.id
    citations = binding_citations(bindings)
    assert all(c.purpose == "lesson" for c in citations)
    lesson = {
        "title": "Iteration", "introduction": "Read the sequence.",
        "sections": [{
            "heading": "Loop", "explanation": "The loop visits each item.",
            "code_example": "for x in items:\n    print(x)",
            "source_refs": [],
            "material_citations": [c.model_dump(mode="json") for c in citations],
        }],
        "recall_prompts": ["What does each loop iteration visit?"],
    }
    gateway, _, _ = provider(settings, author=json.dumps(lesson))
    assert drain(tutor, settings, lesson_turn, gateway, session.token).status == "accepted"
    saved = workflow.snapshot(session.token).lessons[0]
    assert saved.document.sections[0].material_citations == citations
    assert not saved.sources
    assert len([
        demand for demand in intake.demands(session.token, goal.id)
        if demand.scope_mode == "teaching_goal"
    ]) == 2
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1,
        node_key="iteration", lesson_id=saved.id,
    )
    turn = tutor.submit(
        session.token, conversation.id, str(uuid4()), TurnInput(text="Explain again.", focus=focus)
    )
    advance_consumer_materials(database, session, settings, goal.id)
    gateway, wires, _ = provider(settings)
    assert drain(tutor, settings, turn, gateway, session.token).status == "accepted"
    context = json.loads(
        wires[0]["messages"][1]["content"].removeprefix("Learning context (data): ")
    )
    assert context["node"]["selected_lesson"]["id"] == str(saved.id)
    citations = context["materials"]["material_citations"]
    assert citations and all(c["purpose"] == "teaching" for c in citations)


@pytest.mark.parametrize("field", ["binding", "revision", "purpose", "span", "digest"])
def test_qualified_plan_rejects_citations_outside_exact_supplied_binding(consumer, field):
    _, _, _, _, _, _, binding, document, _ = consumer
    citation = document["nodes"][0]["material_citations"][0]
    if field == "binding":
        citation["binding_id"] = str(uuid4())
    elif field == "revision":
        citation["binding_revision"] += 1
    elif field == "purpose":
        citation["purpose"] = "lesson"
    elif field == "span":
        citation["ref"]["span"]["end"] += 1
    else:
        citation["ref"]["content_digest"] = "0" * 64
    task = {
        "kind": "planning", "fragments": [],
        "context_manifest": {
            "material_bindings": [{
                "id": str(binding.id), "revision": binding.revision, "purpose": binding.purpose,
                "refs": [r.model_dump(mode="json") for r in binding.refs],
            }]
        },
    }
    with pytest.raises(ValueError, match="unsupported"):
        TeachingDelivery.candidate(task, json.dumps(document))


def test_revocation_between_candidate_and_acceptance_cannot_create_plan(
    database, session, consumer
):
    tutor, settings, conversation, materials, _, version, _, document, _ = consumer
    turn = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Teach iteration.", expected_revision=0),
    )
    advance_consumer_materials(database, session, settings, conversation.goal_id)
    gateway, sent, _ = provider(settings, author=json.dumps(document))
    AgentLoop(tutor, gateway).run(turn.run_id)
    assert tutor.delivery_task(session.token, turn.delivery_task_id).status == "checking"
    materials.revoke(
        session.token, version.document_id, 1,
        DocumentPermissionAction(expected_revision=1, action="revoke"),
    )
    AgentLoop(tutor, gateway).run(turn.run_id)
    assert len(sent) == 1
    with database.transaction() as connection:
        from leornian.modules.learning.planning import Plans

        assert Plans(connection).for_goal(session.actor, conversation.goal_id) is None


@pytest.mark.parametrize("consumer", [False], indirect=True)
def test_plan_permission_does_not_authorize_lesson_materials(session, consumer):
    tutor, _, _, materials, _, version, _, _, _ = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    with pytest.raises(BusinessError, match="not allowed"):
        tutor.submit_lesson(
            session.token, plan.id, str(uuid4()),
            LessonRequestInput(
                expected_plan_revision=1, node_key="iteration", instruction="Explain iteration."
            ),
        )
    assert materials.version(session.token, version.document_id, 1).revision == 1


def test_new_document_head_does_not_retarget_accepted_plan(session, consumer):
    tutor, _, _, materials, _, version, binding, _, text = consumer
    plan, _, _ = draft(consumer, session)
    materials.import_text(
        session.token, str(uuid4()),
        text.model_copy(update={
            "document_id": version.document_id, "expected_revision": 1,
            "text": "# New iteration\n\nCompletely different text.",
        }),
    )
    confirmed = tutor.confirm_plan(session.token, plan.id, 1)
    assert confirmed.active.document.nodes[0].material_citations == binding_citations([binding])
    assert all(
        c.ref.document_revision == 1 for c in confirmed.active.document.nodes[0].material_citations
    )


def test_lesson_sections_still_require_real_citations():
    with pytest.raises(ValidationError, match="needs an exact"):
        LessonSection(
            heading="Unsupported", explanation="An invented claim.",
            code_example="", source_refs=[],
        )
    with pytest.raises(ValidationError):
        MaterialCitation(
            binding_id=uuid4(), binding_revision=0, purpose="lesson", ref={}
        )


def test_distinct_exact_ranges_of_one_block_can_be_bound(session, material_setup):
    materials, goal, text = material_setup
    original = "abcde " * 600
    version = materials.import_text(
        session.token, str(uuid4()), text.model_copy(update={"format": "text", "text": original})
    )
    block = materials.blocks(session.token, version.document_id, 1, "planning").blocks[0]
    refs = [
        block.ref.model_copy(update={
            "span": MaterialSpan(start=start, end=end),
            "content_digest": digest(original[start:end]),
        })
        for start, end in ((0, 1200), (1200, 2400))
    ]
    binding = materials.bind(
        session.token, str(uuid4()), MaterialBindingInput(
            goal_id=goal.id, purpose="planning", expected_binding_revision=0, refs=refs
        )
    )
    assert [b.text for b in materials.bound_blocks(session.token, binding.id, 1).blocks] == [
        original[:1200], original[1200:2400],
    ]
    with pytest.raises(ValidationError, match="Repeated"):
        MaterialBindingInput(
            goal_id=goal.id, purpose="planning", expected_binding_revision=0, refs=[refs[0]] * 2
        )
