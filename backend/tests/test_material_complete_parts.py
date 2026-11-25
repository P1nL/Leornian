import base64
import io
import json
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter

from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.bootstrap.material_change_reviews import (
    MaterialChangeReviewWorkflow,
    review_comparison_scope,
)
from leornian.bootstrap.material_goal_coverage import (
    MaterialGoalCoverageWorkflow,
    parse_goal_verdict,
    summary_refs,
    validate_goal_verdict,
)
from leornian.modules.knowledge.change_contracts import MaterialBlockMapping
from leornian.modules.knowledge.docx_parser import parse_docx, render_docx_image
from leornian.modules.knowledge.file_parser import extract_file, parse_file
from leornian.modules.knowledge.goal_coverage_contracts import (
    MaterialGoalFinding,
    MaterialGoalVerdict,
)
from leornian.modules.knowledge.intake import MaterialIntake
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.material_contracts import DocumentBlock, MaterialRef
from leornian.modules.knowledge.materials import digest
from leornian.modules.knowledge.review_parts import partition_review_blocks
from leornian.shared_kernel.errors import BusinessError

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def docx(body, *, parts=None, rels=""):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:a="{A}">'
            f"<w:body>{body}</w:body></w:document>",
        )
        if rels:
            archive.writestr(
                "word/_rels/document.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                f'relationships">{rels}</Relationships>',
            )
        for name, content in (parts or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def ref(text="for value in values:\n    print(value)\n", revision=1):
    return MaterialRef(
        document_id=uuid4(),
        document_revision=revision,
        block_id=uuid4(),
        span={"start": 17, "end": 17 + len(text)},
        content_digest=digest(text),
    )


def test_docx_keeps_code_table_links_math_and_note_source_parts():
    source = docx(
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>Iteration</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Code"/></w:pPr>'
        "<w:r><w:t>for value in values:</w:t><w:br/><w:t>    print(value)</w:t></w:r></w:p>"
        '<w:p><w:hyperlink r:id="link"><w:r><w:t>Reference</w:t></w:r></w:hyperlink></w:p>'
        '<w:p><m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        "<m:r><m:t>x+1</m:t></m:r></m:oMath></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>",
        rels='<Relationship Id="link" Target="https://example.com/reference" '
        'TargetMode="External"/>',
        parts={
            "word/footnotes.xml": f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1">'
            "<w:p><w:r><w:t>Exact original note</w:t></w:r></w:p>"
            "</w:footnote></w:footnotes>"
        },
    )
    parsed = parse_docx(source)
    assert parsed["issues"] == []
    assert [block["kind"] for block in parsed["blocks"]] == [
        "heading",
        "code",
        "paragraph",
        "paragraph",
        "table",
        "paragraph",
    ]
    assert parsed["blocks"][1]["text"] == "for value in values:\n    print(value)"
    assert "https://example.com/reference" in parsed["blocks"][2]["text"]
    assert "x+1" in parsed["blocks"][3]["text"]
    assert parsed["blocks"][4]["text"] == "A\tB"
    assert parsed["blocks"][-1]["text"] == "Exact original note"
    assert all(page["location_basis"] == "document_part" for page in parsed["pages"])
    assert parsed["pages"][-1]["original_part"].startswith("word/footnotes.xml#1")
    assert extract_file(source, "docx") == parsed


def test_html_ignores_explicit_decorations_but_keeps_meaningful_graphics_and_math_pending():
    decorative = extract_file(
        b"<main><h1>Iteration</h1><p>A loop visits every item.</p>"
        b'<svg aria-hidden="true"><path d="M0 0"/></svg>'
        b'<canvas role="presentation"></canvas><img alt="" src="/logo.png"></main>',
        "html-main",
    )
    assert decorative["issues"] == []
    assert "A loop visits every item." in decorative["text"]
    for body in (
        b'<img src="/diagram.png" alt="The complete loop flow">',
        b'<svg><text>Meaningful flow</text></svg>',
        b"<math><msup><mi>x</mi><mn>2</mn></msup></math>",
    ):
        parsed = extract_file(b"<main><p>Original text.</p>" + body + b"</main>", "html-main")
        assert parsed["issues"] == ["html_nontext_content_pending"]


def test_docx_embedded_image_uses_complete_original_regions_without_external_fetch():
    image = io.BytesIO()
    Image.new("RGB", (1200, 100), "white").save(image, format="PNG")
    source = docx(
        '<w:p><w:r><w:t>Before</w:t></w:r><w:r><w:drawing><a:blip r:embed="figure"/>'
        "</w:drawing></w:r><w:r><w:t>After</w:t></w:r></w:p>",
        rels='<Relationship Id="figure" Target="media/figure.png"/>',
        parts={"word/media/figure.png": image.getvalue()},
    )
    parsed = parse_docx(source)
    regions = [page for page in parsed["pages"] if page["requires_ocr"]]
    assert [page["region"] for page in regions] == [[0, 0, 1000, 100], [1000, 0, 1200, 100]]
    assert [block["text"] for block in parsed["blocks"]] == ["Before", "After"]
    assert parsed["issues"] == ["docx_image_ocr_pending"]
    for page, width in zip(regions, [1000, 200], strict=True):
        rendered = base64.b64decode(render_docx_image(source, page["number"])["image"])
        with Image.open(io.BytesIO(rendered)) as actual:
            assert actual.size == (width, 100)
    external = docx(
        '<w:p><w:r><w:drawing><a:blip r:link="figure"/></w:drawing></w:r></w:p>',
        rels='<Relationship Id="figure" Target="https://example.com/figure.png" '
        'TargetMode="External"/>',
    )
    assert "docx_external_or_missing_image" in parse_docx(external)["issues"]


def test_docx_rejects_entity_package():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY e "value">]><x/>')
    with pytest.raises(BusinessError, match="Office XML cannot declare"):
        parse_docx(output.getvalue())


