import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_material_consumers import consumer as consumer
from test_material_consumers import draft
from test_material_files import pdf_bytes
from test_material_lifecycle import material_setup as material_setup
from test_material_sources_and_goals import (
    advance_consumer_materials,
    goal_gateway,
    material_transport,
)

from leornian.bootstrap.item_supply import ItemSupply
from leornian.bootstrap.material_acquisition import MaterialAcquisition
from leornian.bootstrap.material_consumers import (
    binding_citations,
    ensure_consumer_material_in,
    prepare_consumer_in,
)
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.material_files import MaterialFilesWorkflow
from leornian.bootstrap.material_goal_coverage import (
    GoalVerdictProtocolError,
    MaterialGoalCoverageWorkflow,
    parse_goal_verdict,
    planning_evidence_rows,
    prior_source_quality,
    usable_planning_evidence,
    validate_goal_verdict,
)
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.planning_materials import PlanningMaterials
from leornian.bootstrap.route_discussion import RouteDiscussionReply
from leornian.modules.identity.application import Identity
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import PackRequest
from leornian.modules.knowledge.file_contracts import (
    FileMaterialInput,
    MaterialFileJobInput,
    MaterialUploadInput,
)
from leornian.modules.knowledge.goal_coverage_contracts import (
    MaterialGoalFinding,
    MaterialGoalVerdict,
)
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.retrieval import Retrieval
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.knowledge.source_candidates import material_matches_gaps, ranked_candidates
from leornian.modules.knowledge.stage_sections import (
    StageSections,
    example_excerpts,
    guide_chapters,
    map_stage_sections,
    shared_readings,
)
from leornian.modules.learning.contracts import PlanDocument
from leornian.modules.learning.material_contracts import MaterialBindingInput, MaterialCitation
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.learning.planning import Plans
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.shared_kernel.errors import BusinessError


def curriculum_document(citation, *, source_url="https://book.invalid/guide/", document_id=None):
    chapter = {"text_key": "guide", "title": "Iteration", "source_url": source_url}
    if document_id:
        chapter["document_id"] = str(document_id)
    return PlanDocument(
        title="Iteration", summary="Read sequences, then extend the same organizer.",
        assumptions=[],
        curriculum={
            "technologies": [{"name": "Python", "version": None}],
            "texts": [{
                "key": "guide", "title": "The sequence guide", "role": "primary",
                "source_url": source_url, "material_citations": [citation],
            }],
            "project": {
                "title": "File organizer", "outcome": "Print intended moves before changing files.",
                "conventions": ["Use pathlib and keep a dry-run mode."],
            },
        },
        nodes=[{
            "key": "iteration", "title": "Iteration", "objective": "Iteration",
            "estimated_minutes": 30, "material_citations": [citation],
            "curriculum_chapters": [chapter], "project_milestone": "List the input files.",
        }],
    )


def exact_citation():
    return MaterialCitation(
        binding_id=uuid4(), binding_revision=1, purpose="planning",
        ref={
            "document_id": uuid4(), "document_revision": 1, "block_id": uuid4(),
            "span": {"start": 0, "end": 10}, "content_digest": "a" * 64,
        },
    )


def test_clean_ranges_must_stay_inside_each_exact_frozen_version():
    selected, other = exact_citation().ref, exact_citation().ref
    fields = dict(demand_id=uuid4(), expected_demand_revision=1, query="types", mode="lexical",
                  source_versions=[{"document_id": selected.document_id, "document_revision": 1}])
    assert MaterialSearchInput(**fields, required_refs=[selected]).required_refs == [selected]
    for mismatch in (other, selected.model_copy(update={"document_revision": 2})):
        with pytest.raises(ValidationError, match="outside the frozen"):
            MaterialSearchInput(**fields, required_refs=[selected, mismatch])


def test_clean_search_does_not_borrow_ranges_from_a_lexical_only_document(monkeypatch):
    selected, still_indexing = exact_citation().ref, exact_citation().ref
    workflow = MaterialDiscoveryWorkflow(None, None)
    builds = [
        {"id": uuid4(), "document_id": ref.document_id, "document_revision": 1, "space": space}
        for ref, space in ((selected, {"mode": "lexical"}), (selected, {"provider": "test"}),
                           (still_indexing, {"mode": "lexical"}))
    ]
    demand = SimpleNamespace(id=uuid4(), goal_id=uuid4(), plan_id=uuid4(), plan_revision=1,
                             revision=1, node_key="types", purpose="teaching", goal_text="Types",
                             consumer_ref="node-material:test", preparation="complete")
    monkeypatch.setattr(workflow, "available_builds", lambda *_: builds)
    monkeypatch.setattr(workflow, "curriculum_in", lambda *_, **kw: None)
    monkeypatch.setattr(MaterialBindings, "for_scope", lambda *_, **kw: [])
    monkeypatch.setattr(MaterialIntake, "pending_goal_uploads", lambda *_: [])
    monkeypatch.setattr(Retrieval, "reuse_goal_selection", lambda *_, **kw: None)

    def remaining(_retrieval, chosen, _findings, **_options):
        return [ref for ref in [selected, still_indexing]
                if any(build["document_id"] == ref.document_id for build in chosen)]

    monkeypatch.setattr(Retrieval, "unaffected_refs", remaining)
    finding = MaterialGoalFinding(issue="incorrect", scope="refs", refs=[exact_citation().ref],
                                  explanation="Retain the known defect")
    row = {"search_id": None, "acquisition_state": {"excluded_findings": [finding.model_dump()]}}
    request = workflow.semantic_input(None, SimpleNamespace(id=uuid4()), row, demand)
    assert [item.document_id for item in request.source_versions] == [selected.document_id]
    assert request.required_refs == [selected]
    builds.append({**builds[-1], "id": uuid4(), "space": {"provider": "test"}})
    later = workflow.semantic_input(None, SimpleNamespace(id=uuid4()), row, demand)
    assert {ref.document_id for ref in later.required_refs} == {
        selected.document_id, still_indexing.document_id,
    }


