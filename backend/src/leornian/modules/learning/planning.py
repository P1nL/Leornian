from __future__ import annotations

import re
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.knowledge.contracts import Material
from leornian.modules.learning.contracts import (
    LearningPlan,
    PlanConfirmation,
    PlanDocument,
    PlanRevision,
)
from leornian.modules.learning.material_contracts import MaterialCitation, citation_key
from leornian.shared_kernel.errors import BusinessError


class Plans:
    """Append-only plan content; explicit confirmation owns the active pointer."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def require_base(self, actor: Actor, goal_id: UUID, revision: int) -> None:
        row = self.connection.execute(
            "SELECT latest_revision FROM learning.plans WHERE actor_id = %s AND goal_id = %s "
            "FOR SHARE",
            (actor.id, goal_id),
        ).fetchone()
        if (row["latest_revision"] if row else 0) != revision:
            raise BusinessError("stale_version", "Plan changed; generate from the latest revision.")

    def record(
        self,
        actor: Actor,
        goal_id: UUID,
        base_revision: int,
        run_id: UUID,
        document: PlanDocument,
        materials: list[Material],
        material_citations: list[MaterialCitation] | None = None,
        *,
        require_evidence: bool = True,
    ) -> LearningPlan:
        allowed = {(material.source_id, material.revision) for material in materials}
        used = {
            (ref.source_id, ref.revision) for node in document.nodes for ref in node.source_refs
        }
        supplied = {citation_key(c) for c in material_citations or [] if c.purpose == "planning"}
        cited = {
            citation_key(c) for node in document.nodes for c in node.material_citations
        }
        if document.curriculum:
            cited.update(
                citation_key(c)
                for text in document.curriculum.texts for c in text.material_citations
            )
        if not used <= allowed or not cited <= supplied or (
            require_evidence and (allowed or supplied) and not (used or cited)
        ):
            raise BusinessError(
                "invalid_plan_output", "Plan must cite only supplied source versions."
            )
        self.connection.execute(
            "INSERT INTO learning.plans(id, actor_id, goal_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (actor_id, goal_id) DO NOTHING",
            (uuid4(), actor.id, goal_id),
        )
        head = self.connection.execute(
            "SELECT id, latest_revision FROM learning.plans WHERE actor_id = %s AND goal_id = %s "
            "FOR UPDATE",
            (actor.id, goal_id),
        ).fetchone()
        if head["latest_revision"] != base_revision:
            raise BusinessError("stale_version", "Generated plan has a stale predecessor.")
        self.connection.execute(
            "INSERT INTO learning.plan_revisions(id, plan_id, revision, predecessor_revision, "
            "produced_by_run, document, sources) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                uuid4(),
                head["id"],
                base_revision + 1,
                base_revision,
                run_id,
                Jsonb(document.model_dump(mode="json")),
                Jsonb([material.model_dump(mode="json") for material in materials]),
            ),
        )
        self.connection.execute(
            "UPDATE learning.plans SET latest_revision = %s WHERE id = %s",
            (base_revision + 1, head["id"]),
        )
        return self.get(actor, head["id"])

    def get(self, actor: Actor, plan_id: UUID, *, lock: bool = False) -> LearningPlan:
        head = self.connection.execute(
            "SELECT id, goal_id, latest_revision, active_revision FROM learning.plans "
            "WHERE id = %s AND actor_id = %s " + ("FOR UPDATE" if lock else ""),
            (plan_id, actor.id),
        ).fetchone()
        if not head:
            raise BusinessError("not_found", "Learning plan not found.")
        revisions = self.connection.execute(
            "SELECT id, revision, predecessor_revision, document, sources, created_at "
            "FROM learning.plan_revisions WHERE plan_id = %s AND revision IN (%s, %s)",
            (plan_id, head["latest_revision"], head["active_revision"]),
        ).fetchall()
        versions = {row["revision"]: PlanRevision(**row) for row in revisions}
        return LearningPlan(
            id=head["id"],
            goal_id=head["goal_id"],
            latest=versions[head["latest_revision"]],
            active=versions.get(head["active_revision"]),
        )

    def node_directory(self, actor, plan_id, revisions):
        return self.connection.execute(
            "SELECT r.revision AS plan_revision,n.node->>'key' AS node_key,"
            "n.node->>'title' AS title,n.position FROM learning.plans p "
            "JOIN learning.plan_revisions r ON r.plan_id=p.id "
            "CROSS JOIN LATERAL jsonb_array_elements(r.document->'nodes') "
            "WITH ORDINALITY AS n(node,position) "
            "WHERE p.actor_id=%s AND p.id=%s AND r.revision=ANY(%s) "
            "ORDER BY r.revision DESC,n.position", (actor.id, plan_id, list(revisions)),
        ).fetchall()

    def for_goal(self, actor: Actor, goal_id: UUID) -> LearningPlan | None:
        row = self.connection.execute(
            "SELECT id FROM learning.plans WHERE actor_id = %s AND goal_id = %s",
            (actor.id, goal_id),
        ).fetchone()
        return self.get(actor, row["id"]) if row else None

    def curriculum_snapshot(
        self, actor, plan_id, plan_revision=None, *, node_key=None, include_stage=False,
    ):
        """Return the selected curriculum from an owned immutable plan revision."""
        plan = self.get(actor, plan_id)
        revision = plan.active or plan.latest
        if plan_revision is not None and revision.revision != plan_revision:
            row = self.connection.execute(
                "SELECT id,revision,predecessor_revision,document,sources,created_at "
                "FROM learning.plan_revisions WHERE plan_id=%s AND revision=%s",
                (plan_id, plan_revision),
            ).fetchone()
            if not row:
                raise BusinessError("not_found", "Curriculum plan revision not found.")
            revision = PlanRevision(**row)
        nodes = [
            node for node in revision.document.nodes if node_key is None or node.key == node_key
        ]
        if node_key is not None and not nodes:
            raise BusinessError("not_found", "Curriculum node not found.")
        if revision.document.curriculum is None:
            return None
        snapshot = {
            "plan_id": str(plan.id), "plan_revision": revision.revision,
            **revision.document.curriculum.model_dump(mode="json"),
            "node_chapters": [
                {"node_key": node.key,
                 "chapters": [
                     chapter.model_dump(mode="json") for chapter in node.curriculum_chapters
                 ],
                 "project_milestone": node.project_milestone,
                 "material_plan": self.node_material_plan(revision.document, node)}
                for node in nodes
            ],
        }
        if include_stage and node_key is not None:
            stage = self.material_stage(revision.document, node_key)
            snapshot["material_stage"] = {
                "key": stage[0].key,
                "nodes": [{
                    "key": item.key, "title": item.title, "objective": item.objective,
                    **self.node_material_plan(revision.document, item),
                } for item in stage],
            }
        return snapshot

    @staticmethod
    def material_stage(document, node_key):
        groups = []
        previous = None
        milestones = any(node.project_milestone for node in document.nodes)
        for node in document.nodes:
            explicit = node.material_plan.stage_key if node.material_plan else None
            signature = explicit or (
                tuple(node.material_plan.technologies[:1])
                if node.material_plan and not milestones else ()
            )
            boundary = previous is None or signature != previous[0] or (
                not explicit and previous[1].project_milestone
            )
            if boundary:
                groups.append([])
            groups[-1].append(node)
            previous = (signature, node)
        return next(group for group in groups if any(node.key == node_key for node in group))

    @staticmethod
    def node_material_plan(document, node):
        """Derive pending needs without fetching sources or changing the saved route."""
        proposed = node.material_plan
        prerequisites = set(node.prerequisite_keys)
        for earlier in reversed(document.nodes):
            if earlier.key in prerequisites:
                prerequisites.update(earlier.prerequisite_keys)
        text = "\n".join([
            node.title, node.objective, *(
                proposed.topics if proposed else []
            ), *(chapter.title for chapter in node.curriculum_chapters),
            *(part for earlier in document.nodes if earlier.key in prerequisites
              for part in (earlier.title, earlier.objective)),
        ])
        technologies = []
        for item in document.curriculum.technologies if document.curriculum else []:
            words = re.findall(r"[A-Za-z][A-Za-z0-9_.+#-]*", item.name)
            mentioned = any(re.search(
                r"(?<![a-z0-9_])" + re.escape(word) + r"(?![a-z0-9_])",
                text, re.I,
            ) for word in words) if words else item.name in text
            if (
                item.name in proposed.technologies
                if proposed and proposed.technologies else mentioned
            ):
                technologies.append(item.model_dump(mode="json"))
        if not technologies and document.curriculum and len(
            document.curriculum.technologies
        ) == 1 and not (proposed and proposed.technologies):
            technologies = [
                document.curriculum.technologies[0].model_dump(mode="json")
            ]
        readings = [
            item.model_dump(mode="json") for item in proposed.readings
        ] if proposed else []
        for chapter in node.curriculum_chapters:
            if chapter.source_url:
                reading = {"title": chapter.title, "source_url": chapter.source_url}
            else:
                citation = next(
                    (
                        citation for citation in [
                            *node.material_citations,
                            *(citation for text in document.curriculum.texts
                              for citation in text.material_citations),
                        ] if citation.ref.document_id == chapter.document_id
                    ),
                    None,
                )
                if citation is None:
                    raise BusinessError(
                        "source_not_current", "Selected chapter lacks its exact document revision.",
                    )
                reading = {
                    "title": chapter.title, "source_url": None,
                    "document_id": str(chapter.document_id),
                    "document_revision": citation.ref.document_revision,
                }
            if not any(
                item.get("source_url") == reading.get("source_url")
                and item.get("document_id") == reading.get("document_id")
                for item in readings
            ):
                readings.append(reading)
        return {
            "topics": list(proposed.topics) if proposed and proposed.topics else [node.objective],
            "technologies": technologies,
            "readings": readings,
        }

    def produced_revision(self, actor, plan_id, run_id):
        self.get(actor, plan_id)
        row = self.connection.execute(
            "SELECT revision FROM learning.plan_revisions "
            "WHERE plan_id=%s AND produced_by_run=%s", (plan_id, run_id),
        ).fetchone()
        return row["revision"] if row else None

    def list(self, actor: Actor) -> list[LearningPlan]:
        rows = self.connection.execute(
            "SELECT id FROM learning.plans WHERE actor_id = %s ORDER BY id LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [self.get(actor, row["id"]) for row in rows]

    def history(self, actor: Actor, plan_id: UUID, before=None, limit=20) -> list[PlanRevision]:
        self.get(actor, plan_id)
        return [
            PlanRevision(**row)
            for row in self.connection.execute(
                "SELECT id, revision, predecessor_revision, document, sources, created_at "
                "FROM learning.plan_revisions WHERE plan_id=%s "
                + ("AND revision<%s " if before else "")
                + "ORDER BY revision DESC LIMIT %s",
                (plan_id, *((before,) if before else ()), limit),
            ).fetchall()
        ]

    def confirm(self, actor: Actor, plan_id: UUID, revision: int) -> tuple[LearningPlan, bool]:
        plan = self.get(actor, plan_id, lock=True)
        if plan.latest.revision != revision:
            raise BusinessError(
                "stale_version", "Only the latest exact plan revision can be confirmed."
            )
        if plan.active and plan.active.revision == revision:
            return plan, False
        self.connection.execute(
            "INSERT INTO learning.plan_confirmations(plan_id, revision) VALUES (%s, %s)",
            (plan_id, revision),
        )
        self.connection.execute(
            "UPDATE learning.plans SET active_revision = %s WHERE id = %s",
            (revision, plan_id),
        )
        return self.get(actor, plan_id), True

    def confirmation(self, actor, plan_id, revision):
        self.get(actor, plan_id)
        row = self.connection.execute(
            "SELECT plan_id,revision,confirmed_at FROM learning.plan_confirmations "
            "WHERE plan_id=%s AND revision=%s", (plan_id, revision),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "This exact plan revision was not confirmed.")
        return PlanConfirmation(**row)
