import json
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from psycopg.errors import ForeignKeyViolation
from psycopg.types.json import Jsonb
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import prepare
from test_material_processing_retrieval import rag as rag

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.loop import AgentLoop
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.material_files import MaterialFilesWorkflow
from leornian.bootstrap.material_goal_coverage import MaterialGoalCoverageWorkflow
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.material_sources import MaterialSourceWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.bootstrap.planning_materials import PlanningMaterials
from leornian.bootstrap.route_discussion import RouteDiscussionReply
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.knowledge.file_contracts import (
    FileMaterialInput,
    MaterialFileJobInput,
    MaterialUploadInput,
)
from leornian.modules.knowledge.file_parser import HTML_MAIN_PARSER_VERSION, parse_file
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput, MaterialTextJobInput
from leornian.modules.knowledge.material_contracts import (
    DocumentPermissionAction,
    TextMaterialImport,
)
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.knowledge.source_contracts import MaterialSourceAction, MaterialSourceInput
from leornian.modules.knowledge.source_extraction import SourceLinks
from leornian.modules.learning.contracts import GoalInput, GoalMaterialScope
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.tutor.contracts import PlanningInput
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.platform.config import Settings
from leornian.platform.model_contracts import ModelConnectionInput, ModelProfileInput
from leornian.shared_kernel.errors import BusinessError


def test_planning_gap_reuses_ready_private_material_before_requesting_another_source(
    database, session, rag, monkeypatch
):
    prepared = prepare(rag, session)
    discovery = MaterialDiscoveryWorkflow(database, rag["settings"])

    def unexpected_acquisition(*_):
        pytest.fail(
            "Existing authorized material must be searched before acquiring another source."
        )

    monkeypatch.setattr(discovery, "acquire", unexpected_acquisition)
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{rag['goal'].id}:gap:existing-private-source",
            MaterialDemandInput(
                goal_id=rag["goal"].id, purpose="planning", scope_mode="teaching_goal",
                goal_text="Find the supplied explanation and examples of iteration.",
            ),
        )
        pending = discovery.ensure_in(
            connection, session.actor, Identity.digest(session.token), demand
        )
        actor, row, current = discovery.current(connection, pending.id)
        request = discovery.semantic_input(connection, actor, row, current)
        assert request is not None
        assert request.demand_id == demand.id
        assert any(
            source.document_id == prepared.document_id for source in request.source_versions
        )


def test_ready_planning_batch_merges_into_a_later_binding_without_reusing_its_old_command(
    database, session, rag, monkeypatch,
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    prepare(rag, session)
    settings = replace(rag["settings"], model_enabled=True)
    configure_goal_models(database, session, settings)
    digest = Identity.digest(session.token)
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{rag['goal'].id}:binding-successor",
            MaterialDemandInput(
                goal_id=rag["goal"].id, purpose="planning", scope_mode="teaching_goal",
                goal_text="Explain iteration using the supplied sequence example.",
            ),
        )
        with pytest.raises(BusinessError, match="pending"):
            PlanningMaterials.ready_in(connection, session.actor, digest, demand)
    advance_consumer_materials(database, session, settings, rag["goal"].id)
    with database.transaction() as connection:
        selection = PlanningMaterials.ready_in(connection, session.actor, digest, demand)
        original = MaterialBindings(connection).for_scope(
            session.actor, rag["goal"].id, "planning",
        )[0]
    assert len(original.refs) > 1
    successor = rag["materials"].bind(
        session.token, str(uuid4()), MaterialBindingInput(
            goal_id=rag["goal"].id, purpose="planning",
            expected_binding_revision=original.revision, refs=original.refs[:1],
        ),
    )
    with database.transaction() as connection:
        assert PlanningMaterials.ready_in(connection, session.actor, digest, demand) == selection
        bindings = MaterialBindings(connection)
        merged = bindings.for_scope(session.actor, rag["goal"].id, "planning")[0]
        assert merged.revision == successor.revision + 1
        assert merged.refs == original.refs
        assert bindings.get(session.actor, original.id, original.revision) == original
        assert bindings.get(session.actor, successor.id, successor.revision) == successor
        assert PlanningMaterials.ready_in(connection, session.actor, digest, demand) == selection
        assert bindings.for_scope(session.actor, rag["goal"].id, "planning")[0] == merged


def test_java_route_shortlists_related_sources_but_registers_only_the_selected_entry(
    database, workflow, session, rag,
):
    accepted = workflow.submit(session.token, str(uuid4()), GoalInput(
        title="Java backend",
        material_scope=GoalMaterialScope(
            language="java", framework="Spring Boot", authorized_official_sources=True,
        ),
    ))
    with database.transaction() as connection:
        event = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (accepted.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event)
    goal = next(g for g in workflow.snapshot(session.token).goals if g.title == "Java backend")
    discovery_workflow = MaterialDiscoveryWorkflow(database, rag["settings"])
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{goal.id}:java-official-route",
            MaterialDemandInput(
                goal_id=goal.id, purpose="planning", scope_mode="teaching_goal",
                language="java", framework="Spring Boot", preparation="complete",
                goal_text="Java, Maven, JUnit, MySQL, Spring dependency injection and Spring Boot.",
            ),
        )
        sources = MaterialSources(connection)
        assert sources.list(session.actor, goal.id) == []
        discovery = sources.ensure_discovery(session.actor, Identity.digest(session.token), demand)
        row = connection.execute(
            "SELECT * FROM knowledge.material_discovery_jobs WHERE id=%s", (discovery.id,),
        ).fetchone()
        shortlist = discovery_workflow.catalog_in(connection, session.actor, demand)
        assert 6 <= len(shortlist) <= 12
        discovery_workflow.acquire(connection, session.actor, row, demand, [demand.goal_text])
        registered = sources.list(session.actor, goal.id)
        assert len(registered) == 1
        assert all(source.basis == "official_catalog" for source in registered)
        assert sources.discovery(session.actor, demand.id, demand.revision).status == "queued"
        selected = connection.execute(
            "SELECT DISTINCT source_id FROM knowledge.source_observations "
            "WHERE actor_id=%s AND source_id=ANY(%s)",
            (session.actor.id, [source.id for source in registered]),
        ).fetchall()
        assert len(selected) == 1
        discovery_workflow.acquire(connection, session.actor, row, demand, [demand.goal_text])
        assert len(sources.list(session.actor, goal.id)) == 1
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.source_observations WHERE source_id=ANY(%s)",
            ([source.id for source in registered],),
        ).fetchone()["n"] == 1


PAGE = (
    "<html><nav><p>navigation release {noise}</p></nav><main><h1>Iteration</h1>"
    "<p>A loop visits every item in a sequence.</p>"
    "<pre>for item in items:\n    print(item{change})\n</pre>"
    "<a href='/approved/next'>Next chapter</a></main></html>"
)