def test_material_stages_use_explicit_boundaries_or_old_project_milestones():
    raw = curriculum_document(exact_citation()).model_dump(mode="json")
    first = raw["nodes"][0]
    raw["nodes"] = [
        {**first, "key": key, "project_milestone": milestone}
        for key, milestone in (("types", None), ("arrays", "first project"), ("ui", None))
    ]
    route = PlanDocument(**raw)
    assert [node.key for node in Plans.material_stage(route, "arrays")] == ["types", "arrays"]
    assert [node.key for node in Plans.material_stage(route, "ui")] == ["ui"]
    for node, stage in zip(raw["nodes"], ["basics", "project", "project"], strict=True):
        node["material_plan"] = {"stage_key": stage}
    route = PlanDocument(**raw)
    assert [node.key for node in Plans.material_stage(route, "arrays")] == ["arrays", "ui"]


def test_stage_maps_different_sections_and_shares_only_compatible_readings():
    tech = [{"name": "TypeScript"}]
    guide = {"title": "Guide", "source_url": "https://book.invalid/guide/"}
    nodes = [
        {"key": key, "title": topic, "topics": [topic], "readings": [], "technologies": tech}
        for key, topic in (("types", "annotations"), ("arrays", "arrays"), ("ui", "props"))
    ]
    nodes[1]["readings"] = [guide]
    nodes[2].update(technologies=[{"name": "Vue"}], readings=[{**guide, "source_url": "vue"}])
    rows = [{"id": uuid4(), "document_id": uuid4(), "source_url": guide["source_url"],
             "text": word, "section_path": [word]} for word in ("annotations", "arrays", "props")]
    mapped = map_stage_sections(rows, nodes)
    assert mapped == {node["key"]: [str(row["id"])] for node, row in zip(nodes, rows, strict=True)}
    assert shared_readings({"nodes": nodes}, nodes[0]) == {guide["source_url"]}


def test_named_guide_targets_observed_chapters_and_preserves_document_boundaries():
    resources = [
        {"url": f"https://book.invalid/{slug}", "link_label": label,
         "depth": 1, "link_order": order}
        for order, (slug, label) in enumerate((
            ("intro", "Introduction"), ("list", "列表渲染"), ("events", "事件处理"),
            ("props", "Props"),
        ))
    ]
    assert guide_chapters(resources, ["v-for 列表渲染", "事件处理"], []) == (
        "https://book.invalid/list", "https://book.invalid/events",
    )
    assert not guide_chapters(resources, ["SQL transactions"], [])
    rows = [{"id": uuid4(), "ordinal": 0, "document_id": uuid4(), "source_url": item["url"],
             "text": item["link_label"], "section_path": []} for item in resources]
    node = {"key": "props", "title": "Props", "topics": ["Props"],
            "technologies": [], "readings": []}
    assert map_stage_sections(rows, [node])["props"] == [str(rows[-1]["id"])]


def test_direct_chapter_beats_neighboring_chapters_with_partial_title_matches():
    pages = [
        {"url": f"https://book.invalid/guide/{slug}.html", "link_label": label,
         "depth": 1, "link_order": order}
        for order, (slug, label) in enumerate((
            ("forms", "表单输入绑定"), ("custom-directives", "自定义指令"), ("props", "Props"),
            ("events", "事件"),
        ))
    ]
    assert guide_chapters(pages, ["props 类型与默认值", "emit 自定义事件",
                                  "拆出条目组件与输入组件"], []) == (
        pages[2]["url"], pages[3]["url"],
    )


def test_node_packet_requires_exact_evidence_for_every_supported_checklist_item():
    ref = exact_citation().ref
    data = {
        "status": "supported", "summary": "The two chapters show both behaviors.",
        "evidence_refs": ["ref_1"], "reviewed_refs": ["ref_1"],
        "topic_evidence": {"declare": ["ref_1"], "listen": ["ref_1"]},
    }
    topics = ["declare", "listen"]
    validate_goal_verdict(parse_goal_verdict(json.dumps(data), [ref]), [ref], node_topics=topics)
    data["topic_evidence"].pop("listen")
    with pytest.raises(GoalVerdictProtocolError, match="invalid_material_goal_output"):
        validate_goal_verdict(
            parse_goal_verdict(json.dumps(data), [ref]), [ref], node_topics=topics,
        )
    data.update(status="partial", missing_topics=["listen"])
    validate_goal_verdict(parse_goal_verdict(json.dumps(data), [ref]), [ref], node_topics=topics)
    data.update(issues=["incorrect"])
    with pytest.raises(GoalVerdictProtocolError):
        validate_goal_verdict(
            parse_goal_verdict(json.dumps(data), [ref]), [ref], node_topics=topics,
        )


