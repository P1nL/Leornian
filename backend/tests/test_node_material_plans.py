import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_automatic_material_discovery import automatic as automatic
from test_material_consumers import consumer as consumer
from test_material_consumers import draft
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import rag as rag
from test_material_sources_and_goals import advance_consumer_materials
from test_route_curriculum import curriculum_consumer as curriculum_consumer
from test_teaching_delivery import drain, provider

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_consumers import (
    ensure_consumer_material_in,
    prepare_consumer_in,
)
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.material_goal_coverage import MaterialGoalCoverageWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.material_web import MaterialWebWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.node_turn_context import CONTEXT_PREFIX
from leornian.bootstrap.planning_materials import PlanningMaterials
from leornian.bootstrap.teaching_context import TeachingContext
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput, MaterialTextJobInput
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.knowledge.source_candidates import ranked_candidates
from leornian.modules.knowledge.source_contracts import MaterialSourceInput
from leornian.modules.learning.contracts import PlanDocument
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.contracts import TeachingFocus, TurnInput
from leornian.platform.material_search_configuration import TavilyConfigurationInput
from leornian.shared_kernel.errors import BusinessError


def test_pending_material_plans_keep_only_node_technologies_and_no_invented_sources():
    profiles = (("Python", "Flask"), ("Java", "Spring Boot"), ("TypeScript", "Vue 3"))
    for language, framework in profiles:
        document = PlanDocument(
            title="A continuing project", summary="Basics before the framework.", assumptions=[],
            curriculum={
                "basis": "model_knowledge",
                "technologies": [{"name": language, "version": "1.2.3"},
                                 {"name": framework, "version": "4.5.6"}],
                "texts": [], "project": {"title": "Organizer", "outcome": "Organize entries."},
            },
            nodes=[{
                "key": "first_program", "title": f"First {language} program",
                "objective": "Write a minimal program and inspect its output.",
                "estimated_minutes": 30,
            }],
        )
        node = document.nodes[0]
        assert node.material_plan is None
        preparation = Plans.node_material_plan(document, node)
        assert preparation["technologies"] == [{"name": language, "version": "1.2.3"}]
        assert preparation["topics"] == [node.objective] and preparation["readings"] == []
        assert PlanDocument.model_validate_json(document.model_dump_json()) == document
        snapshot = {
            **document.curriculum.model_dump(mode="json"),
            "node_chapters": [{"material_plan": preparation}],
        }
        scope = MaterialDiscoveryWorkflow.node_frameworks(snapshot)
        assert MaterialDiscoveryWorkflow.source_matches_node(
            scope, title=f"{language} handbook", topics=[language],
        )
        assert not MaterialDiscoveryWorkflow.source_matches_node(
            scope, title=f"{framework} guide", topics=[framework],
        )
    reading = {
        "id": "selected-reference", "title": "TypeScript reference in a framework guide",
        "url": "https://guide.invalid/typescript", "origin": "official",
        "languages": ["typescript"], "frameworks": ["vue"], "topics": ["typescript"],
        "locales": ["en"],
    }
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="teaching", scope_mode="teaching_goal",
        language="typescript", goal_text="A minimal typed program",
    )
    candidates = ranked_candidates(
        demand, demand.goal_text, extra=[reading], deferred_frameworks=["vue"],
    )
    assert all(entry["id"] != reading["id"] for entry in candidates)
    assert ranked_candidates(
        demand, demand.goal_text, extra=[reading], deferred_frameworks=["vue"],
        preferred_urls=[reading["url"]],
    )[0]["id"] == reading["id"]
    role = MaterialGoalCoverageWorkflow.make_role(
        "Run a first program in the workbench", [], purpose="teaching", node_preparation=True,
    )
    assert "do not demand that a public textbook document Leornian" in role.messages[0]["content"]
    assert "necessary conditions and usable examples" in role.messages[0]["content"]


