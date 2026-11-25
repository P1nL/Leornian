import hashlib
import io
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_material_intake import intake_setup as intake_setup
from test_material_lifecycle import ORIGINAL
from test_material_lifecycle import material_setup as material_setup

from leornian.bootstrap.material_files import MaterialFilesWorkflow
from leornian.bootstrap.material_intake import MaterialIntakeWorkflow
from leornian.entrypoints.api import create_app
from leornian.modules.knowledge.file_contracts import (
    MAX_FILE_BYTES,
    FileMaterialInput,
    MaterialFileJobInput,
    MaterialUploadInput,
)
from leornian.modules.knowledge.file_parser import (
    HTML_MAIN_PARSER_VERSION,
    extract_file,
    main_html,
    parse_file,
)
from leornian.modules.knowledge.file_store import OriginalFileStore
from leornian.modules.knowledge.material_contracts import DocumentPermissionAction
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.platform.config import Settings
from leornian.shared_kernel.errors import BusinessError

HTML = (
    "<html><head><title>Not body</title><style>hide()</style></head><body>"
    "<h1>中文 Python</h1><script>do_not_run()</script>"
    "<p>Use &lt; and &amp; as text.</p>"
    "<pre><code>for value in values:\n    print(value)\n</code></pre>"
    "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    "</body></html>"
).encode()


