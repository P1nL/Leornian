"""Maintained recipes, never learner-supplied images, commands or dependency sources."""

import json
from dataclasses import dataclass
from hashlib import sha256

from leornian.modules.execution.environment_contracts import (
    CourseEnvironment,
    EnvironmentRequirement,
)
from leornian.shared_kernel.errors import BusinessError


@dataclass(frozen=True)
class Recipe:
    requirement: EnvironmentRequirement
    base_image: str
    dockerfile: str | None = None
    companion_images: tuple[tuple[str, str], ...] = ()
    requires_consent: bool = False


def _recipe(
    key,
    language,
    title,
    image,
    toolchains,
    *,
    dialect=None,
    dependencies=(),
    dockerfile=None,
    companions=(),
    sources=(),
    requires_consent=False,
):
    return Recipe(
        EnvironmentRequirement(
            recipe_id=key,
            recipe_revision=1,
            profile="sql-query.v1"
            if dialect
            else ("web-check.v1" if language == "html-css" else "project-stdio.v1"),
            language=language,
            dialect=dialect,
            title=title,
            toolchains=toolchains,
            dependency_lock=list(dependencies),
            version_policy=(
                "Recipe fixes the runtime family and dependency versions; an installed release "
                "freezes exact image IDs and observed versions. Rebuild uses the same cached "
                "images; a changed dependency lock requires a new requirement revision."
            ),
            sources=[
                (
                    "https://mcr.microsoft.com"
                    if image.startswith("mcr.microsoft.com/")
                    else "https://registry-1.docker.io"
                )
            ]
            + list(sources),
            services=[dialect + " (isolated local socket; no host port)"]
            if dialect in {"postgresql", "mysql"}
            else [],
        ),
        base_image=image,
        dockerfile=dockerfile,
        companion_images=tuple(companions),
        requires_consent=requires_consent,
    )


_RECIPES = [
    _recipe(
        "python-standard.v1", "python", "Python 标准库项目", "python:3.12-slim", ["Python 3.12"]
    ),
    _recipe(
        "python-flask.v1",
        "python",
        "Python / Flask 受控项目",
        "python:3.12-slim",
        ["Python 3.12"],
        dependencies=[
            "Flask==3.1.2",
            "blinker==1.9.0",
            "click==8.3.1",
            "itsdangerous==2.2.0",
            "Jinja2==3.1.6",
            "MarkupSafe==3.0.3",
            "Werkzeug==3.1.4",
        ],
        dockerfile="Dockerfile.python-flask",
        sources=["https://pypi.org", "https://files.pythonhosted.org"],
        requires_consent=True,
    ),
    _recipe(
        "javascript-standard.v1",
        "javascript",
        "JavaScript / Node.js 项目",
        "mcr.microsoft.com/devcontainers/javascript-node:1-22-bookworm",
        ["Node.js 22"],
    ),
    _recipe(
        "typescript-standard.v1",
        "typescript",
        "TypeScript 编译与 Node.js 运行",
        "mcr.microsoft.com/devcontainers/javascript-node:1-22-bookworm",
        ["Node.js 22", "TypeScript 5.9.3"],
        dependencies=["typescript@5.9.3", "@types/node@22.19.0", "undici-types@6.21.0"],
        dockerfile="Dockerfile.typescript",
        sources=["https://registry.npmjs.org"],
    ),
    _recipe(
        "java-standard.v1",
        "java",
        "Java 编译与运行",
        "mcr.microsoft.com/openjdk/jdk:25-ubuntu",
        ["OpenJDK 25"],
    ),
    _recipe(
        "go-standard.v1",
        "go",
        "Go 编译与运行",
        "mcr.microsoft.com/devcontainers/go:1.26-bookworm",
        ["Go 1.26"],
    ),
    _recipe(
        "csharp-standard.v1",
        "csharp",
        "C# / .NET 编译与运行",
        "mcr.microsoft.com/dotnet/sdk:10.0",
        [".NET SDK 10.0", ".NET runtime 10.0"],
        dockerfile="Dockerfile.csharp",
        sources=["https://mcr.microsoft.com"],
    ),
    _recipe(
        "html-css-browser.v1",
        "html-css",
        "HTML/CSS 结构、样式与交互检查",
        "python:3.12-slim",
        ["Chromium headless shell (Playwright 1.64.1 pinned revision)", "Python 3.12"],
        dependencies=[
            "playwright==1.64.1",
            "pyee==14.0.0",
            "greenlet==3.5.6",
            "typing_extensions==4.15.0",
        ],
        dockerfile="Dockerfile.web",
        sources=[
            "https://pypi.org",
            "https://files.pythonhosted.org",
            "https://cdn.playwright.dev",
            "https://playwright.download.prss.microsoft.com",
            "https://deb.debian.org",
            "https://security.debian.org",
        ],
    ),
    _recipe(
        "sqlite-query.v1",
        "sql",
        "SQLite 只读查询",
        "python:3.12-slim",
        ["Python 3.12", "SQLite (bundled exact version)"],
        dialect="sqlite",
    ),
    _recipe(
        "postgresql-query.v1",
        "sql",
        "PostgreSQL 只读查询",
        "python:3.12-slim",
        ["Python 3.12", "PostgreSQL 15"],
        dialect="postgresql",
        dependencies=[
            "psycopg==3.3.8",
            "psycopg-binary==3.3.8",
            "PyMySQL==1.1.2",
            "typing_extensions==4.15.0",
        ],
        dockerfile="Dockerfile.sql-client",
        companions=[("server", "postgres:15")],
        sources=["https://pypi.org", "https://files.pythonhosted.org"],
    ),
    _recipe(
        "mysql-query.v1",
        "sql",
        "MySQL 只读查询",
        "python:3.12-slim",
        ["Python 3.12", "MySQL 8.0"],
        dialect="mysql",
        dependencies=[
            "psycopg==3.3.8",
            "psycopg-binary==3.3.8",
            "PyMySQL==1.1.2",
            "typing_extensions==4.15.0",
        ],
        dockerfile="Dockerfile.sql-client",
        companions=[("server", "mysql:8.0")],
        sources=["https://pypi.org", "https://files.pythonhosted.org"],
    ),
]
RECIPES = {recipe.requirement.recipe_id: recipe for recipe in _RECIPES}