def test_pdf_metadata_and_page_ranges_cover_beyond_the_previous_eighty_page_limit():
    writer = PdfWriter()
    for _ in range(85):
        writer.add_blank_page(width=600, height=800)
    output = io.BytesIO()
    writer.write(output)
    source = output.getvalue()
    assert extract_file(source, "pdf-metadata") == {"page_count": 85}
    final = extract_file(source, "pdf-range:81:85")
    assert [page["number"] for page in final["pages"]] == list(range(81, 86))
    assert all(page["requires_ocr"] for page in final["pages"])


def test_oversized_change_blocks_are_split_into_exact_complete_old_and_new_ranges():
    blocks = []
    for revision in (1, 2):
        text = ("old " if revision == 1 else "new ") * 3000
        source = ref(text, revision)
        blocks.append(
            DocumentBlock(
                id=source.block_id,
                ordinal=0,
                kind="code",
                section_path=["Iteration"],
                text=text,
                ref=source,
            )
        )
    batches = partition_review_blocks(
        blocks, lambda pairs: sum(len(block.text) for block, _ in pairs) <= 1300
    )
    assert len(batches) > 16
    for original in blocks:
        pieces = sorted(
            [block for batch in batches for block, parent in batch if parent == original.ref],
            key=lambda block: block.ref.span.start,
        )
        assert "".join(piece.text for piece in pieces) == original.text
        assert pieces[0].ref.span.start == original.ref.span.start
        assert pieces[-1].ref.span.end == original.ref.span.end
        assert all(piece.ref.content_digest == digest(piece.text) for piece in pieces)
        assert all(
            left.ref.span.end == right.ref.span.start
            for left, right in zip(pieces, pieces[1:], strict=False)
        )


def test_appended_material_does_not_displace_unchanged_counterparts_in_review_parts():
    def block(text, revision, ordinal):
        source = ref(text, revision)
        return DocumentBlock(
            id=source.block_id, ordinal=ordinal, kind="paragraph",
            section_path=[], text=text, ref=source,
        )

    old = block("Original paragraph", 1, 0)
    current = block(old.text, 2, 0)
    added = block("New negative-index examples", 2, 1)
    report = SimpleNamespace(
        unchanged_blocks=[MaterialBlockMapping(baseline=old.ref, candidate=current.ref)],
        removed_or_changed_blocks=[], added_or_changed_blocks=[added.ref],
    )
    batches = partition_review_blocks(
        [added, old, current], lambda pairs: len(pairs) <= 2
    )
    assert [[value.ref for value, _ in batch] for batch in batches] == [
        [old.ref, current.ref], [added.ref]
    ]
    unchanged = review_comparison_scope(report, [old, current])
    assert [entry["role"] for entry in unchanged["block_inventory"]] == [
        "unchanged_context", "unchanged_context"
    ]
    assert unchanged["block_inventory"][0]["counterpart_ref"] == current.ref.model_dump(
        mode="json"
    )
    append_only = review_comparison_scope(report, [added])
    assert append_only["unmatched_baseline_blocks"] == 0
    assert append_only["unmatched_candidate_blocks"] == 1
    assert append_only["block_inventory"] == [{"block_index": 0, "role": "unmatched_candidate"}]


