import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { apiBase, explain, request } from "./api";
import type { MaterialDemand, MaterialJob, Session } from "./api";
import { fileFormat, fileLimit, materialStatus, mergeMaterialJobs, prepareFile } from "./material-upload";
import type { UploadKeys } from "./material-upload";

const date = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" });
type Goal = { id: string; title: string };

export function MaterialUploadPanel({ session, goal }: { session: Session; goal: Goal }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("");
  const [topics, setTopics] = useState(goal.title);
  const [sourceUrl, setSourceUrl] = useState("");
  const [useUntil, setUseUntil] = useState("");
  const [retainUntil, setRetainUntil] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [demands, setDemands] = useState<MaterialDemand[]>([]);
  const [demandId, setDemandId] = useState("");
  const [jobs, setJobs] = useState<MaterialJob[]>([]);
  const [more, setMore] = useState(false);
  const [moreDemands, setMoreDemands] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [reading, setReading] = useState(false);
  const attempt = useRef<{ signature: string; keys: UploadKeys } | null>(null);
  const transfer = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const activeDemand = useRef(demandId);
  activeDemand.current = demandId;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; transfer.current?.abort(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void request<MaterialDemand[]>(`/v1/material-demands?goal_id=${goal.id}&limit=20`,
      session.token, { signal: controller.signal }).then((items) => {
      if (controller.signal.aborted) return;
      setDemands(items); setMoreDemands(items.length === 20);
      setDemandId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? "");
    }).catch((problem: unknown) => { if (!controller.signal.aborted) setError(explain(problem)); });
    return () => controller.abort();
  }, [session.token, goal.id, refresh]);

  useEffect(() => {
    if (!demandId) { setJobs([]); return; }
    const controller = new AbortController();
    setJobs([]); setMore(false);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      try {
        const items = await request<MaterialJob[]>(`/v1/material-demands/${demandId}/jobs?limit=20`,
          session.token, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJobs((previous) => mergeMaterialJobs(previous, items)); setMore(items.length === 20);
        if (items.some((job) => job.state === "queued" || job.state === "parsing"))
          timer = setTimeout(() => void read(), 2500);
      } catch (problem) {
        if (!controller.signal.aborted) setError(explain(problem));
      }
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [demandId, session.token, refresh]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !authorized || busy) return;
    const format = fileFormat(file.name);
    const invalid = fileLimit(file.size, format);
    if (invalid || !format) { setError(invalid); return; }
    const facets = [...new Set(topics.split("\n").map((s) => s.trim()).filter(Boolean))];
    if (!facets.length || facets.length > 100 || facets.some((s) => s.length > 300)) {
      setError("请每行写一个主题，最多 100 行，每行不超过 300 字。"); return;
    }
    setBusy(true); setError(""); setProgress("正在读取原文件");
    const controller = new AbortController();
    transfer.current = controller;
    try {
      const bytes = await file.arrayBuffer();
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        (byte) => byte.toString(16).padStart(2, "0")).join("");
      const details = {
        goalId: goal.id, title: title.trim(), language: language.trim(), topics: facets,
        sourceUrl: sourceUrl.trim(), useUntil: useUntil ? new Date(useUntil).toISOString() : null,
        retainUntil: retainUntil ? new Date(retainUntil).toISOString() : null,
      };
      const signature = JSON.stringify({ digest, format, details });
      if (attempt.current?.signature !== signature) attempt.current = {
        signature, keys: { demand: crypto.randomUUID(), upload: crypto.randomUUID(), job: crypto.randomUUID() },
      };
      const result = await prepareFile(session.token, bytes, format, digest, details,
        attempt.current.keys, controller.signal, (step) => {
          if (mounted.current) setProgress(step);
        });
      if (!mounted.current) return;
      setDemandId(result.demand.id); setJobs([result.job]);
      setProgress("原文已保存，后台将自动推进可处理步骤。");
      setFile(null); setAuthorized(false); attempt.current = null;
      if (input.current) input.current.value = "";
      setRefresh((value) => value + 1);
    } catch (problem) {
      if (mounted.current && !controller.signal.aborted) { setError(explain(problem)); setProgress(""); }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function cancel(job: MaterialJob) {
    setError(""); setReading(true);
    try {
      const next = await request<MaterialJob>(`/v1/material-jobs/${job.id}/cancel`, session.token,
        { method: "POST" });
      if (mounted.current && activeDemand.current === next.demand_id)
        setJobs((items) => mergeMaterialJobs(items, [next]));
    } catch (problem) { if (mounted.current) setError(explain(problem)); }
    finally { if (mounted.current) setReading(false); }
  }

  async function older(kind: "demands" | "jobs") {
    setReading(true); setError("");
    try {
      if (kind === "demands") {
        const last = demands.at(-1);
        const items = await request<MaterialDemand[]>(
          `/v1/material-demands?goal_id=${goal.id}&limit=20&before=${last?.id}`, session.token);
        if (mounted.current) { setDemands((previous) => [...previous, ...items]); setMoreDemands(items.length === 20); }
      } else {
        const last = jobs.at(-1);
        const items = await request<MaterialJob[]>(
          `/v1/material-demands/${demandId}/jobs?limit=20&before=${last?.id}`, session.token);
        if (mounted.current && activeDemand.current === demandId) {
          setJobs((previous) => mergeMaterialJobs(previous, items)); setMore(items.length === 20);
        }
      }
    } catch (problem) { if (mounted.current) setError(explain(problem)); }
    finally { if (mounted.current) setReading(false); }
  }

  async function original(job: MaterialJob) {
    setReading(true); setError("");
    try {
      const response = await fetch(
        `${apiBase}/v1/material-uploads/${job.upload_id}/content?purpose=reference`,
        { headers: { Authorization: `Bearer ${session.token}` } },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.code === "source_not_current"
          ? "当前用途或保留期限不再允许下载此原文。" : "原文件暂不可读，请同步材料状态。");
      }
      const blob = await response.blob();
      if (!mounted.current) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `original-material.${job.format === "markdown" ? "md"
        : job.format === "text" ? "txt" : job.format ?? "bin"}`;
      anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (problem) { if (mounted.current) setError(explain(problem)); }
    finally { if (mounted.current) setReading(false); }
  }

  return <details className="material-intake">
    <summary>上传教材文件</summary>
    <p className="tutor-description">关联「{goal.title}」。保存原文件并提取正文；解析完成不等于材料已可用于课程。</p>
    <form className="source-form" onSubmit={(event) => void submit(event)}>
      <label htmlFor="material-file">教材文件</label>
      <input ref={input} id="material-file" type="file" accept=".txt,.md,.markdown,.html,.htm,.pdf"
        disabled={busy} required onChange={(event) => {
          const next = event.target.files?.[0] ?? null;
          setFile(next); setTitle(next?.name.replace(/\.[^.]+$/, "").slice(0, 160) ?? "");
          setError(next ? fileLimit(next.size, fileFormat(next.name)) : ""); setProgress("");
        }} aria-describedby="material-limits" />
      <p id="material-limits" className="tutor-description">文本、Markdown、HTML 最多 2 MB；PDF 最多 20 MB / 200 页。扫描页需要 OCR。</p>
      <label htmlFor="material-title">材料标题</label>
      <input id="material-title" value={title} required maxLength={160} disabled={busy}
        onChange={(event) => setTitle(event.target.value)} />
      <label htmlFor="material-language">材料语言或技术</label>
      <input id="material-language" value={language} required maxLength={80} placeholder="例如 Python"
        disabled={busy} onChange={(event) => setLanguage(event.target.value)} />
      <label htmlFor="material-topics">准备参考的主题 · 每行一个</label>
      <textarea id="material-topics" value={topics} required rows={3} disabled={busy}
        onChange={(event) => setTopics(event.target.value)} />
      <label htmlFor="material-source">原文 HTTPS 链接 · 选填</label>
      <input id="material-source" type="url" pattern="https://.*" maxLength={2048} value={sourceUrl}
        disabled={busy} onChange={(event) => setSourceUrl(event.target.value)} />
      <div className="material-deadlines">
        <div><label htmlFor="material-use-until">真实使用截止 · 选填</label>
          <input id="material-use-until" type="datetime-local" value={useUntil} disabled={busy}
            onChange={(event) => setUseUntil(event.target.value)} /></div>
        <div><label htmlFor="material-retain-until">真实保留截止 · 选填</label>
          <input id="material-retain-until" type="datetime-local" value={retainUntil} disabled={busy}
            onChange={(event) => setRetainUntil(event.target.value)} /></div>
      </div>
      <p className="tutor-description">没有真实限制可留空，不会自动设为七天。保留期限到达后清除原文与提取正文，留下记录身份。</p>
      <label className="material-authority"><input type="checkbox" checked={authorized} disabled={busy}
        onChange={(event) => setAuthorized(event.target.checked)} />
        我有权上传此材料，允许为本目标保存、索引与教学参考。云端处理还须本人模型配置中的材料外发授权。</label>
      <div className="form-footer">
        <p>无需手动审核或发布。当前文件链路尚未接通索引/课程消费；OCR 不会借用共享密钥。</p>
        <button className="primary" disabled={busy || !authorized || !file || !title.trim()
          || !language.trim() || !topics.trim() || !!fileLimit(file.size, fileFormat(file.name))}>
          {busy ? "正在接收材料…" : "上传并准备材料"}</button>
      </div>
    </form>
    {progress && <p className="notice" role="status">{progress}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="material-record-heading"><h3>材料准备记录</h3>
      <button type="button" className="text-button" disabled={busy || reading}
        onClick={() => setRefresh((value) => value + 1)}>同步状态</button></div>
    {demands.length === 0 ? <p className="empty">此目标还没有材料准备记录。</p> : <>
      <label htmlFor="material-demand">查看一份材料需求</label>
      <select id="material-demand" value={demandId} disabled={busy || reading}
        onChange={(event) => { setDemandId(event.target.value); setError(""); }}>
        {demands.map((demand) => <option key={demand.id} value={demand.id}>
          {demand.language} · {date.format(new Date(demand.created_at))} · {demand.required_facets[0]}
        </option>)}
      </select>
      {moreDemands && <button className="text-button" type="button" disabled={reading}
        onClick={() => void older("demands")}>加载更早需求</button>}
      <ul className="material-job-list">{jobs.map((job) => <li key={job.id}>
        <h4>{job.title || "材料解析"} <span>{job.format?.toUpperCase()}</span></h4>
        <p>{materialStatus(job)}</p>
        <small>{date.format(new Date(job.created_at))} · {job.steps.length} 条处理记录</small>
        {job.issues.length > 0 && <p className="tutor-description">
          {job.issues.includes("pdf_ocr_pending") ? "缺少可用文字的页未标为已识别，已有正文与原文均保留。"
            : "发现结构或质量疑点，原文未被自动改写。"}
        </p>}
        <div className="source-actions">
          {job.upload_id && (job.state !== "cancelled" || job.document_id)
            && job.reason_code !== "material_retention_expired"
            && <button className="text-button" type="button" disabled={reading}
            onClick={() => void original(job)}>下载原文件</button>}
          {job.state !== "cancelled" && <button className="text-button" type="button" disabled={reading}
            onClick={() => void cancel(job)}>取消材料准备</button>}
        </div>
      </li>)}</ul>
      {jobs.length === 0 && <p className="empty">此需求尚无解析任务。</p>}
      {more && <button className="text-button" type="button" disabled={reading}
        onClick={() => void older("jobs")}>加载更早处理记录</button>}
    </>}
  </details>;
}
