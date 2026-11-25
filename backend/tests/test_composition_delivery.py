import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_composition_directory import bfs_composition
from test_material_consumers import consumer as consumer
from test_material_lifecycle import material_setup as material_setup
from test_material_sources_and_goals import advance_consumer_materials
from test_teaching_delivery import body, drain, report

from leornian.agent_runtime.gateway import ChatCompletionsGateway
from leornian.agent_runtime.repository import Runs
from leornian.bootstrap.compositions import CompositionWorkflow
from leornian.bootstrap.learning_artifacts import LearningArtifactWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.execution.environments import Environments
from leornian.modules.knowledge.contracts import DocumentBlock, DocumentPage, MaterialRef
from leornian.modules.learning.contracts import MaterialCitation
from leornian.modules.tutor.contracts import TurnInput
from leornian.modules.tutor.learning_artifact_contracts import CancelAction
from leornian.shared_kernel.errors import BusinessError


def composition_provider(
    settings, *, conflict=None, definition=None, reply_text=None,
    preparation="prepare_learning_composition", extra=None, pacing=None, template=None,
):
    calls, prepared = [], []
    preparation_call_id = str(uuid4())

    def handle(request):
        wire = json.loads(request.content)
        calls.append(wire)
        if "Independently review" in wire["messages"][0]["content"]:
            assert "composition_checks" in json.loads(wire["messages"][-1]["content"])
            if conflict:
                conflict()
            return httpx.Response(200, json=body(json.dumps(report(
                json.loads(wire["messages"][-1]["content"])
            ))))
        receipt = next((message for message in reversed(wire["messages"])
                        if message["role"] == "tool"
                        and message.get("tool_call_id") == preparation_call_id), None)
        if receipt:
            value = json.loads(receipt["content"])
            assert value["status"] == "completed", value
            prepared.append(value["candidate"])
            return httpx.Response(200, json=body(json.dumps({
                "text": reply_text or (
                    "Observe discovery and the shared queue; this is not an assessment."
                ),
                "interaction": {
                    "type": "artifact", "exact_handle": value["candidate"]["id"],
                    "intent": "introduce_only",
                },
                **({"pacing": pacing} if pacing else {}),
            })))
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{
                        "id": preparation_call_id, "type": "function",
                        "function": {
                            "name": preparation,
                            "arguments": json.dumps({
                                "command_key": "owned-bfs-presentation",
                                **(template if template is not None else {"definition":
                                   definition if definition is not None else bfs_composition()}),
                                **(extra or {}),
                            }),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        })

    return ChatCompletionsGateway(settings, httpx.MockTransport(handle)), calls, prepared


def request(tutor, session, conversation, key=None, supported=True, text=None):
    accepted = tutor.submit(
        session.token, conversation.id, key or str(uuid4()),
        TurnInput(
            text=text or "Show breadth-first traversal of this directed graph.",
            presentation_capabilities={
                "versions": ["learning_composition.v2"] if supported else []
            },
        ),
    )
    advance_consumer_materials(tutor.database, session, tutor.settings, conversation.goal_id)
    return accepted


