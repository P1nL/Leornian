import io
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter
from test_material_files import pdf_bytes
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import rag as rag
from test_material_sources_and_goals import (
    configure_goal_models,
    finish_observed,
    goal_gateway,
    material_transport,
)

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.bootstrap.material_acquisition import MaterialAcquisition, renew_budget
from leornian.bootstrap.material_consumers import ensure_consumer_material_in
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.material_sources import MaterialSourceWorkflow, scan_material_sources_once
from leornian.bootstrap.material_web import MaterialWebWorkflow
from leornian.bootstrap.materials import MaterialWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.knowledge.goal_coverage_contracts import MaterialGoalVerdict
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.progress import MaterialPreparation
from leornian.modules.knowledge.retrieval import Retrieval
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.knowledge.source_candidates import (
    DiscoveredSourceCatalog,
    candidate_source,
    gap_topics,
    ranked_candidates,
    selected_pdf_pages,
)
from leornian.modules.learning.contracts import GoalInput, GoalMaterialScope
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.learning.materials import MaterialBindings
from leornian.platform.material_search_configuration import TavilyConfigurationInput
from leornian.shared_kernel.errors import BusinessError


def entry(name, *, language="java", origin="third_party", framework=""):
    return {
        "id": name, "title": f"{language} iteration {name}",
        "url": f"https://{name}.invalid/guide/iteration",
        "publisher": name, "origin": origin, "languages": [language],
        "frameworks": [framework] if framework else [], "forms": ["html", "tutorial"],
        "locales": ["zh-CN"], "topics": ["iteration", "examples"],
        "version_scope": "unverified", "verification": {"status": "reachable"},
    }


def demand_input(goal_id, **updates):
    return MaterialDemandInput(**{
        "goal_id": goal_id, "purpose": "planning", "scope_mode": "teaching_goal",
        "preparation": "initial", "language": "java", "goal_text": "Java iteration and examples",
        **updates,
    })


@pytest.fixture
def automatic(database, workflow, session, rag, monkeypatch, request):
    language = getattr(request, "param", "java")
    submitted = workflow.submit(session.token, str(uuid4()), GoalInput(
        title=f"Automatic {language} materials",
        material_scope=GoalMaterialScope(
            language=language, authorized_official_sources=True, authorized_public_sources=True,
        ),
    ))
    with database.transaction() as connection:
        event = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (submitted.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event)
    goal = next(goal for goal in workflow.snapshot(session.token).goals
                if goal.title == f"Automatic {language} materials")
    settings = replace(rag["settings"], model_enabled=True)
    configure_goal_models(database, session, settings)
    ModelConfigurationWorkflow(database, settings).save_tavily(
        session.token, TavilyConfigurationInput(
            expected_revision=0, enabled=True, api_key="offline-automatic-discovery",
        ),
    )
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_network.resolve_destination", lambda *_: "1.1.1.1",
    )
    monkeypatch.setattr(
        "leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1",
    )
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{uuid4()}",
            demand_input(
                goal.id, language=language,
                goal_text=f"{language.capitalize()} iteration and examples",
            ),
        )
        discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
    return settings, goal, demand, discovery


def choose(monkeypatch, *entries):
    monkeypatch.setattr(
        MaterialDiscoveryWorkflow, "catalog_in",
        staticmethod(lambda _c, _a, demand, **_kwargs: [
            ("resource:" + item["id"], candidate_source(demand, item)) for item in entries
        ]),
    )


def current(database, session, discovery):
    with database.transaction() as connection:
        return MaterialSources(connection).discovery(session.actor, discovery.demand_id)


def drive(database, session, automatic, page_transport, gateway=None, search_transport=None):
    settings, goal, _demand, discovery = automatic
    source_workflow = MaterialSourceWorkflow(database, settings)
    gateway = gateway or goal_gateway(settings, compact=True)[0]
    search_transport = search_transport or httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"results": []}),
    )
    for _ in range(50):
        MaterialWebWorkflow(database, settings).advance_search(discovery.id, search_transport)
        MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
        with database.transaction() as connection:
            observations = connection.execute(
                "SELECT o.id FROM knowledge.source_observations o "
                "JOIN knowledge.material_source_registrations s ON s.id=o.source_id "
                "WHERE s.goal_id=%s AND o.status IN ('queued','fetching','processing')", (goal.id,),
            ).fetchall()
        for item in observations:
            source_workflow.execute(item["id"], page_transport)
        with database.transaction() as connection:
            jobs = connection.execute(
                "SELECT j.id FROM knowledge.material_jobs j JOIN knowledge.material_demands d "
                "ON d.id=j.demand_id WHERE d.goal_id=%s AND j.state NOT IN "
                "('ready','cancelled','blocked_unknown')", (goal.id,),
            ).fetchall()
            searches = connection.execute(
                "SELECT s.id FROM knowledge.material_searches s JOIN knowledge.material_demands d "
                "ON s.request->>'demand_id'=d.id::text WHERE d.goal_id=%s AND s.status NOT IN "
                "('ready','cancelled','blocked_unknown')", (goal.id,),
            ).fetchall()
        for item in jobs:
            MaterialIntakeWorkflow(database, settings).execute(item["id"], material_transport())
        for item in searches:
            MaterialSearchWorkflow(database, settings).execute(item["id"], material_transport())
        with database.transaction() as connection:
            runs = connection.execute(
                "SELECT p.run_id FROM knowledge.material_goal_coverage_parts p "
                "JOIN knowledge.material_searches s ON s.id=p.search_id "
                "JOIN knowledge.material_demands d ON s.request->>'demand_id'=d.id::text "
                "WHERE d.goal_id=%s AND p.state='running'", (goal.id,),
            ).fetchall()
        for item in runs:
            AgentLoop(TutorWorkflow(database, settings), gateway).run(item["run_id"])
        status = current(database, session, discovery)
        if status.status in {"ready", "blocked_unknown", "cancelled"} or (
            status.error_code == "material_discovery_exhausted"
        ):
            return status
    pytest.fail(f"Automatic discovery made no terminal progress: {status}")


def page(request):
    return httpx.Response(
        200, headers={"content-type": "text/html"},
        stream=httpx.ByteStream(
            b"<main><h1>Java iteration</h1><p>A loop visits every sequence item. "
            b"An empty list performs zero iterations.</p>"
            b"<pre>for (var item : items) { System.out.println(item); }</pre></main>",
        ),
    )


