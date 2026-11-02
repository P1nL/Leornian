import type { PackSummary } from "./api";

export function displayedPack(versions: PackSummary[], selectedId: string, followLatest: boolean) {
  let pack = versions.find((item) => item.id === selectedId) ?? versions[0];
  if (!followLatest) return pack;
  while (pack?.automatic) {
    const child = versions.find((item) => item.predecessor_id === pack.id);
    if (!child) break;
    pack = child;
  }
  return pack;
}

export function supplyStatus(pack: PackSummary): string {
  const reasons: Record<string, string> = {
    unauthorized: "等待更新当前会话授权",
    source_not_current: "等待更新有效来源",
    stale_version: "等待处理计划或教学上下文变化",
    model_unavailable: "等待模型配置恢复",
    provider_rejected: "等待处理模型服务拒绝",
    external_result_unknown: "等待确认已有调用结果，不重复发送",
    no_transfer_candidate: "正在准备新的合格后继",
  };
  const actions: Record<string, string> = {
    generate: "正在生成或独立验证",
    recover: "正在恢复供给",
    repair_output: "正在修复已知输出问题",
    review: "正在完成六角色审核",
    qualify: "正在隔离验证盲解程序",
    check_transfer: "正在检查可分配后继",
    yield_foreground: "等待当前用户回合结束后继续",
    yield_exam: "等待当前考核结束后继续",
    await_receipt: "等待确认已有调用结果，不重复发送",
    published: "已合格发布",
    deliverable: "合格后继已准备好，等待你打开作答",
  };
  if (pack.automation_status === "cancelled") return "本次供给已取消，历史记录保留";
  if (pack.automation_status === "completed") {
    return actions[pack.automation_action ?? ""] ?? "本次供给已完成";
  }
  if (pack.automation_reason) return reasons[pack.automation_reason] ?? `等待恢复：${pack.automation_reason}`;
  return actions[pack.automation_action ?? ""] ?? "系统将持续修复到合格交付，不按版本次数停止";
}
