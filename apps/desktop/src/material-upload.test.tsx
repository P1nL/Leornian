import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MaterialUploadPanel } from "./MaterialUploadPanel";
import { fileFormat, fileLimit, materialStatus, mergeMaterialJobs, prepareFile } from "./material-upload";
import type { MaterialJob } from "./api";

const job: MaterialJob = {
  id: "job-1", root_id: "job-1", demand_id: "demand-1", demand_revision: 1, revision: 3,
  state: "waiting_dependency", phase: "indexing", reason_code: "indexing_pending", issues: [],
  document_id: "document-1", document_revision: 1, upload_id: "upload-1",
  title: "Unicode material", format: "html", steps: [],
  background_deferred: false,
  created_at: "2026-11-03T01:00:00Z", updated_at: "2026-11-03T01:01:00Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("教材文件准备", () => {
  it("只准入当前真实文件类型与大小，不按扩展名执行内容", () => {
    expect(fileFormat("Chapter.PDF")).toBe("pdf");
    expect(fileFormat("source.markdown")).toBe("markdown");
    expect(fileFormat("program.exe")).toBeNull();
    expect(fileLimit(0, "pdf")).toContain("为空");
    expect(fileLimit(20_000_001, "pdf")).toContain("20 MB");
    expect(fileLimit(2_000_001, "html")).toContain("2 MB");
    expect(fileLimit(2_000_000, "html")).toBe("");
  });

  it("缺配置和仅提取的结果不会显示为教材已就绪", () => {
    expect(materialStatus(job)).toBe("正文已提取，等待索引与覆盖验证");
    expect(materialStatus({ ...job, state: "waiting_config",
      reason_code: "ocr_configuration_required" })).toContain("模型配置与材料外发授权");
    expect(materialStatus({ ...job, reason_code: "material_quality_review_pending" }))
      .toContain("等待质量检查");
    expect(materialStatus({ ...job, state: "cancelled" })).toBe("已取消");
  });

  it("旧轮询响应不能覆盖取消结果或清空已加载历史", () => {
    const cancelled = { ...job, state: "cancelled" as const, revision: 4 };
    const older = { ...job, id: "older", created_at: "2026-11-02T01:00:00Z" };
    const merged = mergeMaterialJobs([cancelled, older], [job]);
    expect(merged).toHaveLength(2);
    expect(merged[0].state).toBe("cancelled");
    expect(merged[0].revision).toBe(4);
  });

  it("入口保持折叠、权限默认不勾选，不加入人为七天授权", () => {
    const html = renderToStaticMarkup(<MaterialUploadPanel session={{
      token: "nonpersistent-session", actor: { id: "actor", display_name: "Learner" },
      expires_at: "2026-11-09T00:00:00Z",
    }} goal={{ id: "goal", title: "Study iteration" }} />);
    expect(html).toContain("<summary>上传教材文件</summary>");
    expect(html).not.toContain("<details open");
    expect(html).not.toContain("checked=");
    expect(html).not.toContain("nonpersistent-session");
    expect(html).toContain("解析完成不等于材料已可用于课程");
    expect(html).toContain("不会自动设为七天");
    expect(html).toContain("云端处理还须本人模型配置中的材料外发授权");
    expect(html).not.toContain("<iframe");
  });

  it("先登记本人用途，再上传原始字节，最终只以受控引用创建任务", async () => {
    const responses = [
      { id: "demand-1", revision: 1 }, { id: "upload-1", state: "pending" },
      { id: "upload-1", state: "stored" }, job,
    ];
    const fetch = vi.fn(async () => ({
      ok: true, json: async () => responses.shift(),
    }));
    vi.stubGlobal("fetch", fetch);
    const bytes = new TextEncoder().encode("original \u4e2d\u6587\n    print(value)").buffer;
    const signal = new AbortController().signal;
    const result = await prepareFile("session", bytes, "text", "a".repeat(64), {
      goalId: "goal", title: "My material", language: "Python", topics: ["Iteration"],
      sourceUrl: "", useUntil: null, retainUntil: null,
    }, { demand: "demand-key", upload: "upload-key", job: "job-key" }, signal, () => undefined);
    expect(result.job).toEqual(job);
    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([, init]) => init.method)).toEqual(["POST", "POST", "PUT", "POST"]);
    expect(calls[2][1].body).toBe(bytes);
    expect(calls[2][1].headers).toMatchObject({ "Content-Type": "application/octet-stream" });
    expect(calls.every(([, init]) => init.signal === signal)).toBe(true);
    const metadata = JSON.parse(calls[1][1].body as string);
    expect(metadata.material).toMatchObject({
      authorized_use: true, purposes: ["reference", "teaching", "indexing"],
      use_until: null, retain_until: null,
    });
    expect(metadata.material.text).toBeUndefined();
    expect(JSON.parse(calls[3][1].body as string)).toEqual({
      expected_demand_revision: 1, upload_id: "upload-1",
    });
    expect(calls[3][1].headers).toMatchObject({ "Idempotency-Key": "job-key" });
  });
});
