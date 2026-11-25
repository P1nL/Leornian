import json
from collections import Counter
from importlib.resources import files
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from leornian.modules.execution.environment_recipes import requirements
from leornian.modules.knowledge.intake_contracts import MaterialDemandInput
from leornian.modules.knowledge.source_catalog import catalog_resources, official_sources


def test_catalogue_covers_the_actual_language_and_sql_recipe_matrix():
    resources = catalog_resources()
    languages = {value.language for value in requirements()}
    languages.remove("html-css")
    languages.update({"html", "css"})
    for language in languages:
        selected = catalog_resources(language)
        assert any(entry["origin"] == "official" for entry in selected), language
        assert any(entry["origin"] == "third_party" for entry in selected), language
    for dialect in ("sqlite", "postgresql", "mysql"):
        selected = catalog_resources("sql", dialect)
        assert any(entry["origin"] == "official" for entry in selected)
        assert any(entry["origin"] == "third_party" for entry in selected)
    assert resources


def test_catalogue_records_original_entry_points_and_real_availability_observations():
    resources = catalog_resources()
    assert len({entry["id"] for entry in resources}) == len(resources)
    assert len({entry["url"] for entry in resources}) == len(resources)
    for entry in resources:
        url = urlsplit(entry["url"])
        assert url.scheme == "https" and url.hostname
        assert not url.username and not url.password
        assert entry["publisher"] and entry["topics"] and entry["version_scope"]
        assert entry["origin"] in {"official", "third_party", "translation"}
        assert entry["verification"]["status"] in {"reachable", "http_error", "network_error"}
        assert entry["verification"]["checked_on"]
    catalogue = json.loads(
        files("leornian.modules.knowledge").joinpath(
            "source_catalog_resources.json",
        ).read_text(encoding="utf-8")
    )
    assert len(catalogue["research_rounds"]) >= 3
    assert "not published teaching evidence" in catalogue["policy"]["role"]


def test_catalogue_keeps_nontext_formats_and_localized_sources():
    formats = Counter(form for entry in catalog_resources() for form in entry["forms"])
    for form in (
        "html", "pdf", "epub", "book", "course", "video", "audio",
        "slides", "notebook", "repository", "interactive", "exercise",
    ):
        assert formats[form], form
        assert all(form in entry["forms"] for entry in catalog_resources(form=form))
    assert any(
        entry["origin"] == "translation"
        for entry in catalog_resources(locale="zh")
    )


@pytest.mark.parametrize(
    ("language", "framework", "entry_id"),
    [
        ("C#", None, "csharp-guide"),
        ("JS", "Node.js", "javascript-node22-api"),
        ("TS", "React", "typescript-react-cheatsheet"),
        ("Java", "Spring Boot", "java-spring-boot"),
        ("Java", "Spring Framework", "java-spring-framework"),
        ("SQL", "Postgres", "sql-postgresql15"),
        ("CSharp", "ASP.NET Core", "csharp-aspnet"),
        ("HTML/CSS", None, "css-diner"),
        ("TS", "Next.js", "web-nextjs"),
        ("TS", "Nuxt.js", "web-nuxt"),
        ("TS", "Nest.js", "web-nest"),
        ("JS", "Socket.IO", "web-socketio"),
        ("JS", "Chart.js", "web-chartjs"),
        ("JS", "Three.js", "web-threejs"),
        ("JS", "Solid.js", "web-solid"),
        ("HTML/CSS", "Alpine.js", "web-alpine"),
        ("TS", "Knex.js", "web-knex"),
        ("Python", "sklearn", "python-sklearn"),
        ("Python", "Qt for Python", "python-pyside6"),
        ("C#", ".NET MAUI", "csharp-maui"),
    ],
)
def test_catalogue_lookup_normalizes_supported_subject_aliases(language, framework, entry_id):
    assert entry_id in {entry["id"] for entry in catalog_resources(language, framework)}


def test_catalogue_lookup_is_bounded_and_cannot_mutate_cached_entries():
    entries = catalog_resources("python", limit=2)
    assert len(entries) == 2
    entries[0]["topics"].append("consumer mutation")
    entries[0]["verification"]["status"] = "consumer mutation"
    current = catalog_resources("python", limit=2)
    assert current[0]["topics"] != entries[0]["topics"]
    assert current[0]["verification"]["status"] != "consumer mutation"
    assert catalog_resources("python", limit=0) == []
    assert catalog_resources("unsupported-language") == []
    with pytest.raises(ValueError):
        catalog_resources(limit=-1)


def test_catalogue_distinguishes_blocked_candidates_from_reachable_entries_and_authorization():
    resources = catalog_resources()
    assert all("authorized_use" not in entry for entry in resources)
    reachable = catalog_resources(reachable_only=True)
    assert all(entry["verification"]["status"] == "reachable" for entry in reachable)
    assert {entry["id"] for entry in reachable} == {
        entry["id"] for entry in resources if entry["verification"]["status"] == "reachable"
    }
    assert any(entry["origin"] == "third_party" for entry in reachable)