def test_node_supplement_keeps_only_live_proven_refs_and_checks_only_the_gap(monkeypatch):
    supported, new, revoked = (exact_citation().ref for _ in range(3))
    demand = SimpleNamespace(node_key="node", id=uuid4(), revision=1)
    state = {"id": uuid4(), "acquisition_state": {}, "search_id": uuid4()}
    topics = ["declaration", "listener", "previously revoked"]
    stage = {"nodes": [{"key": "node", "title": "events", "topics": topics}]}
    builds = [{"document_id": ref.document_id, "document_revision": 1} for ref in (supported, new)]
    original = {"scope": {"node_checklist": topics},
                "request": {"required_refs": [supported.model_dump(mode="json")]}}
    selection = SimpleNamespace(id=uuid4(), coverage=SimpleNamespace(
        missing_facets=["listener"], required=[
            SimpleNamespace(facet=topic, status="supported", evidence=[ref])
            for topic, ref in ((topics[0], supported), (topics[2], revoked))
        ],
    ))
    observations = []

    def chunks(_self, *args, topics, reviewed):
        observations.append((topics, reviewed))
        return [str(new.block_id)]

    monkeypatch.setattr(StageSections, "chunks", chunks)
    monkeypatch.setattr(Retrieval, "unaffected_refs", lambda *args, **kwargs: [new])
    workflow = MaterialDiscoveryWorkflow(None, None)
    connection = SimpleNamespace(execute=lambda *_: None)
    def next_packet():
        return workflow.node_packet(connection, None, state, demand, stage, builds, original,
                                    selection)

    request = next_packet()
    assert observations == [([topics[1], topics[2]], {str(supported.block_id)})]
    assert request.required_refs == [new, supported]
    assert request.mode == "lexical" and request.query.splitlines() == topics[1:]
    original["scope"].update(node_parent_selection=str(uuid4()), node_carried={topics[0]: []})
    selection.coverage.required = selection.coverage.required[:1]
    stopped = []
    monkeypatch.setattr(workflow, "transition", lambda *args, missing: stopped.append(
        (args[-1], missing),
    ))
    assert next_packet() is None
    assert stopped == [("material_discovery_exhausted", topics[1:])]
    assert len(observations) == 1


def test_programming_gap_selects_code_and_its_local_explanation_not_prose_or_another_book():
    rows = [
        {"id": index, "ordinal": ordinal, "build_id": book, "section_path": ["Examples"],
         "kind": kind, "text": text}
        for index, (book, ordinal, kind, text) in enumerate((
            ("other", 7, "paragraph", "The map/filter documentation has many examples."),
            ("other", 8, "heading", "Arrow functions"),
            ("guide", 1, "paragraph", "An arrow expression transforms each input value."),
            ("guide", 2, "code", "x => x + 1"),
            ("guide", 3, "code", "items.map(n => n + 1).filter(n => n > 0)"),
        ))
    ]
    found = example_excerpts(rows, {"不可变更新": "map filter =>"}, [{"name": "TypeScript"}])
    assert set(found) == {"2", "3", "4"} and found[0] == "4"
    assert example_excerpts(rows, {"打开文件": "File.OpenRead"}, []) == []


def test_example_retrieves_a_separately_cited_rule_not_explained_beside_the_code():
    rows = [
        {"id": index, "ordinal": index, "build_id": "guide", "section_path": [section],
         "kind": kind, "text": text}
        for index, (section, kind, text) in enumerate((
            ("Overview", "paragraph", "C# 使用分号定义语句的末尾。"),
            ("Strings", "paragraph", "字符串字面量使用成对的双引号。"),
            ("Strings", "code", 'string name = "hello";'),
        ))
    ]
    assert example_excerpts(rows, {"字符串与语句": "string 字符串字面量 分号"}, []) == [
        "2", "1", "0",
    ]


def test_new_example_is_reviewed_with_partial_evidence_for_same_open_item(monkeypatch):
    covered, explanation, snippet, revoked = (exact_citation().ref for _ in range(4))
    topics = ["output", "strings and semicolons"]
    original = {"scope": {"node_checklist": topics, "node_example_queries": {topics[1]: "string"}},
                "request": {"required_refs": [ref.model_dump(mode="json")
                                              for ref in (covered, explanation)]}}
    selection = SimpleNamespace(
        id=uuid4(), evidence=[SimpleNamespace(ref=ref) for ref in (covered, revoked, explanation)],
        coverage=SimpleNamespace(status="partial", missing_facets=[topics[1]], required=[
            SimpleNamespace(facet=topics[0], status="supported", evidence=[covered]),
        ]),
    )
    stage = {"nodes": [{"key": "hello", "title": "intro", "topics": topics}]}
    state = {"id": uuid4(), "acquisition_state": {}}
    builds = [{"document_id": ref.document_id, "document_revision": 1}
              for ref in (covered, explanation, snippet)]
    demand = SimpleNamespace(node_key="hello", id=uuid4(), revision=1, language="csharp")
    workflow = MaterialDiscoveryWorkflow(None, None)
    writes = []
    connection = SimpleNamespace(execute=lambda sql, params: writes.append(params[0].obj))
    monkeypatch.setattr(StageSections, "chunks", lambda *args, **kwargs: [str(snippet.block_id)])
    monkeypatch.setattr(Retrieval, "unaffected_refs", lambda *args, **kwargs: [snippet])
    packet = workflow.node_packet(connection, None, state, demand, stage, builds, original,
                                  selection)
    assert packet.query == topics[1]
    assert packet.required_refs == [snippet, explanation, covered]
    state["acquisition_state"] = writes[-1]
    assert state["acquisition_state"]["node_gap_context"]["refs"] == [
        explanation.model_dump(mode="json")
    ]
    monkeypatch.setattr(Retrieval, "unaffected_refs", lambda *args, **kwargs: [])
    acquisitions = []
    monkeypatch.setattr(workflow, "acquire", lambda *args, **kwargs: acquisitions.append(args[-1]))
    assert not workflow.node_packet(connection, None, state, demand, stage, builds, original,
                                    selection)
    assert acquisitions == [[topics[1]]]