def test_directory_chapters_outside_the_old_prefix_get_their_own_public_grant(
    database, session, automatic, monkeypatch,
):
    settings, _goal, demand, _discovery = automatic
    root = entry("chapter-index")

    def catalog(connection, actor, current_demand, **_kwargs):
        entries = [root, *DiscoveredSourceCatalog(connection).entries(actor)]
        return [
            (item["id"] if item["id"].startswith("discovered:") else "resource:" + item["id"],
             candidate_source(current_demand, item))
            for item in entries
        ]

    monkeypatch.setattr(MaterialDiscoveryWorkflow, "catalog_in", staticmethod(catalog))
    fetched = []

    def get(request):
        fetched.append(f"https://{request.headers['host']}{request.url.raw_path.decode()}")
        if request.url.path == "/guide/iteration":
            body = "<main>" + "".join(
                f'<a href="/lessons/iteration-{index}">Iteration examples {index}</a>'
                for index in range(3)
            ) + "</main>"
            return httpx.Response(
                200, headers={"content-type": "text/html"},
                stream=httpx.ByteStream(body.encode()),
            )
        return page(request)

    status = drive(database, session, automatic, httpx.MockTransport(get))
    assert status.status == "ready"
    assert fetched[0] == root["url"] and any("/lessons/" in url for url in fetched[1:])
    with database.transaction() as connection:
        root_source = connection.execute(
            "SELECT id,specification FROM knowledge.material_source_registrations "
            "WHERE goal_id=%s AND catalog_id=%s",
            (demand.goal_id, "resource:" + root["id"]),
        ).fetchone()
        assert root_source["specification"]["allowed_prefixes"] == [
            "https://chapter-index.invalid/guide/",
        ]
        observation = connection.execute(
            "SELECT * FROM knowledge.source_observations WHERE source_id=%s",
            (root_source["id"],),
        ).fetchone()
        assert observation["upload_id"] is None and observation["job_id"] is None
        assert observation["request_identity"]["source_structure"]["role"] == "directory"
        child = connection.execute(
            "SELECT basis,specification FROM knowledge.material_source_registrations "
            "WHERE goal_id=%s AND basis='public_discovery'", (demand.goal_id,),
        ).fetchone()
        assert child and "/lessons/" in child["specification"]["entry_url"]
    selected = MaterialSearchWorkflow(database, settings).selection(
        session.token, status.selection_id,
    )
    assert selected.evidence and all(
        item.source_url != root["url"] for item in selected.evidence
    )


def test_repeated_invalid_leaf_review_rotates_source_without_waiting_for_the_learner(
    database, session, automatic, monkeypatch,
):
    settings, _goal, _demand, _discovery = automatic
    choose(monkeypatch, entry("invalid-review"), entry("usable-body"))
    calls = []

    def handle(request):
        wire = json.loads(request.content)
        payload = json.loads(wire["messages"][1]["content"])
        source = payload["source_parts"][0]["source_url"]
        calls.append(source)
        refs = [part["reference_key"] for part in payload["source_parts"]]
        result = {
            "status": "supported", "summary": "Iteration visits the source sequence.",
            "evidence_refs": refs[:1], "reviewed_refs": refs, "reviewed_parts": [],
        }
        if "invalid-review" in source:
            result["reviewed_parts"] = [str(uuid4())]
        return httpx.Response(200, json={
            "choices": [{
                "message": {"role": "assistant", "content": json.dumps(result)},
                "finish_reason": "stop",
            }],
        })

    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    status = drive(database, session, automatic, httpx.MockTransport(page), gateway)
    assert status.status == "ready"
    assert sum("invalid-review" in url for url in calls) == 2
    assert sum("usable-body" in url for url in calls) == 1
    with database.transaction() as connection:
        failed = connection.execute(
            "SELECT p.state,p.result,r.status,c.status AS call_status,c.applied "
            "FROM knowledge.material_goal_coverage_parts p JOIN runtime.runs r ON r.id=p.run_id "
            "JOIN runtime.external_calls c ON c.run_id=r.id "
            "WHERE r.actor_id=%s AND r.status='failed'", (session.actor.id,),
        ).fetchall()
        assert failed and all(
            item["state"] == "waiting_dependency" and item["result"] is None
            and item["call_status"] == "result_recorded" for item in failed
        )


def test_candidates_filter_language_form_and_locale_without_acquisition():
    demand = demand_input(uuid4())
    selected = ranked_candidates(
        demand, "Java iteration", extra=[entry("community"), entry("wrong", language="python")],
    )
    assert len(selected) <= 12
    assert all("java" in item["languages"] for item in selected)
    assert any(item["id"] == "community" for item in selected)
    assert candidate_source(demand, entry("community")).language_version is None


@pytest.mark.parametrize("language,framework", [
    ("python", "fastapi"), ("java", "junit"), ("javascript", "vitest"),
    ("typescript", "nestjs"), ("go", "gin"), ("csharp", "aspnetcore"),
    ("sql", "postgresql"), ("html", "tailwind"), ("css", "bootstrap"),
])
def test_gap_ranking_prioritizes_the_needed_ecosystem_in_every_catalogue_language(
    monkeypatch, language, framework,
):
    basic = {**entry("basic", language=language), "title": f"{language} basics",
             "topics": ["basics", "syntax"]}
    needed = {**entry("needed", language=language, framework=framework),
              "title": f"{framework} transactions", "topics": ["transactions"], "locales": ["en"]}
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_candidates.catalog_resources",
        lambda: [basic, needed],
    )
    result = ranked_candidates(
        demand_input(uuid4(), language=language),
        f"{language} basics syntax {framework}", missing=[f"{framework} transactions"],
    )
    assert [item["id"] for item in result] == ["needed"]
    assert language not in MaterialDiscoveryWorkflow.topic_terms([f"{language} transactions"])
    assert ranked_candidates(
        demand_input(uuid4(), language=language),
        f"学习{framework}事务", missing=[f"使用{framework}处理transactions"],
    )[0]["id"] == "needed"


def test_named_dependency_can_cross_language_without_using_a_prerequisite_as_the_target(
    monkeypatch,
):
    java = entry("java", language="java")
    python = entry("python", language="python")
    database = entry("database", language="sql", framework="mysql")
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_candidates.catalog_resources",
        lambda: [java, python, database],
    )
    demand = demand_input(uuid4())
    base = ranked_candidates(demand, "I know Python and want Java iteration")
    assert {item["id"] for item in base} == {"java"}
    selected = ranked_candidates(
        demand, "Java backend", missing=["MySQL transactions"],
    )
    assert selected[0]["id"] == "database"
    assert candidate_source(demand, selected[0]).language == "sql"


@pytest.mark.parametrize("automatic", [
    "python", "java", "javascript", "typescript", "go", "csharp",
], indirect=True)
def test_goal_coverage_never_dispatches_unused_query_embedding_or_rerank(
    database, session, automatic, monkeypatch,
):
    language = automatic[2].language
    choose(monkeypatch, entry("community", language=language))
    monkeypatch.setattr(
        MaterialSearchWorkflow, "operation",
        lambda *_args, **_kwargs: pytest.fail("Goal coverage must not rank unused search hits"),
    )
    status = drive(database, session, automatic, httpx.MockTransport(page))
    assert status.status == "ready"
    with database.transaction() as connection:
        assert not connection.execute(
            "SELECT 1 FROM knowledge.material_search_operations o "
            "JOIN knowledge.material_searches s ON s.id=o.search_id "
            "WHERE s.actor_id=%s", (session.actor.id,),
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM knowledge.material_goal_coverage_parts p "
            "JOIN knowledge.material_searches s ON s.id=p.search_id "
            "WHERE s.actor_id=%s AND p.state='reviewed'", (session.actor.id,),
        ).fetchone()
        assert not connection.execute(
            "SELECT 1 FROM knowledge.material_operations o "
            "JOIN knowledge.material_jobs j ON j.id=o.job_id "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "WHERE d.goal_id=%s AND o.purpose='embedding'", (automatic[1].id,),
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM knowledge.material_index_builds b "
            "JOIN knowledge.material_jobs j ON j.id=b.job_id "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "WHERE d.goal_id=%s AND b.space->>'mode'='lexical' AND b.state='indexed'",
            (automatic[1].id,),
        ).fetchone()


