from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.knowledge.contracts import (
    MaterialUpdateDependency,
    MaterialUpdateImpact,
)
from leornian.modules.learning.material_contracts import MaterialBindingInput
from leornian.modules.learning.material_update_contracts import MaterialUpdateDecision
from leornian.modules.learning.materials import MaterialBindings
from leornian.shared_kernel.errors import BusinessError


def references_material(value, refs):
    if isinstance(value, dict):
        ref = value.get("ref", value)
        if isinstance(ref, dict):
            span = ref.get("span", {})
            if any(
                ref.get("document_id") == str(r.document_id)
                and ref.get("document_revision") == r.document_revision
                and ref.get("block_id") == str(r.block_id)
                and isinstance(span.get("start"), int)
                and isinstance(span.get("end"), int)
                and span["start"] < r.span.end and r.span.start < span["end"]
                for r in refs
            ):
                return True
        return any(references_material(v, refs) for v in value.values())
    if isinstance(value, list):
        return any(references_material(v, refs) for v in value)
    return False


class MaterialUpdateDecisions:
    """Learning owns explicit decisions, immutable successors and dependency markers."""

    def __init__(self, connection):
        self.connection = connection

    def impact(self, actor, binding, document_id=None):
        dependencies = []
        refs = [
            r for r in binding.refs if document_id is None or r.document_id == document_id
        ]
        plans = self.connection.execute(
            "SELECT v.plan_id,v.revision,v.document FROM learning.plan_revisions v "
            "JOIN learning.plans p ON p.id=v.plan_id WHERE p.actor_id=%s AND p.goal_id=%s",
            (actor.id, binding.goal_id),
        ).fetchall()
        for row in plans:
            if references_material(row["document"], refs):
                dependencies.append(MaterialUpdateDependency(
                    kind="plan", id=row["plan_id"], revision=row["revision"],
                    plan_id=row["plan_id"], plan_revision=row["revision"],
                ))
        lessons = self.connection.execute(
            "SELECT d.id,r.plan_id,r.plan_revision,r.node_key,d.document "
            "FROM learning.lesson_documents d "
            "JOIN learning.lesson_requests r ON r.id=d.request_id "
            "JOIN learning.plans p ON p.id=r.plan_id WHERE r.actor_id=%s AND p.goal_id=%s",
            (actor.id, binding.goal_id),
        ).fetchall()
        for row in lessons:
            if references_material(row["document"], refs):
                dependencies.append(MaterialUpdateDependency(
                    kind="lesson", id=row["id"], plan_id=row["plan_id"],
                    plan_revision=row["plan_revision"],
                    node_key=row["node_key"],
                ))
        return MaterialUpdateImpact(dependencies=dependencies)

    def public(self, row):
        marker = self.connection.execute(
            "SELECT dependencies FROM learning.material_update_migrations WHERE decision_id=%s",
            (row["id"],),
        ).fetchone()
        return MaterialUpdateDecision(
            **{key: row[key] for key in MaterialUpdateDecision.model_fields
               if key != "requires_reprepare"},
            requires_reprepare=marker["dependencies"] if marker else [],
        )

    def replay(self, actor, offer_id, key, data):
        request = {"offer_id": str(offer_id), **data.model_dump(mode="json")}
        row = self.connection.execute(
            "SELECT * FROM learning.material_update_decisions WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if row:
            if row["request"] != request:
                raise BusinessError("idempotency_conflict", "Update decision key changed.")
            return self.public(row)
        return None

    def get(self, actor, offer_id, key):
        row = self.connection.execute(
            "SELECT * FROM learning.material_update_decisions "
            "WHERE actor_id=%s AND offer_id=%s AND command_key=%s",
            (actor.id, offer_id, key),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Material update decision not found.")
        return self.public(row)

    def decide(self, actor, offer, binding, key, data, successor_refs):
        final = self.connection.execute(
            "SELECT 1 FROM learning.material_update_decisions WHERE actor_id=%s AND offer_id=%s "
            "AND decision IN ('accept_update','keep_current_for_track')",
            (actor.id, offer.id),
        ).fetchone()
        if final:
            raise BusinessError("stale_version", "This update already has a final decision.")
        if (
            data.expected_offer_revision != offer.revision
            or data.expected_binding_revision != binding.revision
            or binding.revision != offer.binding_revision
        ):
            raise BusinessError("stale_version", "Update offer or binding changed.")
        decision_id = uuid4()
        successor = None
        impact = self.impact(actor, binding, offer.document_id)
        if data.decision == "accept_update":
            if impact != offer.impact:
                raise BusinessError("stale_version", "Update dependencies changed.")
            successor = MaterialBindings(self.connection).bind(
                actor, "material-update:" + str(decision_id),
                MaterialBindingInput(
                    goal_id=binding.goal_id, purpose=binding.purpose, plan_id=binding.plan_id,
                    plan_revision=binding.plan_revision, node_key=binding.node_key,
                    expected_binding_revision=binding.revision, refs=successor_refs,
                    expected_completion_at=binding.expected_completion_at,
                ),
            )
        self.connection.execute(
            "INSERT INTO learning.material_update_decisions"
            "(id,actor_id,offer_id,command_key,request,decision,binding_id,binding_revision,"
            "successor_binding_id,successor_binding_revision) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                decision_id, actor.id, offer.id, key,
                Jsonb({"offer_id": str(offer.id), **data.model_dump(mode="json")}),
                data.decision, binding.id, binding.revision,
                successor.id if successor else None, successor.revision if successor else None,
            ),
        )
        if successor and impact.dependencies:
            self.connection.execute(
                "INSERT INTO learning.material_update_migrations(decision_id,state,dependencies) "
                "VALUES (%s,'requires_reprepare',%s)",
                (
                    decision_id,
                    Jsonb([d.model_dump(mode="json") for d in impact.dependencies]),
                ),
            )
        row = self.connection.execute(
            "SELECT * FROM learning.material_update_decisions WHERE id=%s", (decision_id,),
        ).fetchone()
        return self.public(row)