def test_example_lookup_uses_one_search_and_two_distinct_pages_before_reporting_the_gap(
    monkeypatch,
):
    lookup = {"gaps": ["callbacks"], "remaining": ["callbacks", "integration"],
              "attempted": [], "reviewed": []}
    state = {"id": uuid4(), "acquisition_state": {"node_example_lookup": lookup}}
    addresses = [f"https://source.invalid/{page}" for page in ("first", "second", "third")]
    resources = [{"url": url, "depth": 1} for url in addresses]
    work = MaterialAcquisition(SimpleNamespace(public_sources_in=lambda *_: False))
    searches, reads, gaps = [], [], []

    def search(*args, examples=False):
        searches.append((args[-2], examples))
        lookup["hits"] = addresses
        return True

    monkeypatch.setattr(work, "search", search)
    monkeypatch.setattr(work, "schedule", lambda *args: reads.append(args[-2]["url"]))
    monkeypatch.setattr(work, "exhausted", lambda *args: gaps.extend(args[-1]))
    for _ in range(4):
        work.example_source(SimpleNamespace(execute=lambda *_: None), None, state, None,
                            [], ["callbacks"], resources, {}, [], len(reads), {}, set(reads))
    assert searches == [(["callbacks"], True)] and reads == addresses[:2]
    assert gaps == ["callbacks", "integration"]


@pytest.mark.parametrize("limit", ["deadline", "total_resources"])
def test_example_lookup_stops_before_another_read_or_search_when_budget_is_spent(limit):
    lookup = {"attempted": ["https://guide.invalid/start"], "remaining": ["callbacks"]}
    if limit == "deadline":
        lookup["deadline_at"] = "2000-01-01T00:00:00+00:00"
    state = {"id": uuid4(), "acquisition_state": {"node_example_lookup": lookup}}
    stops = []
    work = MaterialAcquisition(SimpleNamespace(transition=lambda *args, **kw: stops.append(kw)))
    budget = {"read_limit": 1 if limit == "total_resources" else 12}
    work.example_source(SimpleNamespace(execute=lambda *_: None), None, state, None, [],
                        ["callbacks"], [], {}, [], 1, budget, set())
    assert stops == [{"missing": ["callbacks"]}] and "searched" not in lookup


def test_node_tries_named_guide_before_reviewing_unrelated_cached_books(monkeypatch):
    workflow = MaterialDiscoveryWorkflow(None, None)
    reading = {"title": "Vue Guide", "source_url": "https://book.invalid/guide/"}
    demand = SimpleNamespace(id=uuid4(), goal_id=uuid4(), plan_id=uuid4(), plan_revision=1,
                             revision=1, node_key="props", purpose="teaching", goal_text="props",
                             consumer_ref="node-material:test", preparation="complete")
    monkeypatch.setattr(workflow, "available_builds", lambda *_: [
        {"id": uuid4(), "document_id": uuid4()},
    ])
    monkeypatch.setattr(workflow, "curriculum_in", lambda *_, **kw: {"node_chapters": [{
        "material_plan": {"readings": [reading], "technologies": [{"name": "Vue"}]},
    }]})
    monkeypatch.setattr(workflow, "curriculum_resources_in", lambda *_: {})
    monkeypatch.setattr(MaterialBindings, "for_scope", lambda *_, **kw: [])
    monkeypatch.setattr(Retrieval, "reuse_goal_selection", lambda *_, **kw: None)
    monkeypatch.setattr(MaterialSources, "document_origins", lambda *_: [{"url": "unrelated"}])
    requests = []

    def acquire(_self, _conn, _actor, _row, _demand, missing, *, preferred_only=False):
        requests.append((missing, preferred_only))
        return True

    monkeypatch.setattr(MaterialAcquisition, "acquire", acquire)
    assert workflow.semantic_input(None, None, {"search_id": None}, demand) is None
    assert requests == [(["props"], True)]


def test_stage_chunk_map_persists_once_and_serves_another_node(
    database, session, curriculum_consumer,
):
    tutor, _, _, _, goal, version, _, document, _ = curriculum_consumer
    raw = deepcopy(document)
    first = raw["nodes"][0]
    first.update(project_milestone=None)
    raw["nodes"].append({**first, "key": "sequences", "prerequisite_keys": ["iteration"]})
    plan, _, _ = draft((*curriculum_consumer[:7], raw, curriculum_consumer[8]), session)
    tutor.confirm_plan(session.token, plan.id, 1)
    with database.transaction() as connection:
        stage = Plans(connection).curriculum_snapshot(
            session.actor, plan.id, 1, node_key="iteration", include_stage=True,
        )["material_stage"]
        demand = SimpleNamespace(plan_id=plan.id, plan_revision=1, node_key="iteration")
        builds = connection.execute(
            "SELECT * FROM knowledge.material_index_builds WHERE actor_id=%s "
            "AND document_id=%s AND state='indexed'", (session.actor.id, version.document_id),
        ).fetchall()
        sections = StageSections(connection)
        assert sections.chunks(session.actor, demand, stage, builds)
        demand.node_key = "sequences"
        assert sections.chunks(session.actor, demand, stage, builds)
        rows = connection.execute(
            "SELECT node_sections FROM knowledge.stage_material_sections WHERE plan_id=%s",
            (plan.id,),
        ).fetchall()
        assert len(rows) == 1 and set(rows[0]["node_sections"]) == {"iteration", "sequences"}