def test_preparation_checked_exact_handle_delivery_and_versioned_reads(
    database, workflow, session, consumer
):
    tutor, settings, conversation, _, _, _, _, _, _ = consumer
    key = str(uuid4())
    accepted = request(tutor, session, conversation, key)
    gateway, calls, prepared = composition_provider(settings)
    task = drain(tutor, settings, accepted, gateway, session.token)
    assert task.status == "accepted" and len(calls) == 3
    flow = LearningArtifactWorkflow(database)
    assert flow.list(session.token, conversation.id) == []
    summaries = flow.list_v2(session.token, conversation.id)
    assert len(summaries) == 1
    view = flow.get_v2(session.token, conversation.id, summaries[0].id)
    assert view.schema_version == "learning_artifact.v2"
    assert view.kind == "learning_composition" and not view.allowed_actions
    assert view.content_ref.owner == "tutor" and view.content_ref.revision == 1
    assert str(view.content_ref.id) == prepared[0]["content_ref"]["id"]
    assert view.presentation.definition.inputs["network"].start == "Y"
    snapshot = workflow.snapshot(session.token)
    assert not snapshot.node_progress
    assert not snapshot.python_attempts and not snapshot.choice_results
    turn = next(t for page in snapshot.turns for t in page.turns if t.id == accepted.turn_id)
    assert str(turn.learning_interaction.exact_handle) == prepared[0]["id"]
    assert request(tutor, session, conversation, key) == accepted
    assert tutor.requested_turn(session.token, conversation.id, key) == accepted
    with pytest.raises(BusinessError, match="No committed"):
        tutor.requested_turn(session.token, conversation.id, "unknown-request")
    with pytest.raises(BusinessError, match="support changed"):
        request(tutor, session, conversation, key, supported=False)
    with database.transaction() as connection:
        assert "prepare_learning_practice_composition" not in Runs(connection).lock(
            accepted.run_id
        )["tool_contracts"]
        presentation = connection.execute(
            "SELECT * FROM tutor.learning_presentations WHERE prepared_run_id=%s",
            (accepted.run_id,),
        ).fetchone()
        assert presentation["quality_call_id"] and presentation["accepted_at"]
        assert connection.execute(
            "SELECT pack_id,slot FROM tutor.learning_candidates WHERE id=%s",
            (prepared[0]["id"],),
        ).fetchone() == {"pack_id": None, "slot": None}
    data = CancelAction(
        action="cancel", client_action_id=uuid4(), expected_artifact_revision=view.revision
    )
    receipt = flow.action(session.token, conversation.id, view.id, data)
    assert receipt.state == "cancelled" and receipt.artifact_revision == 2
    assert flow.action(session.token, conversation.id, view.id, data) == receipt
    assert flow.action_receipt(
        session.token, conversation.id, view.id, data.client_action_id
    ) == receipt
    cancelled = flow.get_v2(session.token, conversation.id, view.id)
    assert cancelled.content_ref == view.content_ref
    assert cancelled.revision == 2 and not cancelled.allowed_actions
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer " + session.token}
    path = f"/v2/conversations/{conversation.id}/learning-artifacts/{view.id}"
    assert client.get(path, headers=headers).json()["content_ref"]["revision"] == 1
    assert client.get(
        path + f"/actions/{data.client_action_id}", headers=headers
    ).json()["artifact_revision"] == 2
    assert client.get(
        f"/v1/conversations/{conversation.id}/turn-requests/{key}", headers=headers
    ).json()["run_id"] == str(accepted.run_id)


def test_source_reader_uses_exact_bound_range_and_clears_permission_through_committed_event(
    database, workflow, session, consumer
):
    from datetime import UTC, datetime, timedelta

    from leornian.bootstrap.material_consumers import binding_citations
    from leornian.modules.knowledge.material_contracts import DocumentPermissionAction, MaterialSpan
    from leornian.modules.knowledge.materials import digest
    from leornian.modules.learning.material_contracts import MaterialBindingInput

    tutor, settings, conversation, materials, goal, _, _, _, text = consumer
    deadline = datetime.now(UTC) + timedelta(hours=1)
    version = materials.import_text(
        session.token, str(uuid4()), text.model_copy(update={"use_until": deadline})
    )
    block = materials.blocks(session.token, version.document_id, 1, "teaching").blocks[0]
    excerpt = block.text[2:-1]
    ref = block.ref.model_copy(update={
        "span": MaterialSpan(start=block.ref.span.start + 2, end=block.ref.span.end - 1),
        "content_digest": digest(excerpt),
    })
    binding = materials.bind(session.token, str(uuid4()), MaterialBindingInput(
        goal_id=goal.id, purpose="teaching", expected_binding_revision=0, refs=[ref]
    ))
    definition = bfs_composition()
    definition["components"].append({
        "id": "citation", "component": "SourceReference",
        "props": {
            "label": "Exact supplied paragraph",
            "citation": binding_citations([binding])[0].model_dump(mode="json"),
        },
    })
    accepted = request(tutor, session, conversation)
    gateway, _, _ = composition_provider(settings, definition=definition)
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    flow = LearningArtifactWorkflow(database)
    artifact = flow.list_v2(session.token, conversation.id)[0]
    newer = materials.import_text(session.token, str(uuid4()), text.model_copy(update={
        "document_id": version.document_id, "expected_revision": 1,
        "title": "Replacement version", "text": "New text must not replace a pinned citation.",
    }))
    assert newer.revision == 2
    source = flow.composition_source(
        session.token, conversation.id, artifact.id, "citation"
    )
    assert source.block.text == excerpt and source.block.ref == ref
    assert source.title == version.title
    assert source.valid_until == deadline
    assert source.location is None
    assert not source.excerpt
    other = workflow.create_session("Other reader")
    with pytest.raises(BusinessError, match="not found"):
        flow.composition_source(other.token, conversation.id, artifact.id, "citation")
    with pytest.raises(BusinessError, match="No source"):
        flow.composition_source(session.token, conversation.id, artifact.id, "player")
    revoked = materials.revoke(session.token, version.document_id, 1, DocumentPermissionAction(
        expected_revision=1, action="revoke"
    ))
    materials.revoke(session.token, version.document_id, 1, DocumentPermissionAction(
        expected_revision=revoked.permission.revision, action="revoke"
    ))
    events = [
        e for e in workflow.snapshot(session.token).events
        if e.event_type == "knowledge.material_permission_changed"
    ]
    assert len(events) == 1 and events[0].payload.document_id == version.document_id
    with pytest.raises(BusinessError):
        flow.composition_source(session.token, conversation.id, artifact.id, "citation")
    cancelled = flow.action(session.token, conversation.id, artifact.id, CancelAction(
        action="cancel", expected_artifact_revision=1, client_action_id=uuid4()
    ))
    assert cancelled.state == "cancelled"