def test_scoped_planning_previews_candidates_without_starting_source_work(
    database, session, automatic,
):
    _settings, goal, _demand, _discovery = automatic
    with database.transaction() as connection:
        candidates = PlanningMaterials.reading_sources_in(connection, session.actor, goal.id)
        assert 0 < len(candidates) <= 12
        assert all(item["basis"] == "catalog_candidate" for item in candidates)
        assert not MaterialSources(connection).list(session.actor, goal.id)
        assert connection.execute(
            "SELECT count(*) n FROM runtime.external_calls WHERE actor_id=%s", (session.actor.id,),
        ).fetchone()["n"] == 0


def test_observed_reading_can_be_planned_before_its_body_is_prepared(
    database, session, curriculum_consumer,
):
    tutor, settings, conversation, _materials, goal, _version, _binding, original, _text = (
        curriculum_consumer
    )
    with database.transaction() as connection:
        sources = MaterialSources(connection)
        source = sources.register(
            session.actor, Identity.digest(session.token), str(uuid4()),
            MaterialSourceInput(
                goal_id=goal.id, title="Sequence handbook", entry_url="https://guide.invalid/",
                allowed_prefixes=["https://guide.invalid/"], authorized_use=True,
                purposes=["planning", "teaching", "indexing"],
            ),
        )
        sources.schedule(session.actor, source.id, Identity.digest(session.token), str(uuid4()))
        sources.add_resource(
            source.id, "https://guide.invalid/iteration", depth=1, label="Iteration",
        )
    document = deepcopy(original)
    document["nodes"][0]["material_plan"] = {
        "topics": ["Iteration"], "technologies": ["Python"],
        "readings": [{"title": "Iteration", "source_url": "https://guide.invalid/iteration"}],
    }
    updated = (*curriculum_consumer[:7], document, curriculum_consumer[8])
    plan, _, _ = draft(updated, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="iteration",
    )
    with database.transaction() as connection:
        PlanningMaterials.validate_route_in(
            connection, session.actor, goal.id, plan.latest.document,
        )
        demand = prepare_consumer_in(
            connection, session.actor, conversation, SimpleNamespace(id=uuid4()),
            "teaching", focus, session_digest=Identity.digest(session.token),
        )
        preferred = MaterialDiscoveryWorkflow.curriculum_resources_in(
            connection, session.actor, demand,
        )
        assert preferred["https://guide.invalid/iteration"] == source.id
        assert connection.execute(
            "SELECT count(*) n FROM knowledge.source_observations "
            "WHERE source_id=%s AND job_id IS NOT NULL", (source.id,),
        ).fetchone()["n"] == 0
    advance_consumer_materials(database, session, settings, goal.id)
    with database.transaction() as connection:
        context, _manifest = TeachingContext.build(
            connection, session.actor, conversation, focus, material_demand=demand,
            session_digest=Identity.digest(session.token),
        )
        assert context["node_material_plan"]["topics"] == ["Iteration"]
        assert "material_plan" not in context["confirmed_node"]


def test_node_followup_reuses_the_prepared_demand_and_coverage(
    database, session, curriculum_consumer,
):
    tutor, settings, conversation, _materials, goal, *_ = curriculum_consumer
    plan, _, _ = draft(curriculum_consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="iteration",
    )
    with database.transaction() as connection:
        first = prepare_consumer_in(
            connection, session.actor, conversation, SimpleNamespace(id=uuid4()),
            "teaching", focus, session_digest=Identity.digest(session.token),
        )
    advance_consumer_materials(database, session, settings, goal.id)
    with database.transaction() as connection:
        original = ensure_consumer_material_in(
            connection, session.actor, Identity.digest(session.token), first,
        )
        second = prepare_consumer_in(
            connection, session.actor, conversation, SimpleNamespace(id=uuid4()),
            "teaching", focus, session_digest=Identity.digest(session.token),
        )
        assert second.id == first.id
        assert ensure_consumer_material_in(
            connection, session.actor, Identity.digest(session.token), second,
        ).id == original.id
        assert connection.execute(
            "SELECT count(*) n FROM knowledge.material_discovery_jobs WHERE demand_id=%s",
            (first.id,),
        ).fetchone()["n"] == 1


