import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_item_supply import document
from test_python_execution import code_document

from leornian.modules.item_bank.python_contracts import PythonItem, PythonQuestion
from leornian.modules.item_bank.supply_contracts import (
    AuthoredQuestion,
    ItemReview,
    PackMaterialContext,
    PublicQuestion,
)
from leornian.modules.learning.contracts import MaterialCitation


def citations():
    origin = MaterialCitation(
        binding_id=uuid4(), binding_revision=1, purpose="planning",
        ref={
            "document_id": uuid4(), "document_revision": 1, "block_id": uuid4(),
            "span": {"start": 0, "end": 10}, "content_digest": "a" * 64,
        },
    )
    return (
        origin,
        origin.model_copy(update={"binding_id": uuid4(), "purpose": "item_author"}),
        origin.model_copy(update={"binding_id": uuid4(), "purpose": "item_review"}),
    )


@pytest.mark.parametrize("python", [False, True])
def test_legacy_question_serialization_and_public_identity_do_not_change(python):
    raw = (code_document if python else document)(SimpleNamespace(id=uuid4()))["items"][0]
    private_type = PythonItem if python else AuthoredQuestion
    public_type = PythonQuestion if python else PublicQuestion
    public_fields = (
        [
            "slot", "language", "title", "prompt", "starter_code", "sample", "difficulty",
            "source_refs",
        ]
        if python else ["slot", "title", "prompt", "options", "difficulty", "source_refs"]
    )
    private_fields = public_fields + (
        ["tests", "explanation"] if python else ["correct_key", "explanation"]
    )
    item = private_type.model_validate(raw)
    old_private = {key: raw[key] for key in private_fields}
    old_public = {key: raw[key] for key in public_fields}
    assert item.model_dump(mode="json") == old_private
    assert item.model_dump_json() == json.dumps(
        old_private, ensure_ascii=False, separators=(",", ":")
    )
    assert item.public().model_dump_json() == json.dumps(
        old_public, ensure_ascii=False, separators=(",", ":")
    )
    assert "source_refs" in public_type.model_json_schema()["required"]
    for invalid in (
        {k: v for k, v in old_public.items() if k != "source_refs"},
        {**old_public, "source_refs": []},
    ):
        with pytest.raises(ValidationError):
            public_type.model_validate(invalid)


@pytest.mark.parametrize("python", [False, True])
def test_new_citations_keep_exact_reference_without_disclosing_private_answers(python):
    _, author, _ = citations()
    raw = (code_document if python else document)(SimpleNamespace(id=uuid4()))["items"][0]
    raw.update(source_refs=[], material_citations=[author.model_dump(mode="json")])
    item = (PythonItem if python else AuthoredQuestion).model_validate(raw)
    public = item.public().model_dump(mode="json")
    assert public["material_citations"] == [author.model_dump(mode="json")]
    assert not {"correct_key", "explanation", "tests"} & public.keys()


def test_old_review_shape_is_unchanged_but_new_review_evidence_is_serialized():
    old = {"slot": "practice_1", "verdict": "revise", "reason": "Ambiguous behavior."}
    report = ItemReview.model_validate(old)
    assert report.model_dump(mode="json") == old
    _, _, reviewer = citations()
    new = {**old, "material_citations": [reviewer.model_dump(mode="json")]}
    assert ItemReview.model_validate(new).model_dump(mode="json") == new


@pytest.mark.parametrize("change", ["purpose", "missing", "range", "duplicate"])
def test_pack_roles_must_bind_the_complete_exact_origin_for_each_separate_purpose(change):
    origin, author, reviewer = citations()
    value = PackMaterialContext(
        origin_citations=[origin], author_citations=[author], review_citations=[reviewer]
    ).model_dump(mode="json")
    if change == "purpose":
        value["review_citations"][0]["purpose"] = "item_author"
    elif change == "missing":
        value["review_citations"] = []
    elif change == "range":
        value["review_citations"][0]["ref"]["span"]["end"] = 9
    else:
        value["author_citations"] *= 2
    with pytest.raises(ValidationError):
        PackMaterialContext.model_validate(value)