def test_legacy_authorization_and_defective_quality_receipts_keep_their_boundaries():
    scope = GoalMaterialScope(authorized_official_sources=True)
    assert not scope.authorized_public_sources
    assert "authorized_public_sources" not in scope.model_dump(mode="json")
    with pytest.raises(ValidationError):
        MaterialGoalVerdict(
            status="supported", summary="Version contradicts the goal",
            evidence_refs=[], issues=["version_mismatch"],
        )


def test_planning_lexical_material_is_vectorized_only_for_a_later_hybrid_query(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("community"))
    assert drive(database, session, automatic, httpx.MockTransport(page)).status == "ready"
    settings, goal, _demand, _discovery = automatic
    intake = MaterialIntakeWorkflow(database, settings)
    demand = intake.create_demand(
        session.token, str(uuid4()), MaterialDemandInput(
            goal_id=goal.id, purpose="teaching", required_facets=["iteration"],
        ),
    )
    searcher = MaterialSearchWorkflow(database, settings)
    search = searcher.submit(session.token, str(uuid4()), MaterialSearchInput(
        demand_id=demand.id, expected_demand_revision=demand.revision,
        query="iteration", mode="hybrid",
    ))
    for _ in range(12):
        searcher.execute(search.id, material_transport())
        search = searcher.get(session.token, search.id)
        if search.status == "ready":
            break
    assert search.status == "ready"
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT 1 FROM knowledge.material_index_builds b "
            "JOIN knowledge.material_jobs j ON j.id=b.job_id "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "WHERE d.goal_id=%s AND b.space ? 'model' AND b.state='indexed'", (goal.id,),
        ).fetchone()


@pytest.mark.parametrize(("purpose", "preparation"), [
    ("planning", "initial"), ("planning", "complete"), ("teaching", "complete"),
])
def test_scoped_bad_paragraph_is_excluded_without_discarding_the_usable_document(
    database, session, automatic, monkeypatch, purpose, preparation,
):
    choose(monkeypatch, entry("scoped"))
    settings, goal, _demand, _discovery = automatic
    if (purpose, preparation) != ("planning", "initial"):
        with database.transaction() as connection:
            demand = MaterialIntake(connection).ensure_consumer_demand(
                session.actor, "scoped-evidence:" + str(uuid4()),
                demand_input(goal.id, purpose=purpose, preparation=preparation),
            )
            discovery = MaterialDiscoveryWorkflow.ensure_in(
                connection, session.actor, Identity.digest(session.token), demand,
            )
        automatic = settings, goal, demand, discovery
    seen = []

    def content(_request):
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(
            b"<main><h1>Iteration</h1><p>A loop visits every sequence item. "
            b"An empty sequence runs zero times.</p>"
            b"<p>outdated dependency: use RELEASE for all runtime versions.</p></main>",
        ))

    def review(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        seen.append(payload)
        parts = payload["source_parts"]
        bad = [part for part in parts if "outdated dependency" in part["text"]]
        result = {
            "status": "partial" if bad else "supported",
            "summary": "The loop explanation is usable; the outdated dependency is excluded.",
            "reviewed_refs": [part["reference_key"] for part in parts],
            "evidence_refs": [
                part["reference_key"] for part in parts if part not in bad
            ][:8],
            "issues": ["version_mismatch"] if bad else [],
            "supported_topics": ["Java iteration"],
            "findings": [{
                "issue": "version_mismatch", "scope": "refs",
                "refs": [part["reference_key"] for part in bad],
                "topics": ["dependency"], "explanation": "RELEASE is not a fixed version.",
            }] if bad else [],
            "missing_topics": ["A usable selection excluding the outdated command"] if bad else [],
        }
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": json.dumps(result)},
            "finish_reason": "stop",
        }], "usage": {"prompt_tokens": 50, "completion_tokens": 60}})

    result = drive(
        database, session, automatic, httpx.MockTransport(content),
        gateway=ChatCompletionsGateway(settings, httpx.MockTransport(review)),
    )
    assert result.status == "ready" and len(seen) == 2
    with database.transaction() as connection:
        selection = Retrieval(connection).selection(session.actor, result.selection_id)
        assert all("outdated dependency" not in item.text for item in selection.evidence)
        state = connection.execute(
            "SELECT acquisition_state FROM knowledge.material_discovery_jobs WHERE id=%s",
            (result.id,),
        ).fetchone()["acquisition_state"]
        assert not state["excluded_versions"]
        assert len(state["excluded_findings"]) == 1


def test_complete_gap_acquires_new_source_after_cleaned_old_material_still_has_gaps(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("rotation-old"), entry("rotation-new"))
    settings, goal, _demand, _discovery = automatic
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{goal.id}:gap:{uuid4()}",
            demand_input(goal.id, preparation="complete"),
        )
        discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
    events = []

    def content(request):
        if request.headers["host"] == "rotation-new.invalid":
            events.append("fetch_new")
            return page(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(
            b"<main><h1>Java iteration</h1>"
            + b"".join(
                f"<p>Unrelated story {index}; no iteration conditions or examples.</p>".encode()
                for index in range(8)
            ) + b"</main>",
        ))

    def review(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        children = payload["complete_child_summaries"]
        if children:
            supported = any(child["status"] == "supported" for child in children)
            evidence = [
                ref for child in children if child["status"] == "supported"
                for ref in child["evidence_refs"]
            ]
            findings = [finding for child in children for finding in child["findings"]]
            reviewed = []
        else:
            supported = "rotation-new.invalid" in payload["source_documents"][0]["source_url"]
            events.append("review_new" if supported else "review_old")
            reviewed = [part["reference_key"] for part in payload["source_parts"]]
            bad = [
                part["reference_key"] for part in payload["source_parts"]
                if part["text"].startswith("Unrelated story")
            ][:1] if not supported else []
            evidence = [ref for ref in reviewed if ref not in bad]
            findings = [{
                "issue": "irrelevant", "scope": "refs", "refs": bad,
                "topics": ["Java iteration"], "explanation": "This story does not teach iteration.",
            }] if bad else []
        result = {
            "status": "supported" if supported else "partial",
            "summary": "New source explains iteration and empty input; old material has gaps.",
            "reviewed_refs": reviewed, "reviewed_parts": [child["id"] for child in children],
            "evidence_refs": evidence[:8], "findings": findings,
            "issues": ["irrelevant"] if findings else [],
            "supported_topics": ["Java iteration"] if evidence else [],
            "missing_topics": [] if supported else ["Java iteration conditions and examples"],
        }
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": json.dumps(result)},
            "finish_reason": "stop",
        }], "usage": {"prompt_tokens": 50, "completion_tokens": 60}})

    result = drive(
        database, session, (settings, goal, demand, discovery), httpx.MockTransport(content),
        gateway=ChatCompletionsGateway(settings, httpx.MockTransport(review)),
    )
    assert result.status == "ready"
    assert events[:events.index("fetch_new")].count("review_old") == 2
    assert "review_new" in events
    with database.transaction(snapshot=True) as connection:
        state = connection.execute(
            "SELECT acquisition_state FROM knowledge.material_discovery_jobs WHERE id=%s",
            (discovery.id,),
        ).fetchone()["acquisition_state"]
        assert state["excluded_findings"]
        assert not state["excluded_versions"]


def test_gap_topics_split_compound_feedback_without_changing_original_topic_text():
    assert gap_topics(["Unit tests\nLogging", "unit   tests", "   "]) == [
        "Unit tests", "Logging",
    ]