def test_automatic_official_materials_and_preplanning_upload_share_one_goal_and_search(
    database, workflow, session, rag, monkeypatch,
):
    from fastapi.testclient import TestClient

    from leornian.entrypoints.api import create_app

    monkeypatch.setattr("leornian.modules.knowledge.source_network.resolve_destination",
                        lambda *_: "1.1.1.1")
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings = replace(rag["settings"], delivery_enabled=True)
    configure_goal_models(database, session, settings)
    accepted = workflow.submit(
        session.token, str(uuid4()), GoalInput(
            title="New learning plan",
            material_scope=GoalMaterialScope(authorized_official_sources=True),
        ),
    )
    with database.transaction() as connection:
        event = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (accepted.job_id,),
        ).fetchone()["event_id"]
    workflow.process_goal(event)
    goal = next(g for g in workflow.snapshot(session.token).goals if g.title == "New learning plan")
    files = MaterialFilesWorkflow(database, settings)
    intake = MaterialIntakeWorkflow(database, settings)
    demand = intake.create_demand(session.token, str(uuid4()), MaterialDemandInput(
        goal_id=goal.id, purpose="reference", scope_mode="whole_source",
    ))
    content = b"# Iteration\n\nMy textbook: a loop visits every item in a sequence."
    upload = files.reserve(session.token, demand.id, str(uuid4()), MaterialUploadInput(
        expected_demand_revision=demand.revision, content_digest=sha256(content).hexdigest(),
        byte_size=len(content), material=FileMaterialInput(
            goal_id=goal.id, title="My textbook", format="markdown", authorized_use=True,
            purposes=["reference", "indexing", "planning", "teaching"],
        ),
    ))
    files.store_content(session.token, upload.id, content)
    job = files.submit(session.token, demand.id, str(uuid4()), MaterialFileJobInput(
        expected_demand_revision=demand.revision, upload_id=upload.id,
    ))
    client = TestClient(create_app(settings))
    response = client.patch(f"/v1/goals/{goal.id}", headers={
        "Authorization": f"Bearer {session.token}",
    }, json={"title": "Python", "motivation": "Learn Python 3.12 iteration using my textbook."})
    assert response.status_code == 200
    updated = next(g for g in workflow.snapshot(session.token).goals if g.id == goal.id)
    assert updated.motivation == "Learn Python 3.12 iteration using my textbook."
    assert updated.material_scope.language is None
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, goal.id)
    turn = tutor.submit_plan(session.token, conversation.id, str(uuid4()), PlanningInput(
        text=updated.motivation, expected_revision=0, discussion=True,
    ))
    assert not any(d.purpose == "planning" for d in intake.demands(session.token, goal.id))
    # Author/review publication is covered separately; enter its checked-intent handoff here.
    with database.transaction() as connection:
        planning = PlanningMaterials.apply_in(
            connection, session.actor, conversation,
            PgTutorStore(connection).get_turn(conversation.id, turn.turn_id),
            RouteDiscussionReply.model_validate_json(json.dumps({
                "text": "Let us discuss a small first step.",
                "ready_for_route": True,
                "rag_intent": {
                    "action": "prepare", "goal": "Python iteration", "topics": ["Iteration"],
                    "reason": "The learner supplied a learning direction and their own textbook.",
                    "learner_evidence": [{
                        "source_turn_id": str(turn.turn_id), "source_quote": updated.motivation,
                    }],
                },
            })), Identity.digest(session.token),
        )
    assert planning.preparation == "initial"
    planning = next(d for d in intake.demands(session.token, goal.id) if d.purpose == "planning")
    discovery_workflow = MaterialDiscoveryWorkflow(database, settings)
    discovery = discovery_workflow.get(session.token, planning.id)
    discovery_workflow.execute(discovery.id)
    assert discovery_workflow.get(session.token, planning.id).error_code == (
        "approved_source_fetch_pending"
    )
    with database.transaction() as connection:
        assert [item.id for item in MaterialIntake(connection).pending_goal_uploads(
            session.actor, goal.id,
        )] == [job.id]
    uploaded = prepare(rag, session, job)
    sources_workflow = MaterialSourceWorkflow(database, settings)
    sources = sources_workflow.list(session.token, goal.id)
    assert len(sources) == 1 and sources[0].basis == "official_catalog"
    assert sources[0].entry_url.startswith("https://docs.python.org/3.12/")
    with database.transaction() as connection:
        observation_id = connection.execute(
            "SELECT id FROM knowledge.source_observations WHERE source_id=%s", (sources[0].id,),
        ).fetchone()["id"]
    sources_workflow.execute(observation_id, httpx.MockTransport(lambda _request: httpx.Response(
        200, headers={"Content-Type": "text/html"},
        stream=httpx.ByteStream(PAGE.format(noise="one", change="").encode()),
    )))
    with database.transaction(snapshot=True) as connection:
        assert MaterialIntake(connection).pending_goal_uploads(session.actor, goal.id) == []
    progress_path = f"/v1/conversations/{conversation.id}/material-progress"
    headers = {"Authorization": f"Bearer {session.token}"}
    progress = client.get(progress_path, headers=headers)
    assert progress.status_code == 200
    assert progress.json()["status"] != "idle"
    assert progress.json()["preparation"] == "initial"
    assert progress.json()["background_ready_documents"] >= 1
    other = workflow.create_session("Another learner")
    assert client.get(progress_path, headers={
        "Authorization": f"Bearer {other.token}",
    }).status_code == 404
    observation = finish_observed(
        (sources_workflow, settings, sources[0], None), session, rag,
        sources_workflow.observation(session.token, observation_id),
    )
    assert observation.status == "changed"
    discovery_workflow.execute(discovery.id)
    with database.transaction() as connection:
        frozen = connection.execute(
            "SELECT search_id FROM knowledge.material_discovery_jobs WHERE id=%s", (discovery.id,),
        ).fetchone()["search_id"]
        assert frozen
        before = connection.execute(
            "SELECT request FROM knowledge.material_searches WHERE id=%s", (frozen,),
        ).fetchone()["request"]
    late_demand = intake.create_demand(
        session.token, str(uuid4()),
        MaterialDemandInput(goal_id=goal.id, purpose="reference", scope_mode="whole_source"),
    )
    late_job = intake.submit_text(
        session.token, late_demand.id, str(uuid4()),
        MaterialTextJobInput(
            expected_demand_revision=1,
            material=TextMaterialImport(
                goal_id=goal.id, title="Later textbook chapter",
                source_url="https://book.invalid/later",
                text="Later details about iteration and sequences.", authorized_use=True,
                purposes=["reference", "planning", "indexing", "teaching"],
            ),
        ),
    )
    later = prepare(rag, session, late_job)
    assert str(later.document_id) not in {item["document_id"] for item in before["source_versions"]}
    discovery_workflow.execute(discovery.id)
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT search_id FROM knowledge.material_discovery_jobs WHERE id=%s", (discovery.id,),
        ).fetchone()["search_id"] == frozen
    advance_consumer_materials(database, session, settings, goal.id)
    ready = discovery_workflow.get(session.token, planning.id)
    assert ready.status == "ready"
    completed = client.get(progress_path, headers=headers).json()
    assert completed["status"] == "ready"
    assert all(step["status"] == "completed" for step in completed["steps"])
    assert completed["preparation"] == "initial"
    with database.transaction() as connection:
        search = connection.execute(
            "SELECT s.request FROM knowledge.material_searches s "
            "JOIN knowledge.material_discovery_jobs d ON d.search_id=s.id WHERE d.id=%s",
            (ready.id,),
        ).fetchone()["request"]
    assert {item["document_id"] for item in search["source_versions"]} == {
        str(uploaded.document_id), str(observation.document_id),
    }
    assert search == before
    selection = MaterialSearchWorkflow(database, settings).selection(
        session.token, ready.selection_id,
    )
    assert selection.coverage.basis == "planning-batch-evidence.v1"
    from leornian.bootstrap.material_consumers import ensure_consumer_material_in

    with database.transaction() as connection, pytest.raises(BusinessError, match="exact goal"):
        ensure_consumer_material_in(
            connection, session.actor, Identity.digest(session.token), planning,
        )


def test_confirmed_sql_goal_automatically_registers_only_the_matching_mysql_source(
    database, workflow, session
):
    scope = GoalMaterialScope(
        language="SQL", framework="MySQL", authorized_official_sources=True,
    )
    accepted = workflow.submit(
        session.token, str(uuid4()),
        GoalInput(title="Teach me to query relational data", material_scope=scope),
    )
    with database.transaction() as connection:
        event = connection.execute(
            "SELECT event_id FROM platform.outbox WHERE job_id=%s", (accepted.job_id,)
        ).fetchone()["event_id"]
    workflow.process_goal(event)
    goal = workflow.snapshot(session.token).goals[0]
    settings = Settings(
        database_url=database.url, delivery_enabled=True, model_configuration_mode="user"
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, goal.id)
    turn = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Prepare a query learning route.", expected_revision=0),
    )
    intake = MaterialIntakeWorkflow(database, settings)
    demand = next(
        item for item in intake.demands(session.token, goal.id)
        if item.consumer_ref == f"tutor-turn:{turn.turn_id}:planning:semantic-goal.v1"
    )
    assert (demand.language, demand.framework, demand.framework_version) == ("SQL", "MySQL", None)
    discovery_workflow = MaterialDiscoveryWorkflow(database, settings)
    discovery = discovery_workflow.get(session.token, demand.id)
    assert discovery is not None
    discovery_workflow.execute(discovery.id)
    sources = MaterialSourceWorkflow(database, settings).list(session.token, goal.id)
    assert len(sources) == 1 and sources[0].basis == "official_catalog"
    assert (sources[0].language, sources[0].framework, sources[0].framework_version) == (
        "SQL", "MySQL", "8.0"
    )
    assert sources[0].entry_url == "https://dev.mysql.com/doc/refman/8.0/en/"
    assert goal.material_scope.framework_version is None
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM runtime.external_calls WHERE run_id=%s", (turn.run_id,)
        ).fetchone()["n"] == 0