def pdf_bytes(texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Courier"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 40 700 Td (" + text.encode("ascii") + b") Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def files_setup(database, intake_setup):
    _, demand, _, _ = intake_setup
    settings = Settings(
        database_url=database.url,
        material_storage_dir=str(Path(__file__).parents[2] / ".runtime" / "test-materials"),
    )
    return (
        MaterialFilesWorkflow(database, settings),
        MaterialIntakeWorkflow(database, settings),
        demand,
    )


def upload_request(demand, content, format="html", **updates):
    return MaterialUploadInput(
        expected_demand_revision=demand.revision,
        content_digest=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        material=FileMaterialInput(
            goal_id=demand.goal_id,
            title="File material",
            format=format,
            authorized_use=True,
            purposes=["reference", "teaching", "indexing"],
            **updates,
        ),
    )


def stored(files, session, demand, content=HTML, format="html", **updates):
    data = upload_request(demand, content, format, **updates)
    upload = files.reserve(session.token, demand.id, str(uuid4()), data)
    files.store_content(session.token, upload.id, content)
    return upload


def submitted(files, session, demand, upload):
    return files.submit(
        session.token,
        demand.id,
        str(uuid4()),
        MaterialFileJobInput(expected_demand_revision=demand.revision, upload_id=upload.id),
    )


def test_html_extracts_structures_without_running_or_rewriting_original():
    parsed = parse_file(HTML, "html")
    assert parsed["text_basis"] == "extracted_text" and parsed["issues"] == []
    assert [block["kind"] for block in parsed["blocks"]] == [
        "heading",
        "paragraph",
        "code",
        "table",
    ]
    assert parsed["blocks"][2]["text"] == "for value in values:\n    print(value)\n"
    assert parsed["blocks"][3]["text"] == "A\tB\n1\t2"
    assert "Use < and & as text." in parsed["text"]
    assert "do_not_run" not in parsed["text"] and "Not body" not in parsed["text"]
    assert all(parsed["text"][b["start"] : b["end"]] == b["text"] for b in parsed["blocks"])


def test_article_content_outweighs_short_recommendation_articles():
    content = (
        "<html><nav>Topics</nav><div class='article-content'><h1>Unit testing</h1>"
        "<p>" + "A test makes assertions about actual behavior. " * 30
        + "</p><pre>@Test\nvoid example() { assertEquals(2, 1 + 1); }</pre></div>"
        "<article><a href='/other'>CPU cache recommendations</a></article></html>"
    ).encode()
    parsed = parse_file(content, "html-main")
    assert "assertEquals" in parsed["text"]
    assert "CPU cache" not in parsed["text"]


@pytest.mark.parametrize("attributes", [
    'class="theme-article-content"',
    'class="theme-markdown"',
    'itemprop="articleBody"',
])
def test_prefixed_article_containers_exclude_page_navigation(attributes):
    content = (
        '<html><div class="site-menu"><a href="/login">Log in</a>'
        '<a href="/events">Community events</a></div>'
        f"<div {attributes}><h1>Working with collections</h1>"
        "<p>Keep the original entries in insertion order.</p>"
        "<pre>for (var item : items) { consume(item); }</pre></div>"
        '<div class="recommendations">Unrelated article suggestions</div></html>'
    ).encode()
    parsed = parse_file(content, "html-main")
    assert "consume(item)" in parsed["text"]
    assert "Log in" not in parsed["text"] and "Community events" not in parsed["text"]
    assert "Unrelated article suggestions" not in parsed["text"]


@pytest.mark.parametrize("layout", ["legacy", "styled"])
def test_repository_embedded_source_preserves_code_and_unresolved_diagram_location(layout):
    source = (
        "# Tests\n\nUse assertions.\n\n```java\nassertEquals(2, 1 + 1);\n```\n\n![Flow](flow.svg)"
    )
    blob = {"rawLines": source.splitlines()}
    payload = {"blob" if layout == "legacy" else "codeViewBlobLayoutRoute.StyledBlob": blob}
    content = (
        '<nav>Repository navigation</nav><script type="application/json" '
        'data-target="react-app.embeddedData">'
        + json.dumps({"payload": payload}) + "</script>"
    ).encode()
    parsed = parse_file(content, "html-main")
    assert "Repository navigation" not in parsed["text"] and "assertEquals" in parsed["text"]
    assert any(block["kind"] == "code" for block in parsed["blocks"])
    assert parsed["issues"] == ["html_nontext_content_pending"]
    assert parsed["unresolved_regions"][0]["after_block"] == len(parsed["blocks"]) - 1
    assert parsed["unresolved_regions"][0]["section_path"] == ["Tests"]
    assert all(parsed["text"][block["start"]:block["end"]] == block["text"]
               for block in parsed["blocks"])


def test_repository_code_file_is_not_misread_as_markdown():
    source = "def example():\n    # preserve indentation\n    return 42\n"
    content = (
        '<script type="application/json" data-target="react-app.embeddedData">'
        + json.dumps({"payload": {"blob": {"rawLines": source.split("\n"), "path": "example.py"}}})
        + "</script>"
    ).encode()
    parsed = parse_file(content, "html-main")
    assert len(parsed["blocks"]) == 1 and parsed["blocks"][0]["kind"] == "code"
    assert parsed["blocks"][0]["text"] == source
    assert parsed["issues"] == []


def test_html_reports_nontext_context_without_discarding_usable_text():
    parsed = parse_file(
        b"<main><h1>Logging</h1><p>Use a logger.</p>"
        b'<img src="/flow.svg" alt="Logging flow"><pre>logger.info("Ready");</pre></main>',
        "html-main",
    )
    assert parsed["issues"] == ["html_nontext_content_pending"]
    assert 'logger.info("Ready");' in parsed["text"]
    assert parsed["unresolved_regions"] == [{
        "ordinal": 0, "kind": "img", "label": "Logging flow", "source_url": "/flow.svg",
        "section_path": ["Logging"], "after_block": 2,
    }]


def test_readability_locates_unlabelled_body_without_changing_technical_structures(monkeypatch):
    import socket

    def offline(*_args, **_kwargs):
        pytest.fail("HTML extraction must not fetch sources.")

    monkeypatch.setattr(socket.socket, "connect", offline)
    code = "def total(values):\n    return sum(values)\n"
    content = (
        '<html><div><a href="/login">Log in</a><a href="/events">Events</a></div>'
        '<main><header><h1><a href="#lesson">Working with totals</a></h1></header>'
        '<div data-record="lesson"><p>' + "Add the values without changing their order. " * 12
        + "</p><h2><a href='#example'>Example</a></h2>"
        f"<pre><code>{code}</code></pre>"
        '<p hidden>Hidden navigation</p><p style="display: none">Hidden promotion</p>'
        "<table><tr><th>Input</th><th>Output</th></tr><tr><td>1, 2</td><td>3</td></tr></table>"
        '<p>Use the following flow to understand the call.</p>'
        '<svg aria-label="Call flow"><path d="M0 0L5 5"/></svg>'
        '<iframe src="/interactive-flow"></iframe>'
        '</div></main><div class="recommendations">Unrelated suggestions</div></html>'
    ).encode()
    parsed = parse_file(content, "html-main")
    assert parsed["parser_version"] == HTML_MAIN_PARSER_VERSION
    assert "Log in" not in parsed["text"] and "Unrelated suggestions" not in parsed["text"]
    assert "Hidden navigation" not in parsed["text"] and "Hidden promotion" not in parsed["text"]
    assert [block["text"] for block in parsed["blocks"] if block["kind"] == "code"] == [code]
    assert [block["text"] for block in parsed["blocks"] if block["kind"] == "table"] == [
        "Input\tOutput\n1, 2\t3",
    ]
    assert [block["text"] for block in parsed["blocks"] if block["kind"] == "heading"] == [
        "Working with totals", "Example",
    ]
    assert [region["kind"] for region in parsed["unresolved_regions"]] == ["svg", "iframe"]
    assert parsed["unresolved_regions"][1]["source_url"] == "/interactive-flow"
    assert all(region["section_path"] == ["Working with totals", "Example"]
               for region in parsed["unresolved_regions"])
    assert all(parsed["text"][block["start"]:block["end"]] == block["text"]
               for block in parsed["blocks"])
    assert "data-leornian-source-node" not in main_html(content.decode())


def test_known_readability_parse_failure_uses_one_local_fallback(monkeypatch):
    from readability import Document
    from readability.readability import Unparseable

    calls = []

    def fail(*_args, **_kwargs):
        calls.append(1)
        raise Unparseable("unparseable fixture")

    monkeypatch.setattr(Document, "summary", fail)
    parsed = parse_file(
        b"<nav>Menu</nav><article><h1>Short lesson</h1><pre>print(1)</pre></article>",
        "html-main",
    )
    assert calls == [1]
    assert "print(1)" in parsed["text"] and "Menu" not in parsed["text"]
    assert parsed["parser_version"] == HTML_MAIN_PARSER_VERSION


def test_main_html_canonicalizes_line_endings_without_changing_code_indentation():
    code = "def example():\r\n\treturn 42\r\n"
    content = f"<main><h1>Example</h1><pre>{code}</pre></main>".encode()
    parsed = parse_file(content, "html-main")
    assert [block["text"] for block in parsed["blocks"] if block["kind"] == "code"] == [
        code.replace("\r\n", "\n"),
    ]
    assert [block["text"] for block in parse_file(content, "html")["blocks"]
            if block["kind"] == "code"] == [code]


@pytest.mark.parametrize("format", ["html", "html-main"])
def test_actual_parser_subprocess_is_bounded_and_receives_no_secrets(monkeypatch, format):
    monkeypatch.setenv("LEORNIAN_MODEL_API_KEY", "must-not-enter-parser")
    original = subprocess.run
    calls = []

    def record(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record)
    parsed = extract_file(HTML, format)
    assert parsed["parser_version"] == (
        HTML_MAIN_PARSER_VERSION if format == "html-main" else "html-text.v1"
    )
    assert calls[0]["timeout"] == 60 and "LEORNIAN_MODEL_API_KEY" not in calls[0]["env"]


def test_pdf_pages_keep_actual_provenance_and_missing_text_requires_ocr():
    parsed = extract_file(
        pdf_bytes(["Iterate over the sequence.", None, "Keep the final page too."]), "pdf"
    )
    assert [p["number"] for p in parsed["pages"]] == [1, 2, 3]
    assert [p["requires_ocr"] for p in parsed["pages"]] == [False, True, False]
    assert [b["source_page"] for b in parsed["blocks"]] == [1, 3]
    assert parsed["pages"][1]["method"] == "none" and "pdf_ocr_pending" in parsed["issues"]
    assert all("bbox" not in b for b in parsed["blocks"])
    assert all(parsed["text"][b["start"] : b["end"]] == b["text"] for b in parsed["blocks"])


def test_invalid_encrypted_large_and_non_utf8_inputs_have_safe_reasons():
    for content, format, code in (
        (b"not a PDF", "pdf", "material_format_mismatch"),
        (b"\xff\xfe\x00", "text", "material_encoding_required"),
        (b"binary\x00text", "text", "material_text_limit"),
        (b"x" * (MAX_FILE_BYTES + 1), "text", "material_file_limit"),
        (b"# Topic\n" * 10_001, "markdown", "material_block_limit"),
    ):
        with pytest.raises(BusinessError) as error:
            parse_file(content, format)
        assert error.value.code == code
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("fixture-only-secret")
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(BusinessError) as error:
        extract_file(output.getvalue(), "pdf")
    assert error.value.code == "material_encrypted"


def test_file_text_limit_is_separate_from_direct_text_import_limit():
    from leornian.modules.knowledge.material_contracts import TextMaterialImport

    text = "x" * 2_000_001
    assert parse_file(text.encode(), "text")["text"] == text
    with pytest.raises(ValidationError):
        TextMaterialImport(
            goal_id=uuid4(), title="Direct text", source_url="https://example.com/text",
            text=text, authorized_use=True, purposes=["teaching"],
        )


def test_parser_timeout_is_not_an_unknown_external_call(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(BusinessError) as error:
        extract_file(HTML, "html")
    assert error.value.code == "material_parser_timeout"


def test_file_reference_contract_cannot_carry_host_paths_or_unbounded_payload():
    with pytest.raises(ValidationError):
        MaterialFileJobInput(expected_demand_revision=1, upload_id=r"C:\secret")
    with pytest.raises(ValidationError):
        MaterialUploadInput(
            expected_demand_revision=1,
            content_digest="a" * 64,
            byte_size=20_000_001,
            material={
                "goal_id": uuid4(),
                "title": "x",
                "format": "pdf",
                "authorized_use": True,
                "purposes": ["teaching"],
            },
        )


def test_uuid_storage_rejects_mismatched_bytes_and_cleans_staging(tmp_path):
    store = OriginalFileStore(tmp_path)
    actor, upload = uuid4(), uuid4()
    with pytest.raises(BusinessError):
        store.put(actor, upload, HTML, "0" * 64, len(HTML))
    assert not list(tmp_path.rglob("*"))
    store.put(actor, upload, HTML, hashlib.sha256(HTML).hexdigest(), len(HTML))
    assert store.read(actor, upload) == HTML
    pending = tmp_path / str(actor) / (str(upload) + ".pending")
    pending.write_bytes(b"crashed staging")
    store.delete(actor, upload)
    assert not pending.exists() and not list(tmp_path.rglob("*.blob"))


def test_upload_and_task_dedupe_are_content_bound(database, session, files_setup):
    files, intake, demand = files_setup
    key = str(uuid4())
    data = upload_request(demand, HTML)
    first = files.reserve(session.token, demand.id, key, data)
    assert files.reserve(session.token, demand.id, str(uuid4()), data).id == first.id
    assert files.reserve(session.token, demand.id, key, data) == first
    with pytest.raises(BusinessError) as error:
        files.reserve(
            session.token,
            demand.id,
            key,
            data.model_copy(update={"content_digest": "0" * 64}),
        )
    assert error.value.code == "idempotency_conflict"
    with pytest.raises(BusinessError):
        files.store_content(session.token, first.id, b"other bytes")
    files.store_content(session.token, first.id, HTML)
    files.store_content(session.token, first.id, HTML)
    job = submitted(files, session, demand, first)
    assert submitted(files, session, demand, first).id == job.id
    intake.execute(job.id)
    prepared = intake.job(session.token, job.id)
    assert prepared.phase == "indexing" and prepared.state == "waiting_dependency"
    assert prepared.document_id is not None and prepared.upload_id == first.id
    assert HTML.decode() not in prepared.model_dump_json()
    assert files.original(session.token, first.id, "teaching") == HTML
    with database.transaction(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM knowledge.document_versions WHERE upload_id=%s",
                (first.id,),
            ).fetchone()["n"]
            == 1
        )


def test_file_reads_and_parsing_preserve_goal_owner_and_permission(
    database,
    workflow,
    session,
    files_setup,
    material_setup,
):
    files, intake, demand = files_setup
    materials, _, _ = material_setup
    upload = stored(files, session, demand)
    other = workflow.create_session("Other owner")
    with pytest.raises(BusinessError):
        files.original(other.token, upload.id, "teaching")
    with pytest.raises(BusinessError):
        files.original(session.token, upload.id, "item_review")
    wrong = upload_request(demand, HTML)
    wrong = wrong.model_copy(
        update={"material": wrong.material.model_copy(update={"goal_id": uuid4()})}
    )
    with pytest.raises(BusinessError):
        files.reserve(session.token, demand.id, str(uuid4()), wrong)
    job = submitted(files, session, demand, upload)
    intake.execute(job.id)
    prepared = intake.job(session.token, job.id)
    page = materials.blocks(session.token, prepared.document_id, 1, "teaching")
    assert page.document.text_basis == "extracted_text" and page.document.upload_id == upload.id
    assert page.document.source_url == "leornian-upload:" + str(upload.id)
    assert all(block.span_basis == "extracted_text" for block in page.blocks)
    materials.revoke(
        session.token,
        prepared.document_id,
        1,
        DocumentPermissionAction(expected_revision=1, action="revoke"),
    )
    with pytest.raises(BusinessError):
        files.original(session.token, upload.id, "teaching")


def test_scan_like_page_waits_for_user_ocr_not_development_fallback(
    session,
    files_setup,
    material_setup,
):
    files, intake, demand = files_setup
    materials, _, _ = material_setup
    upload = stored(files, session, demand, pdf_bytes([None]), "pdf")
    job = submitted(files, session, demand, upload)
    intake.execute(job.id)
    result = intake.job(session.token, job.id)
    assert result.state == "waiting_config" and result.phase == "ocr"
    assert result.reason_code == "ocr_configuration_required"
    version = materials.version(session.token, result.document_id, 1)
    assert version.processing_state == "partial" and version.pages[0].requires_ocr
    assert materials.blocks(session.token, result.document_id, 1, "teaching").blocks == []


def test_cancel_fences_file_parse_and_discards_only_unconsumed_original(
    session,
    files_setup,
    monkeypatch,
):
    files, intake, demand = files_setup
    upload = stored(files, session, demand)
    job = submitted(files, session, demand, upload)
    claim = intake._claim(job.id)
    assert claim is not None
    intake.cancel(session.token, job.id)
    monkeypatch.setattr(intake, "_claim", lambda _: claim)
    intake.execute(job.id)
    assert intake.job(session.token, job.id).document_id is None
    assert files.upload(session.token, upload.id).state == "purged"
    with pytest.raises(BusinessError):
        files.original(session.token, upload.id, "teaching")


def test_cancel_after_parse_does_not_delete_lawfully_retained_document(session, files_setup):
    files, intake, demand = files_setup
    upload = stored(files, session, demand)
    job = submitted(files, session, demand, upload)
    intake.execute(job.id)
    intake.cancel(session.token, job.id)
    assert files.original(session.token, upload.id, "teaching") == HTML


def test_file_parse_cannot_commit_after_its_lease_expires(
    database, session, files_setup, monkeypatch
):
    files, intake, demand = files_setup
    upload = stored(files, session, demand)
    job = submitted(files, session, demand, upload)

    def expire(*_args):
        with database.transaction() as connection:
            connection.execute(
                "UPDATE knowledge.material_jobs SET lease_until=now()-interval '1 second' "
                "WHERE id=%s",
                (job.id,),
            )
        return parse_file(HTML, "html")

    with monkeypatch.context() as patch:
        patch.setattr("leornian.bootstrap.material_intake.extract_file", expire)
        intake.execute(job.id)
    assert intake.job(session.token, job.id).document_id is None
    intake.execute(job.id)
    assert intake.job(session.token, job.id).document_id is not None


def test_expired_unused_upload_cleans_incomplete_file_not_its_reference(
    database, session, files_setup
):
    files, _, demand = files_setup
    upload = files.reserve(session.token, demand.id, str(uuid4()), upload_request(demand, HTML))
    path = files.store.root / str(session.actor.id) / (str(upload.id) + ".pending")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"interrupted partial upload")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.material_uploads SET expires_at=now()-interval '1 second' "
            "WHERE id=%s",
            (upload.id,),
        )
    with pytest.raises(BusinessError):
        files.store_content(session.token, upload.id, HTML)
    assert files.expire_retained() >= 1
    assert not path.exists() and files.upload(session.token, upload.id).state == "purged"


