import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import prepare
from test_material_processing_retrieval import rag as rag
from test_teaching_delivery import drain, provider

from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput, MaterialTextJobInput
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.tutor.contracts import PlanningInput
from leornian.platform.model_contracts import ModelProfileInput


def change_space(session, rag):
    rag["configuration"].save_profile(
        session.token, str(uuid4()),
        ModelProfileInput(
            label="New embedding", connection_id=rag["connection"].id,
            model="different-embedding", operation="embedding", roles=["embedding"],
            embedding_dimensions=8, enabled=True, allow_private_material=True,
        ),
    )


def search(session, rag, query="Iteration"):
    searches = MaterialSearchWorkflow(rag["intake"].database, rag["settings"])
    job = searches.submit(
        session.token, str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id, expected_demand_revision=1, query=query
        ),
    )
    return searches, job


def test_rebuild_unknown_never_reissues_embedding_even_after_redelivery(session, rag):
    prepare(rag, session)
    change_space(session, rag)
    searches, job = search(session, rag)
    dispatched = []

    def unknown(request):
        dispatched.append(json.loads(request.content))
        raise httpx.ReadTimeout("Offline unknown", request=request)

    transport = httpx.MockTransport(unknown)
    searches.execute(job.id, transport)
    assert searches.get(session.token, job.id).status == "blocked_unknown"
    searches.execute(job.id, transport)
    assert len(dispatched) == 1
    assert searches.get(session.token, job.id).selection_id is None
    with searches.database.transaction(snapshot=True) as connection:
        calls = connection.execute(
            "SELECT status FROM runtime.external_calls WHERE actor_id=%s ORDER BY created_at",
            (session.actor.id,),
        ).fetchall()
    assert [r["status"] for r in calls] == ["result_recorded", "unknown"]


def test_cancelled_rebuild_keeps_late_receipt_without_apply_and_next_search_reuses_it(
    session, rag
):
    prepare(rag, session)
    change_space(session, rag)
    searches, job = search(session, rag)

    def cancel_in_flight(request):
        searches.cancel(session.token, job.id)
        return rag["transport"].handle_request(request)

    searches.execute(job.id, httpx.MockTransport(cancel_in_flight))
    assert searches.get(session.token, job.id).status == "cancelled"
    with searches.database.transaction(snapshot=True) as connection:
        calls = connection.execute(
            "SELECT status,applied FROM runtime.external_calls "
            "WHERE actor_id=%s ORDER BY created_at",
            (session.actor.id,),
        ).fetchall()
    assert calls[-1] == {"status": "result_recorded", "applied": False}
    assert len(rag["sent"]) == 2
    _, next_job = search(session, rag, "Iteration sequence")
    searches.execute(next_job.id, rag["transport"])
    assert len(rag["sent"]) == 2
    searches.execute(next_job.id, rag["transport"])
    assert searches.get(session.token, next_job.id).status == "ready"
    assert len(rag["sent"]) == 4


def test_hybrid_rebuilds_missing_space_without_omitting_another_ready_material(
    database, session, rag, material_setup
):
    original = prepare(rag, session)
    change_space(session, rag)
    _, goal, text = material_setup
    demand = rag["intake"].create_demand(
        session.token, str(uuid4()),
        MaterialDemandInput(goal_id=goal.id, purpose="teaching", required_facets=["Iteration"]),
    )
    second = rag["intake"].submit_text(
        session.token, demand.id, str(uuid4()),
        MaterialTextJobInput(
            expected_demand_revision=1,
            material=text.model_copy(update={"title": "Second material"}),
        ),
    )
    prepare(rag, session, second)
    searches, job = search(session, rag)
    searches.execute(job.id, rag["transport"])
    assert searches.get(session.token, job.id).error_code == "index_rebuild_pending"
    assert all(w.get("parameters", {}).get("text_type") != "query" for w in rag["sent"])
    searches.execute(job.id, rag["transport"])
    assert searches.get(session.token, job.id).status == "ready"
    with database.transaction(snapshot=True) as connection:
        scope = connection.execute(
            "SELECT scope FROM knowledge.material_searches WHERE id=%s", (job.id,)
        ).fetchone()["scope"]
        documents = connection.execute(
            "SELECT document_id,space FROM knowledge.material_index_builds "
            "WHERE id=ANY(%s::uuid[])",
            (scope["build_ids"],),
        ).fetchall()
    assert len(documents) == 2
    assert len({r["document_id"] for r in documents}) == 2
    assert all(r["space"]["dimensions"] == 8 for r in documents)
    assert rag["intake"].job(session.token, original.id).state == "ready"
    assert len(rag["sent"]) == 5