def configure_goal_models(
    database, session, settings, *, material_roles=False, context_tokens=128000,
):
    models = ModelConfigurationWorkflow(database, settings)
    if material_roles:
        connection = models.create_connection(
            session.token, str(uuid4()),
            ModelConnectionInput(
                label="Owned consumer material", protocol="dashscope",
                base_url="https://dashscope.aliyuncs.com", region="cn-beijing",
                enabled=True, api_key="offline-owned-material-channel",
            ),
        )
        for role in ("embedding", "rerank", "ocr"):
            models.save_profile(
                session.token, str(uuid4()),
                ModelProfileInput(
                    label=role, connection_id=connection.id, model="fixture-" + role,
                    operation=role, roles=[role], enabled=True, allow_private_material=True,
                    embedding_dimensions=4,
                ),
            )
    connection = models.create_connection(
        session.token, str(uuid4()),
        ModelConnectionInput(
            label="Owned semantic material check", protocol="chat_completions",
            base_url="https://material-check.invalid/v1", region="offline",
            enabled=True, api_key="offline-owned-check-channel",
        ),
    )
    return models.save_profile(
        session.token, str(uuid4()),
        ModelProfileInput(
            label="Material goal coverage", connection_id=connection.id,
            model="fixture-material-check", operation="chat", roles=["material_check.v1"],
            enabled=True, allow_private_material=True,
            context_tokens=context_tokens, max_output_tokens=16384,
        ),
    )


def material_transport():
    def handle(request):
        wire = json.loads(request.content)
        if wire["model"] == "fixture-embedding":
            result = {"output": {"embeddings": [
                {"text_index": i, "embedding": [1.0, 0.2, 0.3, 0.4]}
                for i, _ in enumerate(wire["input"]["texts"])
            ]}}
        elif wire["model"] == "fixture-rerank":
            result = {"output": {"results": [
                {"index": i, "relevance_score": 1 / (i + 1)}
                for i, _ in enumerate(wire["input"]["documents"])
            ]}}
        else:
            result = {"choices": [{
                "message": {"role": "assistant", "content": "Iteration visits every item."},
                "finish_reason": "stop",
            }]}
        return httpx.Response(200, json={**result, "usage": {"total_tokens": 10}})
    return httpx.MockTransport(handle)


def goal_gateway(
    settings, *, status="supported", before_receipt=None, omit_ref=False, compact=False,
):
    sent = []

    def handle(request):
        wire = json.loads(request.content)
        sent.append(wire)
        assert wire["model"] == "fixture-material-check"
        assert not wire.get("tools")
        data = json.loads(wire["messages"][1]["content"])
        children = data["complete_child_summaries"]
        refs = [item["reference_key"] if compact else item["ref"] for item in data["source_parts"]]
        evidence = refs if not children else list({
            json.dumps(ref, sort_keys=True): ref for child in children
            for ref in child["evidence_refs"]
        }.values())
        result = {
            "status": status,
            "summary": "Iteration visits each sequence item; the exact sources show a loop.",
            "evidence_refs": evidence[:8],
            "reviewed_refs": refs[1:] if omit_ref else refs,
            "reviewed_parts": [child["id"] for child in children],
        }
        if status == "supported" and "topic_evidence" in data["schema"]["properties"]:
            result["topic_evidence"] = {
                topic: evidence[:1] for topic in data["schema"]["properties"]["topic_evidence"][
                    "properties"
                ]
            }
        if before_receipt:
            before_receipt()
        return httpx.Response(200, json={
            "choices": [{
                "message": {"role": "assistant", "content": json.dumps(result)},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 50, "completion_tokens": 100},
        })
    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), sent


def advance_consumer_materials(database, session, settings, goal_id, *, gateway=None):
    gateway = gateway or goal_gateway(settings)[0]
    transport = material_transport()
    for _ in range(40):
        with database.transaction() as connection:
            discoveries = connection.execute(
                "SELECT d.id,d.status FROM knowledge.material_discovery_jobs d "
                "JOIN knowledge.material_demands m ON m.id=d.demand_id "
                "WHERE m.actor_id=%s AND m.goal_id=%s", (session.actor.id, goal_id),
            ).fetchall()
        if discoveries and all(item["status"] == "ready" for item in discoveries):
            return
        for item in discoveries:
            if item["status"] not in {"ready", "cancelled", "blocked_unknown"}:
                MaterialDiscoveryWorkflow(database, settings).execute(item["id"])
        with database.transaction() as connection:
            jobs = connection.execute(
                "SELECT j.id FROM knowledge.material_jobs j "
                "JOIN knowledge.material_demands m ON m.id=j.demand_id "
                "WHERE m.actor_id=%s AND m.goal_id=%s "
                "AND j.state NOT IN ('ready','cancelled','blocked_unknown')",
                (session.actor.id, goal_id),
            ).fetchall()
            searches = connection.execute(
                "SELECT s.id FROM knowledge.material_searches s "
                "JOIN knowledge.material_demands m ON s.request->>'demand_id'=m.id::text "
                "WHERE m.actor_id=%s AND m.goal_id=%s "
                "AND s.status NOT IN ('ready','cancelled','blocked_unknown')",
                (session.actor.id, goal_id),
            ).fetchall()
        for item in jobs:
            MaterialIntakeWorkflow(database, settings).execute(item["id"], transport)
        for item in searches:
            MaterialSearchWorkflow(database, settings).execute(item["id"], transport)
        with database.transaction() as connection:
            runs = connection.execute(
                "SELECT p.run_id FROM knowledge.material_goal_coverage_parts p "
                "JOIN knowledge.material_searches s ON s.id=p.search_id "
                "JOIN knowledge.material_demands m ON m.id=(s.request->>'demand_id')::uuid "
                "WHERE m.actor_id=%s AND m.goal_id=%s AND p.state='running'",
                (session.actor.id, goal_id),
            ).fetchall()
        for item in runs:
            AgentLoop(TutorWorkflow(database, settings), gateway).run(item["run_id"])
    pytest.fail(f"Consumer materials remain unresolved: {discoveries}")


@pytest.fixture
def source_case(database, session, rag, monkeypatch):
    monkeypatch.setattr("leornian.modules.knowledge.source_network.resolve_destination",
                        lambda *_: "1.1.1.1")
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings = replace(rag["settings"], model_enabled=True)
    workflow = MaterialSourceWorkflow(database, settings)
    data = MaterialSourceInput(
        goal_id=rag["goal"].id, title="Approved iteration reference",
        entry_url="https://source.invalid/approved/index",
        allowed_prefixes=["https://source.invalid/approved/"],
        authorized_use=True, purposes=["reference", "planning", "teaching", "indexing"],
    )
    key = str(uuid4())
    source = workflow.register(session.token, key, data)
    return workflow, settings, source, key


def observed(case, session, *, noise="one", change="", code=200, before_receipt=None):
    workflow, _settings, source, _key = case
    key = str(uuid4())
    observation = workflow.check(
        session.token, source.id, key, MaterialSourceAction(expected_revision=source.revision)
    )
    sent = []

    def handle(request):
        sent.append(request)
        if before_receipt:
            before_receipt()
        return httpx.Response(
            code, headers={"Content-Type": "text/html", "ETag": '"' + noise + change + '"'},
            stream=httpx.ByteStream(
                PAGE.format(noise=noise, change=change).encode() if code == 200 else b""
            ),
        )
    workflow.execute(observation.id, httpx.MockTransport(handle))
    return workflow.observation(session.token, observation.id), sent, key


