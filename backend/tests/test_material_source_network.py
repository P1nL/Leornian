import base64
import gzip
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from leornian.modules.knowledge.file_parser import (
    HTML_MAIN_PARSER_VERSION,
    extract_file,
    page_image_regions,
    parse_file,
    render_image_region,
)
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.source_catalog import official_sources
from leornian.modules.knowledge.source_extraction import SourceLinks, teaching_identity
from leornian.modules.knowledge.source_network import ApprovedSourceClient, approved_source_url
from leornian.shared_kernel.errors import BusinessError


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example.test/book/a",
        "https://127.0.0.1/book/a",
        "https://docs.example.test:8443/book/a",
        "https://docs.example.test/book/../secret",
        "https://docs.example.test/book/%2e%2e/secret",
        "https://docs.example.test/book/%252e%252e/",
        "https://docs.example.test/book/%2Fsecret",
        "https://docs.example.test/bookish/a",
        "https://other.example.test/book/a",
        "https://docs.example.test/book/a?token=private",
    ],
)
def test_approved_scope_rejects_other_origins_and_path_escapes(url):
    with pytest.raises(BusinessError):
        approved_source_url(url, ["https://docs.example.test/book/"])


def test_conditional_public_pinning_redirects_and_bounded_gzip(monkeypatch):
    resolutions, requests = [], []

    def resolve(origin, _local):
        resolutions.append(origin)
        return "1.1.1.1"

    monkeypatch.setattr("leornian.modules.knowledge.source_network.resolve_destination", resolve)

    def handle(request):
        requests.append(request)
        assert request.url.host == "1.1.1.1"
        assert request.headers["host"] == "docs.example.test"
        assert request.extensions["sni_hostname"] == "docs.example.test"
        assert request.headers["if-none-match"] == '"old"'
        assert request.headers["if-modified-since"] == "Thu, 05 Nov 2026 01:00:00 GMT"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        if request.url.path.endswith("start"):
            return httpx.Response(
                302, headers={"Location": "chapter", "Set-Cookie": "secret=not-forwarded"}
            )
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip", "ETag": '"new"', "Content-Type": "text/plain"},
            stream=httpx.ByteStream(gzip.compress(b"Iteration source")),
        )

    response = ApprovedSourceClient(transport=httpx.MockTransport(handle)).get(
        "https://docs.example.test/book/start",
        ["https://docs.example.test/book/"],
        etag='"old"',
        last_modified="Thu, 05 Nov 2026 01:00:00 GMT",
    )
    assert response.content == b"Iteration source"
    assert response.url == "https://docs.example.test/book/chapter"
    assert response.etag == '"new"'
    assert len(requests) == 2 and len(resolutions) == 2


@pytest.mark.parametrize("late", ["redirect", "body"])
def test_example_get_keeps_its_deadline_through_redirects_and_streaming(monkeypatch, late):
    now = datetime.now(UTC)
    deadline = now + timedelta(seconds=3)
    requests = []
    monkeypatch.setattr("leornian.modules.knowledge.source_network.datetime",
                        SimpleNamespace(now=lambda _: now))
    monkeypatch.setattr("leornian.modules.knowledge.source_network.resolve_destination",
                        lambda *_: "1.1.1.1")

    def fetch(request):
        nonlocal now
        requests.append(request.url.path)
        assert request.extensions["timeout"]["read"] == 3
        now = deadline
        if late == "redirect":
            return httpx.Response(302, headers={"Location": "next"})
        return httpx.Response(200, stream=httpx.ByteStream(b"too late"))

    with pytest.raises(BusinessError) as stopped:
        ApprovedSourceClient(transport=httpx.MockTransport(fetch)).get(
            "https://guide.invalid/doc/start", ["https://guide.invalid/doc/"], deadline=deadline,
        )
    assert stopped.value.code == "material_example_deadline" and requests == ["/doc/start"]


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_public_get_network_failures_are_replaceable(monkeypatch, failure):
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_network.resolve_destination", lambda *_: "1.1.1.1"
    )

    def interrupted(request):
        raise failure("Public source is unavailable.", request=request)

    with pytest.raises(BusinessError) as error:
        ApprovedSourceClient(transport=httpx.MockTransport(interrupted)).get(
            "https://docs.example.test/book/start", ["https://docs.example.test/book/"],
        )
    assert error.value.code == "source_network_unavailable"


