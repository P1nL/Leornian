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
export type DeliveryTask = components["schemas"]["DeliveryTask"];
export type TeachingFocus = components["schemas"]["TeachingFocus"];
export type Turn = components["schemas"]["Turn"];
export type ArtifactView = components["schemas"]["ArtifactView"];
export type ArtifactJob = components["schemas"]["ArtifactJob"];
export type ModelAvailability = components["schemas"]["ModelAvailability"];
export type ModelConfiguration = components["schemas"]["ModelConfiguration"];
export type ModelConnection = components["schemas"]["ModelConnection"];
export type ModelProfile = components["schemas"]["ModelProfile"];
export type ModelProfileInput = components["schemas"]["ModelProfileInput"];
export type ModelConnectionTest = components["schemas"]["ModelConnectionTest"];
export type Track = components["schemas"]["Track"];
export type Attempt = components["schemas"]["Attempt"];
export type LessonView = components["schemas"]["LessonView"];
export type Source = components["schemas"]["Source"];
export type MaterialDemand = components["schemas"]["MaterialDemand"];
export type MaterialJob = components["schemas"]["MaterialJob"];
export type MaterialUpload = components["schemas"]["MaterialUpload"];
export type ReviewCard = components["schemas"]["ReviewCard"];
export type LearningPlan = components["schemas"]["LearningPlan"];
export type PlanRevision = components["schemas"]["PlanRevision"];
export type GeneratedLesson = components["schemas"]["GeneratedLesson"];
export type PackSummary = components["schemas"]["PackSummary"];
export type PackAccepted = components["schemas"]["PackAccepted"];
export type PracticeSet = components["schemas"]["PracticeSet"];
export type ChoiceResult = components["schemas"]["ChoiceResult"];
export type PublicQuestion = components["schemas"]["PublicQuestion"];
export type Remediation = components["schemas"]["Remediation"];
export type GateSummary = components["schemas"]["GateSummary"];
export type GateView = components["schemas"]["GateView"];
export type NodeProgress = components["schemas"]["NodeProgress"];
export type TransferSummary = components["schemas"]["TransferSummary"];
export type TransferView = components["schemas"]["TransferView"];
export type SupplyDemand = components["schemas"]["SupplyDemand"];
export type Evaluation = components["schemas"]["Evaluation"];
export type PythonQuestion = components["schemas"]["PythonQuestion"];
export type PythonAttempt = components["schemas"]["PythonAttempt"];
export type ExecutionProgress = components["schemas"]["ExecutionProgress"];

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
    if (error.code === "model_unavailable") return "请检查当前身份的模型连接、职责映射、启用状态和材料外发授权；系统不会借用开发或其他用户的密钥。";
    if (error.code.startsWith("material_")) return "材料尚未接收完成：请检查文件格式、大小和用途；相同提交不会重复创建任务。";
    if (error.code === "run_active") return "当前回合尚未结束，请先等待、承接已有回执或取消。";
    if (error.code === "unknown_unresolved") return "仍没有完整回执，不会重新发送这次模型调用。";
    if (error.code === "resume_not_allowed") return "当前状态不允许续行，请重新同步服务端状态。";
    if (error.code === "stale_version") return "当前计划、来源版本或执行租约已变化，请同步后再操作。";
    if (error.code === "precondition_failed") return "当前条件尚未满足：请检查计划版本、练习与补救、活动考核或复习状态。";
    if (error.code === "source_not_current") return "来源已过期、撤销或改版。请检查当前版本及有效期，再发起新的教学回合。";
    if (error.code === "invalid_plan_output") return "模型返回的计划不符合节点、依赖或来源合同，草案未保存。原始回执已保留，请修改要求后发起新请求。";
    if (error.code === "invalid_lesson_output") return "课时正文或来源引用不符合合同，未保存正文。回执已保留，请同步后检查资料与生成要求。";
    if (error.code === "invalid_item_output") return "题目或审核结果不符合合同，本版未发布。回执已保存，请检查资料和修订要求。";
    if (error.code === "invalid_gate_output") return "考核关系报告缺项或格式不合格，题目未开放。回执已保留，请检查当前考核状态。";
    if (error.code === "assessment_not_independent") return "相同材料已未通过独立性检查，不会重复审核刷过。请修订题包，或在教学与实际曝光变化后重新检查。";
    if (error.code === "no_transfer_candidate") return "没有符合条件的新情境题。请先生成并审核同一节点的新题包；旧题和作答不会重置。";
    if (error.code === "invalid_transfer_output") return "新情境关系报告缺项或不合格，未开放题目。回执已保留，不会自动重审。";
    if (error.status === 422) return "请检查输入长度、HTTPS 来源链接和必填内容。";
  }
  return "暂时无法连接服务。请检查本地服务后重试；重试不会重复保存目标。";
}