def test_review_windows_keep_verified_counterparts_and_real_replacements_distinct():
    original = ref("Unchanged paragraph")
    candidate = original.model_copy(update={"document_revision": 2, "block_id": uuid4()})
    removed, added = ref("Removed condition"), ref("Replacement condition", 2)
    report = SimpleNamespace(
        unchanged_blocks=[MaterialBlockMapping(baseline=original, candidate=candidate)],
        removed_or_changed_blocks=[removed], added_or_changed_blocks=[added],
    )
    window = original.model_copy(update={
        "span": original.span.model_copy(update={"end": original.span.start + 4}),
        "content_digest": digest("Unch"),
    })
    blocks = [
        DocumentBlock(
            id=source.block_id, ordinal=index, kind="paragraph", section_path=[],
            text=text, ref=source,
        )
        for index, (source, text) in enumerate([
            (window, "Unch"), (removed, "Removed condition"), (added, "Replacement condition"),
        ])
    ]
    scope = review_comparison_scope(report, blocks)
    assert scope["unmatched_baseline_blocks"] == scope["unmatched_candidate_blocks"] == 1
    assert [entry["role"] for entry in scope["block_inventory"]] == [
        "unchanged_context", "unmatched_baseline", "unmatched_candidate"
    ]
    assert scope["block_inventory"][0]["counterpart_ref"] == candidate.model_dump(mode="json")


@pytest.mark.parametrize("mode", ["keys", "legacy", "missing", "duplicate", "foreign", "full_refs"])
def test_change_review_restores_only_the_exact_recorded_reference_keys(mode):
    sources = [ref("First paragraph"), ref("Second paragraph")]
    keys = {f"r{index}": source.model_dump(mode="json") for index, source in enumerate(sources)}
    selected = list(keys)
    if mode == "missing":
        selected = selected[:1]
    elif mode == "duplicate":
        selected = ["r0", "r0"]
    elif mode == "foreign":
        selected = ["r0", "r2"]
    elif mode in {"legacy", "full_refs"}:
        selected = list(keys.values())
    content = {
        "classification": "semantic_change", "summary": "A source condition changed.",
        "reviewed_refs": selected,
    }
    call = SimpleNamespace(
        response_body=json.dumps({"choices": [{
            "message": {"role": "assistant", "content": json.dumps(content)},
            "finish_reason": "stop",
        }]}),
        policy_snapshot={"response_bytes": 1_000_000},
        context_manifest={
            "required_refs": list(keys.values()),
            **({"reference_keys": keys} if mode != "legacy" else {}),
        },
    )
    if mode in {"keys", "legacy"}:
        assert MaterialChangeReviewWorkflow.result(call).reviewed_refs == sources
    else:
        with pytest.raises(ModelProtocolError, match="incomplete_change_review"):
            MaterialChangeReviewWorkflow.result(call)


def test_semantic_goal_is_complete_text_and_keeps_original_facet_command_identity():
    legacy = MaterialDemandInput(goal_id=uuid4(), purpose="teaching", required_facets=["iteration"])
    identity = MaterialIntake.demand_request(legacy)
    assert "scope_mode" not in identity and "goal_text" not in identity
    goal = "Learn iteration, even when the word Learn is absent from the material."
    semantic = MaterialDemandInput(
        goal_id=legacy.goal_id, purpose="teaching", scope_mode="teaching_goal", goal_text=goal
    )
    assert MaterialIntake.demand_request(semantic)["goal_text"] == goal
    assert semantic.required_facets == []
    with pytest.raises(ValidationError):
        semantic.model_copy(update={"goal_text": None}).model_validate(
            {
                **semantic.model_dump(),
                "goal_text": None,
            }
        )


