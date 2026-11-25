from uuid import uuid4

import pytest
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import prepare
from test_material_processing_retrieval import rag as rag

from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.bootstrap.teaching_context import TeachingContext
from leornian.bootstrap.tutor import TutorWorkflow
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction, MaterialSpan
from leornian.modules.knowledge.materials import digest
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.tutor.contracts import TeachingFocus
from leornian.shared_kernel.errors import BusinessError


def bind_code_ranges(session, rag, values):
    job = prepare(rag, session)
    code = next(
        block
        for block in rag["materials"]
        .blocks(session.token, job.document_id, job.document_revision, "teaching")
        .blocks
        if block.kind == "code"
    )
    refs = []
    for value in values:
        start = code.ref.span.start + code.text.index(value)
        refs.append(
            code.ref.model_copy(
                update={
                    "span": MaterialSpan(start=start, end=start + len(value)),
                    "content_digest": digest(value),
                }
            )
        )
    binding = rag["materials"].bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id,
            purpose="teaching",
            expected_binding_revision=0,
            refs=refs,
        ),
    )
    return job, binding


def submit_search(session, rag, binding, *, query="print", mode="lexical"):
    searches = MaterialSearchWorkflow(rag["intake"].database, rag["settings"])
    search = searches.submit(
        session.token,
        str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id,
            expected_demand_revision=1,
            query=query,
            mode=mode,
            binding_id=binding.id,
            expected_binding_revision=binding.revision,
        ),
    )
    return searches, search


def selected(session, rag, searches, search):
    searches.execute(search.id, rag["transport"])
    result = searches.get(session.token, search.id)
    assert result.status == "ready", result
    return searches.selection(session.token, result.selection_id)


def test_lexical_bound_subrange_is_saved_and_read_by_actual_consumer(database, session, rag):
    _, binding = bind_code_ranges(session, rag, ["print(x)"])
    sent = len(rag["sent"])
    searches, search = submit_search(session, rag, binding)
    selection = selected(session, rag, searches, search)
    assert len(selection.evidence) == 1
    evidence = selection.evidence[0]
    assert evidence.text == "print(x)"
    assert evidence.ref.model_copy(update={"selection_id": None}) == binding.refs[0]
    assert evidence.ref.selection_id == selection.id
    assert evidence.ref.content_digest == digest(evidence.text)
    assert ORIGINAL[evidence.ref.span.start : evidence.ref.span.end] == evidence.text
    rebound = rag["materials"].bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=rag["goal"].id,
            purpose="teaching",
            expected_binding_revision=binding.revision,
            refs=[evidence.ref],
        ),
    )
    assert [
        block.text
        for block in rag["materials"]
        .bound_blocks(session.token, rebound.id, rebound.revision)
        .blocks
    ] == ["print(x)"]
    tutor = TutorWorkflow(database, rag["settings"])
    conversation = tutor.conversation(session.token, rag["goal"].id)
    with database.transaction() as connection:
        context, manifest = TeachingContext.build(
            connection, session.actor, conversation, TeachingFocus()
        )
    assert [block["text"] for block in context["bound_materials"][0]["blocks"]] == ["print(x)"]
    assert manifest["material_bindings"][0]["revision"] == rebound.revision
    assert len(rag["sent"]) == sent


def test_disjoint_ranges_in_one_chunk_stay_separate_and_exclude_outside_text(session, rag):
    _, binding = bind_code_ranges(session, rag, ["items", "print(x)"])
    searches, search = submit_search(session, rag, binding, query="items print")
    selection = selected(session, rag, searches, search)
    assert len(selection.evidence) == 2
    assert {e.text for e in selection.evidence} == {"items", "print(x)"}
    assert {
        e.ref.model_copy(update={"selection_id": None}).model_dump_json()
        for e in selection.evidence
    } == {ref.model_dump_json() for ref in binding.refs}
    assert all(e.ref.content_digest == digest(e.text) for e in selection.evidence)
    assert all("for x in" not in e.text and "```" not in e.text for e in selection.evidence)
    outside, search = submit_search(session, rag, binding, query="python")
    selection = selected(session, rag, outside, search)
    assert selection.evidence == []
    assert selection.coverage.status == "unavailable"


def test_hybrid_uses_parent_recall_but_only_reranks_the_bound_slice(session, rag):
    _, binding = bind_code_ranges(session, rag, ["print(x)"])
    sent = len(rag["sent"])
    searches, search = submit_search(
        session, rag, binding, query="display each element", mode="hybrid"
    )
    selection = selected(session, rag, searches, search)
    assert [e.text for e in selection.evidence] == ["print(x)"]
    assert len(rag["sent"]) == sent + 2
    embedding, rerank = rag["sent"][-2:]
    assert embedding["model"] == "fixture-embedding"
    assert embedding["parameters"]["text_type"] == "query"
    assert embedding["input"]["texts"] == ["display each element"]
    assert rerank["model"] == "fixture-rerank"
    assert rerank["input"]["documents"] == ["print(x)"]
    assert rerank["input"]["query"] == "display each element"
    assert selection.coverage.semantic_quality == "not_certified"


def test_bound_search_and_saved_selection_keep_live_material_permissions(session, rag):
    job, binding = bind_code_ranges(session, rag, ["print(x)"])
    searches, search = submit_search(session, rag, binding)
    selection = selected(session, rag, searches, search)
    assert selection.evidence
    _, queued = submit_search(session, rag, binding, query="print x")
    sent = len(rag["sent"])
    rag["materials"].revoke(
        session.token,
        job.document_id,
        job.document_revision,
        DocumentPermissionAction(expected_revision=1, action="revoke"),
    )
    with pytest.raises(BusinessError) as error:
        searches.selection(session.token, selection.id)
    assert error.value.code == "source_not_current"
    searches.execute(queued.id, rag["transport"])
    result = searches.get(session.token, queued.id)
    assert result.status == "waiting_dependency"
    assert result.selection_id is None
    assert len(rag["sent"]) == sent