def finish_observed(case, session, rag, observation):
    workflow, _settings, _source, _key = case
    for _ in range(12):
        current = workflow.observation(session.token, observation.id)
        if current.status in {"changed", "noise_only", "unchanged", "cancelled", "blocked_unknown"}:
            return current
        assert current.status in {"processing", "waiting_config"}, current
        if current.job_id:
            rag["intake"].execute(current.job_id, rag["transport"])
        workflow.execute(current.id)
    pytest.fail(f"Source did not finish its normal material job: {current}")


def test_a_new_source_request_does_not_reuse_a_cancelled_preparation_job(
    database, session, rag, source_case,
):
    workflow, _settings, _source, _key = source_case
    first, _sent, _command = observed(source_case, session)
    assert first.job_id is not None
    rag["intake"].cancel(session.token, first.job_id)
    workflow.execute(first.id)
    second, _sent, _command = observed(source_case, session)
    assert second.id != first.id and second.job_id is not None
    assert second.job_id != first.job_id
    assert rag["intake"].job(session.token, first.job_id).state == "cancelled"
    assert rag["intake"].job(session.token, second.job_id).state == "queued"


def test_directory_keeps_the_source_receipt_and_discovers_chapters_without_indexing_labels(
    database, session, source_case,
):
    workflow, _settings, source, _key = source_case
    content = ("<main><h1>Guide</h1><ul>" + "".join(
        f'<li><a href="/approved/{topic}">Complete {topic} chapter</a></li>'
        for topic in ("introduction", "iteration", "functions")
    ) + '</ul><a href="/private/outside">Outside</a></main>').encode()

    def handle(request):
        assert "if-none-match" not in request.headers
        return httpx.Response(
            200, headers={"Content-Type": "text/html", "ETag": '"directory-v1"'},
            stream=httpx.ByteStream(content),
        )

    for _ in range(2):
        observation = workflow.check(
            session.token, source.id, str(uuid4()),
            MaterialSourceAction(expected_revision=source.revision),
        )
        workflow.execute(observation.id, httpx.MockTransport(handle))
        result = workflow.observation(session.token, observation.id)
        assert result.status == "changed" and result.job_id is None
        with database.transaction() as connection:
            recorded = connection.execute(
                "SELECT raw_digest,original_id,teaching_digest FROM knowledge.source_observations "
                "WHERE id=%s", (observation.id,),
            ).fetchone()
            assert recorded["raw_digest"] == sha256(content).hexdigest()
            assert recorded["original_id"] and recorded["teaching_digest"]
    with database.transaction() as connection:
        children = connection.execute(
            "SELECT url,depth FROM knowledge.material_source_resources "
            "WHERE source_id=%s AND depth>0", (source.id,),
        ).fetchall()
    assert {item["url"].rsplit("/", 1)[-1] for item in children} == {
        "introduction", "iteration", "functions",
    }
    assert all(item["depth"] == 1 for item in children)


def test_old_indexed_directory_is_classified_from_the_saved_response_only(
    database, session, rag, source_case, monkeypatch,
):
    workflow, _settings, source, _key = source_case
    body = "<main>" + "".join(
        f'<a href="/approved/chapter-{index}">Iteration example chapter {index}</a>'
        for index in range(4)
    ) + "</main>"
    observation = workflow.check(
        session.token, source.id, str(uuid4()),
        MaterialSourceAction(expected_revision=source.revision),
    )
    with monkeypatch.context() as patch:
        patch.setattr(SourceLinks, "is_directory", lambda *_: False)
        workflow.execute(observation.id, httpx.MockTransport(lambda _request: httpx.Response(
            200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(body.encode()),
        )))
        original = finish_observed(source_case, session, rag, observation)
    assert original.document_id is not None
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.source_observations SET request_identity="
            "request_identity-'source_structure' WHERE id=%s", (observation.id,),
        )
        origin = connection.execute(
            "SELECT r.*,v.document_id AS origin_document_id,v.revision AS origin_revision,"
            "v.format FROM knowledge.material_source_resources r "
            "JOIN knowledge.document_versions v ON v.document_id=r.document_id "
            "AND v.revision=r.document_revision WHERE r.id=%s", (original.resource_id,),
        ).fetchone()
        expected = {(original.document_id, original.document_revision)}
        assert workflow.directory_versions_in(connection, session.actor, [origin]) == expected
        patch_target = "leornian.bootstrap.material_sources.extract_file"
        with monkeypatch.context() as patch:
            patch.setattr(
                patch_target, lambda *_: pytest.fail("A saved structural fact must be reused."),
            )
            assert workflow.directory_versions_in(connection, session.actor, [origin]) == expected
        retained = connection.execute(
            "SELECT original_id,raw_digest,document_id,document_revision,job_id "
            "FROM knowledge.source_observations WHERE id=%s", (observation.id,),
        ).fetchone()
        assert retained["document_id"] == original.document_id
        assert retained["document_revision"] == original.document_revision
        assert retained["original_id"] and retained["job_id"] == original.job_id


def test_discovered_chapters_stay_shallow_and_second_hop_requires_a_specific_gap(
    database, session, rag, source_case,
):
    from leornian.bootstrap.material_sources import scan_material_sources_once
    from leornian.modules.knowledge.source_acquisition import MaterialSources

    _sources, settings, source, _ = source_case
    first, _, _ = observed(source_case, session)
    first = finish_observed(source_case, session, rag, first)
    prepare(rag, session, rag["intake"].job(session.token, first.job_id))
    demand = rag["intake"].create_demand(session.token, str(uuid4()), MaterialDemandInput(
        goal_id=rag["goal"].id, purpose="teaching", required_facets=["next"],
    ))
    with database.transaction() as connection:
        discovery = MaterialSources(connection).ensure_discovery(
            session.actor, connection.execute(
                "SELECT session_digest FROM knowledge.material_jobs WHERE id=%s",
                (first.job_id,),
            ).fetchone()["session_digest"], demand,
        )
        connection.execute(
            "UPDATE knowledge.material_source_resources SET depth=80 WHERE source_id=%s "
            "AND depth>0", (source.id,),
        )
    scan_material_sources_once(database, settings)
    with database.transaction() as connection:
        assert not connection.execute(
            "SELECT o.id FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
            "WHERE o.source_id=%s AND r.depth>0", (source.id,),
        ).fetchone()
        acquisition = MaterialDiscoveryWorkflow(database, settings)
        actor, row, current = acquisition.current(connection, discovery.id)
        acquisition.acquire(connection, actor, row, current, ["next"])
        selected = connection.execute(
            "SELECT r.depth,r.url FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
            "WHERE o.source_id=%s AND r.depth>0", (source.id,),
        ).fetchone()
        assert selected is None
        connection.execute(
            "UPDATE knowledge.material_source_resources SET depth=2 WHERE source_id=%s "
            "AND depth=80", (source.id,),
        )
        actor, row, current = acquisition.current(connection, discovery.id)
        acquisition.acquire(connection, actor, row, current, ["unrelated-topic"])
        assert not connection.execute(
            "SELECT id FROM knowledge.source_observations WHERE source_id=%s AND id<>%s",
            (source.id, first.id),
        ).fetchone()
        acquisition.acquire(connection, actor, row, current, ["next"])
        selected = connection.execute(
            "SELECT r.depth,r.url,o.request_identity FROM knowledge.source_observations o "
            "JOIN knowledge.material_source_resources r ON r.id=o.resource_id "
            "WHERE o.source_id=%s AND r.depth>0", (source.id,),
        ).fetchone()
        assert selected["depth"] == 2 and selected["url"].endswith("/next")
        assert selected["request_identity"]["missing_topics"] == ["next"]
        connection.execute(
            "UPDATE knowledge.source_observations SET status='waiting_dependency',"
            "error_code='material_quality_pending',next_run_at=now() WHERE id=%s", (first.id,),
        )
    assert first.id in scan_material_sources_once(database, settings, limit=10000)