@pytest.mark.parametrize("basis", [None, "document_page", "image_region", "document_part"])
def test_source_reader_projects_the_exact_parser_location(monkeypatch, basis):
    ref = MaterialRef(
        document_id=uuid4(), document_revision=2, block_id=uuid4(),
        span={"start": 0, "end": 11}, content_digest="a" * 64,
    )
    citation = MaterialCitation(
        binding_id=uuid4(), binding_revision=1, purpose="teaching", ref=ref
    )
    block = DocumentBlock(
        id=ref.block_id, ordinal=0, kind="paragraph", section_path=[],
        text="Source text", ref=ref, source_page=4 if basis else None,
    )
    location = DocumentPage(
        number=4, method="ocr", requires_ocr=False, reason_code=None,
        location_basis=basis,
        region=[1000, 1000, 1191, 1684] if basis == "image_region" else None,
        original_part="word/media/image4.png" if basis == "document_part" else None,
    ) if basis else None
    definition = SimpleNamespace(components=[
        SimpleNamespace(id="citation", component="SourceReference", props=SimpleNamespace(
            citation=citation
        ))
    ])
    monkeypatch.setattr(
        CompositionWorkflow, "current", lambda *_: (None, definition, None)
    )
    monkeypatch.setattr(
        "leornian.bootstrap.compositions.Tutor.get", lambda *_: SimpleNamespace(goal_id=uuid4())
    )
    monkeypatch.setattr(
        "leornian.bootstrap.compositions.read_citations_in", lambda *_: [block]
    )
    monkeypatch.setattr(
        "leornian.bootstrap.compositions.Materials.version",
        lambda *_: SimpleNamespace(
            title="Exact source", pages=[location] if location else [],
            permission=SimpleNamespace(use_until=None, retain_until=None),
        ),
    )
    source = CompositionWorkflow.source_in(None, None, uuid4(), None, "citation")
    assert source.block == block and source.citation == citation
    assert source.location == location


