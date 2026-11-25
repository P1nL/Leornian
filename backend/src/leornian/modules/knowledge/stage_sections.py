import re
from collections import Counter
from math import log1p
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.retrieval import terms


def shared_readings(stage, current):
    own = {item["source_url"] for item in current["readings"] if item.get("source_url")}
    if own:
        return own
    technologies = {item["name"] for item in current["technologies"]}
    return {
        reading["source_url"] for sibling in stage["nodes"]
        if sibling["technologies"] and {item["name"] for item in sibling["technologies"]}
        <= technologies for reading in sibling["readings"] if reading.get("source_url")
    }


def map_stage_sections(rows, nodes):
    words = [set(terms(row["text"])) for row in rows]
    headings = [set(terms(" ".join(row["section_path"] or ()))) for row in rows]
    frequencies = Counter(word for body, heading in zip(words, headings, strict=True)
                          for word in body | heading)
    weights = {word: log1p(len(rows) / count) for word, count in frequencies.items()}
    mapping = {}
    for node in nodes:
        selected = set()
        subject = set(terms(" ".join(item["name"] for item in node["technologies"])))
        for topic in [node["title"], *node["topics"]]:
            wanted = set(terms(topic)) - subject
            if not wanted:
                continue
            scored = [
                (sum(weights[word] for word in sorted(wanted & body))
                 + 2 * sum(weights[word] for word in sorted(wanted & heading)), index)
                for index, (body, heading) in enumerate(zip(words, headings, strict=True))
            ]
            for score, index in sorted(scored, key=lambda item: (-item[0], item[1]))[:2]:
                if not score:
                    break
                selected.add(index)
                for neighbor in (index - 1, index + 1):
                    if 0 <= neighbor < len(rows) and (
                        rows[neighbor]["document_id"] == rows[index]["document_id"]
                        and rows[neighbor]["section_path"] == rows[index]["section_path"]
                        and abs(rows[neighbor].get("ordinal", neighbor)
                                - rows[index].get("ordinal", index)) == 1
                    ):
                        selected.add(neighbor)
        if not selected and rows and any(
            reading.get("document_id") == str(rows[0]["document_id"]) or (
                reading.get("source_url") and
                urlsplit(reading["source_url"]) == urlsplit(rows[0]["source_url"])
            ) for reading in node["readings"]
        ):
            selected.update(range(min(len(rows), 4)))
        mapping[node["key"]] = [str(rows[index]["id"]) for index in sorted(selected)]
    return mapping


def chapter_location(url):
    link = urlsplit(url)
    return link.netloc, link.path.rstrip("/").removesuffix(".html"), link.query


def topic_words(text):
    return {word for word in terms(re.sub(r"([a-z])([A-Z])", r"\1 \2", text))
            if len(word) > 1 and not word.isdecimal()}


def node_excerpts(rows, topics, technologies):
    if not rows:
        return []
    subject = topic_words(" ".join(item["name"] for item in technologies))
    bodies = [topic_words(row["text"]) for row in rows]
    headings = [topic_words(" ".join(row["section_path"] or ())) for row in rows]
    frequency = Counter(word for body, heading in zip(bodies, headings, strict=True)
                        for word in body | heading)
    weights = {word: (1.7 if word.isascii() else 1) * log1p(len(rows) / count)
               for word, count in frequency.items()}
    selected = {}
    for topic in topics:
        wanted = topic_words(topic) - subject
        ranked = []
        for index, row in enumerate(rows):
            if row["kind"] == "heading" or len(row["text"].strip()) < 12:
                continue
            body = sum(weights[word] for word in sorted(wanted & bodies[index]))
            heading = sum(weights[word] for word in sorted(wanted & headings[index]))
            if body or heading:
                ranked.append((body + heading * 1.5, body, index))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        if not ranked:
            continue
        best = rows[ranked[0][2]]
        chosen = [best]
        for kind in ("paragraph", "code"):
            kind_rows = [(score, rows[index]) for score, _, index in ranked
                         if rows[index]["kind"] == kind and rows[index]["id"] != best["id"]]
            same_section = [row for _, row in kind_rows
                            if row["document_id"] == best["document_id"]
                            and row["section_path"] == best["section_path"]]
            if same_section and kind != best["kind"]:
                nearest = min(same_section, key=lambda row: abs(row["ordinal"] - best["ordinal"]))
                chosen.append(nearest)
            elif kind_rows:
                chosen.append(kind_rows[0][1])
        selected.update((str(row["id"]), None) for row in chosen)
    return list(selected)