def test_budget_has_one_exploration_batch_and_stops_after_no_progress():
    assert renew_budget({}, 12, set(), new_candidate=False) is None
    grant = renew_budget({}, 12, set(), new_candidate=True)
    assert grant["read_limit"] == 16 and grant["search_limit"] == 3
    assert grant["grants"][-1]["basis"] == "new_gap_candidate"
    assert renew_budget(grant, 16, set(), new_candidate=True) is None


def test_budget_renews_only_on_new_checked_support_and_keeps_absolute_caps():
    grant = {}
    for index, used in enumerate((12, 16, 20)):
        supports = {f"doc:{revision}" for revision in range(index + 1)}
        grant = renew_budget(grant, used, supports, new_candidate=False)
        assert grant["read_limit"] == used + 4
        assert grant["grants"][-1]["basis"] == "coverage_progress"
    assert grant["search_limit"] == 4
    assert renew_budget(grant, 24, {"doc:99"}, new_candidate=True) is None


def test_search_extension_does_not_reset_read_usage_or_reward_the_same_evidence_twice():
    grant = renew_budget({}, 8, {"doc:1"}, new_candidate=False, search_exhausted=True)
    assert grant["read_limit"] == 12 and grant["search_limit"] == 3
    assert renew_budget(
        grant, 8, {"doc:1"}, new_candidate=False, search_exhausted=True,
    ) is None


def test_search_metadata_does_not_label_unrelated_results_with_the_requested_framework():
    catalog = DiscoveredSourceCatalog(SimpleNamespace(execute=lambda *_args: None))
    item = catalog.remember(
        SimpleNamespace(id=uuid4()), uuid4(),
        {"url": "https://example.invalid/guide/iteration", "title": "Iteration basics"},
        demand_input(uuid4(), framework="junit"),
    )
    assert item["frameworks"] == []


def test_catalog_is_read_before_search_and_only_one_entry_is_registered(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("first"), entry("second"))
    monkeypatch.setattr(
        MaterialWebWorkflow, "ensure_search",
        lambda *_a, **_k: pytest.fail("A matching catalogue entry must precede search"),
    )
    settings, goal, _demand, discovery = automatic
    MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    with database.transaction() as connection:
        sources = MaterialSources(connection).list(session.actor, goal.id)
        assert len(sources) == 1 and sources[0].basis == "learning_catalog"
        assert sources[0].entry_url == entry("first")["url"]
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.source_observations WHERE source_id=%s",
            (sources[0].id,),
        ).fetchone()["n"] == 1
        assert not connection.execute(
            "SELECT 1 FROM knowledge.material_web_requests WHERE discovery_id=%s", (discovery.id,),
        ).fetchone()


def test_known_forbidden_page_automatically_changes_source_and_keeps_the_failure(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("first"), entry("second"))
    settings, goal, _demand, discovery = automatic
    workflow = MaterialDiscoveryWorkflow(database, settings)
    workflow.execute(discovery.id)
    with database.transaction() as connection:
        first = connection.execute(
            "SELECT o.id FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_registrations s ON s.id=o.source_id "
            "WHERE s.goal_id=%s", (goal.id,),
        ).fetchone()["id"]
    MaterialSourceWorkflow(database, settings).execute(
        first, httpx.MockTransport(lambda _request: httpx.Response(403)),
    )
    workflow.execute(discovery.id)
    with database.transaction() as connection:
        assert len(MaterialSources(connection).list(session.actor, goal.id)) == 2
        failed = MaterialSources(connection).observation(session.actor, first)
        assert failed.status == "waiting_dependency" and failed.response_status == 403
        assert current(database, session, discovery).status == "queued"
        assert not connection.execute(
            "SELECT 1 FROM knowledge.material_web_requests WHERE discovery_id=%s", (discovery.id,),
        ).fetchone()


def test_example_lookup_reuses_the_search_and_counts_readable_bodies_after_a_legacy_stop(
    database, session, automatic, rag, monkeypatch,
):
    settings, goal, *_ = automatic
    choose(monkeypatch)
    workflow = MaterialDiscoveryWorkflow(database, settings)
    sources = MaterialSourceWorkflow(database, settings)
    gaps = ["iteration"]
    urls = [entry(name)["url"] for name in ("oversize", "denied", "third", "fourth", "unused")]
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"node-material:{uuid4()}:teaching", demand_input(goal.id),
        )
        discovery = workflow.ensure_in(connection, session.actor, Identity.digest(session.token),
                                       demand)
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
            (Jsonb({"node_example_lookup": {"gaps": gaps, "remaining": gaps, "attempted": [],
                                            "reviewed": []}}), discovery.id),
        )

    def advance():
        with database.transaction() as connection:
            actor, row, demand = workflow.current(connection, discovery.id)
            MaterialAcquisition(workflow).acquire(
                connection, actor, row, demand, gaps, examples=True,
            )

    advance()
    searches, fetched = [], []

    def search(request):
        searches.append(request.url.path)
        return httpx.Response(200, json={"results": [{"url": url, "title": "Java iteration"}
                                                      for url in urls]})

    def fetch(request):
        fetched.append(request.headers["host"])
        if fetched[-1] == "oversize.invalid":
            return httpx.Response(200, headers={"Content-Type": "text/html"},
                                  stream=httpx.ByteStream(b"<main>bad\x00text</main>"))
        return httpx.Response(403) if fetched[-1] == "denied.invalid" else page(request)

    web = MaterialWebWorkflow(database, settings)
    web.advance_search(discovery.id, httpx.MockTransport(search))
    for index, url in enumerate(urls[:4]):
        if index == 2:
            with database.transaction() as connection:
                connection.execute(
                    "UPDATE knowledge.material_discovery_jobs SET status='waiting_dependency',"
                    "error_code='material_discovery_exhausted',acquisition_state="
                    "(acquisition_state #- '{node_example_lookup,deadline_at}' "
                    "#- '{node_example_lookup,readable}')"
                    "||'{\"exhausted\":true}'::jsonb WHERE id=%s", (discovery.id,),
                )
            previous = workflow.get(session.token, demand.id)
            assert previous.error_code == "material_discovery_exhausted"
            assert workflow.ensure(session.token, demand.id).id == discovery.id
        advance()
        with database.transaction(snapshot=True) as connection:
            observation = connection.execute(
                "SELECT o.id,r.url FROM knowledge.source_observations o "
                "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
                "WHERE o.actor_id=%s AND o.status='queued'", (session.actor.id,),
            ).fetchall()
        assert len(observation) == 1 and observation[0]["url"] == url
        sources.execute(observation[0]["id"], httpx.MockTransport(fetch))
        result = sources.observation(session.token, observation[0]["id"])
        if index < 2:
            assert result.error_code == ("material_text_limit", "source_http_unavailable")[index]
        else:
            result = finish_observed((sources, settings, None, None), session, rag, result)
            assert result.document_id and result.status == "changed"
    advance()
    stopped = workflow.ensure(session.token, demand.id)
    assert stopped.error_code == "material_discovery_exhausted" and stopped.missing_facets == gaps
    web.advance_search(discovery.id, httpx.MockTransport(search))
    assert searches == ["/search"] and fetched == [url.split("/")[2] for url in urls[:4]]
    with database.transaction(snapshot=True) as connection:
        lookup = connection.execute(
            "SELECT acquisition_state->'node_example_lookup' AS lookup "
            "FROM knowledge.material_discovery_jobs WHERE id=%s", (discovery.id,),
        ).fetchone()["lookup"]
    assert lookup["attempted"] == urls[:4] and set(lookup["readable"]) == set(urls[2:4])


