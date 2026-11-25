import json
from uuid import uuid4

import httpx
import pytest
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import rag as rag
from test_material_sources_and_goals import source_case as source_case

from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.material_discovery import MaterialDiscoveryWorkflow
from leornian.bootstrap.material_recovery import MaterialRecoveryWorkflow
from leornian.bootstrap.material_web import MaterialWebWorkflow
from leornian.bootstrap.model_configuration import ModelConfigurationWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.source_acquisition import MaterialSources
from leornian.modules.tutor.infrastructure import PgTutorStore
from leornian.platform.material_search_configuration import TavilyConfigurationInput
from leornian.shared_kernel.errors import BusinessError


def setup_search(database, session, source_case, *, examples=False):
    _workflow, settings, source, _key = source_case
    config = ModelConfigurationWorkflow(database, settings)
    config.save_tavily(session.token, TavilyConfigurationInput(
        expected_revision=0, enabled=True, api_key="tvly-owned-test-key",
    ))
    with database.transaction() as connection:
        demand = MaterialIntake(connection).ensure_consumer_demand(
            session.actor, f"planning-batch:{uuid4()}",
            MaterialDemandInput(
                goal_id=source.goal_id, purpose="planning", scope_mode="teaching_goal",
                preparation="initial", goal_text="Iteration over sequences",
            ),
        )
        sources = MaterialSources(connection)
        discovery = sources.ensure_discovery(session.actor, Identity.digest(session.token), demand)
        row = connection.execute(
            "SELECT * FROM knowledge.material_discovery_jobs WHERE id=%s", (discovery.id,),
        ).fetchone()
        if examples:
            row["acquisition_state"]["node_example_lookup"] = {
                "gaps": ["iteration"], "attempted": [], "searched": True,
            }
        assert MaterialWebWorkflow(database, settings).ensure_search(
            connection, session.actor, row, demand, [source.id], ["Iteration over sequences"],
            examples=examples,
        )
    return settings, source, demand, discovery, row


def test_example_lookup_keeps_only_authorized_hits_from_its_own_receipt(
    database, session, source_case,
):
    settings, _, _, discovery, _ = setup_search(database, session, source_case, examples=True)
    sent = []
    permitted = "https://source.invalid/approved/loop"

    def handle(request):
        wire = json.loads(request.content)
        assert "code example" in wire["query"] and wire["include_domains"] == ["source.invalid"]
        sent.append(wire["query"])
        return httpx.Response(200, json={"results": [
            {"url": permitted, "title": "A worked loop"},
            {"url": "https://source.invalid/other/loop", "title": "Outside approved prefix"},
        ], "request_id": "example-lookup"})

    web = MaterialWebWorkflow(database, settings)
    web.advance_search(discovery.id, httpx.MockTransport(handle))
    web.advance_search(discovery.id, httpx.MockTransport(handle))
    with database.transaction(snapshot=True) as connection:
        lookup = connection.execute(
            "SELECT acquisition_state->'node_example_lookup' AS lookup "
            "FROM knowledge.material_discovery_jobs WHERE id=%s", (discovery.id,),
        ).fetchone()["lookup"]
    assert len(sent) == 1 and lookup["hits"] == [permitted] and lookup["operation"]


@pytest.mark.parametrize("unknown", [False, True])
def test_expired_example_search_never_dispatches_and_keeps_an_unknown(
    database, session, source_case, unknown,
):
    settings, _, _, discovery, _ = setup_search(database, session, source_case, examples=True)
    with database.transaction() as connection:
        operation = connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state=jsonb_set("
            "acquisition_state,'{node_example_lookup,deadline_at}',"
            "to_jsonb((now()-interval '1 second')::text)) WHERE id=%s "
            "RETURNING acquisition_state->'node_example_lookup'->>'operation' AS id",
            (discovery.id,),
        ).fetchone()["id"]
        if unknown:
            journal = Runs(connection)
            call = journal.operation(operation)
            assert journal.dispatch(call.id)
            journal.record(call.id, unknown=True)
    web = MaterialWebWorkflow(database, settings)
    transport = httpx.MockTransport(lambda _: pytest.fail("Expired search was dispatched"))
    if unknown:
        with pytest.raises(BusinessError) as error:
            web.advance_search(discovery.id, transport)
        assert error.value.code == "external_result_unknown"
    else:
        web.advance_search(discovery.id, transport)
        web.advance_search(discovery.id, transport)
    with database.transaction(snapshot=True) as connection:
        status = Runs(connection).operation(operation).status
        assert status == ("unknown" if unknown else "not_sent")