def test_model_curriculum_allows_original_nodes_but_validates_selected_source_chapters():
    citation = exact_citation()
    raw = curriculum_document(citation).model_dump(mode="json")
    raw["curriculum"].update(basis="model_knowledge", texts=[])
    raw["nodes"][0].update(material_citations=[], curriculum_chapters=[])
    document = PlanDocument(**raw)
    restored = PlanDocument.model_validate_json(document.model_dump_json())
    assert restored.curriculum.project == document.curriculum.project
    assert restored.nodes[0].project_milestone == "List the input files."
    raw["nodes"][0]["curriculum_chapters"] = [{
        "text_key": "invented", "title": "Unobserved chapter",
        "source_url": "https://book.invalid/fiction",
    }]
    raw["nodes"][0]["material_citations"] = [citation.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="belong to the selected curriculum"):
        PlanDocument(**raw)
    raw["nodes"][0].update(material_citations=[], curriculum_chapters=[])
    raw["curriculum"]["basis"] = "selected_materials"
    with pytest.raises(ValidationError, match="primary textbook"):
        PlanDocument(**raw)


def test_prior_source_quality_keeps_defects_without_repeating_old_coverage_inventory():
    ref = exact_citation().ref.model_dump(mode="json")
    finding = {
        "issue": "version_mismatch", "scope": "refs", "refs": [ref],
        "topics": ["Vue 2 setup"], "explanation": "This paragraph uses the previous major API.",
    }
    saved = {
        "status": "partial", "summary": "Useful Vue 3 introduction with one old API paragraph.",
        "issues": ["version_mismatch"], "findings": [finding],
        "supported_topics": ["Vue 3 prerequisites"],
        "missing_topics": ["A complete runnable lesson and all exercises"],
        "reviewed_refs": [
            {**ref, "block_id": str(uuid4())} for _ in range(400)
        ],
        "reviewed_parts": [], "evidence_refs": [ref],
    }
    original = deepcopy(saved)
    quality = prior_source_quality(saved)
    assert quality["findings"] == [finding]
    assert quality["issues"] == ["version_mismatch"]
    assert quality["previous_scope_status"] == "partial"
    assert quality["supported_topics"] == ["Vue 3 prerequisites"]
    assert "missing_topics" not in quality and "reviewed_refs" not in quality
    assert len(json.dumps(quality)) < len(json.dumps(saved)) / 20
    assert saved == original


def test_usable_partial_batch_reaches_route_author_without_certifying_teaching(
    database, session, consumer,
):
    _tutor, settings, conversation, _, goal, _, _, _, _ = consumer
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{goal.id}:route-draft",
            MaterialDemandInput(
                goal_id=goal.id, purpose="planning", preparation="complete",
                scope_mode="teaching_goal",
                goal_text="Choose a sequence guide and plan iteration lessons.",
            ),
        )
        MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
    advance_consumer_materials(
        database, session, settings, goal.id,
        gateway=goal_gateway(settings, status="partial")[0],
    )
    with database.transaction() as connection:
        selection = PlanningMaterials.ready_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
        assert selection.coverage.status == "partial" and selection.coverage.missing_facets
        assert selection.coverage.usable_for_planning
        overview = PlanningMaterials.overview_in(
            connection, conversation,
            SimpleNamespace(stage_replies=[], material_demand_id=demand.id),
            {"material_goal_coverage": selection.coverage.model_dump(mode="json")},
        )
        assert overview["route_ready"]
        assert overview["batches"][-1]["coverage_status"] == "partial"
        assert overview["batches"][-1]["missing_topics"] == selection.coverage.missing_facets
    for changes in (
        {"consumer_ref": f"planning-batch:{goal.id}:gap:missing-primary-text"},
        {"consumer_ref": f"tutor-turn:{uuid4()}:planning"},
        {"purpose": "lesson"},
    ):
        assert not PlanningMaterials.can_draft_from_partial(
            demand.model_copy(update=changes), selection,
        )
    uncertain = selection.model_copy(update={
        "coverage": selection.coverage.model_copy(update={
            "required": [selection.coverage.required[0].model_copy(update={"status": "uncertain"})],
        }),
    })
    assert not PlanningMaterials.can_draft_from_partial(demand, uncertain)
    with database.transaction() as connection:
        gap = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{goal.id}:gap:iteration-introduction",
            MaterialDemandInput(
                goal_id=goal.id, purpose="planning", preparation="complete",
                scope_mode="teaching_goal", goal_text="Confirm the iteration introduction.",
            ),
        )
        MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), gap,
        )
    advance_consumer_materials(database, session, settings, goal.id)
    with database.transaction() as connection:
        checked = PlanningMaterials.ready_in(
            connection, session.actor, Identity.digest(session.token), gap,
        )
        assert checked.coverage.status == "sufficient"
        retained = PlanningMaterials.apply_in(
            connection, session.actor, conversation, SimpleNamespace(planning_requested=True),
            RouteDiscussionReply(text="The route is ready.", route=consumer[7]),
            Identity.digest(session.token), previous=gap,
        )
        assert retained.id == gap.id


