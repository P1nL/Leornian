from psycopg.types.json import Jsonb

from leornian.shared_kernel.errors import BusinessError


class SupplyTasks:
    """One durable generation goal across immutable versions; not another execution engine."""

    def __init__(self, connection):
        self.connection = connection

    def for_pack(self, actor, pack_id, *, lock=False):
        return self.connection.execute(
            "SELECT t.* FROM item_bank.supply_tasks t JOIN item_bank.packs p "
            "ON p.supply_task_id=t.id WHERE p.id=%s AND t.actor_id=%s"
            + (" FOR SHARE OF t" if lock else ""),
            (pack_id, actor.id),
        ).fetchone()

    def require_current(self, actor, pack_id):
        task = self.for_pack(actor, pack_id, lock=True)
        if task and task["status"] == "cancelled":
            raise BusinessError("supply_cancelled", "The whole supply task was cancelled.")
        return task

    def lock(self, actor, task_id):
        return self.connection.execute(
            "SELECT * FROM item_bank.supply_tasks WHERE id=%s AND actor_id=%s FOR UPDATE",
            (task_id, actor.id),
        ).fetchone()

    def for_transfer(self, actor, transfer_id, *, lock=False):
        task = self.connection.execute(
            "SELECT * FROM item_bank.supply_tasks WHERE actor_id=%s AND transfer_id=%s"
            + (" FOR SHARE" if lock else ""),
            (actor.id, transfer_id),
        ).fetchone()
        if task and task["status"] == "cancelled":
            raise BusinessError("supply_cancelled", "The supply task was cancelled.")
        return task

    def attach(self, actor, pack_id, digest, parent=None):
        if parent:
            task = self.require_current(actor, parent["id"])
            task_id = task["id"]
            self.connection.execute(
                "UPDATE item_bank.supply_tasks SET head_pack_id=%s,session_digest=%s,"
                "status='running',action='generate',reason=NULL,transfer_id=NULL,"
                "next_action_at=now() WHERE id=%s",
                (pack_id, digest, task_id),
            )
        else:
            task_id = pack_id
            self.connection.execute(
                "INSERT INTO item_bank.supply_tasks"
                "(id,actor_id,root_pack_id,head_pack_id,session_digest) VALUES(%s,%s,%s,%s,%s)",
                (task_id, actor.id, pack_id, pack_id, digest),
            )
        self.connection.execute(
            "UPDATE item_bank.packs SET supply_task_id=%s WHERE id=%s", (task_id, pack_id)
        )
        return task_id

    def candidates(self, limit=20, pack_id=None):
        return self.connection.execute(
            "SELECT t.*,t.head_pack_id AS pack_id FROM item_bank.supply_tasks t "
            "JOIN item_bank.packs p ON p.supply_task_id=t.id "
            "WHERE t.status<>'cancelled' AND (%s::uuid IS NULL OR p.id=%s) "
            "AND (%s::uuid IS NOT NULL OR t.next_action_at<=now()) "
            "GROUP BY t.id ORDER BY t.checked_at,t.id LIMIT %s",
            (pack_id, pack_id, pack_id, limit),
        ).fetchall()

    def update(self, task_id, status, action, reason=None, *, delay=0):
        changed = self.connection.execute(
            "UPDATE item_bank.supply_tasks SET status=%s,action=%s,reason=%s,"
            "checked_at=now(),next_action_at=now()+make_interval(secs=>%s) "
            "WHERE id=%s AND status<>'cancelled' RETURNING head_pack_id",
            (status, action, reason, delay, task_id),
        ).fetchone()
        return changed

    def remember_failure(self, task, findings):
        strategy = "redesign_decisions" if task["last_failure"] == findings else "targeted_revision"
        self.connection.execute(
            "UPDATE item_bank.supply_tasks SET last_failure=%s,strategy=%s WHERE id=%s",
            (Jsonb(findings), strategy, task["id"]),
        )
        return strategy

    def bind_transfer(self, task_id, transfer_id):
        self.connection.execute(
            "UPDATE item_bank.supply_tasks SET transfer_id=%s WHERE id=%s", (transfer_id, task_id)
        )

    def cancel(self, actor, pack_id):
        # No Run lock while holding this lock: Runtime checks run -> task. Cleanup follows commit.
        task = self.connection.execute(
            "UPDATE item_bank.supply_tasks t SET status='cancelled',action='cancelled',"
            "reason=NULL,cancelled_at=COALESCE(cancelled_at,now()) "
            "FROM item_bank.packs p WHERE p.id=%s AND p.supply_task_id=t.id "
            "AND t.actor_id=%s RETURNING t.*",
            (pack_id, actor.id),
        ).fetchone()
        if task:
            self.connection.execute(
                "UPDATE item_bank.packs SET status='cancelled' WHERE supply_task_id=%s "
                "AND status NOT IN ('published','cancelled')",
                (task["id"],),
            )
        return task

    def pack_ids(self, task_id):
        return [
            row["id"]
            for row in self.connection.execute(
                "SELECT id FROM item_bank.packs WHERE supply_task_id=%s ORDER BY revision",
                (task_id,),
            ).fetchall()
        ]