def test_node_requests_keep_stable_prefixes_across_questions_and_search_states(
    database, session, consumer,
):
    tutor, settings, conversation, _, goal, *_ = consumer
    plan, _, _ = draft(consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    focus = TeachingFocus(kind="node", plan_id=plan.id, expected_plan_revision=1,
                          node_key="iteration")
    questions = ["循环先取哪一项？", "接着取哪一项？", "可以提前结束吗？"]
    authors, reviews = [], []
    for question in questions:
        turn = tutor.submit(session.token, conversation.id, str(uuid4()),
                            TurnInput(text=question, focus=focus))
        if question == questions[0]:
            with database.transaction() as connection:
                demand = tutor._material_demand(connection, session.actor, turn.turn_id, "teaching")
                job = MaterialSources(connection).discovery(session.actor, demand.id)
                assert job.status == "ready" and job.selection_id is None
                assert not connection.execute(
                    "SELECT 1 FROM knowledge.material_searches WHERE request->>'demand_id'=%s",
                    (str(demand.id),),
                ).fetchone()
        elif question == questions[-1]:
            with database.transaction() as connection:
                demand = tutor._material_demand(connection, session.actor, turn.turn_id, "teaching")
                discovery = MaterialSources(connection).discovery(session.actor, demand.id)
                MaterialDiscoveryWorkflow.transition(
                    connection, discovery.id, "waiting_dependency", "material_discovery_exhausted",
                    missing=[question],
                )
        gateway, sent, _ = provider(settings, author="循环依次取出列表中的名字。")
        assert drain(tutor, settings, turn, gateway, session.token).status == "accepted"
        author, reviewer = sent
        authors.append(author["messages"])
        raw = reviewer["messages"][-1]["content"]
        reviews.append(raw)
        payload = json.loads(raw)
        evidence = payload["turn_evidence"]
        assert list(payload)[-2:] == ["candidate", "candidate_call_id"]
        assert list(evidence)[-2:] == ["learner_messages", "origin"]
        assert evidence["learner_messages"] == [question]
        assert evidence["origin"]["turn_id"] == str(turn.turn_id)

    assert authors[0][0] == authors[1][0] == authors[2][0]
    materials = [json.loads(messages[1]["content"].removeprefix(CONTEXT_PREFIX))["materials"]
                 for messages in authors]
    assert "material_preparation" not in materials[0]
    assert materials[2]["material_preparation"]["status"] == "search_exhausted"
    initial = json.loads(reviews[0])["turn_evidence"]
    assert initial["materials"]["bound_materials"]
    stable = {key: initial[key] for key in ("materials", "node")}
    prefix = '"turn_evidence":' + json.dumps(stable, ensure_ascii=False, separators=(",", ":"))[:-1]
    before, marker, _ = reviews[0].partition(prefix + ",")
    assert marker and reviews[1].startswith(before + marker)


@pytest.mark.parametrize("supply", ["partial_reading", "checked_excerpt", "bound_book",
                                   "no_excerpt"])
def test_node_teaches_with_available_material_or_an_original_example(
    database, session, request, supply,
):
    fixture = "consumer" if supply == "bound_book" else "curriculum_consumer"
    course = request.getfixturevalue(fixture)
    tutor, settings, conversation, materials, _goal, book, *_ = course
    plan, _, _ = draft(course, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    focus = TeachingFocus(kind="node", plan_id=plan.id, expected_plan_revision=1,
                          node_key="iteration")
    question = "能举个遍历的例子吗？"
    turn = tutor.submit(session.token, conversation.id, str(uuid4()),
                        TurnInput(text=question, focus=focus))
    reply = "比如遍历两个名字，循环每次取出一个名字。"
    gateway, requests, _ = provider(settings, author=reply)
    checked = supply in {"checked_excerpt", "partial_reading"}
    if checked:
        assert drain(tutor, settings, turn, gateway, session.token).status == "waiting_dependency"
        assert not requests
    digest = Identity.digest(session.token)
    blocks = materials.blocks(session.token, book.document_id, book.revision, "teaching").blocks
    code = next(block for block in blocks if block.kind == "code")
    gap = "Early loop termination"
    with database.transaction() as connection:
        demand = tutor._material_demand(connection, session.actor, turn.turn_id, "teaching")
        sources = MaterialSources(connection)
        discovery = sources.discovery(session.actor, demand.id)
        if checked:
            data = MaterialSearchInput(
                demand_id=demand.id, expected_demand_revision=demand.revision,
                query="Iteration", mode="lexical", required_refs=[block.ref for block in blocks],
            )
            search = MaterialSearchWorkflow.submit_in(
                connection, session.actor, digest, f"semantic-material-discovery:{discovery.id}:p",
                data,
            )
            sources.attach_search(session.actor, discovery.id, search.id)
            MaterialGoalCoverageWorkflow.finish(connection, session.actor, {
                "id": search.id, "request": MaterialSearchWorkflow.request(data),
                "scope": {"node_checklist": ["Iteration", gap], "node_carried": {}},
            }, demand, {"id": uuid4(), "result": {
                "status": "partial", "summary": "The loop visits each item.",
                "evidence_refs": [block.ref for block in blocks],
                "topic_evidence": {"Iteration": [code.ref]}, "missing_topics": [gap],
            }})
        elif supply == "bound_book":
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
                (Jsonb({"excluded_findings": [{"issue": "incorrect", "explanation": "Bad table",
                        "refs": [blocks[-1].ref.model_dump(mode="json")]}]}), discovery.id),
            )
        if supply != "partial_reading":
            MaterialDiscoveryWorkflow.transition(connection, discovery.id, "waiting_dependency",
                                                 "material_discovery_exhausted", missing=[gap])
            with pytest.raises(BusinessError) as strict:
                ensure_consumer_material_in(connection, session.actor, digest, demand)
            assert strict.value.code == "material_discovery_exhausted"

    if supply == "partial_reading":
        MaterialDiscoveryWorkflow(database, settings).execute_semantic(discovery.id)
    if checked:
        tutor.reconcile_deliveries()
    assert drain(tutor, settings, turn, gateway, session.token).status == "accepted"
    history = tutor.turn_history(session.token, conversation.id)
    assert next(item for item in history if item.id == turn.turn_id).assistant_text == reply
    author, reviewer = requests
    facts = json.loads(author["messages"][1]["content"].removeprefix(CONTEXT_PREFIX))
    assert "an example you design" in author["messages"][0]["content"]
    if supply == "partial_reading":
        assert facts["materials"]["material_goal_coverage"]["status"] == "partial"
    else:
        preparation = facts["materials"]["material_preparation"]
        assert preparation["status"] == "search_exhausted" and gap in preparation["reason"]
    cited = facts["materials"].get("material_citations", [])
    if checked:
        assert [entry["ref"]["block_id"] for entry in cited] == [str(code.ref.block_id)]
        assert facts["materials"]["bound_materials"][0]["blocks"][0]["text"] == code.text
    elif supply == "bound_book":
        assert {entry["ref"]["block_id"] for entry in cited} == {
            str(block.ref.block_id) for block in blocks[:-1]
        }
    else:
        assert not cited and not facts["materials"].get("bound_materials")
    review = json.loads(reviewer["messages"][-1]["content"])["turn_evidence"]
    assert review["learner_messages"] == [question]
    assert review["materials"].get("material_citations", []) == cited
    with database.transaction() as connection:
        after = MaterialSources(connection).discovery(session.actor, demand.id)
        assert after.id == discovery.id
        if supply == "partial_reading":
            assert after.status == "ready" and after.error_code is None
            assert not connection.execute(
                "SELECT 1 FROM knowledge.material_web_requests WHERE discovery_id=%s",
                (after.id,),
            ).fetchone()
        else:
            assert after.error_code == "material_discovery_exhausted"
        assert after.missing_facets == [gap]


@pytest.mark.parametrize("shared", [False, True])
def test_stop_teaching_stops_owned_preparation_and_preserves_shared_work_and_unknown(
    database, session, curriculum_consumer, shared,
):
    tutor, settings, conversation, _, goal, _, _, _, text = curriculum_consumer
    plan, _, _ = draft(curriculum_consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="iteration",
    )
    turn = tutor.submit(
        session.token, conversation.id, str(uuid4()),
        TurnInput(text="Start the node.", focus=focus),
    )
    ModelConfigurationWorkflow(database, settings).save_tavily(
        session.token, TavilyConfigurationInput(
            expected_revision=0, enabled=True, api_key="offline-node-materials",
        ),
    )
    digest = Identity.digest(session.token)
    with database.transaction() as connection:
        intake = MaterialIntake(connection)
        sources, runs = MaterialSources(connection), Runs(connection)
        demand = TutorWorkflow._material_demand(connection, session.actor, turn.turn_id, "teaching")
        discovery = sources.discovery(session.actor, demand.id)
        source = sources.register(
            session.actor, digest, str(uuid4()), MaterialSourceInput(
                goal_id=goal.id, title="Supplement", entry_url="https://guide.invalid/iteration",
                allowed_prefixes=["https://guide.invalid/"], authorized_use=True,
                purposes=["teaching", "indexing"],
            ),
        )
        resource = connection.execute(
            "SELECT id FROM knowledge.material_source_resources WHERE source_id=%s", (source.id,),
        ).fetchone()["id"]
        observation = sources.schedule(
            session.actor, source.id, digest,
            f"discovery:{discovery.id}:shallow-v1:{resource}", resource_id=resource,
        )
        index_demand = intake.ensure_consumer_demand(
            session.actor, str(uuid4()),
            MaterialDemandInput(goal_id=goal.id, purpose="indexing", scope_mode="whole_source"),
        )
        job = intake.submit_text(
            session.actor, digest, index_demand.id, str(uuid4()),
            MaterialTextJobInput(expected_demand_revision=1, material=text),
        )
        connection.execute(
            "UPDATE knowledge.source_observations SET job_id=%s WHERE id=%s",
            (job.id, observation.id),
        )
        if shared:
            other = intake.ensure_consumer_demand(
                session.actor, str(uuid4()), MaterialDemandInput(
                    goal_id=goal.id, purpose="teaching", scope_mode="teaching_goal",
                    goal_text="A separate active lesson",
                ),
            )
            other_discovery = sources.ensure_discovery(session.actor, digest, other)
            assert sources.schedule(
                session.actor, source.id, digest,
                f"discovery:{other_discovery.id}:shallow-v1:{resource}", resource_id=resource,
            ).id == observation.id
        operation = MaterialWebWorkflow.prepare(
            connection, session.actor, settings, "search", {"query": "Iteration"},
            discovery=discovery.id,
        )
        call = runs.operation(operation)
        assert runs.dispatch(call.id)
        ready_jobs = connection.execute(
            "SELECT count(*) n FROM knowledge.material_jobs WHERE actor_id=%s AND state='ready'",
            (session.actor.id,),
        ).fetchone()["n"]
    tutor.cancel(session.token, turn.run_id)
    with database.transaction() as connection:
        intake = MaterialIntake(connection)
        sources, runs = MaterialSources(connection), Runs(connection)
        assert sources.discovery(session.actor, demand.id).status == "cancelled"
        assert intake.demand(session.actor, demand.id).status == "cancelled"
        assert intake.job(session.actor, job.id).state == ("queued" if shared else "cancelled")
        assert sources.observation(session.actor, observation.id).status == (
            "queued" if shared else "cancelled"
        )
        assert runs.operation(operation).status == "unknown"
        assert connection.execute(
            "SELECT count(*) n FROM knowledge.material_jobs WHERE actor_id=%s AND state='ready'",
            (session.actor.id,),
        ).fetchone()["n"] == ready_jobs
