"""Maintained discovery candidates and the existing authorized official entry points."""

import json
import re
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files

from leornian.modules.knowledge.source_contracts import MaterialSourceInput

ALL_PURPOSES = [
    "reference", "planning", "lesson", "teaching", "item_author", "item_review", "indexing",
]
CATALOG_VERSION = "official-docs.v1"


@lru_cache(maxsize=1)
def _resource_catalog():
    return json.loads(
        files(__package__).joinpath("source_catalog_resources.json").read_text(encoding="utf-8")
    )


@lru_cache(maxsize=1)
def catalog_languages():
    return frozenset(
        language for entry in _resource_catalog()["resources"] for language in entry["languages"]
    )


def catalog_resources(
    language=None, framework=None, *, form=None, locale=None, reachable_only=False, limit=None,
):
    """Browse candidates; this does not grant acquisition rights or certify their contents."""
    if limit is not None and limit < 0:
        raise ValueError("A catalogue limit cannot be negative")
    language_key = (language or "").strip().casefold()
    language_key = {"js": "javascript", "ts": "typescript", "c#": "csharp"}.get(
        language_key, language_key,
    )
    language_keys = (
        {"html", "css"} if language_key in {"html-css", "html/css"} else {language_key}
    )
    framework_aliases = {
        "node.js": "nodejs", "node": "nodejs", "postgres": "postgresql",
        ".net": "dotnet", "asp.netcore": "aspnetcore", "entityframeworkcore": "efcore",
        "next.js": "nextjs", "nuxt.js": "nuxt", "nest.js": "nestjs",
        "socket.io": "socketio", "chart.js": "chartjs", "three.js": "threejs",
        "solid.js": "solidjs", "alpine.js": "alpinejs", "knex.js": "knex",
        "sklearn": "scikitlearn", "qtforpython": "pyside6", ".netmaui": "maui",
    }
    wanted_framework = framework_key(framework)
    wanted_framework = framework_aliases.get(wanted_framework, wanted_framework)
    resources = [
        entry for entry in _resource_catalog()["resources"]
        if (not language_key or language_keys.intersection(entry["languages"]))
        and (
            not wanted_framework
            or wanted_framework in {framework_key(value) for value in entry["frameworks"]}
        )
        and (not form or form in entry["forms"])
        and (not reachable_only or entry["verification"]["status"] == "reachable")
        and (
            not locale
            or any(
                value.casefold() == locale.casefold()
                or value.casefold().startswith(locale.casefold() + "-")
                for value in entry["locales"]
            )
        )
    ]
    return deepcopy(resources if limit is None else resources[:limit])


def framework_key(value):
    key = re.sub(r"[\s_-]+", "", (value or "").casefold())
    return "spring" if key == "springframework" else key


