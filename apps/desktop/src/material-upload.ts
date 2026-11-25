import { request } from "./api";
import type { MaterialDemand, MaterialJob, MaterialUpload } from "./api";

export const fileFormats = ["text", "markdown", "html", "pdf"] as const;
export type FileFormat = typeof fileFormats[number];

export function fileFormat(name: string): FileFormat | null {
  const extension = name.split(".").pop()?.toLowerCase();
  if (extension === "pdf") return "pdf";
  if (extension === "html" || extension === "htm") return "html";
  if (extension === "md" || extension === "markdown") return "markdown";
  if (extension === "txt") return "text";
  return null;
}

export function fileLimit(size: number, format: FileFormat | null): string {
  if (!format) return "请选择 TXT、Markdown、HTML 或 PDF 文件。";
  if (size === 0) return "文件为空，请选择有正文的材料。";
  if (size > (format === "pdf" ? 20_000_000 : 2_000_000))
    return format === "pdf" ? "PDF 超过 20 MB，请按章节拆分。" : "文本或 HTML 超过 2 MB，请拆分。";
  return "";
}

export function materialStatus(job: MaterialJob): string {
  if (job.state === "cancelled") return job.reason_code === "material_retention_expired"
    ? "保留期限已到，处理已停止" : "已取消";
  if (job.state === "queued") return "等待解析";
  if (job.state === "parsing") return "正在提取正文";
  if (job.reason_code === "ocr_configuration_required") return "等待 OCR 模型配置与材料外发授权";
  if (job.reason_code === "ocr_pipeline_pending") return "部分页面需要 OCR，等待识别处理";
  if (job.reason_code === "indexing_pending") return "正文已提取，等待索引与覆盖验证";
  if (job.reason_code === "material_quality_review_pending") return "正文已保留，等待质量检查";
  if (["material_text_limit", "material_pdf_limit", "material_page_limit", "material_block_limit",
    "material_parser_limit", "material_parser_timeout"].includes(job.reason_code ?? ""))
    return "材料超出处理容量，需拆分或换用较小章节";
  if (job.reason_code === "material_encoding_required") return "文本编码暂不支持，需要 UTF-8 原文";
  if (job.reason_code === "material_encrypted") return "PDF 已加密，需提供有权使用的未加密原文";
  if (job.reason_code === "unauthorized") return "发起会话已失效，处理已停止";
  if (job.reason_code === "source_not_current") return "用途许可或保留条件已变化";
  return "等待材料处理依赖";
}

export type UploadDetails = {
  goalId: string; title: string; language: string; topics: string[];
  sourceUrl: string; useUntil: string | null; retainUntil: string | null;
};
export type UploadKeys = { demand: string; upload: string; job: string };

export function mergeMaterialJobs(previous: MaterialJob[], incoming: MaterialJob[]): MaterialJob[] {
  const latest = new Map(previous.map((job) => [job.id, job]));
  for (const job of incoming) {
    if ((latest.get(job.id)?.revision ?? 0) <= job.revision) latest.set(job.id, job);
  }
  return [...latest.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)
    || b.id.localeCompare(a.id));
}

export async function prepareFile(
  token: string, bytes: ArrayBuffer, format: FileFormat, digest: string,
  details: UploadDetails, keys: UploadKeys, signal: AbortSignal, progress: (step: string) => void,
): Promise<{ demand: MaterialDemand; job: MaterialJob }> {
  const send = <T>(path: string, key: string, body: unknown) => request<T>(path, token, {
    method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(body), signal,
  });
  progress("正在登记材料用途");
  const demand = await send<MaterialDemand>("/v1/material-demands", keys.demand, {
    goal_id: details.goalId, purpose: "teaching", language: details.language,
    required_facets: details.topics, optional_facets: [],
  });
  const upload = await send<MaterialUpload>(`/v1/material-demands/${demand.id}/uploads`, keys.upload, {
    expected_demand_revision: demand.revision, content_digest: digest, byte_size: bytes.byteLength,
    material: {
      goal_id: details.goalId, title: details.title, format, source_url: details.sourceUrl || null,
      authorized_use: true, purposes: ["reference", "teaching", "indexing"],
      use_until: details.useUntil, retain_until: details.retainUntil,
    },
  });
  progress("正在上传原文件");
  await request<MaterialUpload>(`/v1/material-uploads/${upload.id}/content`, token, {
    method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: bytes, signal,
  });
  progress("正在交给后台解析");
  const job = await send<MaterialJob>(`/v1/material-demands/${demand.id}/files`, keys.job, {
    expected_demand_revision: demand.revision, upload_id: upload.id,
  });
  return { demand, job };
}