def example_excerpts(rows, queries, technologies):
    def example_words(text):
        return topic_words(text) | set(re.findall(r"=>|->|::|\?\?|\|>|:=", text))

    subject = topic_words(" ".join(item["name"] for item in technologies))
    generic = subject | {"example", "examples", "code", "snippet", "sample", "示例", "代码"}
    sections = {}
    paragraphs = []
    for row in rows:
        key = (row["build_id"], tuple(row["section_path"] or ()))
        sections.setdefault(key, []).append(row)
        if row["kind"] == "paragraph" and "```" not in row["text"]:
            paragraphs.append((row, example_words(row["text"])))
    frequency = Counter(word for _, words in paragraphs for word in words)
    chosen = {}
    for topic, hint in queries.items():
        hint_words = example_words(hint) - generic
        wanted = (example_words(topic) | hint_words) - generic
        ranked = []
        for (_, path), items in sections.items():
            heading = topic_words(" ".join(path))
            for index, item in enumerate(items):
                if item["kind"] != "code" and "```" not in item["text"]:
                    continue
                body = example_words(item["text"])
                nearby = [neighbor for neighbor in items[max(0, index-3):index+4]
                          if neighbor["kind"] == "paragraph" and len(neighbor["text"].strip()) > 10
                          and abs(neighbor["ordinal"] - item["ordinal"]) <= 3]
                explanation = max(nearby, key=lambda neighbor: (
                    len(wanted & topic_words(neighbor["text"])),
                    -abs(neighbor["ordinal"] - item["ordinal"]),
                ), default=None)
                context = topic_words(explanation["text"]) if explanation else set()
                identified = wanted & body
                described = wanted & (heading | context)
                if not (identified or len(described) >= 2 or wanted and wanted <= described):
                    continue
                score = (3 * len(identified) + 2 * len(wanted & heading) + len(wanted & context)
                         + 3 * sum(word.isascii() for word in identified))
                ranked.append((score, item, explanation))
        ranked.sort(key=lambda entry: -entry[0])
        present = set()
        for _, item, explanation in ranked[:2]:
            chosen[str(item["id"])] = None
            present.update(example_words(item["text"]))
            if explanation:
                chosen[str(explanation["id"])] = None
                present.update(example_words(explanation["text"]))
        if ranked and (unexplained := hint_words - present):
            support = max((
                (sum(log1p(len(paragraphs) / frequency[word]) for word in sorted(overlap)), row)
                for row, words in paragraphs if (overlap := unexplained & words)
            ), key=lambda pair: pair[0], default=None)
            if support:
                chosen[str(support[1]["id"])] = None
    return list(chosen)