def test_approved_original_conditional_read_noise_and_semantic_change_share_the_normal_pipeline(
    database, session, rag, source_case
):
    workflow, _settings, source, key = source_case
    assert workflow.registration_receipt(session.token, key).id == source.id
    first, _sent, command = observed(source_case, session)
    assert workflow.check_receipt(session.token, source.id, command).id == first.id
    first = finish_observed(source_case, session, rag, first)
    assert first.status == "changed"
    assert workflow.original(session.token, first.id, "teaching") == PAGE.format(
        noise="one", change=""
    ).encode()
    blocks = rag["materials"].blocks(
        session.token, first.document_id, first.document_revision, "teaching"
    ).blocks
    binding = rag["materials"].bind(
        session.token, str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id, purpose="teaching", expected_binding_revision=0,
            refs=[block.ref for block in blocks],
        ),
    )
    calls = len(rag["sent"])
    noise, _, _ = observed(source_case, session, noise="two")
    assert noise.status == "noise_only" and noise.document_revision == first.document_revision
    assert len(rag["sent"]) == calls
    unchanged, sent, _ = observed(source_case, session, code=304)
    assert unchanged.status == "unchanged"
    assert sent[0].headers["if-none-match"] == '"two"'
    changed, _, _ = observed(source_case, session, noise="three", change=" + 1")
    changed = finish_observed(source_case, session, rag, changed)
    assert changed.status == "changed" and changed.document_revision > first.document_revision
    with database.transaction() as connection:
        checks = connection.execute(
            "SELECT id FROM knowledge.material_change_checks WHERE binding_id=%s "
            "AND candidate_revision=%s", (binding.id, changed.document_revision),
        ).fetchall()
    assert len(checks) == 1
    assert rag["materials"].binding(session.token, binding.id).revision == binding.revision


def test_recorded_source_resumes_after_storage_recovers_without_another_http_read(
    database, session, source_case, monkeypatch
):
    workflow, _settings, _source, _key = source_case
    read = workflow.store.read

    def unavailable(*args, **kwargs):
        raise BusinessError("material_storage_unavailable", "Original storage is unavailable.")

    monkeypatch.setattr(workflow.store, "read", unavailable)
    first, sent, _command = observed(source_case, session)
    assert first.status == "waiting_dependency"
    assert first.error_code == "material_storage_unavailable"
    assert first.response_status == 200 and first.job_id is None
    with database.transaction(snapshot=True) as connection:
        recorded = connection.execute(
            "SELECT recorded_at,original_id,dispatched_at FROM knowledge.source_observations "
            "WHERE id=%s",
            (first.id,),
        ).fetchone()
    assert recorded["recorded_at"] is not None and recorded["original_id"] == first.id

    monkeypatch.setattr(workflow.store, "read", read)

    def no_read(request):
        sent.append(request)
        pytest.fail("A recorded source must not be requested again.")

    workflow.execute(first.id, httpx.MockTransport(no_read))
    resumed = workflow.observation(session.token, first.id)
    assert resumed.status == "processing"
    assert resumed.error_code == "source_preparation_pending" and resumed.job_id is not None
    assert len(sent) == 1
    with database.transaction(snapshot=True) as connection:
        after = connection.execute(
            "SELECT recorded_at,original_id,dispatched_at FROM knowledge.source_observations "
            "WHERE id=%s",
            (first.id,),
        ).fetchone()
        assert after == recorded
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.source_observations WHERE source_id=%s",
            (first.source_id,),
        ).fetchone()["n"] == 1


@pytest.mark.parametrize("failure", ["storage_before_recording", "unknown_response"])
def test_unrecorded_source_failure_does_not_replay_http(
    database, session, source_case, monkeypatch, failure
):
    workflow, _settings, _source, _key = source_case
    put = workflow.store.put

    def unavailable(*args, **kwargs):
        raise BusinessError("material_storage_unavailable", "Original storage is unavailable.")

    def unknown_response():
        raise httpx.ReadError("The original source response is unknown.")

    if failure == "storage_before_recording":
        monkeypatch.setattr(workflow.store, "put", unavailable)
    first, sent, _command = observed(
        source_case, session,
        before_receipt=unknown_response if failure == "unknown_response" else None,
    )
    assert first.status == "waiting_dependency"
    assert first.error_code == (
        "material_storage_unavailable" if failure == "storage_before_recording"
        else "source_network_unavailable"
    )
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT recorded_at FROM knowledge.source_observations WHERE id=%s", (first.id,),
        ).fetchone()["recorded_at"] is None
    monkeypatch.setattr(workflow.store, "put", put)

    def no_read(request):
        sent.append(request)
        pytest.fail("An unrecorded source response must not be replayed.")

    workflow.execute(first.id, httpx.MockTransport(no_read))
    assert workflow.observation(session.token, first.id) == first
    assert len(sent) == 1 and first.job_id is None


@pytest.mark.parametrize("depth", [0, 2])
def test_periodic_source_retry_uses_new_identity_but_discovery_failure_is_skipped(
    database, session, rag, source_case, depth,
):
    from leornian.bootstrap.material_sources import scan_material_sources_once
    from leornian.modules.knowledge.source_acquisition import MaterialSources

    workflow, settings, source, _key = source_case

    def interrupted():
        raise httpx.ReadError("Original public GET response is unknown.")

    if depth == 0:
        first, _sent, _command = observed(source_case, session, before_receipt=interrupted)
    else:
        with database.transaction() as connection:
            sources = MaterialSources(connection)
            digest = sources.row(session.actor, source.id)["session_digest"]
            discovery = sources.ensure_discovery(session.actor, digest, rag["demand"])
            resource = sources.add_resource(source.id, source.entry_url + "/iteration", depth)
            first = sources.schedule(
                session.actor, source.id, digest,
                f"discovery:{discovery.id}:shallow-v1:{resource['id']}",
                resource_id=resource["id"], missing_topics=["Iteration"],
            )
        workflow.execute(first.id, httpx.MockTransport(lambda _request: interrupted()))
        first = workflow.observation(session.token, first.id)
    with database.transaction() as connection:
        resource = connection.execute(
            "SELECT read_failures,next_check_at>now() AS deferred "
            "FROM knowledge.material_source_resources WHERE id=%s", (first.resource_id,),
        ).fetchone()
        assert resource == {"read_failures": 1, "deferred": True}
        connection.execute(
            "UPDATE knowledge.material_source_resources SET next_check_at=now() WHERE id=%s",
            (first.resource_id,),
        )
        connection.execute(
            "UPDATE knowledge.material_source_resources SET next_check_at=now()+interval '1 day' "
            "WHERE source_id=%s AND id<>%s", (source.id, first.resource_id),
        )
    ids = scan_material_sources_once(database, settings, limit=10000)
    with database.transaction(snapshot=True) as connection:
        if depth == 2:
            assert connection.execute(
                "SELECT id FROM knowledge.source_observations WHERE resource_id=%s",
                (first.resource_id,),
            ).fetchall() == [{"id": first.id}]
            assert first.id not in ids
            return
        retry = connection.execute(
            "SELECT id FROM knowledge.source_observations WHERE resource_id=%s AND id<>%s",
            (first.resource_id, first.id),
        ).fetchone()["id"]
    assert retry in ids and retry != first.id
    workflow.execute(retry, httpx.MockTransport(lambda _request: httpx.Response(
        200, headers={"Content-Type": "text/html"},
        stream=httpx.ByteStream(PAGE.format(noise="retry", change="").encode()),
    )))
    assert workflow.observation(session.token, first.id) == first
    assert workflow.observation(session.token, retry).response_status == 200


@pytest.mark.parametrize("provider", ["direct", "tavily"])
def test_expired_source_read_lease_does_not_replay_and_keeps_paid_results_unknown(
    database, session, source_case, provider,
):
    workflow, _settings, source, _key = source_case
    observation = workflow.check(
        session.token, source.id, str(uuid4()),
        MaterialSourceAction(expected_revision=source.revision),
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.source_observations SET status='fetching',dispatched_at=now(),"
            "lease_token=%s,lease_until=now()-interval '1 second',"
            "request_identity=request_identity||%s WHERE id=%s",
            (uuid4(), Jsonb({"acquisition_provider": provider}), observation.id),
        )
    workflow.execute(observation.id, httpx.MockTransport(
        lambda _request: pytest.fail("An expired read must not replay the original request.")
    ))
    failed = workflow.observation(session.token, observation.id)
    assert failed.status == ("waiting_dependency" if provider == "direct" else "blocked_unknown")
    assert failed.error_code == (
        "source_network_unavailable" if provider == "direct" else "source_read_unknown"
    )


