from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from leornian.modules.learning.material_contracts import (
    MaterialBinding,
    MaterialBindingInput,
    material_content_key,
)
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError


def review_due_at(now, expected_completion_at=None, *, review_days=180, grace_days=30):
    return max(
        now + timedelta(days=review_days),
        expected_completion_at + timedelta(days=grace_days) if expected_completion_at else now,
    )


class MaterialBindings:
    """Learning owns immutable binding revisions, never document permissions."""

    def __init__(self, connection: Connection, *, review_days=180, grace_days=30):
        self.connection = connection
        self.review_days, self.grace_days = review_days, grace_days

    @staticmethod
    def require_ref_in(binding, ref):
        if not any(
            original.document_id == ref.document_id
            and original.document_revision == ref.document_revision
            and original.block_id == ref.block_id
            and original.span.start <= ref.span.start < ref.span.end <= original.span.end
            for original in binding.refs
        ):
            raise BusinessError("source_not_current", "Citation is outside its bound source range.")
        return ref

    def get(self, actor, binding_id, revision=None, *, lock=False):
        row = self.connection.execute(
            "SELECT b.id,b.goal_id,b.purpose,v.* FROM learning.material_bindings b "
            "JOIN learning.material_binding_revisions v ON v.binding_id=b.id "
            "AND v.revision=COALESCE(%s,b.revision) WHERE b.id=%s AND b.actor_id=%s"
            + (" FOR SHARE OF b" if lock else ""),
            (revision, binding_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material binding not found.")
        return MaterialBinding(**{key: value for key, value in row.items() if key != "binding_id"})

    def for_scope(
        self, actor, goal_id, purpose, *, plan_id=None, plan_revision=None, node_key=None
    ):
        rows = self.connection.execute(
            "SELECT b.id FROM learning.material_bindings b "
            "JOIN learning.material_binding_revisions v ON v.binding_id=b.id "
            "AND v.revision=b.revision WHERE b.actor_id=%s AND b.goal_id=%s AND b.purpose=%s "
            "AND v.plan_id IS NOT DISTINCT FROM %s::uuid "
            "AND v.plan_revision IS NOT DISTINCT FROM %s::integer "
            "AND v.node_key IS NOT DISTINCT FROM %s ORDER BY b.id",
            (actor.id, goal_id, purpose, plan_id, plan_revision, node_key),
        ).fetchall()
        return [self.get(actor, row["id"]) for row in rows]

    def current_for_document(self, actor, goal_id, document_id):
        rows = self.connection.execute(
            "SELECT b.id FROM learning.material_bindings b "
            "JOIN learning.material_binding_revisions v ON v.binding_id=b.id "
            "AND v.revision=b.revision WHERE b.actor_id=%s AND b.goal_id=%s "
            "AND EXISTS (SELECT 1 FROM jsonb_array_elements(v.refs) ref "
            "WHERE ref->>'document_id'=%s) ORDER BY b.id",
            (actor.id, goal_id, str(document_id)),
        ).fetchall()
        return [self.get(actor, row["id"]) for row in rows]

    def accepted_successor_of(self, actor, binding, origin_refs):
        expected = {material_content_key(ref) for ref in origin_refs}
        revision = binding.revision
        while revision > 1:
            predecessor = self.connection.execute(
                "SELECT binding_id,binding_revision FROM learning.material_update_decisions "
                "WHERE actor_id=%s AND decision='accept_update' AND successor_binding_id=%s "
                "AND successor_binding_revision=%s",
                (actor.id, binding.id, revision),
            ).fetchone()
            if not predecessor:
                predecessor = self.connection.execute(
                    "SELECT r.derived_binding_id AS binding_id,"
                    "r.predecessor_binding_revision AS binding_revision "
                    "FROM learning.material_repreparations r "
                    "JOIN learning.material_update_decisions d ON d.id=r.decision_id "
                    "WHERE r.actor_id=%s AND d.decision='accept_update' "
                    "AND r.derived_binding_id=%s AND r.derived_binding_revision=%s "
                    "AND r.predecessor_binding_revision>0",
                    (actor.id, binding.id, revision),
                ).fetchone()
            if (
                not predecessor or predecessor["binding_id"] != binding.id
                or predecessor["binding_revision"] >= revision
            ):
                return False
            old = self.get(actor, binding.id, predecessor["binding_revision"])
            if {material_content_key(ref) for ref in old.refs} == expected:
                return True
            revision = old.revision
        return False

    def require_scope(self, actor, data):
        if data.plan_id:
            plan = Plans(self.connection).get(actor, data.plan_id, lock=True)
            if (
                plan.goal_id != data.goal_id
                or not plan.active
                or plan.active.revision != data.plan_revision
            ):
                raise BusinessError(
                    "stale_version", "Material binding needs the active exact plan."
                )
            if data.node_key and data.node_key not in {n.key for n in plan.active.document.nodes}:
                raise BusinessError("not_found", "Material binding node not found.")

    def replay(self, actor, key, data: MaterialBindingInput):
        request = data.model_dump(mode="json")
        previous = self.connection.execute(
            "SELECT * FROM learning.material_binding_commands WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if previous:
            if previous["request"] != request:
                raise BusinessError("idempotency_conflict", "Binding key has different content.")
            return self.get(actor, previous["binding_id"], previous["binding_revision"])
        return None

    def bind(self, actor, key, data: MaterialBindingInput):
        previous = self.replay(actor, key, data)
        if previous:
            return previous
        request = data.model_dump(mode="json")
        self.require_scope(actor, data)
        scope = (
            f"plan:{data.plan_id}:{data.plan_revision}:{data.node_key or ''}"
            if data.plan_id
            else "goal"
        )
        self.connection.execute(
            "INSERT INTO learning.material_bindings(id,actor_id,goal_id,scope_key,purpose) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (uuid4(), actor.id, data.goal_id, scope, data.purpose),
        )
        head = self.connection.execute(
            "SELECT id,revision FROM learning.material_bindings WHERE actor_id=%s AND goal_id=%s "
            "AND scope_key=%s AND purpose=%s FOR UPDATE",
            (actor.id, data.goal_id, scope, data.purpose),
        ).fetchone()
        if head["revision"] != data.expected_binding_revision:
            raise BusinessError("stale_version", "Material binding changed; read it again.")
        now = datetime.now(UTC)
        revision = head["revision"] + 1
        self.connection.execute(
            "INSERT INTO learning.material_binding_revisions"
            "(binding_id,revision,plan_id,plan_revision,node_key,refs,expected_completion_at,"
            "review_due_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                head["id"],
                revision,
                data.plan_id,
                data.plan_revision,
                data.node_key,
                Jsonb([ref.model_dump(mode="json") for ref in data.refs]),
                data.expected_completion_at,
                review_due_at(
                    now,
                    data.expected_completion_at,
                    review_days=self.review_days,
                    grace_days=self.grace_days,
                ),
            ),
        )
        self.connection.execute(
            "UPDATE learning.material_bindings SET revision=%s WHERE id=%s",
            (revision, head["id"]),
        )
        self.connection.execute(
            "INSERT INTO learning.material_binding_commands"
            "(actor_id,command_key,request,binding_id,binding_revision) VALUES (%s,%s,%s,%s,%s)",
            (actor.id, key, Jsonb(request), head["id"], revision),
        )
        return self.get(actor, head["id"], revision)