@pytest.mark.parametrize("change", ["missing_ref", "foreign_evidence", "duplicate_ref"])
def test_goal_coverage_requires_exact_exhaustive_refs(change):
    first, second = ref(), ref("An exact second source")
    result = MaterialGoalVerdict(
        status="supported",
        summary="The source explains iteration with a working loop.",
        evidence_refs=[first],
        reviewed_refs=[first, second],
    )
    if change == "missing_ref":
        result = result.model_copy(update={"reviewed_refs": [first]})
    elif change == "foreign_evidence":
        result = result.model_copy(update={"evidence_refs": [ref("foreign")]})
    else:
        result = result.model_copy(update={"reviewed_refs": [first, first, second]})
    with pytest.raises(ModelProtocolError, match="invalid_material_goal_output"):
        validate_goal_verdict(result, [first, second])


def test_goal_aggregate_consumes_all_children_and_cannot_clear_uncertainty():
    source = ref()
    children = [
        {"id": uuid4(), "result": {"status": "supported"}},
        {"id": uuid4(), "result": {"status": "uncertain"}},
    ]
    result = MaterialGoalVerdict(
        status="supported",
        summary="A complete aggregate.",
        evidence_refs=[source],
        reviewed_parts=[child["id"] for child in children],
    )
    with pytest.raises(ModelProtocolError):
        validate_goal_verdict(result, [source], children)
    validate_goal_verdict(result.model_copy(update={"status": "uncertain"}), [source], children)


def test_compact_goal_receipt_expands_all_135_exact_refs_and_rejects_unknown_keys():
    refs = [ref(f"Exact source {index}") for index in range(135)]
    data = {
        "status": "supported", "summary": "The complete source explains the learning goal.",
        "evidence_refs": ["ref_1", "ref_135"],
        "reviewed_refs": [f"ref_{index + 1}" for index in range(135)],
        "reviewed_parts": [],
    }
    result = parse_goal_verdict(json.dumps(data), refs)
    validate_goal_verdict(result, refs)
    assert result.reviewed_refs == refs
    assert result.evidence_refs == [refs[0], refs[-1]]
    with pytest.raises(ValidationError):
        parse_goal_verdict(json.dumps({**data, "evidence_refs": ["ref_136"]}), refs)


def test_html_graphical_content_stays_a_real_pending_dependency():
    parsed = parse_file(
        b"<main><h1>Iteration</h1><p>Explanation</p><svg><text>Graph</text></svg></main>",
        "html-main",
    )
    assert parsed["issues"] == ["html_nontext_content_pending"]


@pytest.mark.parametrize("scope", ["refs", "document"])
def test_scoped_source_defect_cannot_be_used_as_evidence(scope):
    good, bad = ref("Accurate concept"), ref("Outdated dependency")
    finding = MaterialGoalFinding(
        issue="version_mismatch", scope=scope, refs=[bad],
        topics=["dependency version"], explanation="The dependency example is outdated.",
    )
    result = MaterialGoalVerdict(
        status="supported", summary="The unaffected source supports this goal.",
        evidence_refs=[good], reviewed_refs=[good, bad],
        issues=["version_mismatch"], findings=[finding],
    )
    validate_goal_verdict(result, [good, bad])
    with pytest.raises(ValidationError, match="Defective source ranges"):
        MaterialGoalVerdict(**{**result.model_dump(), "evidence_refs": [bad]})
    with pytest.raises(ModelProtocolError):
        validate_goal_verdict(result, [good])


def test_document_finding_also_blocks_another_paragraph_in_the_same_document():
    bad = ref("Wrong language throughout")
    same_document = bad.model_copy(update={"block_id": uuid4()})
    with pytest.raises(ValidationError):
        MaterialGoalVerdict(
            status="supported", summary="Do not use an invalid document.",
            evidence_refs=[same_document],
            issues=["irrelevant"],
            findings=[MaterialGoalFinding(
                issue="irrelevant", scope="document", refs=[bad],
                explanation="The entire document teaches the wrong language.",
            )],
        )