@pytest.mark.parametrize("definition", [
    {
        "schema_version": "learning_composition.v2", "title": "Parameter-linked binary search",
        "states": {"target": {"type": "number", "value": -2}, "cursor": {"type": "playback"}},
        "inputs": {"sequence": {
            "type": "binary_search", "values": [-7, -2, 3, 11], "target_state": "target",
        }},
        "components": [
            {"id": "target", "component": "ParameterControl", "props": {
                "label": "Target", "state": "target", "minimum": -10, "maximum": 20,
            }},
            {"id": "player", "component": "AlgorithmPlayer", "props": {
                "label": "Trace", "algorithm": "binary_search", "input": "sequence",
                "state": "cursor",
            }},
            {"id": "sequence", "component": "AlgorithmSequence", "props": {
                "label": "Search interval", "timeline": "player",
            }},
        ],
    },
    {
        "schema_version": "learning_composition.v2", "title": "Restricted HTML and CSS preview",
        "states": {
            "html": {"type": "code", "value": "<p>Owned preview input</p>"},
            "css": {"type": "code", "value": "p { color: teal; }"},
        },
        "components": [
            {"id": "html", "component": "CodeEditor", "props": {
                "label": "HTML", "state": "html",
            }},
            {"id": "css", "component": "CodeDiff", "props": {
                "label": "CSS changes", "state": "css", "before": "p { color: black; }",
            }},
            {"id": "preview", "component": "IsolatedPreview", "props": {
                "title": "Local preview", "html_state": "html", "css_state": "css",
            }},
            {"id": "refresh", "component": "ArtifactAction", "props": {
                "label": "Preview draft", "event": "preview", "for_component": "preview",
            }},
        ],
    },
], ids=["parameterized-search", "html-css-preview"])
def test_local_components_use_checked_native_preparation_not_only_bfs(
    database, workflow, session, consumer, definition
):
    tutor, settings, conversation, *_ = consumer
    accepted = request(tutor, session, conversation, text="Show " + definition["title"] + ".")
    reply_text = "Observe " + definition["title"] + "; this is not an assessment."
    gateway, calls, prepared = composition_provider(
        settings, definition=definition, reply_text=reply_text
    )
    assert drain(tutor, settings, accepted, gateway, session.token).status == "accepted"
    assert len(calls) == 3 and len(prepared) == 1
    flow = LearningArtifactWorkflow(database)
    artifact = flow.list_v2(session.token, conversation.id)[0]
    view = flow.get_v2(session.token, conversation.id, artifact.id)
    actual = view.presentation.definition
    assert actual.title == definition["title"]
    assert [node.component for node in actual.components] == [
        node["component"] for node in definition["components"]
    ]
    assert not view.allowed_actions
    snapshot = workflow.snapshot(session.token)
    assert next(
        turn for page in snapshot.turns for turn in page.turns
        if turn.id == accepted.turn_id
    ).assistant_text == reply_text
    assert not snapshot.python_attempts
    assert not snapshot.choice_results and not snapshot.node_progress
    with database.transaction(snapshot=True) as connection:
        assert Environments(connection).snapshot(session.actor).demands == []
    receipt = flow.action(session.token, conversation.id, artifact.id, CancelAction(
        action="cancel", expected_artifact_revision=1, client_action_id=uuid4()
    ))
    assert receipt.state == "cancelled"
    assert flow.get_v2(session.token, conversation.id, artifact.id).content_ref == view.content_ref


def test_unsupporting_client_run_does_not_gain_composition_tools(database, session, consumer):
    tutor, _, conversation, _, _, _, _, _, _ = consumer
    accepted = request(tutor, session, conversation, supported=False)
    with database.transaction() as connection:
        row = Runs(connection).lock(accepted.run_id)
        assert "prepare_learning_composition" not in row["tool_contracts"]
        assert "prepare_learning_practice_composition" not in row["tool_contracts"]
        assert "get_learning_component_contracts" not in row["tool_contracts"]
    tutor.cancel(session.token, accepted.run_id)


def test_teaching_cas_conflict_leaves_no_approved_composition_or_half_delivery(
    database, workflow, session, consumer
):
    tutor, settings, conversation, _, _, _, _, _, _ = consumer
    accepted = request(tutor, session, conversation)

    def conflict():
        with database.transaction() as connection:
            connection.execute(
                "UPDATE tutor.conversations SET teaching_revision=teaching_revision+1 WHERE id=%s",
                (conversation.id,),
            )

    gateway, _, prepared = composition_provider(settings, conflict=conflict)
    assert drain(tutor, settings, accepted, gateway, session.token).status == "superseded"
    assert not LearningArtifactWorkflow(database).list_v2(session.token, conversation.id)
    with database.transaction() as connection:
        assert connection.execute(
            "SELECT quality_call_id FROM tutor.learning_presentations WHERE prepared_run_id=%s",
            (accepted.run_id,),
        ).fetchone()["quality_call_id"] is None
        assert connection.execute(
            "SELECT 1 FROM tutor.learning_turn_candidates WHERE candidate_id=%s",
            (prepared[0]["id"],),
        ).fetchone() is None
    turn = next(
        t for page in workflow.snapshot(session.token).turns
        for t in page.turns if t.id == accepted.turn_id
    )
    assert turn.assistant_text is None and turn.learning_interaction is None