@pytest.mark.parametrize("failure", ["timeout", "http_503"])
def test_unavailable_public_page_finishes_with_a_replacement_and_is_not_background_retried(
    database, session, automatic, monkeypatch, failure,
):
    choose(monkeypatch, entry("first"), entry("second"))
    fetched = []

    def fetch(request):
        host = request.headers["host"]
        fetched.append(host)
        if host == "first.invalid":
            if failure == "http_503":
                return httpx.Response(503)
            raise httpx.ReadTimeout("Public page interrupted.", request=request)
        return page(request)

    settings, goal, _demand, discovery = automatic
    MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    with database.transaction(snapshot=True) as connection:
        first = connection.execute(
            "SELECT o.id FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_registrations s ON s.id=o.source_id "
            "WHERE s.goal_id=%s", (goal.id,),
        ).fetchone()["id"]
    MaterialSourceWorkflow(database, settings).execute(first, httpx.MockTransport(fetch))
    with database.transaction() as connection:
        failed = connection.execute(
            "SELECT o.id,o.resource_id,o.status,o.error_code FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
            "WHERE r.url=%s AND o.actor_id=%s",
            (entry("first")["url"], session.actor.id),
        ).fetchone()
        assert failed["status"] == "waiting_dependency"
        assert failed["error_code"] == (
            "source_network_unavailable" if failure == "timeout" else "source_http_unavailable"
        )
        connection.execute(
            "UPDATE knowledge.material_source_resources SET next_check_at=now() WHERE id=%s",
            (failed["resource_id"],),
        )
    scan_material_sources_once(database, settings, limit=10000)
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT id FROM knowledge.source_observations WHERE resource_id=%s",
            (failed["resource_id"],),
        ).fetchall() == [{"id": failed["id"]}]
    result = drive(database, session, automatic, httpx.MockTransport(fetch))
    assert result.status == "ready"
    assert fetched == ["first.invalid", "second.invalid"]
    with database.transaction() as connection:
        selection = Retrieval(connection).selection(session.actor, result.selection_id)
        assert all("second.invalid" in item.source_url for item in selection.evidence)


@pytest.mark.parametrize("provider", ["direct", "tavily"])
def test_historical_public_read_unknown_can_be_skipped_but_paid_extraction_still_blocks(
    database, session, automatic, monkeypatch, provider,
):
    choose(monkeypatch, entry("first"), entry("second"))
    settings, goal, _demand, discovery = automatic
    workflow = MaterialDiscoveryWorkflow(database, settings)
    workflow.execute(discovery.id)
    with database.transaction() as connection:
        first = connection.execute(
            "SELECT o.id FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_registrations s ON s.id=o.source_id "
            "WHERE s.goal_id=%s", (goal.id,),
        ).fetchone()["id"]
        connection.execute(
            "UPDATE knowledge.source_observations SET status='blocked_unknown',"
            "error_code='source_read_unknown',dispatched_at=now(),"
            "request_identity=request_identity||%s WHERE id=%s",
            (Jsonb({"acquisition_provider": provider} if provider != "direct" else {}), first),
        )
    workflow.execute(discovery.id)
    with database.transaction(snapshot=True) as connection:
        unchanged = MaterialSources(connection).observation(session.actor, first)
        assert unchanged.status == "blocked_unknown"
        assert unchanged.error_code == "source_read_unknown"
        assert len(MaterialSources(connection).list(session.actor, goal.id)) == (
            2 if provider == "direct" else 1
        )
    assert current(database, session, discovery).status == (
        "queued" if provider == "direct" else "blocked_unknown"
    )


def test_unresolved_html_returns_to_parent_and_rotates_away_from_a_stalled_site(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("first"), entry("second"))
    fetched = []

    def fetch(request):
        host = request.headers.get("host", request.url.host)
        fetched.append(host)
        if host == "first.invalid":
            return httpx.Response(
                200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(
                    b"<main><h1>Iteration examples</h1><p>The diagram is required.</p>"
                    b"<svg><path d='M0 0L5 5'/></svg>"
                    b"<a href='/guide/iteration/chapter1'>Iteration examples 1</a>"
                    b"<a href='/guide/iteration/chapter2'>Iteration examples 2</a></main>"
                ),
            )
        return page(request)

    checks = []

    def review(request):
        data = json.loads(json.loads(request.content)["messages"][1]["content"])
        checks.append(data)
        parts, children = data["source_parts"], data["complete_child_summaries"]
        refs = [part["reference_key"] for part in parts]
        missing = bool(parts and any(
            document.get("unresolved_regions") for document in data["source_documents"]
        ))
        if children:
            missing = not any(child["evidence_refs"] for child in children)
        evidence = refs if not children else [
            ref for child in children for ref in child["evidence_refs"]
        ]
        result = {
            "status": "missing" if missing else "supported",
            "summary": "The diagram is required." if missing else "The text explains iteration.",
            "evidence_refs": [] if missing else evidence[:8],
            "reviewed_refs": refs,
            "reviewed_parts": [child["id"] for child in children],
            "issues": ["incomplete"] if missing else [],
            "missing_topics": ["iteration examples"] if missing else [],
        }
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": json.dumps(result)},
            "finish_reason": "stop",
        }]})

    gateway = ChatCompletionsGateway(automatic[0], httpx.MockTransport(review))
    result = drive(database, session, automatic, httpx.MockTransport(fetch), gateway=gateway)
    assert result.status == "ready"
    assert 1 <= fetched.count("first.invalid") <= 3
    assert fetched.count("second.invalid") == 1
    with database.transaction() as connection:
        partials = connection.execute(
            "SELECT v.processing_state,v.unresolved_regions,j.prepared_scope,j.issues "
            "FROM knowledge.material_jobs j JOIN knowledge.document_versions v "
            "ON v.document_id=j.document_id AND v.revision=j.document_revision "
            "JOIN knowledge.material_demands d ON d.id=j.demand_id WHERE d.goal_id=%s",
            (automatic[1].id,),
        ).fetchall()
        assert any(
            item["processing_state"] == "partial" and item["unresolved_regions"]
            and item["prepared_scope"]["basis"] == "selected-source-text.v1"
            and item["issues"] == [] for item in partials
        )
    assert any(
        document.get("unresolved_regions")
        for check in checks for document in check["source_documents"]
    )
    assert all(
        "unresolved_regions" not in part for check in checks for part in check["source_parts"]
    )


def test_optional_graphic_does_not_block_checked_source_text(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("text-with-diagram"))

    def fetch(_request):
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(
            b"<main><h1>Iteration</h1><p>A loop visits every item.</p>"
            b"<pre>for (var item : items) { System.out.println(item); }</pre>"
            b'<img src="/optional.svg" alt="Optional overview"></main>',
        ))

    status = drive(database, session, automatic, httpx.MockTransport(fetch))
    assert status.status == "ready"
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT v.processing_state,v.unresolved_regions,j.prepared_scope "
            "FROM knowledge.material_jobs j JOIN knowledge.material_demands d ON d.id=j.demand_id "
            "JOIN knowledge.document_versions v ON v.document_id=j.document_id "
            "AND v.revision=j.document_revision WHERE d.goal_id=%s AND j.state='ready'",
            (automatic[1].id,),
        ).fetchone()
        assert row["processing_state"] == "partial" and row["unresolved_regions"]
        assert row["prepared_scope"]["basis"] == "selected-source-text.v1"


