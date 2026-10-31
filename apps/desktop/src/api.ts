import type { components } from "@leornian/api-contracts";

export type Actor = components["schemas"]["Actor"];
export type Session = components["schemas"]["Session"];
export type Snapshot = components["schemas"]["Snapshot"];
export type GoalInput = components["schemas"]["GoalInput"];
export type Accepted = components["schemas"]["Accepted"];
export type Job = components["schemas"]["Job"];
export type PublicEvent = components["schemas"]["PublicEvent"];
export type Conversation = components["schemas"]["Conversation"];
export type TurnAccepted = components["schemas"]["TurnAccepted"];
export type Run = components["schemas"]["Run"];
export type ModelAvailability = components["schemas"]["ModelAvailability"];
export type Track = components["schemas"]["Track"];
export type Attempt = components["schemas"]["Attempt"];
export type LessonView = components["schemas"]["LessonView"];
export type Source = components["schemas"]["Source"];
export type ReviewCard = components["schemas"]["ReviewCard"];
export type LearningPlan = components["schemas"]["LearningPlan"];
export type PlanRevision = components["schemas"]["PlanRevision"];
export type GeneratedLesson = components["schemas"]["GeneratedLesson"];

export const apiBase = import.meta.env.VITE_API_BASE_URL ?? (
  typeof window !== "undefined" && window.location.protocol === "http:" && window.location.port === "5178"
    ? "" : "http://127.0.0.1:8088"
);

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
  }
}

export async function request<T>(
  path: string, token?: string, init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.code ?? "request_failed", body.message ?? "请求未完成");
  }
  return response.json() as Promise<T>;
}

export function explain(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "本地会话已失效，请重新进入。旧目标仍保存在原身份下。";
    if (error.code === "idempotency_conflict") return "这次提交的内容已改变，请发起新的提交。";
    if (error.code === "model_unavailable") return "尚未配置并启用 Leornian 的独立模型，未发送教学请求。";
    if (error.code === "run_active") return "当前回合尚未结束，请先等待、承接已有回执或取消。";
    if (error.code === "unknown_unresolved") return "仍没有完整回执，不会重新发送这次模型调用。";
    if (error.code === "resume_not_allowed") return "当前状态不允许续行，请重新同步服务端状态。";
    if (error.code === "stale_version") return "当前计划、来源版本或执行租约已变化，请同步后再操作。";
    if (error.code === "precondition_failed") return "当前条件尚未满足：请确认计划，或检查复习是否到期、是否已暂停。";
    if (error.code === "source_not_current") return "来源已过期、撤销或改版。请检查当前版本及有效期，再发起新的教学回合。";
    if (error.code === "invalid_plan_output") return "模型返回的计划不符合节点、依赖或来源合同，草案未保存。原始回执已保留，请修改要求后发起新请求。";
    if (error.code === "invalid_lesson_output") return "课时正文或来源引用不符合合同，未保存正文。回执已保留，请同步后检查资料与生成要求。";
    if (error.status === 422) return "请检查输入长度、HTTPS 来源链接和必填内容。";
  }
  return "暂时无法连接服务。请检查本地服务后重试；重试不会重复保存目标。";
}
