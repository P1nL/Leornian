"""Task-sized candidate selection; candidates never substitute for checked source text."""

import re
from urllib.parse import urlsplit, urlunsplit

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.retrieval import terms
from leornian.modules.knowledge.source_acquisition import identity
from leornian.modules.knowledge.source_catalog import (
    ALL_PURPOSES,
    catalog_languages,
    catalog_resources,
    framework_key,
    topic_subjects,
)
from leornian.modules.knowledge.source_contracts import MaterialSourceInput
from leornian.modules.knowledge.source_network import canonical_source_url
from leornian.shared_kernel.errors import BusinessError

MAX_CATALOG_CANDIDATES = 12
MAX_SEARCH_RESULTS = 8
MAX_SEARCH_ROUNDS = 2
MAX_RESOURCE_READS = 12
MAX_RENEWED_RESOURCE_READS = 24
MAX_RENEWED_SEARCH_ROUNDS = 4
MAX_SOURCE_READS = 3
CATALOG_RESOURCE_READS = 8


def gap_topics(values):
    result, seen = [], set()
    for value in values:
        for line in value.splitlines():
            topic = " ".join(line.split())
            if topic and topic.casefold() not in seen:
                seen.add(topic.casefold())
                result.append(topic)
    return result


def candidate_url(value):
    parts = urlsplit(value)
    url = canonical_source_url(urlunsplit(parts._replace(fragment="")))
    if re.search(r"/(?:login|signin|sign-in|subscribe|checkout|pricing)(?:/|$)", parts.path, re.I):
        raise BusinessError("source_access_restricted", "A public alternative is required.")
    return url


def mentions_framework(text, framework):
    words = re.findall(r"\w+", framework.casefold())
    return bool(words and re.search(
        r"(?<![a-z0-9_])" + r"[\s_.-]*".join(re.escape(word) for word in words)
        + r"(?![a-z0-9_])",
        text.casefold(),
    ))


def observed_frameworks(title, url):
    text = title + " " + urlsplit(url).path
    return sorted({
        name for entry in catalog_resources() for name in entry["frameworks"]
        if mentions_framework(text, name)
    })


def material_matches_gaps(text, missing, *, goal_text="", frameworks=None):
    """Match each gap independently; a framework never narrows unrelated gaps."""
    names = frameworks if frameworks is not None else {
        name for entry in catalog_resources() for name in entry["frameworks"]
    }
    topics = [
        (gap, {name for name in names if mentions_framework(gap, name)})
        for gap in gap_topics(missing)
        if gap.strip().casefold() != goal_text.strip().casefold()
    ]
    if not any(named for _gap, named in topics):
        return True
    labels = set(terms(text)) - catalog_languages()
    return any(
        any(mentions_framework(text, name) for name in named)
        if named else bool(labels & (set(terms(gap)) - catalog_languages()))
        for gap, named in topics
    )


def ranked_candidates(
    demand, topic, *, extra=(), limit=MAX_CATALOG_CANDIDATES, allowed_origins=None, missing=(),
    deferred_frameworks=(), active_frameworks=(), preferred_urls=(), node_scope=False,
):
    """Rank metadata locally, before any GET, extraction, embedding or paid search."""
    language = (demand.language or "").casefold()
    language = {"js": "javascript", "ts": "typescript", "c#": "csharp"}.get(language, language)
    inferred = {item["language"] for item in topic_subjects(topic)}
    languages = {language} if language else inferred
    if language in {"html-css", "html/css"}:
        languages = {"html", "css"}
    wanted = set(terms(topic))
    gaps = set(terms(" ".join(missing)))
    gap_text = " ".join(missing)
    requested_framework = framework_key(demand.framework).replace(".", "")
    deferred = {framework_key(value).replace(".", "") for value in deferred_frameworks}
    active = {framework_key(value).replace(".", "") for value in active_frameworks}
    entries = [*catalog_resources(), *extra]
    known_frameworks = {name for entry in entries for name in entry["frameworks"]}
    # A named dependency may use another language, unlike a learner's prior experience.
    if missing:
        languages |= {
            value for entry in entries
            if any(mentions_framework(gap_text, name) for name in entry["frameworks"])
            for value in entry["languages"]
        }
    choices = {}
    for entry in entries:
        if allowed_origins is not None and entry["origin"] not in allowed_origins:
            continue
        if (
            languages and not languages.intersection(entry["languages"])
            and entry["url"] not in preferred_urls
        ):
            continue
        try:
            url = candidate_url(entry["url"])
        except (BusinessError, ValueError, TypeError):
            continue
        if entry.get("verification", {}).get("status") in {"http_error", "network_error"}:
            continue
        labels = set(terms(" ".join([
            entry["title"], *entry["topics"], *entry["frameworks"],
        ])))
        frameworks = {framework_key(value).replace(".", "") for value in entry["frameworks"]}
        if url not in preferred_urls and frameworks & deferred and not frameworks & active:
            continue
        mentioned = {
            framework_key(value).replace(".", "") for value in entry["frameworks"]
            if mentions_framework(topic, value)
        }
        gap_mentions = {
            value for value in entry["frameworks"] if mentions_framework(gap_text, value)
        }
        if node_scope and frameworks and url not in preferred_urls and not (
            frameworks & active or mentioned or gap_mentions or requested_framework in frameworks
        ):
            continue
        if url not in preferred_urls and not material_matches_gaps(
            " ".join([
                entry["title"], entry["url"], *entry["topics"], *entry["frameworks"],
            ]), missing, goal_text=demand.goal_text or "", frameworks=known_frameworks,
        ):
            continue
        matching = bool(requested_framework and requested_framework in frameworks)
        overlap = wanted & labels
        gap_overlap = gaps & labels
        if not (
            url in preferred_urls or overlap or mentioned or matching or gap_mentions or gap_overlap
            or (languages.intersection(entry["languages"]) and not frameworks)
        ):
            continue
        score = (
            8 * len(mentioned) + 12 * matching + 2 * len(overlap)
            + 3 * any(locale.startswith("zh") for locale in entry["locales"])
            + 2 * (not frameworks and bool(languages))
            + (entry["origin"] == "official")
        )
        if gaps:
            score += 6 * len(gap_overlap) + 16 * len(gap_mentions)
        if demand.preparation != "complete":
            score += 3 * bool(labels & {"introduction", "tutorial", "basics", "入门"})
        # A locale preference never turns a stale version into a matching version.
        version = demand.framework_version if matching else (
            demand.language_version if not frameworks else None
        )
        scope_versions = set(re.findall(r"\d+(?:\.\d+)*", entry.get("version_scope", "")))
        if version and scope_versions:
            score += 4 if version in scope_versions else -12
        previous = choices.get(url)
        if not previous or score > previous[0]:
            choices[url] = (score, {**entry, "url": url})
    return [
        entry for _, entry in sorted(
            choices.values(), key=lambda value: (
                value[1]["url"] not in preferred_urls, -value[0], value[1]["id"],
            ),
        )
    ][:limit]