def test_source_checks_do_not_replace_an_unknown_embedding_job(
    session, rag, source_case,
):
    workflow, _settings, source, _key = source_case
    observation, _, _ = observed(source_case, session)
    attempts = []

    def interrupted(request):
        attempts.append(request)
        raise httpx.ReadError("The original embedding receipt is unresolved.", request=request)

    for _ in range(8):
        rag["intake"].execute(observation.job_id, httpx.MockTransport(interrupted))
        if rag["intake"].job(session.token, observation.job_id).state == "blocked_unknown":
            break
    assert len(attempts) == 1
    assert rag["intake"].job(session.token, observation.job_id).state == "blocked_unknown"
    workflow.execute(observation.id, httpx.MockTransport(
        lambda _request: pytest.fail("The original public response is already recorded.")
    ))
    repeated = workflow.check(
        session.token, source.id, str(uuid4()),
        MaterialSourceAction(expected_revision=source.revision),
    )
    assert repeated.id == observation.id and repeated.job_id == observation.job_id
    assert repeated.status == "changed"
    assert rag["intake"].job(session.token, repeated.job_id).state == "blocked_unknown"
    assert len(attempts) == 1


def test_old_deep_source_work_is_deferred_without_provider_calls(
    database, session, rag, source_case,
):
    workflow, _settings, source, _key = source_case
    observation, _, _ = observed(source_case, session)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.material_source_resources SET depth=80 WHERE id=%s",
            (observation.resource_id,),
        )
    rag["intake"].execute(observation.job_id, httpx.MockTransport(
        lambda _request: pytest.fail("An unselected historical chapter cannot call a model.")
    ))
    with database.transaction(snapshot=True) as connection:
        job = connection.execute(
            "SELECT background_deferred,reason_code FROM knowledge.material_jobs WHERE id=%s",
            (observation.job_id,),
        ).fetchone()
    assert job["background_deferred"] and job["reason_code"] == "source_depth_not_selected"
    assert workflow.observation(session.token, observation.id).response_status == 200


def test_ready_material_wakes_unknown_discovery_and_progress_uses_current_dependencies(
    database, session, rag, source_case,
):
    from leornian.bootstrap.material_discovery import scan_material_discovery_once
    from leornian.modules.knowledge.progress import MaterialPreparation
    from leornian.modules.knowledge.source_acquisition import MaterialSources

    workflow, settings, source, _key = source_case
    observation, _, _ = observed(source_case, session)
    with database.transaction() as connection:
        digest = connection.execute(
            "SELECT session_digest FROM knowledge.material_jobs WHERE id=%s",
            (observation.job_id,),
        ).fetchone()["session_digest"]
        discovery = MaterialSources(connection).ensure_discovery(
            session.actor, digest, rag["demand"],
        )
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET status='blocked_unknown',"
            "error_code='uploaded_material_preparation_pending',next_run_at=now() WHERE id=%s",
            (discovery.id,),
        )
    prepare(rag, session, rag["job"])
    assert discovery.id in scan_material_discovery_once(database, limit=10000)
    with database.transaction(snapshot=True) as connection:
        assert connection.execute(
            "SELECT status,error_code FROM knowledge.material_discovery_jobs WHERE id=%s",
            (discovery.id,),
        ).fetchone() == {"status": "queued", "error_code": None}
        progress = MaterialPreparation(connection).for_demand(session.actor, rag["demand"].id)
    assert progress.current_documents >= 2 and progress.last_progress_at
    assert progress.status != "blocked_unknown"
    with database.transaction() as connection:
        sources = MaterialSources(connection)
        resource = sources.add_resource(source.id, source.entry_url + "-old-chapter", 1)
        old = sources.schedule(
            session.actor, source.id, digest, f"discovery:{discovery.id}:legacy-chapter",
            resource_id=resource["id"],
        )
    workflow.execute(old.id, httpx.MockTransport(lambda _request: httpx.Response(
        200, headers={"Content-Type": "text/html"},
        stream=httpx.ByteStream(PAGE.format(noise="legacy", change="").encode()),
    )))
    with database.transaction(snapshot=True) as connection:
        scoped_progress = MaterialPreparation(connection).for_demand(
            session.actor, rag["demand"].id,
        )
    assert scoped_progress.current_documents == progress.current_documents
    assert scoped_progress.background_documents >= 1
    prepared = prepare(rag, session, rag["intake"].job(session.token, observation.job_id))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.material_source_resources SET depth=80 WHERE id=%s",
            (observation.resource_id,),
        )
        scoped = MaterialDiscoveryWorkflow(database, settings).available_builds(
            connection, session.actor, {"missing_facets": ["Iteration"]}, rag["demand"], None,
        )
    assert scoped and prepared.document_id not in {build["document_id"] for build in scoped}


def test_original_html_main_version_is_retained_when_article_repair_derives_a_new_revision(
    session, rag, source_case, monkeypatch
):
    workflow, _settings, source, _key = source_case
    content = (
        b"<main><button><svg></svg>Menu</button><article><h1>Iteration</h1>"
        b"<p>Visit every item.</p><pre>print(1)</pre></article>"
        b'<img src="/avatar.png" alt="Contributor"></main>'
    )
    accepted = workflow.check(
        session.token, source.id, str(uuid4()),
        MaterialSourceAction(expected_revision=source.revision),
    )
    workflow.execute(accepted.id, httpx.MockTransport(
        lambda _request: httpx.Response(
            200, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(content)
        )
    ))
    observation = workflow.observation(session.token, accepted.id)
    old_extraction = parse_file(content, "html")
    old_extraction["parser_version"] = "html-main-text.v1"
    with monkeypatch.context() as previous:
        previous.setattr(
            "leornian.bootstrap.material_intake.extract_file", lambda *_args: old_extraction
        )
        rag["intake"].execute(observation.job_id)
    original = rag["intake"].job(session.token, observation.job_id)
    original_version = rag["materials"].version(
        session.token, original.document_id, original.document_revision
    )
    assert original.issues == ["html_nontext_content_pending"]

    rag["intake"].execute(original.id)
    repaired = rag["intake"].job(session.token, original.id)
    assert repaired.phase == "indexing" and repaired.reason_code == "indexing_pending"
    assert repaired.issues == [] and repaired.document_id == original.document_id
    assert repaired.document_revision == original.document_revision + 1
    assert rag["materials"].version(
        session.token, original.document_id, original.document_revision
    ) == original_version
    assert rag["materials"].version(
        session.token, repaired.document_id, repaired.document_revision
    ).parser_version == HTML_MAIN_PARSER_VERSION
    assert workflow.original(session.token, observation.id, "reference") == content


def test_unresolved_html_graphics_require_real_processing_instead_of_a_null_replacement_wait(
    database, session, rag, source_case,
):
    workflow, _settings, source, _key = source_case
    content = b"<main><h1>Flow</h1><p>Read the diagram.</p><svg><path d='M0 0L5 5'/></svg></main>"
    accepted = workflow.check(
        session.token, source.id, str(uuid4()),
        MaterialSourceAction(expected_revision=source.revision),
    )
    workflow.execute(accepted.id, httpx.MockTransport(lambda _: httpx.Response(
        200, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(content),
    )))
    observation = workflow.observation(session.token, accepted.id)
    for _ in range(3):
        rag["intake"].execute(observation.job_id, rag["transport"])
    job = rag["intake"].job(session.token, observation.job_id)
    assert job.state == "waiting_config"
    assert job.reason_code == "material_nontext_processing_required"
    assert job.issues == ["html_nontext_content_pending"]
    with database.transaction() as connection:
        attempts = connection.execute(
            "SELECT state,replacement_discovery_id FROM knowledge.material_repair_attempts "
            "WHERE job_id=%s", (job.id,),
        ).fetchall()
    assert attempts and not any(
        row["state"] == "waiting" and row["replacement_discovery_id"] is None for row in attempts
    )