def topic_subjects(text):
    """Discover catalogue candidates, without asserting a learner's exact subject."""
    text = text.casefold()
    subjects = []
    for language, names in (
        ("python", ("python",)), ("java", ("java",)),
        ("javascript", ("javascript", "js")), ("typescript", ("typescript", "ts")),
        ("go", ("golang", "go")), ("csharp", ("csharp", "c#")),
        ("html", ("html",)), ("css", ("css",)), ("sql", ("sql",)),
    ):
        if any(re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", text) for name in names):
            version = re.search(
                r"(?<![a-z])(?:" + "|".join(re.escape(name) for name in names)
                + r")\s*(?:v(?:ersion)?\s*)?(\d+(?:\.\d+)*)",
                text,
            )
            subjects.append({
                "language": language, "language_version": version[1] if version else None,
                "framework": None, "framework_version": None,
            })
    for framework, language, name in (
        ("react", "javascript", "react"), ("vue", "javascript", "vue"),
        ("sqlite", "sql", "sqlite"), ("mysql", "sql", "mysql"),
        ("postgresql", "sql", "postgresql"),
        ("spring boot", "java", r"spring[\s_-]*boot"),
        ("spring", "java", r"spring(?:[\s_-]+framework)?(?![\s_-]*boot)"),
        ("maven", "java", "maven"), ("junit", "java", "junit"),
    ):
        if re.search(r"(?<![a-z])" + name + r"(?![a-z])", text):
            version = re.search(
                name + r"\s*(?:v(?:ersion)?\s*)?(\d+(?:\.\d+)*)", text
            )
            subjects.append({
                "language": language, "language_version": None,
                "framework": framework, "framework_version": version[1] if version else None,
            })
    return subjects


def official_sources(demand, *, auto_topic=None):
    if auto_topic is not None:
        candidates = official_sources(demand) if demand.language else []
        for subject in topic_subjects(auto_topic):
            if (demand.language or "").casefold() == subject["language"]:
                subject["language_version"] = (
                    subject["language_version"] or demand.language_version
                )
            if framework_key(demand.framework) == framework_key(subject["framework"]):
                subject["framework_version"] = (
                    subject["framework_version"] or demand.framework_version
                )
            candidates.extend(official_sources(demand.model_copy(update=subject)))
        selected = {}
        for catalog_id, data in candidates:
            selected.setdefault(catalog_id, (catalog_id, data))
        return list(selected.values())
    language = (demand.language or "").casefold()
    framework = framework_key(demand.framework)
    if demand.language_version and (language != "python" or framework):
        return []
    if demand.framework_version and framework not in {"postgresql", "mysql"}:
        return []
    values = []
    if language == "python" and not framework:
        version = demand.language_version or "3"
        if re.fullmatch(r"3(?:\.\d+)?", version):
            prefix = f"https://docs.python.org/{version}/"
            values.append((
                f"python-{version}-tutorial", "Python tutorial",
                prefix + "tutorial/index.html", prefix,
            ))
    elif language == "java" and not framework and not demand.language_version:
        values.append((
            "java-dev-learn", "Java learning documentation",
            "https://dev.java/learn/", "https://dev.java/learn/",
        ))
    elif language in {"javascript", "typescript"} and not framework and not demand.language_version:
        if language == "typescript":
            values.append((
                "typescript-handbook", "TypeScript handbook",
                "https://www.typescriptlang.org/docs/handbook/intro.html",
                "https://www.typescriptlang.org/docs/",
            ))
        else:
            values.append((
                "mdn-javascript", "MDN JavaScript reference",
                "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
                "https://developer.mozilla.org/en-US/docs/Web/JavaScript/",
            ))
    elif language == "go" and not framework and not demand.language_version:
        values.append((
            "go-getting-started", "Go getting started",
            "https://go.dev/doc/tutorial/getting-started", "https://go.dev/doc/",
        ))
    elif language in {"c#", "csharp"} and not framework and not demand.language_version:
        values.append((
            "csharp-tour", "C# documentation",
            "https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/",
            "https://learn.microsoft.com/en-us/dotnet/csharp/",
        ))
    elif language in {"html", "css"} and not framework and not demand.language_version:
        module = "Structuring_content" if language == "html" else "Styling_basics"
        prefix = "https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/"
        values.append((
            f"mdn-{language}-core", f"MDN {language.upper()} core", prefix + module, prefix,
        ))
    elif language == "sql" and not demand.language_version:
        if framework == "sqlite" and not demand.framework_version:
            values.append((
                "sqlite-sql-language", "SQLite SQL language",
                "https://www.sqlite.org/lang.html", "https://www.sqlite.org/",
            ))
        elif framework == "mysql" and demand.framework_version in {None, "8.0"}:
            prefix = "https://dev.mysql.com/doc/refman/8.0/en/"
            values.append(("mysql-8.0-reference", "MySQL 8.0 reference", prefix, prefix))
    if framework == "postgresql":
        version = demand.framework_version or "current"
        if version == "current" or re.fullmatch(r"\d+(?:\.\d+)?", version):
            prefix = f"https://www.postgresql.org/docs/{version}/"
            values.append((
                f"postgresql-{version}", "PostgreSQL documentation", prefix + "index.html", prefix,
            ))
    elif framework == "react" and not demand.framework_version:
        values.append(("react-learn", "React documentation", "https://react.dev/learn", "https://react.dev/"))
    elif framework == "vue" and not demand.framework_version:
        values.append((
            "vue-guide", "Vue documentation", "https://vuejs.org/guide/introduction.html",
            "https://vuejs.org/guide/",
        ))
    elif language == "java" and not demand.framework_version:
        if framework == "springboot":
            values.append((
                "spring-boot-reference", "Spring Boot documentation",
                "https://docs.spring.io/spring-boot/index.html",
                "https://docs.spring.io/spring-boot/",
            ))
        elif framework == "spring":
            values.append((
                "spring-framework-reference", "Spring Framework documentation",
                "https://docs.spring.io/spring-framework/reference/index.html",
                "https://docs.spring.io/spring-framework/",
            ))
        elif framework == "maven":
            values.append((
                "maven-guides", "Maven documentation",
                "https://maven.apache.org/guides/index.html", "https://maven.apache.org/",
            ))
        elif framework == "junit":
            values.append((
                "junit-user-guide", "JUnit user guide",
                "https://docs.junit.org/current/user-guide/", "https://docs.junit.org/",
            ))
    return [
        (
            catalog_id,
            MaterialSourceInput(
                goal_id=demand.goal_id, title=title, entry_url=url, allowed_prefixes=[prefix],
                authorized_use=True, purposes=ALL_PURPOSES,
                language=demand.language, language_version=demand.language_version,
                framework=demand.framework,
                framework_version="8.0"
                if catalog_id == "mysql-8.0-reference" else demand.framework_version,
            ),
        )
        for catalog_id, title, url, prefix in values
    ]