def candidate_source(demand, entry):
    url = candidate_url(entry["url"])
    address = urlsplit(url)
    path = address.path
    prefix_path = path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"
    prefix = urlunsplit(address._replace(path=prefix_path))
    language_key = {"js": "javascript", "ts": "typescript", "c#": "csharp"}.get(
        (demand.language or "").casefold(), (demand.language or "").casefold(),
    )
    language = demand.language if language_key in entry["languages"] else (
        entry["languages"][0] if len(entry["languages"]) == 1 else None
    )
    return MaterialSourceInput(
        goal_id=demand.goal_id, title=entry["title"][:160],
        entry_url=url, allowed_prefixes=[prefix], authorized_use=True,
        purposes=ALL_PURPOSES, language=language,
        # These are acquisition targets, not a claim that the body fits the requested version.
        topics=[
            *entry["frameworks"], *entry["topics"][:90],
            "version scope: " + entry.get("version_scope", "unverified")[:200],
        ],
    )


def selected_pdf_pages(metadata, topics, *, limit=20, exclude_pages=()):
    wanted = set(terms(" ".join(topics)))
    outline = sorted(metadata.get("outline", []), key=lambda item: item["page"])
    matches = [
        (len(wanted & set(terms(item["title"]))), index, item)
        for index, item in enumerate(outline)
    ]
    selected = set()
    excluded = set(exclude_pages)
    for score, index, item in sorted(matches, key=lambda value: (-value[0], value[1])):
        if not score:
            continue
        end = next(
            (other["page"] - 1 for other in outline[index + 1:]
             if other["depth"] <= item["depth"] and other["page"] > item["page"]),
            metadata["page_count"],
        )
        for page in range(item["page"], end + 1):
            if page not in excluded:
                selected.add(page)
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break
    if not selected:
        # An unlabelled book gets a small initial excerpt, not an implicit full-book import.
        selected.update(page for page in range(1, min(metadata["page_count"], 4) + 1)
                        if page not in excluded)
    if not selected:
        raise BusinessError(
            "source_automatic_scope_limit", "No new relevant PDF pages were selected.",
        )
    return sorted(selected)


class DiscoveredSourceCatalog:
    def __init__(self, connection):
        self.connection = connection

    def entries(self, actor):
        return [
            {**row["metadata"], "frameworks": observed_frameworks(
                row["metadata"]["title"], row["metadata"]["url"],
            )} for row in self.connection.execute(
                "SELECT metadata FROM knowledge.discovered_source_catalog "
                "WHERE actor_id=%s ORDER BY updated_at DESC,url", (actor.id,),
            ).fetchall()
        ]

    def remember(self, actor, discovery_id, item, demand):
        url = candidate_url(item["url"])
        title = str(item.get("title", "")).strip()[:160]
        if not title:
            return None
        entry = {
            "id": "discovered:" + identity(url), "title": title, "url": url,
            "publisher": urlsplit(url).hostname, "origin": "third_party",
            "languages": [demand.language.casefold()] if demand.language else [
                item["language"] for item in topic_subjects(demand.goal_text or "")
            ],
            "frameworks": observed_frameworks(title, url),
            "forms": ["html"], "locales": [],
            "topics": sorted(terms(title + " " + urlsplit(url).path))[:30],
            "discovered_for": (demand.goal_text or "")[:1000],
            "version_scope": "unverified; inspect the selected body",
            "verification": {"status": "unverified"},
        }
        self.connection.execute(
            "INSERT INTO knowledge.discovered_source_catalog"
            "(actor_id,url,metadata,discovery_id) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(actor_id,url) DO UPDATE SET metadata=EXCLUDED.metadata,"
            "discovery_id=EXCLUDED.discovery_id,updated_at=now()",
            (actor.id, url, Jsonb(entry), discovery_id),
        )
        return entry