def test_source_redirect_cannot_reach_loopback_or_unapproved_path(monkeypatch):
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_network.resolve_destination", lambda *_: "1.1.1.1"
    )
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/private"})

    with pytest.raises(BusinessError, match="not public"):
        ApprovedSourceClient(transport=httpx.MockTransport(handle)).get(
            "https://docs.example.test/book/start", ["https://docs.example.test/book/"]
        )
    assert len(requests) == 1


def test_compressed_limit_is_on_decoded_original_not_content_length(monkeypatch):
    monkeypatch.setattr(
        "leornian.modules.knowledge.source_network.resolve_destination", lambda *_: "1.1.1.1"
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=httpx.ByteStream(gzip.compress(b"x" * 10000)),
        )
    )
    with pytest.raises(BusinessError, match="byte limit"):
        ApprovedSourceClient(max_bytes=1024, transport=transport).get(
            "https://docs.example.test/book/a", ["https://docs.example.test/book/"]
        )


def test_source_main_scope_ignores_navigation_but_keeps_teaching_dates_code_and_tables():
    def html(nav, code="print(1)", date="2026-11-07"):
        return (
            f"<html><nav>{nav}</nav><main><h1>Iteration</h1><p>Date: {date}</p>"
            f"<pre>{code}</pre><table><tr><td>n</td><td>1</td></tr></table></main>"
            "<footer>2026 page built</footer></html>"
        ).encode()

    first = parse_file(html("Old nav"), "html-main")
    other = parse_file(html("New nav"), "html-main")
    assert teaching_identity(first) == teaching_identity(other)
    assert teaching_identity(first) != teaching_identity(
        parse_file(html("New nav", "print(2)"), "html-main")
    )
    assert teaching_identity(first) != teaching_identity(
        parse_file(html("New nav", date="2025-01-01"), "html-main")
    )
    assert [block["kind"] for block in first["blocks"]] == ["heading", "paragraph", "code", "table"]
    assert "nav" not in first["text"] and "page built" not in first["text"]
    assert first["blocks"][2]["text"] == "print(1)"


def test_single_article_inside_main_excludes_page_controls_and_contributor_images():
    content = (
        b'<article>Unrelated promotion</article><main><button><svg></svg>Menu</button>'
        b'<article><h1>Iteration</h1><p>Visit every item.</p><pre>print(1)</pre>'
        b'<nav><svg></svg>Next chapter</nav></article>'
        b'<img src="/avatar.png" alt="Contributor"><p>Page feedback</p></main>'
    )
    parsed = parse_file(content, "html-main")
    assert parsed["parser_version"] == HTML_MAIN_PARSER_VERSION and parsed["issues"] == []
    assert [block["text"] for block in parsed["blocks"]] == [
        "Iteration", "Visit every item.", "print(1)"
    ]


def test_copy_controls_and_hidden_icons_do_not_turn_text_examples_into_missing_diagrams():
    parsed = parse_file(
        b'<main><h1>Iteration</h1><button aria-label="Copy code"><svg></svg>Copy</button>'
        b'<span aria-hidden="true"><svg></svg></span>'
        b'<img aria-hidden="true" src="/spacer.png"><pre>print(1)</pre></main>',
        "html-main",
    )
    assert parsed["issues"] == []
    assert [block["text"] for block in parsed["blocks"]] == ["Iteration", "print(1)"]