def test_expiry_purges_original_and_derived_content_not_metadata_or_failures(
    database,
    session,
    files_setup,
    material_setup,
):
    files, intake, demand = files_setup
    materials, _, _ = material_setup
    upload = stored(files, session, demand, retain_until=datetime.now(UTC) + timedelta(days=1))
    job = submitted(files, session, demand, upload)
    intake.execute(job.id)
    prepared = intake.job(session.token, job.id)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.document_permissions SET retain_until=now()-interval '1 second' "
            "WHERE document_id=%s",
            (prepared.document_id,),
        )
    with pytest.raises(BusinessError):
        files.original(session.token, upload.id, "teaching")
    assert intake.expire_retained_inputs() >= 2
    version = materials.version(session.token, prepared.document_id, 1)
    assert version.content_state == "purged" and version.purged_at is not None
    assert files.upload(session.token, upload.id).state == "purged"
    assert len(intake.job(session.token, job.id).steps) >= 3
    with database.transaction(snapshot=True) as connection:
        row = connection.execute(
            "SELECT original_text,content_digest FROM knowledge.document_versions "
            "WHERE document_id=%s",
            (prepared.document_id,),
        ).fetchone()
        assert row["original_text"] is None and row["content_digest"]
        blocks = connection.execute(
            "SELECT text,section_path,content_digest FROM knowledge.document_blocks "
            "WHERE document_id=%s",
            (prepared.document_id,),
        ).fetchall()
        assert blocks and all(b["text"] is None and b["section_path"] == [] for b in blocks)
    assert not (files.store.root / str(session.actor.id) / (str(upload.id) + ".blob")).exists()


