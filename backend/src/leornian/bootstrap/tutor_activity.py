"""Project committed model/tool activity without private protocol or review content."""

from datetime import UTC, datetime, timedelta

from leornian.delivery.contracts import EventPayload
from leornian.delivery.events import Events
from leornian.modules.tutor.thinking_contracts import ThinkingStep

_PUBLIC_ROLES = {"tutor.v1", "planner.v1"}
_PHASES = {
    "tutor.v1": "结合当前节点与学习上下文，整理讲解思路。",
    "planner.v1": "整理学习目标与要求，规划有序路线。",
    "delivery_review.v1": "检查内容、引用与学习目标要求。",
}
_TOOL_TITLES = {
    "learning_get_context": "读取学习上下文",
    "list_artifacts": "查找学习文档",
    "read_artifact": "读取学习文档",
    "get_learning_component_contracts": "读取组件说明",
    "get_execution_environments": "读取课程环境",
    "request_execution_environment": "提交环境准备需求",
    "lookup_public_teaching_fact": "核对当前问题的公开资料",
}
_OUTCOMES = {
    "completed": "操作已完成。",
    "accepted": "任务已排队，等待后台处理。",
    "waiting_dependency": "等待依赖准备。",
    "rejected": "操作未通过校验。",
    "conflict": "当前版本已变化，需要重新核对。",
    "unknown": "操作结果未知。",
}


class TutorActivity:
    @classmethod
    def material_wait(cls, connection, row, demand_id, *, completed=False):
        from uuid import uuid5

        now = datetime.now(UTC)
        step_id = uuid5(row["input_ref"], f"material-wait:{demand_id}")
        previous = Events(connection).thinking_step(row["actor_id"], step_id)
        if previous and previous.status == ("completed" if completed else "waiting"):
            return
        cls.publish(connection, row, ThinkingStep(
            id=step_id, kind="tool", title="等待RAG解析",
            summary="所需资料已准备完成。" if completed else "正在等待本次计划所需的资料准备完成。",
            detail="复用已完成资料，仅处理本次需求的证据缺口。",
            status="completed" if completed else "waiting",
            started_at=previous.started_at if previous else now,
            completed_at=now if completed else None,
            tool_name="material_preparation",
        ))

    @staticmethod
    def publish(connection, row, step, **payload):
        Events(connection).append(
            row["actor_id"], "tutor.thinking", row["id"],
            EventPayload(
                run_id=row["id"], conversation_id=row["scope_id"], turn_id=row["input_ref"],
                thinking_step=step, **payload,
            ),
        )

    @classmethod
    def model(cls, connection, row, call, *, text=None, phase=None, status=None):
        stage = call.policy_snapshot.get("stage", row["policy_version"])
        if row["policy_version"] not in _PUBLIC_ROLES or stage not in _PHASES:
            return
        events = Events(connection)
        now = datetime.now(UTC)
        step = events.thinking_step(row["actor_id"], call.id) or ThinkingStep(
            id=call.id, kind="review" if stage == "delivery_review.v1" else "thinking",
            title="检查回复" if stage == "delivery_review.v1" else "思考",
            summary=_PHASES[stage], status="running", started_at=now,
        )
        update, payload = {}, {}
        if text and stage in _PUBLIC_ROLES:
            detail = step.detail + text
            update.update(detail=detail, summary=detail.strip().splitlines()[0][:160])
            payload["thinking_text"] = detail
        elif phase:
            summary = (
                "正在组织回复，随后检查内容。"
                if phase == "composing" and stage in _PUBLIC_ROLES else _PHASES[stage]
            )
            if not step.detail:
                update["summary"] = summary
            payload["thinking_summary"] = summary
        if stage == "delivery_review.v1":
            update["detail"] = "检查内容、引用与目标要求；通过检查后才交付正文。"
        if status:
            update.update(
                status=status, completed_at=now,
                duration_ms=max(0, int((now - step.started_at).total_seconds() * 1000)),
            )
        cls.publish(connection, row, step.model_copy(update=update), **payload)

    @classmethod
    def finish(cls, connection, row, status, reason=None):
        if row["policy_version"] not in _PUBLIC_ROLES:
            return
        now = datetime.now(UTC)
        steps = Events(connection).thinking_steps(
            row["actor_id"], [row["input_ref"]],
        ).get(str(row["input_ref"]), [])
        for step in steps:
            stalled = reason == "delivery_protocol_stalled" and step.id == steps[-1].id
            if step.status != "running" and not stalled and not (
                status == "cancelled" and step.status == "waiting"
            ):
                continue
            cls.publish(connection, row, step.model_copy(update={
                "status": {"blocked_unknown": "unknown", "succeeded": "completed"}.get(
                    status, status,
                ),
                "completed_at": now,
                "duration_ms": max(0, int((now - step.started_at).total_seconds() * 1000)),
                **({
                    "summary": "检查修复没有取得新进展，已暂停。",
                    "detail": "原候选和检查结论已保留。可在后台任务中核对并恢复原任务。",
                } if stalled else {}),
            }))

    @classmethod
    def tool(cls, connection, row, activity_id, tool, result, duration_ms):
        if row["policy_version"] not in _PUBLIC_ROLES:
            return
        name = tool.name
        title = _TOOL_TITLES.get(name)
        if not title:
            title = (
                "查找可用练习" if name.startswith("list_") else
                "准备互动内容" if name.startswith("prepare_") else
                "提交准备任务" if name.startswith("request_") else "读取任务状态"
            )
        outcome = result.get("status", "completed")
        summary = _OUTCOMES.get(outcome, "操作已返回。")
        if name == "lookup_public_teaching_fact" and outcome == "completed":
            summary = (f"找到 {len(result['sources'])} 条相关来源。" if result["sources"]
                       else "没有可用的公开来源，继续本轮讲解。")
        detail = [f"工具：`{name}`", summary]
        # Only public identifiers/counts: never copy preparation bodies, hints or tool JSON.
        arguments = tool.arguments if (
            outcome in {"completed", "accepted"} and isinstance(tool.arguments, dict)
        ) else {}
        for key, label in (
            ("artifact_id", "文档标识"), ("revision", "文档版本"),
            ("offset", "读取起点"), ("limit", "本次读取上限"),
        ):
            if key in arguments:
                detail.append(f"{label}：{arguments[key]}")
        for key, label in (("items", "结果"), ("sections", "文档章节"), ("components", "组件说明")):
            if isinstance(result.get(key), list):
                detail.append(f"{label}数量：{len(result[key])}")
        if name == "learning_get_context":
            detail.append("已读取当前获准的学习上下文。")
        if (
            outcome in {"rejected", "conflict", "waiting_dependency", "unknown"}
            and result.get("code")
        ):
            detail.append(f"状态代码：`{result['code']}`")
        now = datetime.now(UTC)
        cls.publish(connection, row, ThinkingStep(
            id=activity_id, kind="tool", title=title, summary=summary,
            detail="\n\n".join(detail), tool_name=name,
            status={
                "rejected": "failed", "conflict": "failed",
                "waiting_dependency": "waiting", "unknown": "unknown",
            }.get(outcome, "completed"),
            started_at=now - timedelta(milliseconds=duration_ms),
            completed_at=now, duration_ms=duration_ms,
        ))
