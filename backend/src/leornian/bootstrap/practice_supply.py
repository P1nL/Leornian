"""Teaching tool commands enqueue the original supply owner without starting a nested Run."""

from leornian.bootstrap.item_supply import ItemSupply
from leornian.modules.item_bank.supply import Packs
from leornian.modules.item_bank.supply_contracts import PackRequest
from leornian.modules.item_bank.tasks import SupplyTasks
from leornian.modules.knowledge.application import Knowledge
from leornian.modules.learning.planning import Plans
from leornian.shared_kernel.errors import BusinessError


class PracticeSupply:
    @staticmethod
    def require_scope(row, focus, tool):
        if row["tool_contracts"].get(tool) != 1:
            raise BusinessError("precondition_failed", "Run has no practice supply capability.")
        if focus.kind != "node":
            raise BusinessError(
                "precondition_failed", "Choose an exact confirmed node before requesting practice."
            )

    @staticmethod
    def require_kind(row, kind):
        required = (
            "prepare_learning_response_composition" if kind == "response"
            else "prepare_learning_program_composition"
            if kind in {
                "sql_query", "python_project", "project_stdio", "web_project", "http_project",
            }
            else "prepare_learning_practice_composition"
        )
        if row["tool_contracts"].get(required) != 1:
            raise BusinessError(
                "precondition_failed", "This Run cannot present that practice kind."
            )

    @staticmethod
    def request_in(
        connection, actor, conversation, row, focus, args,
        *, tool="request_learning_practice_supply",
    ):
        PracticeSupply.require_scope(row, focus, tool)
        PracticeSupply.require_kind(row, args.kind)
        plan = Plans(connection).get(actor, focus.plan_id)
        if plan.goal_id != conversation.goal_id:
            raise BusinessError("not_found", "Practice request is outside this conversation.")
        if not plan.active or plan.active.revision != focus.expected_plan_revision:
            raise BusinessError("stale_version", "Practice supply needs the exact confirmed plan.")
        node = next((n for n in plan.active.document.nodes if n.key == focus.node_key), None)
        if not node:
            raise BusinessError("source_not_current", "The requested node is not in the plan.")
        data = PackRequest(
            expected_plan_revision=focus.expected_plan_revision,
            node_key=focus.node_key,
            kind=args.kind,
            instruction=args.instruction,
            response_formats=getattr(args, "response_formats", None),
            program_environment=getattr(args, "program_environment", None),
            automatic=True,
        )
        packs = Packs(connection)
        pack, created = packs.request(
            actor, plan.id,
            f"teaching-supply:{row['input_ref']}:{args.command_key}",
            data, Knowledge(connection).current(actor, plan.goal_id, node.source_refs),
            session_digest=row["session_digest"],
            material_context=ItemSupply.prepare_material_context(connection, actor, plan, node),
        )
        ItemSupply.current(connection, actor, pack)
        task = SupplyTasks(connection).for_pack(actor, pack["id"])
        if created:
            SupplyTasks(connection).bind_origin(
                actor, task["id"], row["id"], row["model_configuration_scope"]
            )
            ItemSupply.event(connection, actor.id, pack["id"])
        return {
            "status": "accepted", "task_id": str(task["id"]), "pack_id": str(pack["id"]),
            "message": "Registered with the original supply task. It yields to this teaching "
            "turn, then uses author, public-only blind solve, six reviews and publication. "
            "Not a candidate or delivered interaction. Finish this turn; read task status "
            "later and list published candidates in the selecting Run.",
        }

    @staticmethod
    def status_in(
        connection, actor, row, focus, args, *, tool="get_learning_practice_supply",
    ):
        PracticeSupply.require_scope(row, focus, tool)
        tasks = SupplyTasks(connection)
        task = tasks.get(actor, args.task_id)
        if not task:
            raise BusinessError("not_found", "Practice supply task not found.")
        pack = Packs(connection).row(actor, task["head_pack_id"])
        if (pack["plan_id"], pack["plan_revision"], pack["node_key"]) != (
            focus.plan_id, focus.expected_plan_revision, focus.node_key
        ):
            raise BusinessError("not_found", "Practice supply belongs to another teaching scope.")
        PracticeSupply.require_kind(row, pack["kind"])
        reader = ("get_learning_program_supply" if pack["program_environment"] is not None
                  else "get_learning_practice_supply")
        if tool != reader:
            raise BusinessError(
                "precondition_failed",
                f"This task uses {reader}. If just queued, finish this reply; the task "
                "yields to this turn. Do not request it again.",
            )
        ready = pack["status"] == "published" and task["status"] != "cancelled"
        return {
            "status": "completed", "task_id": str(task["id"]), "pack_id": str(pack["id"]),
            "kind": pack["kind"], "supply_status": task["status"], "action": task["action"],
            "reason": task["reason"], "pack_status": pack["status"],
            "revision": pack["revision"], "response_formats": pack["response_formats"],
            **({"program_environment": pack["program_environment"]}
               if pack["program_environment"] else {}),
            "next_action": (
                "List published candidates in this Run, then prepare a checked composition."
                if ready else "Do not loop on status or create duplicate requests. Finish this "
                "turn and use the task panel. Cancellation is final; UNKNOWN never grants resend."
            ),
        }