def test_text_command_identity_keeps_digest_not_an_indefinite_original(
    database,
    session,
    material_setup,
):
    materials, _, data = material_setup
    key = str(uuid4())
    result = materials.import_text(session.token, key, data)
    with database.transaction(snapshot=True) as connection:
        request = connection.execute(
            "SELECT request FROM knowledge.document_commands WHERE document_id=%s",
            (result.document_id,),
        ).fetchone()["request"]
    assert "text" not in request and request["text_digest"] == result.content_digest
    assert ORIGINAL not in str(request)
    assert materials.import_text(session.token, key, data) == result


def test_text_retention_keeps_pinned_binding_audit_not_original_or_headings(
    database, session, material_setup, files_setup
):
    materials, goal, data = material_setup
    _, intake, _ = files_setup
    data = data.model_copy(update={"retain_until": datetime.now(UTC) + timedelta(days=1)})
    version = materials.import_text(session.token, str(uuid4()), data)
    blocks = materials.blocks(session.token, version.document_id, 1, "teaching").blocks
    binding = materials.bind(
        session.token,
        str(uuid4()),
        MaterialBindingInput(
            goal_id=goal.id,
            purpose="teaching",
            expected_binding_revision=0,
            refs=[block.ref for block in blocks],
        ),
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE knowledge.document_permissions SET retain_until=now()-interval '1 second' "
            "WHERE document_id=%s",
            (version.document_id,),
        )
    assert intake.expire_retained_inputs() >= 1
    assert materials.binding(session.token, binding.id, 1).refs == binding.refs
    with pytest.raises(BusinessError):
        materials.bound_blocks(session.token, binding.id, 1)
    assert materials.version(session.token, version.document_id, 1).content_state == "purged"