def test_acquisition_budget_survives_automatic_successor_batches(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("first"), entry("second"))
    settings, goal, demand, discovery = automatic
    workflow = MaterialDiscoveryWorkflow(database, settings)
    workflow.execute(discovery.id)
    monkeypatch.setattr(MaterialWebWorkflow, "ensure_search", lambda *_a, **_k: False)
    with database.transaction() as connection:
        sources = MaterialSources(connection)
        source = sources.list(session.actor, goal.id)[0]
        acquisition = MaterialAcquisition(workflow)
        _actor, row, _demand = workflow.current(connection, discovery.id)
        for index in range(1, 12):
            resource = sources.add_resource(
                source.id, f"https://first.invalid/guide/iteration/chapter{index}", 1,
                label="Iteration examples", order=index,
            )
            acquisition.schedule(
                connection, session.actor, row, demand, resource, ["iteration examples"],
            )
        connection.execute(
            "UPDATE knowledge.source_observations SET status='waiting_dependency',"
            "error_code='source_http_unavailable',recorded_at=now(),response_status=403 "
            "WHERE source_id=%s", (source.id,),
        )
        acquisition.acquire(connection, session.actor, row, demand, ["iteration examples"])
        root, budget, _family = acquisition.budget(connection, session.actor, row)
        assert budget["read_limit"] == 16 and len(budget["grants"]) == 1
        successor = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, str(uuid4()), demand_input(goal.id, goal_text="Iteration examples next"),
        )
        next_job = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), successor,
        )
        sources.inherit_acquisition_budget(
            session.actor, demand.id, successor.id, chain_started_at=row["created_at"],
        )
        _actor, next_row, _demand = workflow.current(connection, next_job.id)
        inherited_root, inherited_budget, family = acquisition.budget(
            connection, session.actor, next_row,
        )
        assert inherited_root["id"] == root["id"] and inherited_budget == budget
        assert {item["id"] for item in family} == {discovery.id, next_job.id}
        # A new learner turn must not inherit an earlier turn's exhausted budget.
        fresh = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, str(uuid4()), demand_input(goal.id, goal_text="Fresh requested scope"),
        )
        fresh_job = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), fresh,
        )
        _actor, fresh_row, _demand = workflow.current(connection, fresh_job.id)
        sources.inherit_acquisition_budget(
            session.actor, demand.id, fresh.id, chain_started_at=fresh_row["created_at"],
        )
        _actor, fresh_row, _demand = workflow.current(connection, fresh_job.id)
        fresh_root, fresh_budget, fresh_family = acquisition.budget(
            connection, session.actor, fresh_row,
        )
        assert fresh_root["id"] == fresh_job.id and fresh_budget == {}
        assert len(fresh_family) == 1


@pytest.mark.parametrize("retained_public,search_rounds", [(False, 0), (True, 0), (True, 1)])
def test_catalogue_reads_leave_room_for_targeted_search_before_the_total_read_limit(
    database, session, automatic, monkeypatch, retained_public, search_rounds,
):
    choose(monkeypatch, entry("first"), entry("second"))
    settings, goal, demand, discovery = automatic
    workflow = MaterialDiscoveryWorkflow(database, settings)
    workflow.execute(discovery.id)
    searched = []
    monkeypatch.setattr(
        MaterialWebWorkflow, "ensure_search",
        lambda *_args, **_kwargs: searched.append(True) or True,
    )
    with database.transaction() as connection:
        sources = MaterialSources(connection)
        source = sources.list(session.actor, goal.id)[0]
        if retained_public:
            sources.register(
                session.actor, Identity.digest(session.token), "retained-public",
                candidate_source(demand, entry("retained")),
                catalog_id="discovered:retained", basis="public_discovery",
            )
        acquisition = MaterialAcquisition(workflow)
        for index in range(1, 8):
            resource = sources.add_resource(
                source.id, f"https://first.invalid/guide/iteration/chapter{index}", 1,
                label="Iteration examples", order=index,
            )
            acquisition.schedule(
                connection, session.actor, {"id": discovery.id, "session_digest": Identity.digest(
                    session.token,
                )}, demand, resource, [demand.goal_text],
            )
        connection.execute(
            "UPDATE knowledge.source_observations SET status='waiting_dependency',"
            "error_code='source_http_unavailable',recorded_at=now(),response_status=403 "
            "WHERE source_id=%s", (source.id,),
        )
        if search_rounds:
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET acquisition_state=%s WHERE id=%s",
                (Jsonb({"search_rounds": search_rounds}), discovery.id),
            )
        _actor, row, current_demand = workflow.current(connection, discovery.id)
        acquisition.acquire(connection, session.actor, row, current_demand, ["iteration examples"])
        assert len(sources.list(session.actor, goal.id)) == (2 if retained_public else 1)
    assert searched == ([] if search_rounds else [True])


def test_reviewed_parts_survive_supersession_without_repeating_model_calls(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("community"))
    original = drive(database, session, automatic, httpx.MockTransport(page))
    assert original.status == "ready"
    settings, goal, demand, discovery = automatic
    with database.transaction() as connection:
        old_search = connection.execute(
            "SELECT search_id FROM knowledge.material_discovery_jobs WHERE id=%s", (discovery.id,),
        ).fetchone()["search_id"]
        connection.execute(
            "UPDATE knowledge.material_demands SET status='cancelled' WHERE id=%s", (demand.id,),
        )
        connection.execute(
            "UPDATE knowledge.material_searches SET status='cancelled' WHERE id=%s", (old_search,),
        )
        next_demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{uuid4()}", demand_input(goal.id),
        )
        next_discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), next_demand,
        )
        before = connection.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"]
    result = drive(
        database, session, (settings, goal, next_demand, next_discovery),
        httpx.MockTransport(lambda _: pytest.fail("The original source must be reused")),
    )
    assert result.status == "ready"
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"] == before
        assert connection.execute(
            "SELECT 1 FROM knowledge.material_selections WHERE id=%s "
            "AND scope ? 'reused_selection_id'", (result.selection_id,),
        ).fetchone()


@pytest.mark.parametrize("inactive", ["superseded", "exhausted"])
def test_inactive_source_preparation_pauses_and_new_consumer_reuses_its_original(
    database, session, automatic, monkeypatch, inactive,
):
    choose(monkeypatch, entry("community"))
    settings, goal, demand, discovery = automatic
    workflow = MaterialDiscoveryWorkflow(database, settings)
    workflow.execute(discovery.id)
    with database.transaction() as connection:
        observation = connection.execute(
            "SELECT o.id FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_registrations s ON s.id=o.source_id "
            "WHERE s.goal_id=%s", (goal.id,),
        ).fetchone()["id"]
    fetched = []
    MaterialSourceWorkflow(database, settings).execute(
        observation, httpx.MockTransport(
            lambda request: fetched.append(request.url) or page(request),
        ),
    )
    with database.transaction() as connection:
        job_id = MaterialSources(connection).observation(session.actor, observation).job_id
        if inactive == "superseded":
            MaterialIntake(connection).supersede_planning_consumers(
                session.actor, goal.id, [demand.consumer_ref],
            )
        else:
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET status='waiting_config',"
                "error_code='material_discovery_exhausted' WHERE id=%s", (discovery.id,),
            )
    intake = MaterialIntakeWorkflow(database, settings)
    intake.execute(job_id, material_transport())
    assert intake.job(session.token, job_id).background_deferred
    with database.transaction() as connection:
        assert not connection.execute(
            "SELECT 1 FROM runtime.external_calls WHERE actor_id=%s", (session.actor.id,),
        ).fetchone()
        next_demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{uuid4()}", demand_input(goal.id),
        )
        next_discovery = workflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), next_demand,
        )
    result = drive(
        database, session, (settings, goal, next_demand, next_discovery),
        httpx.MockTransport(lambda _: pytest.fail("Retained source must not be fetched again")),
    )
    assert result.status == "ready" and len(fetched) == 1
    assert not intake.job(session.token, job_id).background_deferred