def test_unchanged_source_bytes_are_reextracted_after_a_parser_upgrade(
    database, session, rag, source_case,
):
    workflow, _settings, _source, _key = source_case
    first, _sent, _key = observed(source_case, session)
    first = finish_observed(source_case, session, rag, first)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.document_versions SET parser_version='html-main-text.v5' "
            "WHERE document_id=%s AND revision=%s",
            (first.document_id, first.document_revision),
        )
    second, _sent, _key = observed(source_case, session)
    assert second.status == "processing" and second.job_id != first.job_id
    second = finish_observed(source_case, session, rag, second)
    assert second.document_id == first.document_id
    assert second.document_revision == first.document_revision + 1
    assert rag["materials"].version(
        session.token, second.document_id, second.document_revision,
    ).parser_version == HTML_MAIN_PARSER_VERSION


def test_source_revocation_cancels_unprepared_child_and_raw_access(
    database, session, rag, source_case
):
    workflow, _settings, source, _key = source_case
    observation, _, _ = observed(source_case, session)
    revoked = workflow.revoke(
        session.token, source.id, MaterialSourceAction(expected_revision=source.revision)
    )
    assert workflow.revocation_receipt(session.token, source.id) == revoked
    assert rag["intake"].job(session.token, observation.job_id).state == "cancelled"
    with pytest.raises(BusinessError):
        workflow.original(session.token, observation.id, "teaching")
    sent = len(rag["sent"])
    rag["intake"].execute(observation.job_id, rag["transport"])
    assert len(rag["sent"]) == sent


def test_revoking_the_exact_document_also_denies_the_observed_raw_copy(
    session, rag, source_case
):
    workflow, _settings, _source, _key = source_case
    first, _, _ = observed(source_case, session)
    first = finish_observed(source_case, session, rag, first)
    rag["materials"].revoke(
        session.token, first.document_id, first.document_revision,
        DocumentPermissionAction(expected_revision=1, action="revoke"),
    )
    with pytest.raises(BusinessError):
        workflow.original(session.token, first.id, "teaching")


def start_goal_search(
    database, session, rag, *, configure=True, query="Learn to iterate over a list"
):
    original = prepare(rag, session)
    settings = replace(rag["settings"], model_enabled=True)
    if configure:
        configure_goal_models(database, session, settings)
    demand = rag["intake"].create_demand(
        session.token, str(uuid4()),
        MaterialDemandInput(
            goal_id=rag["goal"].id, purpose="teaching", scope_mode="teaching_goal", goal_text=query
        ),
    )
    searcher = MaterialSearchWorkflow(database, settings)
    search = searcher.submit(
        session.token, str(uuid4()),
        MaterialSearchInput(
            demand_id=demand.id, expected_demand_revision=demand.revision, query=query,
            document_id=original.document_id, document_revision=original.document_revision,
        ),
    )
    return settings, demand, searcher, search, original


def drive_goal(database, session, rag, settings, searcher, search, gateway):
    for _ in range(40):
        searcher.execute(search.id, rag["transport"])
        state = searcher.get(session.token, search.id)
        if state.status in {"ready", "waiting_config", "waiting_dependency", "blocked_unknown"}:
            return state
        with database.transaction() as connection:
            parts = connection.execute(
                "SELECT run_id FROM knowledge.material_goal_coverage_parts "
                "WHERE search_id=%s AND state='running'", (search.id,),
            ).fetchall()
        for part in parts:
            AgentLoop(TutorWorkflow(database, settings), gateway).run(part["run_id"])
    pytest.fail("Semantic material search did not finish")