def test_expired_example_read_is_not_sent_after_waiting_in_the_queue(
    database, session, source_case,
):
    workflow, _, source, _ = source_case
    _, _, _, discovery, _ = setup_search(database, session, source_case, examples=True)
    with database.transaction() as connection:
        sources = MaterialSources(connection)
        resource = sources.add_resource(source.id, "https://source.invalid/approved/run",
                                        1, label="Example", order=1)
        observation = sources.schedule(
            session.actor, source.id, Identity.digest(session.token),
            f"discovery:{discovery.id}:shallow-v1:{resource['id']}", resource_id=resource["id"],
        )
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET acquisition_state=jsonb_set("
            "jsonb_set(acquisition_state,'{node_example_lookup,deadline_at}',"
            "to_jsonb((now()-interval '1 second')::text)),'{node_example_lookup,attempted}',"
            "jsonb_build_array(%s::text)) WHERE id=%s", (resource["url"], discovery.id),
        )
    transport = httpx.MockTransport(lambda _: pytest.fail("Expired read sent"))
    workflow.execute(observation.id, transport)
    result = workflow.observation(session.token, observation.id)
    assert result.status == "cancelled" and result.error_code == "material_example_deadline"


def test_tavily_curates_authorized_urls_extracts_once_and_keeps_owned_key_private(
    database, session, source_case, workflow,
):
    settings, source, demand, discovery, row = setup_search(database, session, source_case)
    seen = []
    url = "https://source.invalid/approved/iteration"

    def handle(request):
        seen.append(request.url.path)
        wire = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer tvly-owned-test-key"
        if request.url.path == "/search":
            assert wire["include_domains"] == ["source.invalid"]
            assert wire["include_answer"] is False and wire["include_raw_content"] is False
            return httpx.Response(200, json={"results": [
                {"url": url, "title": "Iteration"},
                {"url": "https://source.invalid/approved/index", "title": "Contents"},
                {"url": "https://source.invalid/outside/secret", "title": "Out of scope"},
                {"url": "https://other.invalid/reference", "title": "Unapproved"},
            ], "request_id": "search-receipt"})
        assert wire["urls"] == [url] and "query" not in wire
        return httpx.Response(200, json={"results": [{
            "url": url, "raw_content": "# Iteration\n\nA loop visits every sequence item.",
        }], "failed_results": [], "request_id": "extract-receipt"})

    transport = httpx.MockTransport(handle)
    web = MaterialWebWorkflow(database, settings)
    web.advance_search(discovery.id, transport)
    with database.transaction() as connection:
        assert not web.ensure_search(
            connection, session.actor, row, demand, [source.id], ["Iteration over sequences"],
        )
        resource = connection.execute(
            "SELECT * FROM knowledge.material_source_resources WHERE source_id=%s AND url=%s",
            (source.id, url),
        ).fetchone()
        assert resource["acquisition_provider"] == "tavily"
        assert connection.execute(
            "SELECT acquisition_provider FROM knowledge.material_source_resources "
            "WHERE source_id=%s AND depth=0", (source.id,),
        ).fetchone()["acquisition_provider"] == "direct"
        observation = MaterialSources(connection).schedule(
            session.actor, source.id, Identity.digest(session.token),
            f"discovery:{discovery.id}:shallow-v1:{resource['id']}",
            resource_id=resource["id"],
        )
    source_workflow = source_case[0]
    source_workflow.execute(observation.id, transport)
    source_workflow.execute(observation.id, transport)
    assert seen == ["/search", "/extract"]
    current = source_workflow.observation(session.token, observation.id)
    assert current.upload_id and current.job_id
    with database.transaction(snapshot=True) as connection:
        receipts = connection.execute(
            "SELECT c.request,c.status FROM runtime.external_calls c "
            "JOIN knowledge.material_web_requests w ON w.id=c.operation_ref WHERE w.actor_id=%s",
            (session.actor.id,),
        ).fetchall()
    assert all(call["status"] == "result_recorded" for call in receipts)
    assert "tvly-owned-test-key" not in json.dumps(receipts)
    other = workflow.create_session("Other search owner")
    config = ModelConfigurationWorkflow(database, settings)
    assert not config.tavily_configuration(other.token).credential_present
    assert "tvly-owned-test-key" not in config.tavily_configuration(session.token).model_dump_json()


