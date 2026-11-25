from uuid import uuid4

import pytest
from test_material_lifecycle import material_setup as material_setup
from test_material_processing_retrieval import prepare
from test_material_processing_retrieval import rag as rag

from leornian.bootstrap.material_search import MaterialSearchWorkflow
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput, MaterialTextJobInput
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.knowledge.retrieval import Retrieval
from leornian.modules.knowledge.retrieval_contracts import MaterialSearchInput
from leornian.platform.model_contracts import ModelProfileInput


def revise(session, rag, original, text):
    demand = rag["intake"].create_demand(
        session.token,
        str(uuid4()),
        MaterialDemandInput(
            goal_id=rag["goal"].id, purpose="teaching", required_facets=["Iteration"]
        ),
    )
    return rag["intake"].submit_text(
        session.token,
        demand.id,
        str(uuid4()),
        MaterialTextJobInput(
            expected_demand_revision=1,
            material=rag["material"].model_copy(
                update={
                    "document_id": original.document_id,
                    "expected_revision": original.document_revision,
                    "text": text,
                }
            ),
        ),
    )


def test_revised_material_only_embeds_changed_inputs_and_keeps_exact_locators(
    database, session, rag, material_setup
):
    rag["material"] = material_setup[2]
    original = prepare(rag, session)
    before = len(rag["sent"])
    updated = revise(
        session, rag, original, rag["material"].text.replace("print(x)", "print(x + 1)")
    )
    current = prepare(rag, session, updated)
    assert len(rag["sent"]) == before + 1
    assert rag["sent"][-1]["input"]["texts"] == [
        "```python\nfor x in items:\n    print(x + 1)\n```\n"
    ]
    with database.transaction(snapshot=True) as connection:
        rows = connection.execute(
            "SELECT b.document_revision,c.reused_from_chunk_id,c.block_id,db.document_revision "
            "AS block_revision FROM knowledge.material_chunks c "
            "JOIN knowledge.material_index_builds b ON b.id=c.build_id "
            "JOIN knowledge.document_blocks db ON db.id=c.block_id "
            "WHERE b.job_id=%s AND b.space->>'model'='fixture-embedding' ORDER BY c.ordinal",
            (current.id,),
        ).fetchall()
    assert len(rows) == 4
    assert sum(r["reused_from_chunk_id"] is not None for r in rows) == 3
    assert all(r["document_revision"] == r["block_revision"] == 2 for r in rows)


def test_identical_new_version_completes_index_without_new_model_call(
    database, session, rag, material_setup
):
    rag["material"] = material_setup[2]
    original = prepare(rag, session)
    before = len(rag["sent"])
    current = prepare(rag, session, revise(session, rag, original, rag["material"].text))
    assert len(rag["sent"]) == before
    assert current.document_revision == 2
    with database.transaction(snapshot=True) as connection:
        states = connection.execute(
            "SELECT state FROM knowledge.material_index_builds WHERE job_id=%s", (current.id,)
        ).fetchall()
    assert [r["state"] for r in states] == ["indexed", "indexed"]


@pytest.mark.parametrize("change", ["revoked", "cancelled", "space"])
def test_reuse_never_bypasses_permission_or_mixes_spaces(session, rag, material_setup, change):
    rag["material"] = material_setup[2]
    original = prepare(rag, session)
    if change == "revoked":
        rag["materials"].revoke(
            session.token,
            original.document_id,
            1,
            DocumentPermissionAction(expected_revision=1, action="revoke"),
        )
    elif change == "cancelled":
        rag["intake"].cancel(session.token, original.id)
    else:
        rag["configuration"].save_profile(
            session.token,
            str(uuid4()),
            ModelProfileInput(
                label="Different space",
                connection_id=rag["connection"].id,
                model="different-embedding",
                operation="embedding",
                roles=["embedding"],
                enabled=True,
                allow_private_material=True,
                embedding_dimensions=8,
            ),
        )
    before = len(rag["sent"])
    prepare(rag, session, revise(session, rag, original, rag["material"].text))
    assert len(rag["sent"]) == before + 1
    assert len(rag["sent"][-1]["input"]["texts"]) == 4


def test_repeated_builds_do_not_duplicate_retrieval_evidence(database, session, rag):
    original = prepare(rag, session)
    with database.transaction() as connection:
        # Multiple lexical preprocessing builds must not repeat one immutable source range.
        job = connection.execute(
            "SELECT * FROM knowledge.material_jobs WHERE id=%s", (original.id,)
        ).fetchone()
        actor = Identity(PgIdentityStore(connection)).authenticate(session.token)
        retrieval = Retrieval(connection)
        build = retrieval.build(actor, job, {"mode": "lexical", "preprocessing": "another.v1"})
        connection.execute(
            "UPDATE knowledge.material_index_builds SET state='indexed' WHERE id=%s",
            (build["id"],),
        )
    searches = MaterialSearchWorkflow(database, rag["settings"])
    search = searches.submit(
        session.token,
        str(uuid4()),
        MaterialSearchInput(
            demand_id=rag["demand"].id,
            expected_demand_revision=1,
            query="Iteration items print",
            mode="lexical",
        ),
    )
    searches.execute(search.id)
    result = searches.selection(session.token, searches.get(session.token, search.id).selection_id)
    refs = [e.ref.model_dump_json() for e in result.evidence]
    assert len(refs) == 3
    assert len(refs) == len(set(refs))
