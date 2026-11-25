"""Read-only receipt provenance, without retained question or material bodies."""

from leornian.shared_kernel.errors import BusinessError


class EvidenceContext:
    def __init__(self, connection):
        self.connection = connection

    def for_pack(self, actor, pack_id):
        row = self.connection.execute(
            "SELECT id,revision,plan_id,plan_revision,node_key,sources,material_context "
            "FROM item_bank.packs WHERE id=%s AND actor_id=%s",
            (pack_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Evidence item pack not found.")
        material_versions = [
            {"source_id": source["source_id"], "revision": source["revision"]}
            for source in row["sources"]
        ]
        context = row["material_context"] or {}
        material_versions += [
            {
                "binding_id": citation["binding_id"],
                "binding_revision": citation["binding_revision"],
                "purpose": citation["purpose"], **citation["ref"],
            }
            for citation in context.get("origin_citations") or context.get("author_citations", [])
        ]
        return {
            "plan_id": row["plan_id"], "plan_revision": row["plan_revision"],
            "node_key": row["node_key"], "item_version": f"{pack_id}:{row['revision']}",
            "material_versions": material_versions,
        }

    def exposure_before(self, actor, pack_id, slot, occurred_at):
        return [
            {**row, "exposed_at": row["exposed_at"].isoformat()}
            for row in self.connection.execute(
                "SELECT kind,receipt_key,exposed_at FROM item_bank.exposure_facts "
                "WHERE actor_id=%s AND pack_id=%s AND (%s::text IS NULL OR slot=%s) "
                "AND exposed_at<%s ORDER BY exposed_at,kind,receipt_key",
                (actor.id, pack_id, slot, slot, occurred_at),
            ).fetchall()
        ]