def test_child_cancellation_settles_its_waiting_observation(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("community"))
    settings, goal, _demand, discovery = automatic
    MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    with database.transaction() as connection:
        observation = connection.execute(
            "SELECT o.id FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_registrations s ON s.id=o.source_id "
            "WHERE s.goal_id=%s", (goal.id,),
        ).fetchone()["id"]
    source = MaterialSourceWorkflow(database, settings)
    source.execute(observation, httpx.MockTransport(page))
    child = source.observation(session.token, observation).job_id
    MaterialIntakeWorkflow(database, settings).cancel(session.token, child)
    assert source.observation(session.token, observation).status == "cancelled"


def test_catalogue_material_finishes_all_owned_checks_without_any_search(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("community"))
    monkeypatch.setattr(
        MaterialWebWorkflow, "ensure_search",
        lambda *_a, **_k: pytest.fail("Sufficient catalogue material needs no search"),
    )
    status = drive(database, session, automatic, httpx.MockTransport(page))
    assert status.status == "ready"
    with database.transaction() as connection:
        selection = Retrieval(connection).selection(session.actor, status.selection_id)
        assert selection.coverage.status == "sufficient" and selection.evidence
        assert all(item.source_url == entry("community")["url"] for item in selection.evidence)
        assert MaterialPreparation(connection).for_demand(
            session.actor, automatic[2].id,
        ).status == "ready"


def test_identical_checked_task_reuses_text_index_and_verdict_without_provider_calls(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("community"))
    status = drive(database, session, automatic, httpx.MockTransport(page))
    assert status.status == "ready"
    settings, goal, demand, _discovery = automatic
    with database.transaction() as connection:
        next_demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{uuid4()}", demand_input(goal.id),
        )
        next_discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), next_demand,
        )
        before = connection.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"]
    monkeypatch.setattr(
        MaterialDiscoveryWorkflow, "acquire",
        lambda *_a, **_k: pytest.fail("Checked identical materials must be reused"),
    )
    MaterialDiscoveryWorkflow(database, settings).execute(next_discovery.id)
    result = current(database, session, next_discovery)
    assert result.status == "ready" and result.selection_id != status.selection_id
    with database.transaction() as connection:
        selection = Retrieval(connection).selection(session.actor, result.selection_id)
        assert selection.demand_id == next_demand.id and selection.demand_id != demand.id
        assert connection.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE actor_id=%s",
            (session.actor.id,),
        ).fetchone()["n"] == before


def test_missing_catalogue_searches_public_sources_and_saves_candidates_for_later(
    database, session, automatic, monkeypatch,
):
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_candidates.catalog_resources", lambda: [],
    )
    settings, _goal, _demand, discovery = automatic
    seen = []

    def search(request):
        wire = json.loads(request.content)
        seen.append(wire)
        assert "include_domains" not in wire and wire["max_results"] == 8
        return httpx.Response(200, json={"results": [
            {"title": "Java iteration community guide", "url": entry("discovered")["url"]},
            {"title": "Private source", "url": "https://127.0.0.1/private"},
            {"title": "Paid course", "url": "https://course.invalid/subscribe/required"},
        ]})

    result = drive(
        database, session, automatic, httpx.MockTransport(page),
        search_transport=httpx.MockTransport(search),
    )
    assert result.status == "ready" and len(seen) == 1
    with database.transaction() as connection:
        entries = DiscoveredSourceCatalog(connection).entries(session.actor)
        assert len(entries) == 1 and entries[0]["url"] == entry("discovered")["url"]
        other_actor = SimpleNamespace(id=uuid4())
        assert DiscoveredSourceCatalog(connection).entries(other_actor) == []
        registrations = MaterialSources(connection).list(session.actor, automatic[1].id)
        assert registrations[0].basis == "public_discovery"


def test_empty_search_stops_after_two_recorded_rounds_with_explicit_gaps(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch)
    settings, _goal, demand, discovery = automatic
    seen = []

    def empty(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    web = MaterialWebWorkflow(database, settings)
    for _ in range(5):
        web.advance_search(discovery.id, httpx.MockTransport(empty))
        MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    result = current(database, session, discovery)
    assert result.error_code == "material_discovery_exhausted" and len(seen) == 2
    assert result.missing_facets == [demand.goal_text]


def test_unknown_search_keeps_one_call_and_does_not_search_an_alternative(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch)
    settings, _goal, _demand, discovery = automatic
    MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    seen = []

    def interrupted(request):
        seen.append(request.url.path)
        raise httpx.ReadTimeout("unknown result", request=request)

    for _ in range(2):
        with pytest.raises(BusinessError, match="未知"):
            MaterialWebWorkflow(database, settings).advance_search(
                discovery.id, httpx.MockTransport(interrupted),
            )
    assert seen == ["/search"]


def coverage_gateway(settings, *, defect=None, page_threshold=None):
    seen = []

    def check(request):
        data = json.loads(json.loads(request.content)["messages"][1]["content"])
        seen.append(data)
        children = data["complete_child_summaries"]
        first = any("first.invalid" in item["source_url"] for item in data["source_parts"])
        if page_threshold is not None:
            first = any(
                item["source_page"] < page_threshold for item in data["source_parts"]
            )
        bad = first and defect is not None
        refs = [item["reference_key"] for item in data["source_parts"]]
        evidence = refs if not children else [
            item["reference_key"] for item in data["reference_catalog"]
        ]
        status = "uncertain" if bad else (
            "partial" if not children and defect is None else "supported"
        )
        result = {
            "status": status,
            "summary": "The current sources describe iteration; a second part adds exceptions.",
            "evidence_refs": evidence[:8], "reviewed_refs": refs,
            "reviewed_parts": [child["id"] for child in children],
            "issues": [defect] if bad and defect != "unverified" else [],
            "missing_topics": ["Java iteration exceptions"] if status != "supported" else [],
        }
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": json.dumps(result)},
            "finish_reason": "stop",
        }], "usage": {"prompt_tokens": 50, "completion_tokens": 60}})

    return ChatCompletionsGateway(settings, httpx.MockTransport(check)), seen


@pytest.mark.parametrize("defect", ["version_mismatch", "incorrect", "unverified"])
def test_checked_version_or_factual_defect_replaces_only_the_bad_source(
    database, session, automatic, monkeypatch, defect,
):
    choose(monkeypatch, entry("first"), entry("second"))
    gateway, seen = coverage_gateway(automatic[0], defect=defect)
    result = drive(database, session, automatic, httpx.MockTransport(page), gateway=gateway)
    assert result.status == "ready" and len(seen) == 2
    with database.transaction() as connection:
        selection = Retrieval(connection).selection(session.actor, result.selection_id)
        assert all("second.invalid" in item.source_url for item in selection.evidence)
        recorded = connection.execute(
            "SELECT acquisition_state FROM knowledge.material_discovery_jobs WHERE id=%s",
            (result.id,),
        ).fetchone()["acquisition_state"]
        assert len(recorded["excluded_versions"]) == 1