def course_recipe(course: CourseEnvironment) -> Recipe:
    base = RECIPES[f"{course.language}-standard.v1"]
    scope = json.dumps(course.model_dump(mode="json", exclude={"title"}), sort_keys=True)
    fingerprint = sha256(scope.encode()).hexdigest()[:24]
    ecosystem = {
        "python": ("pip", ["https://pypi.org", "https://files.pythonhosted.org"]),
        "javascript": ("npm", ["https://registry.npmjs.org"]),
        "typescript": ("npm", ["https://registry.npmjs.org"]),
        "java": ("Maven", ["https://repo.maven.apache.org", "https://archive.ubuntu.com"]),
        "go": ("Go modules", ["https://proxy.golang.org", "https://sum.golang.org"]),
        "csharp": ("NuGet", ["https://api.nuget.org"]),
    }
    manager, sources = ecosystem[course.language]
    dependencies = [
        f"{item.name}{'==' if course.language == 'python' else '@'}{item.version}"
        for item in course.dependencies
    ]
    extra_sources = (
        RECIPES["html-css-browser.v1"].requirement.sources if course.build == "vite" else []
    )
    if course.build == "http":
        extra_sources += RECIPES["python-standard.v1"].requirement.sources
        if course.database in {"postgresql", "mysql"}:
            extra_sources += RECIPES[f"{course.database}-query.v1"].requirement.sources
    return Recipe(
        requirement=EnvironmentRequirement(
            recipe_id=f"course-{course.language}-{fingerprint}.v1",
            recipe_revision=1,
            profile={
                "stdio": "project-stdio.v1", "vite": "web-check.v1", "http": "project-http.v1",
            }[course.build],
            language=course.language,
            title=course.title,
            toolchains=[*base.requirement.toolchains, manager]
            + (["Vite build and isolated Chromium"] if course.build == "vite" else [])
            + (["Task-local HTTP checks"] if course.build == "http" else [])
            + ([course.database] if course.database else []),
            dependency_lock=list(dict.fromkeys([*base.requirement.dependency_lock, *dependencies])),
            course_environment=course,
            version_policy=(
                "Direct course dependencies have exact versions. The installed image freezes "
                "the resolved dependency tree and tool versions; an unchanged release is reused. "
                "Changed course dependencies require a new installation decision."
            ),
            sources=list(dict.fromkeys([*base.requirement.sources, *sources, *extra_sources])),
            services=(
                ["HTTP (task-local loopback; no host port)"]
                + ([f"{course.database} (task-local writable database)"] if course.database else [])
                if course.build == "http" else []
            ),
        ),
        base_image=base.base_image,
        requires_consent=True,
    )


def recipe(recipe_id: str, course_environment: CourseEnvironment | None = None) -> Recipe:
    if course_environment is not None:
        value = course_recipe(course_environment)
        if value.requirement.recipe_id != recipe_id:
            raise BusinessError("precondition_failed", "Course dependency identity changed.")
        return value
    value = RECIPES.get(recipe_id)
    if value is None:
        raise BusinessError(
            "precondition_failed", "No maintained local recipe for this requirement."
        )
    return value


def requirements() -> list[EnvironmentRequirement]:
    return [value.requirement for value in RECIPES.values()]


def automatic_recipe_ids() -> list[str]:
    return [key for key, value in RECIPES.items() if not value.requires_consent]