def test_scoped_findings_resolve_short_keys_and_survive_aggregation():
    good, bad = ref("Usable text"), ref("Obsolete command")
    finding = {
        "issue": "version_mismatch", "scope": "refs", "refs": ["ref_2"],
        "explanation": "This command targets another version.",
    }
    data = {
        "status": "partial", "summary": "Useful concepts, but one command is obsolete.",
        "reviewed_refs": ["ref_1", "ref_2"], "evidence_refs": ["ref_1"],
        "issues": ["version_mismatch"], "findings": [finding],
    }
    result = parse_goal_verdict(json.dumps(data), [good, bad])
    validate_goal_verdict(result, [good, bad])
    child = {"id": uuid4(), "result": result.model_dump(mode="json")}
    combined = result.model_copy(update={
        "reviewed_refs": [], "reviewed_parts": [child["id"]],
    })
    validate_goal_verdict(combined, [good, bad], [child])
    with pytest.raises(ModelProtocolError):
        validate_goal_verdict(
            combined.model_copy(update={"findings": []}), [good, bad], [child],
        )
    with pytest.raises(ValidationError):
        parse_goal_verdict(json.dumps({
            **data, "findings": [{**finding, "refs": ["ref_3"]}],
        }), [good, bad])


def test_default_hybrid_index_mode_preserves_existing_demand_identity():
    data = MaterialDemandInput(
        goal_id=uuid4(), purpose="indexing", scope_mode="whole_source",
    )
    assert "index_mode" not in MaterialIntake.demand_request(data)
    lexical = data.model_copy(update={"index_mode": "lexical"})
    assert MaterialIntake.demand_request(lexical)["index_mode"] == "lexical"


def test_summary_catalog_keeps_defect_references_separate_from_usable_evidence():
    good, bad, complement = ref("Test basics"), ref("Obsolete command"), ref("Logging basics")
    finding = MaterialGoalFinding(
        issue="version_mismatch", refs=[bad], explanation="Only this command is obsolete.",
    )
    children = [
        {"id": uuid4(), "result": MaterialGoalVerdict(
            status="partial", summary="Test basics, with one separate obsolete command.",
            evidence_refs=[good], issues=["version_mismatch"], findings=[finding],
        ).model_dump(mode="json")},
        {"id": uuid4(), "result": MaterialGoalVerdict(
            status="partial", summary="Complementary logging basics.",
            evidence_refs=[complement],
        ).model_dump(mode="json")},
    ]
    refs = summary_refs(children)
    assert refs == [good, bad, complement]
    blocks = [
        DocumentBlock(
            id=item.block_id, ordinal=index, kind="paragraph",
            section_path=[], text="Original text", ref=item,
        )
        for index, item in enumerate(refs)
    ]
    role = MaterialGoalCoverageWorkflow.make_role("Plan tests and logging", blocks, children)
    payload = json.loads(role.messages[1]["content"])
    assert [item["reference_key"] for item in payload["reference_catalog"]] == [
        "ref_1", "ref_2", "ref_3",
    ]
    assert payload["complete_child_summaries"][0]["evidence_refs"] == ["ref_1"]
    assert payload["complete_child_summaries"][0]["findings"][0]["refs"] == ["ref_2"]
    combined = MaterialGoalVerdict(
        status="supported", summary="Independent usable explanations support the planning goal.",
        reviewed_parts=[child["id"] for child in children],
        evidence_refs=[good, complement], issues=["version_mismatch"], findings=[finding],
    )
    validate_goal_verdict(combined, refs, children)


def test_material_prompt_reuses_evidence_prefix_across_goals_and_prior_checks():
    source = ref("const total = 1;")
    block = DocumentBlock(
        id=source.block_id, ordinal=0, kind="code",
        section_path=["Basics"], text="const total = 1;", ref=source,
    )
    make_role = MaterialGoalCoverageWorkflow.make_role
    original = make_role("Choose a TypeScript textbook", [block], purpose="planning")
    changed = make_role(
        "Plan TypeScript variables", [block], purpose="planning",
        source_metadata={
            f"{source.document_id}:{source.document_revision}": {
                "unchanged_prior_checks": [{"summary": "Useful variable example."}],
            },
        },
    )
    first, second = (role.messages[1]["content"] for role in (original, changed))
    assert original.messages[0] == changed.messages[0]
    assert first.split('"source_documents":')[0] == second.split('"source_documents":')[0]
    payload = json.loads(second)
    assert payload["learning_goal"] == "Plan TypeScript variables"
    assert payload["source_parts"][0]["ref"] == source.model_dump(mode="json")
    assert payload["source_parts"][0]["text"] == block.text
    assert payload["source_documents"][0]["unchanged_prior_checks"]
    assert payload["check_scope"]["expected_reviewed_refs"] == ["ref_1"]