def test_supplemental_search_reuses_already_checked_source_parts(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("first"), entry("second"))
    settings, goal, demand, _discovery = automatic
    with database.transaction() as connection:
        complete = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{goal.id}:gap:{uuid4()}",
            MaterialDemandInput(**{
                **demand.model_dump(include=set(MaterialDemandInput.model_fields)),
                "preparation": "complete",
            }),
        )
        discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), complete,
        )
    gateway, seen = coverage_gateway(settings)
    result = drive(
        database, session, (settings, goal, complete, discovery),
        httpx.MockTransport(page), gateway=gateway,
    )
    assert result.status == "ready" and len(seen) == 3
    assert sum(any("first.invalid" in part["source_url"] for part in item["source_parts"])
               for item in seen) == 1
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.material_goal_coverage_parts p "
            "JOIN knowledge.material_searches s ON s.id=p.search_id "
            "WHERE s.actor_id=%s AND p.reused_part_id IS NOT NULL", (session.actor.id,),
        ).fetchone()["n"] >= 1


def test_pdf_book_selection_uses_only_the_requested_chapter_and_original_page_numbers():
    metadata = {"page_count": 300, "outline": [
        {"title": "Java introduction", "page": 1, "depth": 0},
        {"title": "Java iteration", "page": 101, "depth": 0},
        {"title": "Exceptions", "page": 121, "depth": 0},
    ]}
    assert selected_pdf_pages(metadata, ["iteration"]) == list(range(101, 121))
    assert selected_pdf_pages({"page_count": 300}, ["iteration"]) == [1, 2, 3, 4]


def test_pdf_chapters_reuse_the_retained_original_without_reloading_or_reparsing_the_book(
    database, session, automatic, monkeypatch,
):
    choose(monkeypatch, entry("book"))
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(io.BytesIO(pdf_bytes([
        "Java iteration examples" if page < 121 else "Java exceptions examples"
        for page in range(1, 131)
    ]))))
    writer.add_outline_item("Introduction", 0)
    writer.add_outline_item("Iteration", 100)
    writer.add_outline_item("Exceptions", 120)
    stream = io.BytesIO()
    writer.write(stream)
    reads = []

    def book(request):
        reads.append(request.url.path)
        return httpx.Response(
            200, headers={"content-type": "application/pdf"},
            stream=httpx.ByteStream(stream.getvalue()),
        )

    settings, goal, demand, _discovery = automatic
    first = drive(database, session, automatic, httpx.MockTransport(book))
    assert first.status == "ready" and len(reads) == 1
    with database.transaction() as connection:
        next_demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{uuid4()}",
            MaterialDemandInput(**{
                **demand.model_dump(include=set(MaterialDemandInput.model_fields)),
                "goal_text": "Java exceptions",
            }),
        )
        next_discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), next_demand,
        )
    gateway, _seen = coverage_gateway(settings, defect="irrelevant", page_threshold=121)
    second = drive(
        database, session, (settings, goal, next_demand, next_discovery),
        httpx.MockTransport(book), gateway=gateway,
    )
    assert second.status == "ready" and len(reads) == 1
    with database.transaction() as connection:
        selection = Retrieval(connection).selection(session.actor, second.selection_id)
        assert all(item.source_page >= 121 for item in selection.evidence)
        scopes = connection.execute(
            "SELECT u.specification->'selected_pages' AS pages FROM knowledge.material_uploads u "
            "JOIN knowledge.material_source_registrations s ON s.id=u.source_id "
            "WHERE s.goal_id=%s ORDER BY u.created_at", (goal.id,),
        ).fetchall()
        assert [row["pages"] for row in scopes] == [
            list(range(101, 121)), list(range(121, 131)),
        ]


def test_checked_supplement_extends_the_live_binding_with_cas_and_preserves_its_predecessor(
    database, session, automatic, monkeypatch, rag,
):
    choose(monkeypatch, entry("first"), entry("second"))
    settings, goal, original_demand, _discovery = automatic
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{goal.id}:gap:{uuid4()}",
            MaterialDemandInput(**{
                **original_demand.model_dump(include=set(MaterialDemandInput.model_fields)),
                "preparation": "complete",
            }),
        )
        discovery = MaterialDiscoveryWorkflow.ensure_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
    MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    with database.transaction() as connection:
        source = MaterialSources(connection).list(session.actor, goal.id)[0]
        observation = connection.execute(
            "SELECT id FROM knowledge.source_observations WHERE source_id=%s", (source.id,),
        ).fetchone()["id"]
    source_workflow = MaterialSourceWorkflow(database, settings)
    source_workflow.execute(observation, httpx.MockTransport(page))
    prepared = finish_observed(
        (source_workflow, settings, source, None), session, rag,
        source_workflow.observation(session.token, observation),
    )
    materials = MaterialWorkflow(database, settings)
    refs = [block.ref for block in materials.blocks(
        session.token, prepared.document_id, prepared.document_revision, "planning",
    ).blocks]
    binding = materials.bind(session.token, str(uuid4()), MaterialBindingInput(
        goal_id=goal.id, purpose="planning", expected_binding_revision=0, refs=refs,
    ))
    gateway, _seen = coverage_gateway(settings)
    result = drive(
        database, session, (settings, goal, demand, discovery),
        httpx.MockTransport(page), gateway=gateway,
    )
    assert result.status == "ready"
    with database.transaction() as connection:
        ensure_consumer_material_in(
            connection, session.actor, Identity.digest(session.token), demand,
        )
        bindings = MaterialBindings(connection)
        latest = bindings.for_scope(session.actor, goal.id, "planning")[0]
        assert latest.revision == binding.revision + 1 and len(latest.refs) > len(binding.refs)
        assert bindings.get(session.actor, binding.id, binding.revision) == binding


@pytest.mark.parametrize("inactive", ["superseded", "exhausted"])
def test_inactive_material_task_does_not_dispatch_a_queued_public_read(
    database, session, automatic, monkeypatch, inactive,
):
    choose(monkeypatch, entry("first"))
    settings, goal, demand, discovery = automatic
    MaterialDiscoveryWorkflow(database, settings).execute(discovery.id)
    with database.transaction() as connection:
        source = MaterialSources(connection).list(session.actor, goal.id)[0]
        observation = connection.execute(
            "SELECT id FROM knowledge.source_observations WHERE source_id=%s", (source.id,),
        ).fetchone()["id"]
        if inactive == "superseded":
            MaterialIntake(connection).supersede_planning_consumers(
                session.actor, goal.id, [demand.consumer_ref],
            )
        else:
            connection.execute(
                "UPDATE knowledge.material_discovery_jobs SET status='waiting_config',"
                "error_code='material_discovery_exhausted' WHERE id=%s", (discovery.id,),
            )
    MaterialSourceWorkflow(database, settings).execute(
        observation, httpx.MockTransport(lambda _: pytest.fail("Inactive work read a source")),
    )
    with database.transaction() as connection:
        result = MaterialSources(connection).observation(session.actor, observation)
        assert result.status == "cancelled" and result.error_code == "source_task_cancelled"