def test_another_search_waits_for_inflight_shared_rebuild_instead_of_dispatching_again(
    session, rag
):
    prepare(rag, session)
    change_space(session, rag)
    searches, job = search(session, rag)
    other = []

    def concurrent_search(request):
        _, second = search(session, rag, "Iteration concurrent")
        other.append(second)
        searches.execute(second.id, rag["transport"])
        state = searches.get(session.token, second.id)
        assert state.status == "waiting_dependency"
        assert state.error_code == "index_rebuild_in_progress"
        return rag["transport"].handle_request(request)

    searches.execute(job.id, httpx.MockTransport(concurrent_search))
    assert len(rag["sent"]) == 2
    searches.execute(other[0].id, rag["transport"])
    assert searches.get(session.token, other[0].id).status == "ready"
    assert len(rag["sent"]) == 4


def test_automatic_planning_demand_reuses_authorized_index_and_preserves_selection_origin(
    database, session, rag
):
    prepare(rag, session)
    settings = replace(
        rag["settings"], model_configuration_mode="development", model_enabled=True,
        model_base_url="https://owned.invalid/v1", model_name="offline-owned",
        model_api_key="offline-consumer-fixture", model_context_tokens=128000,
        model_max_output_tokens=32768,
    )
    tutor = TutorWorkflow(database, settings)
    conversation = tutor.conversation(session.token, rag["goal"].id)
    turn = tutor.submit_plan(
        session.token, conversation.id, str(uuid4()),
        PlanningInput(text="Use the material to teach iteration.", expected_revision=0),
    )
    demand = next(
        d for d in rag["intake"].demands(session.token, rag["goal"].id)
        if d.consumer_ref == f"tutor-turn:{turn.turn_id}:planning"
    )
    searches = MaterialSearchWorkflow(database, settings)
    job = searches.submit(
        session.token, str(uuid4()),
        MaterialSearchInput(
            demand_id=demand.id, expected_demand_revision=1, query="Iteration", mode="lexical"
        ),
    )
    searches.execute(job.id)
    result = searches.get(session.token, job.id)
    assert result.status == "ready"
    selection = searches.selection(session.token, result.selection_id)
    binding = rag["materials"].bind(
        session.token, str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id, purpose="planning", expected_binding_revision=0,
            refs=[e.ref for e in selection.evidence],
        ),
    )
    assert all(r.selection_id == selection.id for r in binding.refs)
    document = {
        "title": "Iteration", "summary": "Read the provided sequence.", "assumptions": [],
        "nodes": [{
            "key": "iteration", "title": "Iteration", "objective": "Iteration",
            "estimated_minutes": 20, "prerequisite_keys": [], "source_refs": [],
            "material_citations": [{
                "binding_id": str(binding.id), "binding_revision": 1, "purpose": "planning",
                "ref": r.model_dump(mode="json"),
            } for r in binding.refs],
        }],
    }
    gateway, _, _ = provider(settings, author=json.dumps(document))
    assert drain(tutor, settings, turn, gateway, session.token).status == "accepted"
    assert len(rag["sent"]) == 1
    with database.transaction(snapshot=True) as connection:
        from leornian.modules.learning.planning import Plans

        plan = Plans(connection).for_goal(session.actor, rag["goal"].id)
    assert all(
        c.ref.selection_id == selection.id for c in plan.latest.document.nodes[0].material_citations
    )


@pytest.mark.parametrize("mode", ["lexical", "hybrid"])
def test_get_and_submit_never_rebuild_or_dispatch(session, rag, mode):
    prepare(rag, session)
    change_space(session, rag)
    searches = MaterialSearchWorkflow(rag["intake"].database, rag["settings"])
    job = searches.submit(
        session.token, str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id, expected_demand_revision=1, query="Iteration", mode=mode
        ),
    )
    assert searches.get(session.token, job.id).status == "queued"
    assert len(rag["sent"]) == 1
    if mode == "lexical":
        searches.execute(job.id)
        assert searches.get(session.token, job.id).status == "ready"
        assert len(rag["sent"]) == 1