def test_semantic_goal_uses_real_owned_runtime_and_records_separate_lexical_evidence(
    database, session, rag, monkeypatch
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    with database.transaction() as connection:
        turns_before = connection.execute(
            "SELECT count(*) AS n FROM tutor.turns t JOIN tutor.conversations c "
            "ON c.id=t.conversation_id WHERE c.actor_id=%s", (session.actor.id,),
        ).fetchone()["n"]
    settings, demand, searcher, search, _original = start_goal_search(database, session, rag)
    gateway, sent = goal_gateway(settings)
    state = drive_goal(database, session, rag, settings, searcher, search, gateway)
    assert state.status == "ready", state
    selection = searcher.selection(session.token, state.selection_id)
    assert selection.coverage.status == "sufficient"
    assert selection.coverage.basis == "semantic-goal-evidence.v1"
    assert selection.coverage.required[0].facet == demand.goal_text
    assert selection.coverage.lexical_coverage[0].status == "missing"
    assert selection.coverage.reviewed_parts == 1 and len(sent) == 1
    with database.transaction() as connection:
        part = connection.execute(
            "SELECT * FROM knowledge.material_goal_coverage_parts WHERE search_id=%s", (search.id,)
        ).fetchone()
        run = Runs(connection).get(session.actor.id, part["run_id"])
        assert run.status == "succeeded" and run.purpose == "material_check"
        assert MaterialGoalCoverageWorkflow.row_for_run(connection, run.id) == part["id"]
        assert connection.execute(
            "SELECT count(*) AS n FROM delivery.events WHERE actor_id=%s "
            "AND aggregate_id=%s AND event_type LIKE 'tutor.%%'",
            (session.actor.id, run.id),
        ).fetchone()["n"] == 0
        assert connection.execute(
            "SELECT count(*) AS n FROM tutor.turns t JOIN tutor.conversations c "
            "ON c.id=t.conversation_id WHERE c.actor_id=%s", (session.actor.id,),
        ).fetchone()["n"] == turns_before
        with pytest.raises(ForeignKeyViolation), connection.transaction():
            Runs(connection).create(
                session.actor.id, uuid4(), uuid4(), "not-a-tutor-identity", "planner.v1"
            )


def test_missing_personal_semantic_role_waits_then_completes_with_the_owned_mapping(
    database, session, rag, monkeypatch
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings, _demand, searcher, search, _ = start_goal_search(
        database, session, rag, configure=False
    )
    searcher.execute(search.id, rag["transport"])
    assert searcher.get(session.token, search.id).status == "waiting_config"
    configure_goal_models(database, session, settings)
    gateway, sent = goal_gateway(settings)
    assert drive_goal(database, session, rag, settings, searcher, search, gateway).status == "ready"
    assert len(sent) == 1


@pytest.mark.parametrize("failure", ["missing_ref", "revoked"])
def test_incomplete_or_revoked_goal_receipts_are_saved_without_a_selection(
    database, session, rag, monkeypatch, failure
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings, _demand, searcher, search, original = start_goal_search(database, session, rag)

    def revoke():
        rag["materials"].revoke(
            session.token, original.document_id, original.document_revision,
            DocumentPermissionAction(expected_revision=1, action="revoke"),
        )
    gateway, sent = goal_gateway(
        settings, omit_ref=failure == "missing_ref",
        before_receipt=revoke if failure == "revoked" else None,
    )
    state = drive_goal(database, session, rag, settings, searcher, search, gateway)
    assert state.status == "waiting_dependency" and state.selection_id is None
    expected_calls = 2 if failure == "missing_ref" else 1
    assert len(sent) == expected_calls
    with database.transaction() as connection:
        calls = connection.execute(
            "SELECT c.status,c.applied,c.response_body FROM runtime.external_calls c "
            "JOIN knowledge.material_goal_coverage_parts p ON p.run_id=c.run_id "
            "WHERE p.search_id=%s ORDER BY c.step", (search.id,),
        ).fetchall()
        assert connection.execute(
            "SELECT count(*) AS n FROM delivery.events WHERE actor_id=%s "
            "AND aggregate_id IN (SELECT run_id FROM knowledge.material_goal_coverage_parts "
            "WHERE search_id=%s) AND event_type LIKE 'tutor.%%'",
            (session.actor.id, search.id),
        ).fetchone()["n"] == 0
    assert len(calls) == expected_calls
    assert all(call["status"] == "result_recorded" and call["response_body"] for call in calls)
    assert not calls[-1]["applied"]
    assert all(call["applied"] for call in calls[:-1])


@pytest.mark.parametrize(
    ("context_tokens", "chapters", "sentences"),
    [(128000, 44, 28), (24000, 44, 28), (128000, 135, 1)],
)
def test_whole_source_indexes_and_selects_every_range_then_semantically_reviews_the_complete_book(
    database, session, rag, material_setup, monkeypatch, context_tokens, chapters, sentences,
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    _materials, _goal, original = material_setup
    source = "\n\n".join(
        f"Iteration chapter {number}. " + "A loop visits each item of its sequence. " * sentences
        for number in range(chapters)
    )
    intake = rag["intake"]
    demand = intake.create_demand(
        session.token, str(uuid4()),
        MaterialDemandInput(goal_id=rag["goal"].id, purpose="teaching", scope_mode="whole_source"),
    )
    job = intake.submit_text(
        session.token, demand.id, str(uuid4()),
        MaterialTextJobInput(
            expected_demand_revision=1,
            material=original.model_copy(update={"format": "text", "text": source}),
        ),
    )
    ready = prepare(rag, session, job)
    assert ready.prepared_scope.block_count == chapters
    blocks, after = [], -1
    while True:
        page = rag["materials"].blocks(
            session.token, ready.document_id, ready.document_revision, "teaching", after=after
        )
        blocks.extend(page.blocks)
        if page.next_after is None:
            break
        after = page.next_after
    assert ready.prepared_scope.indexed_characters == sum(len(block.text) for block in blocks)
    searcher = MaterialSearchWorkflow(database, rag["settings"])
    selection_search = searcher.submit(
        session.token, str(uuid4()),
        MaterialSearchInput(
            demand_id=demand.id, expected_demand_revision=1, query="Iteration", mode="lexical",
            document_id=ready.document_id, document_revision=ready.document_revision,
            required_refs=[block.ref for block in blocks],
        ),
    )
    for _ in range(20):
        searcher.execute(selection_search.id)
        selected = searcher.get(session.token, selection_search.id)
        if selected.status == "ready":
            break
    assert selected.status == "ready", selected
    selection = searcher.selection(session.token, selected.selection_id)
    assert len(selection.evidence) == chapters
    assert sum(len(item.text) for item in selection.evidence) == (
        ready.prepared_scope.indexed_characters
    )
    binding = rag["materials"].bind(
        session.token, str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id, purpose="teaching", expected_binding_revision=0,
            refs=[item.ref for item in selection.evidence],
        ),
    )
    settings = replace(rag["settings"], model_enabled=True)
    configure_goal_models(database, session, settings, context_tokens=context_tokens)
    semantic_demand = intake.create_demand(
        session.token, str(uuid4()),
        MaterialDemandInput(
            goal_id=rag["goal"].id, purpose="teaching", scope_mode="teaching_goal",
            goal_text="Explain how iteration reads sequence items, using the complete reference.",
        ),
    )
    semantic = MaterialSearchWorkflow(database, settings)
    request = semantic.submit(
        session.token, str(uuid4()),
        MaterialSearchInput(
            demand_id=semantic_demand.id, expected_demand_revision=1,
            query=semantic_demand.goal_text, binding_id=binding.id,
            expected_binding_revision=binding.revision,
        ),
    )
    gateway, sent = goal_gateway(settings, compact=True)
    finished = drive_goal(database, session, rag, settings, semantic, request, gateway)
    assert finished.status == "ready", finished
    result = semantic.selection(session.token, finished.selection_id)
    assert len(result.evidence) <= 8
    if context_tokens == 128000:
        assert result.coverage.reviewed_parts == len(sent) == 1
    else:
        assert result.coverage.reviewed_parts > 1
    leaf_refs = [
        block["ref"] for wire in sent
        for block in json.loads(wire["messages"][1]["content"])["source_parts"]
    ]
    assert {ref["block_id"] for ref in leaf_refs} == {str(block.ref.block_id) for block in blocks}
    assert sum(ref["span"]["end"] - ref["span"]["start"] for ref in leaf_refs) == (
        ready.prepared_scope.indexed_characters
    )
    assert sum(
        bool(json.loads(wire["messages"][1]["content"])["complete_child_summaries"])
        for wire in sent
    ) == (0 if context_tokens == 128000 else 1)
    assert rag["materials"].binding(session.token, binding.id).revision == 1
    from leornian.modules.knowledge.progress import MaterialPreparation
    from leornian.modules.knowledge.source_acquisition import MaterialSources

    with database.transaction() as connection:
        search = connection.execute(
            "SELECT session_digest FROM knowledge.material_searches WHERE id=%s", (request.id,),
        ).fetchone()
        discovery = MaterialSources(connection).ensure_discovery(
            session.actor, search["session_digest"], semantic_demand,
        )
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET search_id=%s,status='ready' WHERE id=%s",
            (request.id, discovery.id),
        )
        progress = MaterialPreparation(connection).for_demand(session.actor, semantic_demand.id)
        assert progress.steps[-1].unit == "checks"
        assert progress.steps[-1].completed == progress.steps[-1].total == 1
        assert progress.steps[-1].level == (0 if context_tokens == 128000 else 1)
        assert progress.last_progress_at


def test_unknown_semantic_call_keeps_its_original_ledger_and_does_not_resend(
    database, session, rag, monkeypatch
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings, _demand, searcher, search, _ = start_goal_search(database, session, rag)
    sent = []

    def handle(request):
        sent.append(request)
        raise httpx.ReadError("Original semantic receipt is unknown", request=request)
    gateway = ChatCompletionsGateway(settings, httpx.MockTransport(handle))
    state = drive_goal(database, session, rag, settings, searcher, search, gateway)
    assert state.status == "blocked_unknown" and len(sent) == 1
    with database.transaction() as connection:
        part = connection.execute(
            "SELECT run_id FROM knowledge.material_goal_coverage_parts WHERE search_id=%s",
            (search.id,),
        ).fetchone()
        assert connection.execute(
            "SELECT count(*) AS n FROM delivery.events WHERE actor_id=%s "
            "AND aggregate_id=%s AND event_type LIKE 'tutor.%%'",
            (session.actor.id, part["run_id"]),
        ).fetchone()["n"] == 0
    AgentLoop(TutorWorkflow(database, settings), gateway).run(part["run_id"])
    searcher.execute(search.id, rag["transport"])
    assert searcher.get(session.token, search.id).status == "blocked_unknown"
    assert len(sent) == 1


def test_retention_clears_goal_parts_and_original_runtime_body_but_keeps_call_facts(
    database, session, rag, monkeypatch
):
    monkeypatch.setattr("leornian.agent_runtime.gateway.resolve_destination", lambda *_: "1.1.1.1")
    settings, _demand, searcher, search, original = start_goal_search(database, session, rag)
    gateway, _sent = goal_gateway(settings)
    assert drive_goal(database, session, rag, settings, searcher, search, gateway).status == "ready"
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.document_permissions SET retain_until=now()-interval '1 second' "
            "WHERE document_id=%s AND document_revision=%s",
            (original.document_id, original.document_revision),
        )
    rag["intake"].expire_retained_inputs()
    with database.transaction() as connection:
        part = connection.execute(
            "SELECT result,state,run_id FROM knowledge.material_goal_coverage_parts "
            "WHERE search_id=%s", (search.id,),
        ).fetchone()
        run = connection.execute(
            "SELECT messages,context_refs FROM runtime.runs WHERE id=%s", (part["run_id"],)
        ).fetchone()
        call = connection.execute(
            "SELECT request,response_body,status,applied FROM runtime.external_calls "
            "WHERE run_id=%s",
            (part["run_id"],),
        ).fetchone()
    assert part["result"] is None and part["state"] == "purged"
    assert run["messages"] == [] and run["context_refs"] == []
    assert call["request"] == {"model": "fixture-material-check", "content_purged": True}
    assert call["response_body"] is None
    assert call["status"] == "result_recorded" and call["applied"]