def test_upload_api_roundtrip_does_not_parse_on_get_or_render_html(session, files_setup):
    files, intake, demand = files_setup
    with TestClient(create_app(files.settings)) as client:
        headers = {"Authorization": "Bearer " + session.token, "Idempotency-Key": str(uuid4())}
        upload = client.post(
            f"/v1/material-demands/{demand.id}/uploads",
            headers=headers,
            json=upload_request(demand, HTML).model_dump(mode="json"),
        )
        assert upload.status_code == 201
        upload_id = upload.json()["id"]
        preflight = client.options(
            f"/v1/material-uploads/{upload_id}/content",
            headers={
                "Origin": "http://127.0.0.1:5178",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert preflight.status_code == 200
        assert HTML.decode() not in upload.text and str(files.store.root) not in upload.text
        mismatch = client.put(
            f"/v1/material-uploads/{upload_id}/content",
            headers={**headers, "Content-Type": "application/octet-stream"},
            content=b"x" * len(HTML),
        )
        assert (
            mismatch.status_code == 409 and mismatch.json()["code"] == "material_content_mismatch"
        )
        assert (
            client.put(
                f"/v1/material-uploads/{upload_id}/content",
                headers=headers,
                content=HTML,
            ).status_code
            == 409
        )
        assert (
            client.put(
                f"/v1/material-uploads/{upload_id}/content",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=HTML,
            ).json()["state"]
            == "stored"
        )
        response = client.get(
            f"/v1/material-uploads/{upload_id}/content?purpose=teaching",
            headers=headers,
        )
        assert (
            response.content == HTML
            and response.headers["content-type"] == "application/octet-stream"
        )
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["content-security-policy"] == "sandbox"
        job = client.post(
            f"/v1/material-demands/{demand.id}/files",
            headers=headers,
            json={"upload_id": upload_id, "expected_demand_revision": 1},
        )
        assert job.status_code == 202 and job.json()["state"] == "queued"
        assert (
            client.get(
                f"/v1/material-jobs/{job.json()['id']}",
                headers=headers,
            ).json()["document_id"]
            is None
        )
        intake.cancel(session.token, job.json()["id"])