def test_unresolved_region_changes_are_not_treated_as_navigation_noise():
    def parsed(path):
        return parse_file(
            f'<main><h1>Iteration</h1><p>Visit every item.</p><img src="{path}" '
            'alt="Iteration diagram"></main>'.encode(), "html-main",
        )
    first, second = parsed("/old.svg"), parsed("/new.svg")
    assert first["blocks"] == second["blocks"]
    assert teaching_identity(first) != teaching_identity(second)


@pytest.mark.parametrize("body", [
    b"<svg><text>Teaching diagram</text></svg>",
    b'<img src="/diagram.png" alt="A teaching diagram">',
    b"<math><mi>x</mi></math>",
])
def test_article_selection_keeps_meaningful_nontext_content_pending(body):
    parsed = parse_file(
        b"<main><button><svg></svg>Menu</button><article><p>Explanation.</p>"
        + body + b"</article></main>",
        "html-main",
    )
    assert parsed["issues"] == ["html_nontext_content_pending"]


def test_multiple_articles_inside_main_preserve_all_sections():
    parsed = parse_file(
        b"<main><h1>Collected lessons</h1><article><p>First lesson</p></article>"
        b"<article><p>Second lesson</p></article></main>",
        "html-main",
    )
    assert [block["text"] for block in parsed["blocks"]] == [
        "Collected lessons", "First lesson", "Second lesson"
    ]


def test_discovery_links_stay_in_exact_grant_and_do_not_fetch_scripts():
    links = SourceLinks("https://docs.example.test/book/index", ["https://docs.example.test/book/"])
    links.feed(
        '<img aria-hidden="true" src="/spacer.png">'
        '<a href="chapter#part">chapter</a><a href="../private">outside</a>'
        '<a href="https://127.0.0.1/book/a">private</a><a href="file.exe">exe</a>'
        '<a href="chapter">same</a><a href="javascript:alert(1)">bad</a>'
    )
    assert links.links == ["https://docs.example.test/book/chapter"]


def test_source_links_keep_explicit_cross_origin_grants_separate_from_new_candidates():
    links = SourceLinks("https://docs.example.test/book/index", [
        "https://docs.example.test/book/", "https://reference.example.test/api/",
    ])
    links.feed(
        '<a href="chapter">Chapter</a><a href="../lesson">Candidate</a>'
        '<a href="https://reference.example.test/api/iteration">Granted reference</a>'
        '<a href="https://unrelated.example.test/lesson">Unapproved site</a>',
    )
    assert links.links == [
        "https://docs.example.test/book/chapter",
        "https://reference.example.test/api/iteration",
    ]
    assert links.candidates == ["https://docs.example.test/lesson"]


def test_mdn_footer_artwork_and_links_do_not_enter_the_teaching_pipeline():
    content = (
        b'<main><div class="layout__body"><h1>Iteration</h1>'
        b'<p>Visit every item.</p><a href="loops">Loops</a>'
        b'<section class="content-section article-footer"><div>'
        b'<svg width="162" height="162"><path d="M0 0"/></svg>'
        b'<a href="site-feedback">Page feedback</a></div></section></div></main>'
    )
    parsed = parse_file(content, "html-main")
    assert parsed["issues"] == []
    assert [block["text"] for block in parsed["blocks"]] == [
        "Iteration", "Visit every item.", "Loops",
    ]
    links = SourceLinks("https://docs.example.test/book/index", ["https://docs.example.test/book/"])
    links.feed(content.decode())
    assert links.links == ["https://docs.example.test/book/loops"]


def test_link_heavy_directory_is_not_a_shortcut_for_code_tables_or_pending_diagrams():
    links = SourceLinks("https://docs.example.test/book/index", ["https://docs.example.test/book/"])
    body = "".join(f'<a href="{name}">Complete {name} chapter</a>' for name in (
        "iteration", "variables", "functions",
    ))
    links.feed(body)
    assert links.is_directory(parse_file(body.encode(), "html-main"))
    for teaching in (
        "<pre>for x in values:\n    print(x)</pre>",
        "<table><tr><td>Important values</td></tr></table>",
        '<img alt="Iteration flow" src="diagram.png">',
    ):
        assert not links.is_directory(parse_file((body + teaching).encode(), "html-main"))


