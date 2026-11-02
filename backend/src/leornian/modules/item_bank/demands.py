from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.modules.item_bank.demand_contracts import SupplyDemand
from leornian.modules.item_bank.supply import Packs
from leornian.shared_kernel.errors import BusinessError


class Demands:
    def __init__(self, connection):
        self.connection = connection

    def row(self, actor, demand_id):
        row = self.connection.execute(
            "SELECT * FROM item_bank.supply_demands WHERE actor_id=%s AND id=%s",
            (actor.id, demand_id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Supply demand not found.")
        return row

    def previous(self, actor, key):
        return self.connection.execute(
            "SELECT * FROM item_bank.supply_demands WHERE actor_id=%s AND idempotency_key=%s",
            (actor.id, key),
        ).fetchone()

    def create(self, actor, remediation_id, pack, key, data, difficulties, context):
        origin = "python_remediation_id" if pack["kind"] == "python_io" else "remediation_id"
        if self.connection.execute(
            f"SELECT 1 FROM item_bank.supply_demands WHERE actor_id=%s AND {origin}=%s",
            (actor.id, remediation_id),
        ).fetchone():
            raise BusinessError(
                "precondition_failed", "Continue the existing bounded supply chain."
            )
        demand_id = uuid4()
        self.connection.execute(
            "INSERT INTO item_bank.supply_demands(id,actor_id,remediation_id,"
            "python_remediation_id,kind,source_pack_id,"
            "plan_revision,idempotency_key,instruction,allowed_difficulties,context_data) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                demand_id,
                actor.id,
                remediation_id if pack["kind"] == "choice" else None,
                remediation_id if pack["kind"] == "python_io" else None,
                pack["kind"],
                pack["id"],
                data.expected_plan_revision,
                key,
                data.instruction,
                Jsonb(sorted(difficulties)),
                Jsonb(context),
            ),
        )
        return self.row(actor, demand_id)

    def latest(self, actor, demand_id):
        row = self.connection.execute(
            "SELECT id FROM item_bank.packs WHERE actor_id=%s AND supply_demand_id=%s "
            "ORDER BY revision DESC LIMIT 1",
            (actor.id, demand_id),
        ).fetchone()
        if not row:
            raise BusinessError("precondition_failed", "Supply has not been scheduled.")
        return Packs(self.connection).row(actor, row["id"])

    def summary(self, actor, demand_id):
        row = self.row(actor, demand_id)
        return SupplyDemand(
            **{
                key: row[key]
                for key in (
                    "id",
                    "remediation_id",
                    "python_remediation_id",
                    "kind",
                    "source_pack_id",
                    "plan_revision",
                    "allowed_difficulties",
                    "created_at",
                )
            },
            pack=Packs(self.connection).summary(actor, self.latest(actor, demand_id)["id"]),
        )

    def list(self, actor):
        rows = self.connection.execute(
            "SELECT id FROM item_bank.supply_demands WHERE actor_id=%s "
            "ORDER BY created_at DESC,id LIMIT 100",
            (actor.id,),
        ).fetchall()
        return [self.summary(actor, row["id"]) for row in rows]
