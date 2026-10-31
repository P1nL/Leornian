from __future__ import annotations

from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.identity.contracts import Actor
from leornian.modules.knowledge.contracts import Material
from leornian.modules.learning.contracts import LearningPlan, PlanDocument, PlanRevision
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
    ) -> LearningPlan:
        allowed = {(material.source_id, material.revision) for material in materials}
        used = {
            (ref.source_id, ref.revision) for node in document.nodes for ref in node.source_refs
        }
        if not used <= allowed or (allowed and not used):
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

    def for_goal(self, actor: Actor, goal_id: UUID) -> LearningPlan | None:
        row = self.connection.execute(
            "SELECT id FROM learning.plans WHERE actor_id = %s AND goal_id = %s",
            (actor.id, goal_id),
        ).fetchone()
        return self.get(actor, row["id"]) if row else None

    def list(self, actor: Actor) -> list[LearningPlan]:
        rows = self.connection.execute(
            "SELECT id FROM learning.plans WHERE actor_id = %s ORDER BY id LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [self.get(actor, row["id"]) for row in rows]

    def history(self, actor: Actor, plan_id: UUID) -> list[PlanRevision]:
        self.get(actor, plan_id)
        return [
            PlanRevision(**row)
            for row in self.connection.execute(
                "SELECT id, revision, predecessor_revision, document, sources, created_at "
                "FROM learning.plan_revisions WHERE plan_id = %s ORDER BY revision DESC LIMIT 20",
                (plan_id,),
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