def test_material_check_omits_inline_image_bytes_but_keeps_unresolved_regions():
    source = ref("Partial article")
    block = DocumentBlock(
        id=source.block_id, ordinal=0, kind="paragraph",
        section_path=["Storage"], text="Partial article", ref=source,
    )
    regions = [
        {"ordinal": 0, "kind": "img", "label": "Unextracted diagram",
         "source_url": "data:image/png;base64," + "ABCD" * 10000,
         "section_path": ["Storage"], "after_block": 1},
        {"ordinal": 1, "kind": "img", "label": "Another unextracted diagram",
         "source_url": "https://source.invalid/storage.png",
         "section_path": ["Storage"], "after_block": 2},
    ]
    role = MaterialGoalCoverageWorkflow.make_role(
        "Choose storage reading", [block], purpose="planning",
        source_metadata={
            f"{source.document_id}:{source.document_revision}": {
                "unresolved_regions": regions,
            },
        },
    )
    payload = json.loads(role.messages[1]["content"])
    projected = payload["source_documents"][0]["unresolved_regions"]
    assert len(projected) == 2
    assert projected[0] == {
        **regions[0], "source_url": None, "inline_resource_omitted": True,
    }
    assert projected[1] == regions[1]
    assert regions[0]["source_url"].startswith("data:image/png;base64,")
    assert payload["source_parts"][0]["ref"] == source.model_dump(mode="json")
    assert len(role.messages[1]["content"]) < len(regions[0]["source_url"]) / 4


def test_planning_context_merges_prior_defects_and_selects_relevant_directory_entries():
    source = ref("Read storage on startup.")
    block = DocumentBlock(
        id=source.block_id, ordinal=0, kind="paragraph",
        section_path=["Storage"], text="Read storage on startup.", ref=source,
    )
    finding = {
        "issue": "version_mismatch", "scope": "refs",
        "refs": [source.model_dump(mode="json")], "topics": ["Old API"],
        "explanation": "An earlier checked API is obsolete.",
    }
    catalog = {
        "source_id": str(uuid4()), "title": "Browser guide",
        "source_url": "https://source.invalid/guide/",
        "evidence_document_ids": [str(source.document_id)],
        "chapters": [
            {"title": "Server deployment", "source_url": "https://source.invalid/server"},
            {"title": "localStorage", "source_url": "https://source.invalid/storage"},
            {"title": "Loading data", "source_url": "https://source.invalid/current"},
        ],
    }
    metadata = {f"{source.document_id}:{source.document_revision}": {
        "source_url": "https://source.invalid/current",
        "unchanged_prior_checks": [
            {"summary": "Latest source synopsis.", "issues": [], "findings": []},
            {"summary": "Older repeated synopsis.", "issues": ["version_mismatch"],
             "findings": [finding]},
            {"summary": "Another repeated synopsis.", "issues": ["version_mismatch"],
             "findings": [finding]},
        ],
        "curriculum_sources": [catalog, catalog],
    }}
    original = json.dumps(metadata, sort_keys=True)
    role = MaterialGoalCoverageWorkflow.make_role(
        "localStorage", [block], purpose="planning", source_metadata=metadata,
    )
    payload = json.loads(role.messages[1]["content"])
    document = payload["source_documents"][0]
    assert document["unchanged_prior_checks"] == [{
        "summary": "Latest source synopsis.", "issues": ["version_mismatch"],
        "findings": [finding],
    }]
    assert len(document["curriculum_sources"]) == 1
    selected = document["curriculum_sources"][0]
    assert selected["total_chapters"] == 3
    assert [chapter["ordinal"] for chapter in selected["chapters"]] == [1, 2]
    assert "evidence_document_ids" not in selected
    assert payload["source_parts"][0]["ref"] == source.model_dump(mode="json")
    assert json.dumps(metadata, sort_keys=True) == original