@pytest.mark.parametrize("label", ["TypeScript types", "Go HTTP handlers", "Python iterators"])
def test_annotated_indexes_discover_chapters_without_reviewing_their_previews(label):
    body = "<main>" + "".join(
        f'<article><h2><a href="chapter-{index}">{label} {index}</a></h2>'
        f'<p>A short description of chapter {index}, not the actual explanation.</p>'
        f'<img src="preview-{index}.png" alt="Preview"></article>'
        for index in range(4)
    ) + "</main>"
    links = SourceLinks("https://docs.example.test/book/", ["https://docs.example.test/book/"])
    links.feed(body)
    parsed = parse_file(body.encode(), "html-main")
    assert len(links.links) == 4 and links.is_directory(parsed)


def test_readme_with_a_real_tutorial_is_not_discarded_as_a_repository_index():
    body = '<main><h1>README: Iteration tutorial</h1><p>Visit each item.</p><pre>' \
        'for item in items:\n    print(item)</pre>' + "".join(
            f'<a href="chapter-{index}">Chapter {index}</a>' for index in range(10)
        ) + "</main>"
    links = SourceLinks("https://docs.example.test/book/", ["https://docs.example.test/book/"])
    links.feed(body)
    assert not links.is_directory(parse_file(body.encode(), "html-main"))


def test_whole_source_intake_has_real_scope_without_guessing_goal_words():
    data = MaterialDemandInput(goal_id=uuid4(), purpose="reference", scope_mode="whole_source")
    assert data.required_facets == []
    assert official_sources(data) == []
    with pytest.raises(ValidationError):
        MaterialDemandInput(goal_id=data.goal_id, purpose="planning")
    with pytest.raises(ValidationError):
        MaterialDemandInput(
            goal_id=data.goal_id,
            purpose="reference",
            scope_mode="whole_source",
            required_facets=["guessed keyword"],
        )
    verified = data.model_copy(update={"language": "python", "language_version": "3.12"})
    assert (
        official_sources(verified)[0][1].entry_url
        == "https://docs.python.org/3.12/tutorial/index.html"
    )


@pytest.mark.parametrize(
    ("language", "framework", "url", "version"),
    [
        ("Go", None, "https://go.dev/doc/tutorial/getting-started", None),
        ("C#", None, "https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/", None),
        (
            "HTML", None,
            "https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Structuring_content",
            None,
        ),
        (
            "CSS", None,
            "https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Styling_basics",
            None,
        ),
        ("SQL", "SQLite", "https://www.sqlite.org/lang.html", None),
        ("SQL", "MySQL", "https://dev.mysql.com/doc/refman/8.0/en/", "8.0"),
    ],
)
def test_official_catalog_uses_the_explicit_subject_and_preserves_real_version_facts(
    language, framework, url, version
):
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="planning", scope_mode="teaching_goal", goal_text="Confirmed goal",
        language=language, framework=framework,
    )
    entries = official_sources(demand)
    assert len(entries) == 1
    _catalog_id, source = entries[0]
    assert source.entry_url == url
    assert source.language == language and source.framework == framework
    assert source.language_version is None and source.framework_version == version
    assert approved_source_url(source.entry_url, source.allowed_prefixes) == source.entry_url


@pytest.mark.parametrize(
    "subject",
    [
        {"language": "Go", "language_version": "1.23"},
        {"language": "C#", "language_version": "12"},
        {"language": "HTML", "language_version": "5"},
        {"language": "CSS", "language_version": "3"},
        {"language": "SQL", "framework": "SQLite", "framework_version": "3.45"},
        {"language": "SQL", "framework": "MySQL", "framework_version": "9.9"},
        {"language": "SQL", "framework": "MySQL", "framework_version": "8.0.46"},
        {"language": "SQL"},
        {"language": "SQLite"},
        {"language": "Go", "framework": "SQLite"},
        {"language": "JavaScript", "language_version": "ES2025", "framework": "React"},
    ],
)
def test_unversioned_catalog_does_not_claim_unknown_versions_or_guess_the_sql_framework(subject):
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="planning", scope_mode="teaching_goal", goal_text="Confirmed goal",
        **subject,
    )
    assert official_sources(demand) == []