def test_unknown_tavily_receipt_is_not_dispatched_again(
    database, session, source_case, monkeypatch,
):
    settings, _source, _demand, discovery, _row = setup_search(database, session, source_case)
    seen = []
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.material_discovery_jobs SET status='processing',"
            "lease_token=%s,lease_until=now()+interval '2 minutes' WHERE id=%s",
            (uuid4(), discovery.id),
        )
    with monkeypatch.context() as patch:
        patch.setattr(
            MaterialWebWorkflow, "advance_search",
            lambda *_args, **_kwargs: pytest.fail("A duplicate worker consumed an owned search"),
        )
        MaterialDiscoveryWorkflow(database, settings).execute_semantic(discovery.id)
    with database.transaction() as connection:
        MaterialDiscoveryWorkflow.transition(connection, discovery.id, "queued")

    def interrupted(request):
        seen.append(request.url.path)
        raise httpx.ReadTimeout("Connection ended", request=request)

    web = MaterialWebWorkflow(database, settings)
    for _ in range(2):
        with pytest.raises(BusinessError, match="结果未知"):
            web.advance_search(discovery.id, httpx.MockTransport(interrupted))
    assert seen == ["/search"]


def test_failed_extract_automatically_uses_direct_source_without_repeating_tavily(
    database, session, source_case,
):
    settings, source, demand, discovery, _row = setup_search(database, session, source_case)
    url = "https://source.invalid/approved/iteration"
    web = MaterialWebWorkflow(database, settings)
    sent = []

    def handle(request):
        sent.append((request.method, request.url.path))
        if request.method == "GET":
            assert request.headers["host"] == "source.invalid"
            assert request.url.path == "/approved/iteration"
            return httpx.Response(
                200, headers={"Content-Type": "text/html"}, stream=httpx.ByteStream(
                    b"<main><h1>Iteration</h1><p>A loop visits every item.</p>"
                    b"<pre>for item in items:\n    print(item)</pre></main>",
                ),
            )
        return httpx.Response(200, json={
            "results": [{"url": url, "title": "Iteration"}]
            if request.url.path == "/search" else [], "failed_results": [],
        })

    transport = httpx.MockTransport(handle)
    web.advance_search(discovery.id, transport)
    with database.transaction() as connection:
        sources = MaterialSources(connection)
        resource = connection.execute(
            "SELECT * FROM knowledge.material_source_resources WHERE source_id=%s AND url=%s",
            (source.id, url),
        ).fetchone()
        observation = sources.schedule(
            session.actor, source.id, Identity.digest(session.token),
            f"discovery:{discovery.id}:shallow-v1:{resource['id']}",
            resource_id=resource["id"],
        )
        store = PgTutorStore(connection)
        conversation = store.conversation(session.actor, source.goal_id)
        turn, _ = store.request_turn(
            conversation.id, str(uuid4()), "Create the plan.", "planning", 0,
        )
        store.bind_material_demand(turn.id, demand.id)
    source_case[0].execute(observation.id, transport)
    failed = source_case[0].observation(session.token, observation.id)
    assert failed.status == "cancelled" and failed.error_code == "tavily_extraction_failed"
    with database.transaction(snapshot=True) as connection:
        source = connection.execute(
            "SELECT acquisition_provider FROM knowledge.material_source_resources WHERE id=%s",
            (resource["id"],),
        ).fetchone()
        original = MaterialSources(connection).observation(session.actor, observation.id)
        successor = connection.execute(
            "SELECT id,request_identity,status FROM knowledge.source_observations "
            "WHERE resource_id=%s AND id<>%s",
            (resource["id"], observation.id),
        ).fetchone()
    assert source["acquisition_provider"] == "direct" and original.status == "cancelled"
    assert successor["status"] == "queued"
    assert successor["request_identity"].get("acquisition_provider", "direct") == "direct"
    source_case[0].execute(successor["id"], transport)
    assert sent == [("POST", "/search"), ("POST", "/extract"), ("GET", "/approved/iteration")]
    current = source_case[0].observation(session.token, successor["id"])
    assert current.response_status == 200 and current.upload_id