def test_expanded_inventory_does_not_change_frozen_official_registration_payloads():
    demand = MaterialDemandInput(
        goal_id=uuid4(), purpose="planning", scope_mode="teaching_goal",
        goal_text="Learn Python", language="python", language_version="3.12",
    )
    assert len(catalog_resources("python")) > 1
    entries = official_sources(demand)
    assert len(entries) == 1
    key, source = entries[0]
    assert key == "python-3.12-tutorial"
    assert source.entry_url == "https://docs.python.org/3.12/tutorial/index.html"
    assert source.topics == []
    assert source.language_version == "3.12"


@pytest.mark.parametrize(
    ("language", "frameworks"),
    [
        (
            "python",
            (
                "requests", "httpx", "aiohttp", "pydantic", "django-rest-framework",
                "celery", "alembic", "psycopg", "scipy", "scikit-learn", "pytorch",
                "tensorflow", "keras", "transformers", "polars", "pyarrow", "jax",
                "uv", "ruff", "mypy", "hypothesis", "pyside6", "streamlit", "playwright",
            ),
        ),
        (
            "java",
            (
                "spring-security", "spring-data-jpa", "spring-cloud", "spring-kafka",
                "hibernate", "jakartaee", "quarkus", "micronaut", "jackson", "lombok",
                "mapstruct", "hikaricp", "flyway", "jooq", "mockito", "testcontainers",
                "javafx", "mybatis-plus", "nacos", "sentinel", "dubbo", "resilience4j",
            ),
        ),
        (
            "typescript",
            (
                "nextjs", "angular", "sveltekit", "nuxt", "astro", "nestjs", "fastify",
                "hono", "redux-toolkit", "zustand", "pinia", "tanstack-query", "zod",
                "prisma", "drizzle", "socketio", "vite", "eslint", "playwright",
                "storybook", "react-native", "electron", "msw",
            ),
        ),
        (
            "go",
            (
                "echo", "fiber", "chi", "ent", "sqlc", "pgx", "go-redis", "cobra",
                "viper", "zap", "zerolog", "testify", "gomock", "ginkgo", "fx",
                "golangci-lint", "goframe", "go-zero", "kratos", "kitex", "prometheus",
            ),
        ),
        (
            "csharp",
            (
                "dapper", "npgsql", "serilog", "fluentvalidation", "automapper",
                "mapster", "mediatr", "polly", "masstransit", "hangfire", "xunit",
                "nunit", "moq", "testcontainers", "blazor", "maui", "avalonia",
                "unity", "godot", "freesql", "sqlsugar", "abp", "autofac",
            ),
        ),
        (
            "css",
            ("tailwindcss", "bootstrap", "sass", "less", "postcss", "stylelint"),
        ),
        ("sql", ("sqlite", "mysql", "postgresql", "dbt", "sqlfluff", "sqlmesh")),
    ],
)
def test_catalogue_has_project_owned_entries_for_major_ecosystem_categories(language, frameworks):
    for framework in frameworks:
        assert any(
            entry["origin"] == "official"
            for entry in catalog_resources(language, framework)
        ), (language, framework)


@pytest.mark.parametrize(
    "language",
    ["python", "java", "javascript", "typescript", "go", "csharp", "html", "css", "sql"],
)
def test_each_supported_direction_has_chinese_author_or_community_material(language):
    selected = catalog_resources(language, locale="zh")
    assert any(entry["origin"] == "third_party" for entry in selected), language
    assert all(any(value.startswith("zh") for value in entry["locales"]) for entry in selected)


def test_chinese_sources_separate_project_documentation_original_authors_and_translations():
    chinese = {entry["id"]: entry for entry in catalog_resources(locale="zh")}
    assert chinese["zh-csharp-sqlsugar"]["origin"] == "official"
    assert chinese["zh-web-wangdoc-ts"]["origin"] == "third_party"
    assert chinese["zh-python-pandas"]["publisher"] == "Datawhale / Joyful Pandas 作者团队"
    assert chinese["zh-ts-deepdive"]["origin"] == "translation"
    assert "csharp-abp" not in chinese
    assert any(
        entry["id"] == "zh-csharp-sqlsugar"
        for entry in catalog_resources("C#", "SqlSugar", locale="zh-CN")
    )


def test_historical_chinese_tutorials_record_their_actual_generation():
    resources = {entry["id"]: entry for entry in catalog_resources()}
    assert "Vue 2" in resources["zh-web-vue-analysis"]["version_scope"]
    assert "2.x" in resources["zh-java-spring-labs"]["version_scope"]
    assert ".NET 5" in resources["zh-csharp-samples"]["version_scope"]
    assert "1.2" in resources["zh-python-pandas"]["version_scope"]
    assert "3.3" in resources["zh-python-cookbook"]["version_scope"]