@pytest.mark.parametrize("framework", ["Spring Boot", "spring-boot", "SpringBoot"])
def test_java_catalog_resolves_framework_aliases_without_manual_source_registration(framework):
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="planning", scope_mode="teaching_goal",
        goal_text="Java, Maven, JUnit, MySQL, Spring dependency injection and Spring Boot.",
        language="java", framework=framework,
    )
    entries = official_sources(demand, auto_topic=demand.goal_text)
    assert {key for key, _ in entries} == {
        "java-dev-learn", "maven-guides", "junit-user-guide", "mysql-8.0-reference",
        "spring-framework-reference", "spring-boot-reference",
    }
    assert len(entries) == 6
    for _, source in entries:
        assert source.goal_id == demand.goal_id
        assert approved_source_url(source.entry_url, source.allowed_prefixes) == source.entry_url
        assert "planning" in source.purposes and "indexing" in source.purposes


def test_related_topics_preserve_explicit_versions_and_do_not_relabel_other_documentation():
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="planning", scope_mode="teaching_goal", goal_text="Java and MySQL",
        language="java", language_version="21", framework="Spring Boot", framework_version="3.5",
    )
    entries = official_sources(demand, auto_topic=demand.goal_text)
    assert [key for key, _ in entries] == ["mysql-8.0-reference"]
    assert entries[0][1].language == "sql"
    assert entries[0][1].language_version is None


def test_large_image_is_fully_partitioned_into_original_regions_and_png_ocr_inputs():
    image = Image.new("RGB", (2100, 1100), "white")
    original = io.BytesIO()
    image.save(original, format="JPEG")
    parsed = parse_file(original.getvalue(), "jpeg")
    assert len(parsed["pages"]) == 1
    assert parsed["parser_version"] == "image-original.v2"
    assert all(page["requires_ocr"] for page in parsed["pages"])
    assert parsed["pages"][0]["region"] == [0, 0, 2100, 1100]
    rendered = base64.b64decode(
        extract_file(original.getvalue(), "image-region:1:0:0:2100:1100")["image"]
    )
    with Image.open(io.BytesIO(rendered)) as whole:
        assert whole.format == "PNG" and whole.size == (2100, 1100)

    # A pending v1 request still addresses the old final 100-pixel strip.
    rendered = base64.b64decode(render_image_region(original.getvalue(), 6)["image"])
    with Image.open(io.BytesIO(rendered)) as last:
        assert last.format == "PNG" and last.size == (100, 100)


@pytest.mark.parametrize("size", [(1191, 1684), (2201, 3301), (5000, 4600)])
def test_image_regions_cover_original_without_overlap_or_narrow_remainders(size):
    width, height = size
    regions = page_image_regions(width, height)
    if size == (1191, 1684):
        assert regions == [[0, 0, width, height]]
    assert sum((right - left) * (bottom - top) for left, top, right, bottom in regions) == (
        width * height
    )
    for index, (left, top, right, bottom) in enumerate(regions):
        assert 0 <= left < right <= width and 0 <= top < bottom <= height
        assert right - left <= 2200 and bottom - top <= 2200
        assert (right - left) * (bottom - top) <= 2_500_000
        assert right - left >= min(width, 1100)
        for other in regions[index + 1:]:
            assert right <= other[0] or other[2] <= left or bottom <= other[1] or other[3] <= top


def test_frozen_image_region_cannot_read_outside_original_bounds():
    source = io.BytesIO()
    Image.new("RGB", (20, 30), "white").save(source, format="PNG")
    with pytest.raises(BusinessError) as error:
        render_image_region(source.getvalue(), 1, [0, 0, 21, 30])
    assert error.value.code == "material_page_limit"