def test_partial_planning_uses_unaffected_evidence_and_keeps_bad_sources_out():
    good, bad = exact_citation().ref, exact_citation().ref
    defect = {
        "issue": "incorrect", "scope": "document", "refs": [bad],
        "topics": ["Iteration"], "explanation": "This other document contradicts the language.",
    }
    result = MaterialGoalVerdict(
        status="partial", summary="One usable introduction; other lessons remain to prepare.",
        evidence_refs=[good], reviewed_refs=[good, bad],
        issues=["incorrect"], findings=[defect],
    )
    good_part = {
        "refs": [good.model_dump(mode="json")],
        "result": MaterialGoalVerdict(
            status="partial", summary="A checked introduction.",
            evidence_refs=[good], reviewed_refs=[good],
        ).model_dump(mode="json"),
    }
    bad_part = {
        "refs": [bad.model_dump(mode="json")],
        "result": MaterialGoalVerdict(
            status="missing", summary="Known incorrect source.", evidence_refs=[],
            reviewed_refs=[bad], issues=["incorrect"], findings=[defect],
        ).model_dump(mode="json"),
    }
    assert usable_planning_evidence(result, [good_part, bad_part])
    bad_evidence = deepcopy(good_part)
    bad_evidence["result"]["issues"] = ["incorrect"]
    assert not usable_planning_evidence(result, [bad_evidence, bad_part])
    assert not usable_planning_evidence(
        result.model_copy(update={"findings": []}), [good_part, bad_part],
    )


def test_framework_gap_does_not_hide_language_basics_or_native_apis(monkeypatch):
    def entry(key, title, topics, frameworks=()):
        return {
            "id": key, "title": title, "topics": topics, "frameworks": list(frameworks),
            "url": f"https://{key}.invalid/guide/", "origin": "official",
            "languages": ["javascript"], "locales": ["en"], "version_scope": "current",
        }

    entries = [
        entry("basics", "JavaScript iteration", ["loops", "arrays"]),
        entry("native", "Fetch API and AbortController", ["fetch", "abortcontroller"]),
        entry("vitest", "Vitest mocks", ["mock", "tests"], ["vitest"]),
        entry("irrelevant", "JavaScript WebGL rendering", ["webgl", "rendering"]),
    ]
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_candidates.catalog_resources", lambda: entries,
    )
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="planning", scope_mode="teaching_goal",
        language="javascript", goal_text="Build a JavaScript application",
    )
    missing = ["JavaScript loops and arrays", "Fetch AbortController", "Vitest mocks"]
    selected = ranked_candidates(demand, demand.goal_text, missing=missing)
    assert {item["id"] for item in selected} == {"basics", "native", "vitest"}
    assert material_matches_gaps(
        "https://book.invalid/native/fetch Fetch AbortController", missing,
        goal_text=demand.goal_text, frameworks={"vitest"},
    )
    assert not material_matches_gaps(
        "JavaScript arrays", ["Vitest mocks"], frameworks={"vitest"},
    )


def test_uploaded_curriculum_and_unspecified_versions_keep_exact_document_identity():
    citation = exact_citation()
    document = curriculum_document(
        citation, source_url=None, document_id=citation.ref.document_id,
    )
    restored = PlanDocument.model_validate_json(document.model_dump_json())
    assert restored.curriculum.technologies[0].version is None
    assert restored.curriculum.texts[0].source_url is None
    assert restored.nodes[0].curriculum_chapters[0].document_id == citation.ref.document_id
    invalid = document.model_dump(mode="json")
    invalid["nodes"][0]["curriculum_chapters"][0].pop("document_id")
    with pytest.raises(ValidationError, match="observed URL or exact supplied document"):
        PlanDocument(**invalid)
    missing_origin = document.model_dump(mode="json")
    missing_origin["nodes"][0]["material_citations"] = []
    with pytest.raises(ValidationError, match="planning citation"):
        PlanDocument(**missing_origin)


def test_uploaded_pdf_curriculum_uses_its_document_and_rejects_invented_chapters(
    database, session, consumer, tmp_path,
):
    _tutor, settings, _, materials, goal, _, original_binding, _, _ = consumer
    settings = replace(settings, material_storage_dir=str(tmp_path))
    intake = MaterialIntakeWorkflow(database, settings)
    demand = intake.create_demand(
        session.token, str(uuid4()), MaterialDemandInput(
            goal_id=goal.id, purpose="planning", scope_mode="whole_source", index_mode="lexical",
        ),
    )
    content = pdf_bytes(["Iteration visits each item in a sequence. Print each value in order."])
    files = MaterialFilesWorkflow(database, settings)
    upload = files.reserve(
        session.token, demand.id, str(uuid4()), MaterialUploadInput(
            expected_demand_revision=1, content_digest=sha256(content).hexdigest(),
            byte_size=len(content),
            material=FileMaterialInput(
                goal_id=goal.id, title="Uploaded sequence handbook", format="pdf",
                authorized_use=True, purposes=["planning", "indexing", "teaching"],
            ),
        ),
    )
    files.store_content(session.token, upload.id, content)
    job = files.submit(
        session.token, demand.id, str(uuid4()),
        MaterialFileJobInput(expected_demand_revision=1, upload_id=upload.id),
    )
    for _ in range(12):
        intake.execute(job.id, transport=material_transport())
        job = intake.job(session.token, job.id)
        if job.state == "ready":
            break
    assert job.state == "ready"
    page = materials.blocks(session.token, job.document_id, job.document_revision, "planning")
    binding = materials.bind(
        session.token, str(uuid4()), MaterialBindingInput(
            goal_id=goal.id, purpose="planning",
            expected_binding_revision=original_binding.revision, refs=[page.blocks[0].ref],
        ),
    )
    with database.transaction() as connection:
        sources = PlanningMaterials.curriculum_sources_in(connection, session.actor, goal.id)
        source = next(item for item in sources if item["source_url"] is None)
        chapter = source["chapters"][0]
        data = curriculum_document(
            binding_citations([binding])[0], source_url=None, document_id=job.document_id,
        ).model_dump(mode="json")
        data["nodes"][0]["curriculum_chapters"][0]["title"] = chapter["title"]
        document = PlanDocument(**data)
        PlanningMaterials.validate_route_in(connection, session.actor, goal.id, document)
        data["nodes"][0]["curriculum_chapters"][0]["title"] = "An invented chapter"
        with pytest.raises(BusinessError, match="observed curriculum chapter"):
            PlanningMaterials.validate_route_in(
                connection, session.actor, goal.id, PlanDocument(**data),
            )