class StageSections:
    def __init__(self, connection):
        self.connection = connection

    def chunks(self, actor, demand, stage, builds, *, topics=None, reviewed=(), examples=None):
        by_version = {}
        for build in builds:
            version = (build["document_id"], build["document_revision"])
            if version not in by_version or build["space"].get("mode") == "lexical":
                by_version[version] = build
        chunks = []
        for build in by_version.values():
            keys = (actor.id, demand.plan_id, demand.plan_revision, stage["key"], build["id"])
            record = self.connection.execute(
                "SELECT node_sections->%s AS chunks FROM knowledge.stage_material_sections "
                "WHERE actor_id=%s AND plan_id=%s AND plan_revision=%s AND stage_key=%s "
                "AND build_id=%s", (demand.node_key, *keys),
            ).fetchone()
            if record is None:
                rows = self.connection.execute(
                    "SELECT c.id,c.ordinal,c.text,db.section_path,b.document_id,v.source_url "
                    "FROM knowledge.material_index_builds b JOIN knowledge.material_chunks c "
                    "ON c.build_id=b.id JOIN knowledge.document_blocks db ON db.id=c.block_id "
                    "JOIN knowledge.document_versions v ON v.document_id=b.document_id "
                    "AND v.revision=b.document_revision WHERE b.id=%s AND b.actor_id=%s "
                    "AND b.state='indexed' AND c.text IS NOT NULL ORDER BY c.ordinal,c.id",
                    (build["id"], actor.id),
                ).fetchall()
                mapping = map_stage_sections(rows, stage["nodes"])
                self.connection.execute(
                    "INSERT INTO knowledge.stage_material_sections"
                    "(actor_id,plan_id,plan_revision,stage_key,build_id,node_sections) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (*keys, Jsonb(mapping)),
                )
                chunks.extend(mapping[demand.node_key])
            else:
                chunks.extend(record["chunks"] or ())
        if not chunks and topics is None:
            return chunks
        node = next(item for item in stage["nodes"] if item["key"] == demand.node_key)
        rows = self.connection.execute(
            "SELECT c.id,c.build_id,c.ordinal,c.text,b.document_id,db.section_path,db.kind "
            "FROM knowledge.material_chunks c JOIN knowledge.material_index_builds b "
            "ON b.id=c.build_id "
            "JOIN knowledge.document_blocks db ON db.id=c.block_id "
            "WHERE c.build_id=ANY(%s::uuid[]) AND c.text IS NOT NULL "
            "AND NOT (c.block_id=ANY(%s::uuid[])) AND (%s OR EXISTS ("
            "SELECT 1 FROM knowledge.material_chunks anchor JOIN knowledge.document_blocks ab "
            "ON ab.id=anchor.block_id WHERE anchor.id=ANY(%s::uuid[]) "
            "AND anchor.build_id=c.build_id AND ab.section_path=db.section_path)) "
            "ORDER BY b.document_id,c.ordinal,c.id",
            ([item["id"] for item in by_version.values()], list(reviewed),
             topics is not None, chunks),
        ).fetchall()
        if examples:
            return example_excerpts(rows, examples, node["technologies"])
        selected = node_excerpts(
            rows, topics or node["topics"] or [node["title"]], node["technologies"],
        )
        return selected or ([] if topics is not None else chunks[:4])


def guide_chapters(resources, topics, technologies):
    subject = topic_words(" ".join(item["name"] for item in technologies))
    candidates = [(item, topic_words(item["link_label"]),
                   topic_words(chapter_location(item["url"])[1].rsplit("/", 1)[-1]))
                  for item in resources if item["link_label"]]
    frequencies = Counter(word for _, label, slug in candidates for word in label | slug)
    selected = {}
    fallback = {}
    for topic in topics:
        wanted = topic_words(topic) - subject
        ranked = sorted((
            (bool(label and label <= wanted) or any(word.isascii() for word in wanted & slug),
             sum((2 if word in label else 1) * (2 if word.isascii() else 1)
                 * log1p(len(candidates) / frequencies[word])
                 for word in sorted(wanted & (label | slug))), item)
            for item, label, slug in candidates
        ), key=lambda match: (not match[0], -match[1], match[2]["depth"],
                              match[2]["link_order"], match[2]["url"]))
        if ranked and ranked[0][1]:
            direct, _, item = ranked[0]
            direct = direct or any(
                len(word) >= 3 and word[:3] in topic
                for word in re.findall(r"[\u4e00-\u9fff]+", item["link_label"])
            )
            (selected if direct else fallback)[item["url"]] = None
    return tuple(selected or fallback)
