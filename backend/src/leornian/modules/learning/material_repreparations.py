from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.learning.lessons import Lessons
from leornian.modules.learning.material_contracts import material_content_key
from leornian.modules.learning.material_update_contracts import MaterialRepreparation
from leornian.modules.learning.material_updates import references_material
from leornian.modules.learning.materials import MaterialBindings
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError

TERMINAL = {"ready", "superseded", "cancelled"}


class LearningMaterialRepreparations:
    """One original preparation per current dependency of an accepted update."""

    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def public(row):
        return MaterialRepreparation(**{
            key: row[key] for key in MaterialRepreparation.model_fields
        })

    def decision(self, actor, decision_id):
        row = self.connection.execute(
            "SELECT d.*,m.dependencies FROM learning.material_update_decisions d "
            "LEFT JOIN learning.material_update_migrations m ON m.decision_id=d.id "
            "WHERE d.actor_id=%s AND d.id=%s", (actor.id, decision_id),
        ).fetchone()
        if not row or row["decision"] != "accept_update":
            raise BusinessError("not_found", "Accepted material update not found.")
        return row

    def enqueue(self, actor, decision_id, session_digest):
        decision = self.decision(actor, decision_id)
        old = MaterialBindings(self.connection).get(
            actor, decision["binding_id"], decision["binding_revision"],
        )
        successor = MaterialBindings(self.connection).get(
            actor, decision["successor_binding_id"], decision["successor_binding_revision"],
        )
        successor_keys = {material_content_key(ref) for ref in successor.refs}
        changed_refs = [
            ref for ref in old.refs if material_content_key(ref) not in successor_keys
        ]
        dependencies = decision["dependencies"] or []
        plan_ids = {value["plan_id"] for value in dependencies}
        for plan_id in sorted(plan_ids):
            plan = Plans(self.connection).get(actor, plan_id)
            relevant = any(
                references_material(version.document.model_dump(mode="json"), changed_refs)
                for version in (plan.latest, plan.active) if version
            )
            state = "queued" if relevant else "superseded"
            self._insert(
                actor, decision_id, session_digest, "plan", plan.id, plan.latest.revision,
                plan.goal_id, plan.id, None, state,
            )
        for dependency in dependencies:
            if dependency["kind"] != "lesson":
                continue
            plan = Plans(self.connection).get(actor, dependency["plan_id"])
            current = Lessons(self.connection).for_node(
                actor, plan.id, dependency["plan_revision"], dependency["node_key"],
            )
            relevant = (
                plan.active and plan.active.revision == dependency["plan_revision"]
                and current and str(current.id) == dependency["id"]
            )
            self._insert(
                actor, decision_id, session_digest, "lesson", dependency["id"],
                dependency["plan_revision"], plan.goal_id, plan.id,
                dependency["node_key"], "queued" if relevant else "superseded",
            )
        return self.list(actor, decision_id)

    def _insert(
        self, actor, decision_id, digest, kind, source_id, revision, goal_id, plan_id,
        node_key, state,
    ):
        identifier = uuid4()
        self.connection.execute(
            "INSERT INTO learning.material_repreparations"
            "(id,actor_id,decision_id,kind,source_id,source_revision,goal_id,plan_id,node_key,"
            "session_digest,command_key,state,reason) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(decision_id,kind,source_id) DO NOTHING",
            (
                identifier, actor.id, decision_id, kind, source_id, revision, goal_id,
                plan_id, node_key, digest, f"material-reprepare:{identifier}", state,
                "historical_dependency" if state == "superseded" else None,
            ),
        )

    def list(self, actor, decision_id):
        self.decision(actor, decision_id)
        return [
            self.public(row) for row in self.connection.execute(
                "SELECT * FROM learning.material_repreparations "
                "WHERE actor_id=%s AND decision_id=%s ORDER BY kind,created_at,id",
                (actor.id, decision_id),
            ).fetchall()
        ]

    def due(self, limit=20):
        return self.connection.execute(
            "SELECT id,actor_id,session_digest FROM learning.material_repreparations "
            "WHERE state NOT IN ('ready','superseded','cancelled') AND next_action_at<=now() "
            "ORDER BY next_action_at,created_at,id LIMIT %s", (limit,),
        ).fetchall()

    def row(self, actor, identifier, *, lock=False):
        row = self.connection.execute(
            "SELECT * FROM learning.material_repreparations WHERE actor_id=%s AND id=%s "
            + ("FOR UPDATE" if lock else ""), (actor.id, identifier),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material preparation not found.")
        return row

    def parent(self, actor, row):
        return self.connection.execute(
            "SELECT * FROM learning.material_repreparations WHERE actor_id=%s "
            "AND decision_id=%s AND plan_id=%s AND kind='plan'",
            (actor.id, row["decision_id"], row["plan_id"]),
        ).fetchone()

    def state(self, identifier, state, reason=None, *, plan_revision=None, lesson_id=None):
        self.connection.execute(
            "UPDATE learning.material_repreparations SET state=%s,reason=%s,"
            "output_plan_revision=COALESCE(%s,output_plan_revision),"
            "output_lesson_id=COALESCE(%s,output_lesson_id),updated_at=now(),"
            "next_action_at=now()+interval '15 seconds' WHERE id=%s",
            (state, reason, plan_revision, lesson_id, identifier),
        )

    def attach(self, identifier, data, accepted):
        self.connection.execute(
            "UPDATE learning.material_repreparations SET state='running',reason=NULL,"
            "request_data=%s,run_id=%s,delivery_task_id=%s,updated_at=now(),"
            "next_action_at=now()+interval '15 seconds' WHERE id=%s AND run_id IS NULL",
            (
                Jsonb(data.model_dump(mode="json")), accepted.run_id,
                accepted.delivery_task_id, identifier,
            ),
        )

    def derived_binding(self, identifier, binding, predecessor_revision):
        self.connection.execute(
            "UPDATE learning.material_repreparations SET derived_binding_id=%s,"
            "derived_binding_revision=%s,predecessor_binding_revision=%s WHERE id=%s",
            (binding.id, binding.revision, predecessor_revision, identifier),
        )