def test_ready_planning_evidence_is_checked_while_another_uploaded_book_is_pending(
    database, session, consumer, tmp_path,
):
    _tutor, settings, _, _, goal, version, _, _, _ = consumer
    draft(consumer, session)
    settings = replace(settings, material_storage_dir=str(tmp_path))
    intake = MaterialIntakeWorkflow(database, settings)
    pending_demand = intake.create_demand(
        session.token, str(uuid4()), MaterialDemandInput(
            goal_id=goal.id, purpose="planning", scope_mode="whole_source", index_mode="lexical",
        ),
    )
    content = pdf_bytes(["A later chapter that has not yet been parsed."])
    files = MaterialFilesWorkflow(database, settings)
    upload = files.reserve(
        session.token, pending_demand.id, str(uuid4()), MaterialUploadInput(
            expected_demand_revision=1, content_digest=sha256(content).hexdigest(),
            byte_size=len(content),
            material=FileMaterialInput(
                goal_id=goal.id, title="Later textbook", format="pdf", authorized_use=True,
                purposes=["planning", "indexing"],
            ),
        ),
    )
    files.store_content(session.token, upload.id, content)
    pending = files.submit(
        session.token, pending_demand.id, str(uuid4()),
        MaterialFileJobInput(expected_demand_revision=1, upload_id=upload.id),
    )
    workflow = MaterialDiscoveryWorkflow(database, settings)
    with database.transaction() as connection:
        assert pending.id in {
            job.id for job in MaterialIntake(connection).pending_goal_uploads(
                session.actor, goal.id,
            )
        }
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:pending:{uuid4()}", MaterialDemandInput(
                goal_id=goal.id, purpose="planning", scope_mode="teaching_goal",
                goal_text="Select suitable material for an iteration learning route.",
            ),
        )
        discovery = workflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
        actor, row, demand = workflow.current(connection, discovery.id)
        request = workflow.semantic_input(connection, actor, row, demand)
        assert request is not None
        assert any(source.document_id == version.document_id for source in request.source_versions)
    assert intake.job(session.token, pending.id).state == pending.state


def test_curriculum_accepts_observed_chapters_and_rejects_invented_addresses(monkeypatch):
    citation = exact_citation()
    document = curriculum_document(citation)
    source = {
        "source_url": document.curriculum.texts[0].source_url,
        "evidence_document_ids": [str(citation.ref.document_id)],
        "chapters": [{"title": "Iteration", "source_url": document.nodes[0]
                      .curriculum_chapters[0].source_url}],
    }
    monkeypatch.setattr(
        PlanningMaterials, "curriculum_sources_in", staticmethod(lambda *_: [source]),
    )
    PlanningMaterials.validate_route_in(None, None, uuid4(), document)
    invented = document.model_dump(mode="json")
    invented["nodes"][0]["curriculum_chapters"][0]["source_url"] += "imaginary-chapter/"
    with pytest.raises(BusinessError, match="observed curriculum chapter"):
        PlanningMaterials.validate_route_in(None, None, uuid4(), PlanDocument(**invented))
    uploaded = curriculum_document(citation, source_url=None, document_id=citation.ref.document_id)
    source.update(
        source_url=None,
        chapters=[{
            "title": "Iteration", "source_url": None, "document_id": str(citation.ref.document_id),
        }],
    )
    PlanningMaterials.validate_route_in(None, None, uuid4(), uploaded)


def test_planning_samples_introduction_and_relevant_body_without_requiring_every_lesson():
    document_id = uuid4()
    rows = [
        {"id": uuid4(), "document_id": document_id, "document_revision": 1, "ordinal": index,
         "section_path": ["Introduction" if index == 0 else "Chapter"],
         "text": "Fetch AbortController" if index == 8 else f"Other topic {index}"}
        for index in range(12)
    ]
    selected = planning_evidence_rows(rows, "Fetch AbortController")
    assert rows[0] in selected and rows[8] in selected
    assert len(selected) <= 4
    for row in rows:
        row.update(
            block_id=uuid4(), span_start=0, span_end=len(row["text"]),
            content_digest=sha256(row["text"].encode()).hexdigest(), kind="paragraph",
        )
    retrieval = Retrieval(SimpleNamespace(
        execute=lambda *_: SimpleNamespace(fetchall=lambda: rows),
    ))
    full = retrieval.unaffected_refs([{"id": uuid4()}], [])
    defect = MaterialGoalFinding(
        issue="incorrect", scope="refs", refs=[full[1]], topics=["Old example"],
        explanation="The old example is incorrect.",
    )
    remaining = retrieval.unaffected_refs([{"id": uuid4()}], [defect])
    sample = retrieval.unaffected_refs(
        [{"id": uuid4()}], [defect], planning_query="Fetch AbortController",
    )
    assert len(remaining) == 11 and len(sample) <= 4
    assert any(ref.block_id == rows[8]["block_id"] for ref in sample)
    assert all(ref.block_id != rows[1]["block_id"] for ref in sample)
    planning = MaterialGoalCoverageWorkflow.make_role(
        "Choose a suitable Fetch curriculum", [], purpose="planning",
    )
    teaching = MaterialGoalCoverageWorkflow.make_role(
        "Teach cancellation with Fetch", [], purpose="teaching",
    )
    assert "Detailed lesson explanations" in planning.messages[0]["content"]
    assert "necessary conditions and usable examples" in teaching.messages[0]["content"]
    assert json.loads(planning.messages[1]["content"])["evidence_level"] == "route_planning"
    assert json.loads(teaching.messages[1]["content"])["evidence_level"] == "node_teaching"