def test_malformed_search_receipt_automatically_falls_back_to_approved_entries(
    database, session, source_case,
):
    settings, source, demand, discovery, row = setup_search(database, session, source_case)
    web = MaterialWebWorkflow(database, settings)
    sent = []

    def malformed(request):
        sent.append(request.url.path)
        return httpx.Response(200, text="invalid search response")

    web.advance_search(discovery.id, httpx.MockTransport(malformed))
    web.advance_search(discovery.id, httpx.MockTransport(malformed))
    with database.transaction() as connection:
        assert not web.ensure_search(
            connection, session.actor, row, demand, [source.id], ["Iteration over sequences"],
        )
        receipt = connection.execute(
            "SELECT w.applied,c.status,c.response_body FROM knowledge.material_web_requests w "
            "JOIN runtime.external_calls c ON c.operation_ref=w.id WHERE w.discovery_id=%s",
            (discovery.id,),
        ).fetchone()
    assert sent == ["/search"]
    assert receipt["applied"] and receipt["status"] == "result_recorded"
    assert receipt["response_body"] == "invalid search response"


def test_repair_recognizes_authorized_sources_without_a_new_learner_turn(
    database, session, source_case,
):
    settings, source, demand, discovery, _row = setup_search(database, session, source_case)
    MaterialWebWorkflow(database, settings).advance_search(
        discovery.id, httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []})),
    )
    with database.transaction() as connection:
        store = PgTutorStore(connection)
        conversation = store.conversation(session.actor, source.goal_id)
        turn, _ = store.request_turn(
            conversation.id, str(uuid4()), "Create the route.", "planning", 0,
        )
        store.bind_material_demand(turn.id, demand.id)
        MaterialDiscoveryWorkflow.transition(
            connection, discovery.id, "waiting_config", "approved_source_required",
        )
    result = MaterialRecoveryWorkflow(database, settings).repair(session.token, conversation.id)
    assert result.repaired_steps == 1
    with database.transaction() as connection:
        assert len(PgTutorStore(connection).turns(conversation.id)) == 1
        assert MaterialSources(connection).discovery(
            session.actor, demand.id, demand.revision,
        ).status == "queued"
        assert connection.execute(
            "SELECT count(*) AS n FROM knowledge.source_observations WHERE source_id=%s",
            (source.id,),
        ).fetchone()["n"] == 1


def test_manual_repair_rebinds_only_unsent_search_after_key_change(
    database, session, source_case,
):
    settings, source, demand, discovery, row = setup_search(database, session, source_case)
    with database.transaction() as connection:
        store = PgTutorStore(connection)
        conversation = store.conversation(session.actor, source.goal_id)
        turn, _ = store.request_turn(
            conversation.id, str(uuid4()), "Create the plan.", "planning", 0,
        )
        store.bind_material_demand(turn.id, demand.id)
        original = connection.execute(
            "SELECT id FROM knowledge.material_web_requests WHERE discovery_id=%s",
            (discovery.id,),
        ).fetchone()["id"]
        MaterialDiscoveryWorkflow.transition(
            connection, discovery.id, "waiting_config", "tavily_configuration_changed",
        )
    ModelConfigurationWorkflow(database, settings).save_tavily(
        session.token, TavilyConfigurationInput(
            expected_revision=1, enabled=True, api_key="tvly-owned-test-key",
        ),
    )
    repaired = MaterialRecoveryWorkflow(database, settings).repair(session.token, conversation.id)
    assert repaired.repaired_steps == 1
    with database.transaction() as connection:
        web = MaterialWebWorkflow(database, settings)
        assert web.ensure_search(
            connection, session.actor, row, demand, [source.id], ["Iteration over sequences"],
        )
        calls = connection.execute(
            "SELECT w.id,w.retired,c.status FROM knowledge.material_web_requests w "
            "JOIN runtime.external_calls c ON c.operation_ref=w.id WHERE w.discovery_id=%s",
            (discovery.id,),
        ).fetchall()
    assert len(calls) == 2 and all(call["status"] == "prepared" for call in calls)
    assert next(call for call in calls if call["id"] == original)["retired"]