@pytest.fixture
def curriculum_consumer(consumer, session):
    tutor, settings, conversation, materials, goal, version, binding, _document, text = consumer
    representative = materials.bind(
        session.token, str(uuid4()), MaterialBindingInput(
            goal_id=goal.id, purpose="planning", expected_binding_revision=binding.revision,
            refs=binding.refs[:1],
        ),
    )
    document = curriculum_document(
        binding_citations([representative])[0], source_url=version.source_url,
    )
    return (
        tutor, settings, conversation, materials, goal, version, representative,
        document.model_dump(mode="json"), text,
    )


def test_curriculum_persists_with_exact_revision_and_legacy_plans_remain_readable(
    database, session, curriculum_consumer,
):
    plan, _, _ = draft(curriculum_consumer, session)
    with database.transaction() as connection:
        plans = Plans(connection)
        snapshot = plans.curriculum_snapshot(
            session.actor, plan.id, plan.latest.revision, node_key="iteration",
        )
        assert snapshot["plan_revision"] == 1
        assert snapshot["project"]["title"] == "File organizer"
        assert snapshot["node_chapters"][0]["node_key"] == "iteration"
        assert snapshot["texts"][0]["material_citations"][0]["binding_revision"] == 2
        with pytest.raises(BusinessError, match="revision not found"):
            plans.curriculum_snapshot(session.actor, plan.id, 99)
        with pytest.raises(BusinessError, match="not found"):
            plans.curriculum_snapshot(SimpleNamespace(id=uuid4()), plan.id)
    legacy = deepcopy(curriculum_consumer[7])
    legacy.pop("curriculum")
    legacy["nodes"][0].pop("curriculum_chapters")
    legacy["nodes"][0].pop("project_milestone")
    assert "curriculum" not in PlanDocument(**legacy).model_dump(mode="json")


@pytest.mark.parametrize("purpose", ["teaching", "lesson"])
def test_node_preparation_expands_beyond_planning_representative_text(
    database, session, curriculum_consumer, purpose,
):
    tutor, settings, conversation, _, goal, _, representative, _, _ = curriculum_consumer
    plan, _, _ = draft(curriculum_consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    focus = TeachingFocus(
        kind="node", plan_id=plan.id, expected_plan_revision=1, node_key="iteration",
    )
    with database.transaction() as connection:
        demand = prepare_consumer_in(
            connection, session.actor, conversation, SimpleNamespace(id=uuid4()), purpose, focus,
            session_digest=Identity.digest(session.token),
        )
        assert "Selected curriculum chapters: Iteration" in demand.goal_text
        assert not MaterialBindings(connection).for_scope(
            session.actor, goal.id, purpose, plan_id=plan.id, plan_revision=1, node_key="iteration",
        )
    advance_consumer_materials(database, session, settings, goal.id)
    with database.transaction() as connection:
        selection = ensure_consumer_material_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
        binding = MaterialBindings(connection).for_scope(
            session.actor, goal.id, purpose, plan_id=plan.id, plan_revision=1, node_key="iteration",
        )[0]
        assert selection.coverage.basis == "semantic-goal-evidence.v1"
        assert len(binding.refs) > len(representative.refs)


@pytest.mark.parametrize("consumer", [["lesson", "item_author", "item_review"]], indirect=True)
@pytest.mark.parametrize("deferred", [False, True])
def test_item_materials_freeze_after_node_chapters_are_prepared(
    database, session, curriculum_consumer, deferred,
):
    tutor, settings, _, _, goal, _, representative, document, _ = curriculum_consumer
    if deferred:
        document["curriculum"]["basis"] = "model_knowledge"
        document["nodes"][0].update(material_citations=[], curriculum_chapters=[])
    plan, _, _ = draft(curriculum_consumer, session)
    tutor.confirm_plan(session.token, plan.id, 1)
    accepted = ItemSupply(database, settings).submit(
        session.token, plan.id, str(uuid4()),
        PackRequest(
            expected_plan_revision=1, node_key="iteration", instruction="Practice iteration",
        ),
    )
    with database.transaction() as connection:
        pack = Packs(connection).row(session.actor, accepted.pack_id)
        assert Packs.material_context(pack).author_citations == []
        if deferred:
            stage = Packs(connection).stages(accepted.pack_id)[0]
            with pytest.raises(BusinessError, match="being prepared"):
                ItemSupply.role(connection, session.actor, pack, stage)
    advance_consumer_materials(database, session, settings, goal.id)
    with database.transaction() as connection:
        pack = Packs(connection).row(session.actor, accepted.pack_id)
        _demand, selection = ItemSupply.material_selection(
            connection, session.actor, pack, "author", Identity.digest(session.token),
        )
        context = Packs.material_context(pack)
        assert selection.coverage.basis == "semantic-goal-evidence.v1"
        assert context.author_citations and {c.purpose for c in context.author_citations} == {
            "item_author",
        }
        if deferred:
            assert context.origin_citations == [] and context.review_citations == []
        else:
            assert len(context.author_citations) > len(representative.refs)
            assert context.origin_citations == binding_citations([representative])
