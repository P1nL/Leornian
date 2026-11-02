import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, explain, request } from "./api";
import type { ArtifactJob, ArtifactView, Conversation, Session, Snapshot, TeachingFocus } from "./api";

export function ArtifactDocumentView({ artifact }: { artifact: ArtifactView }) {
  return <article className="artifact-document" aria-label={`工件第 ${artifact.revision} 版`}>
    <h4>{artifact.title} · 第 {artifact.revision} 版</h4>
    <p className="artifact-note">已通过教学交付检查。代码仅展示，未执行；不代表学习通过。</p>
    {artifact.document.sections.map((section, index) => <section key={index}>
      <h5>{section.heading}</h5>
      <p className="artifact-text">{section.text}</p>
      {section.code && <pre><code>{section.code}</code></pre>}
      {section.source_refs.length > 0 && <p className="artifact-note">引用：
        {section.source_refs.map((ref) => `${ref.source_id} · v${ref.revision}`).join("；")}
      </p>}
    </section>)}
  </article>;
}

function sameFocus(a: TeachingFocus, b: TeachingFocus) {
  const fields = (value: TeachingFocus) => [
    value.kind, value.plan_id ?? null, value.expected_plan_revision ?? null,
    value.node_key ?? null, value.assessment_receipt_id ?? null, value.lesson_id ?? null,
  ];
  return JSON.stringify(fields(a)) === JSON.stringify(fields(b));
}

const jobLabels: Record<string, string> = {
  queued: "已排队，等待当前对话结束后生成",
  running: "正在生成或检查，尚未交付",
  generating: "正在生成候选，尚未交付",
  checking: "正在独立检查候选",
  repairing: "正在根据检查问题修订",
  waiting_config: "等待会话或模型配置恢复",
  waiting_dependency: "等待来源或其他依赖恢复",
  waiting_input: "需要补充信息，请使用对应交付任务的补充入口",
  blocked_unknown: "调用结果未知，保留回执；不会重复发送",
  accepted: "合格版本已保存，可在下方打开",
  cancelled: "已取消，旧版本保留",
  superseded: "绑定版本已变化，本任务不再应用",
};

export function ArtifactPanel({ session, snapshot, conversation, focus, disabled, onUpdated }: {
  session: Session; snapshot: Snapshot; conversation: Conversation; focus: TeachingFocus;
  disabled: boolean; onUpdated: () => void;
}) {
  const [selection, setSelection] = useState<{ id: string; revision: number } | null>(null);
  const [artifact, setArtifact] = useState<ArtifactView | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const items = (snapshot.artifacts ?? []).filter((item) =>
    item.goal_id === conversation.goal_id && sameFocus(item.focus, focus));
  const jobs = (snapshot.artifact_jobs ?? []).filter((job) =>
    job.conversation_id === conversation.id);
  const head = items.find((item) => item.id === selection?.id);
  const oldRevision = Boolean(selection && head && selection.revision !== head.revision);

  useEffect(() => {
    setArtifact(null);
    if (!selection) return;
    const controller = new AbortController();
    void request<ArtifactView>(
      `/v1/artifacts/${selection.id}?revision=${selection.revision}`, session.token,
      { signal: controller.signal },
    ).then(setArtifact).catch((problem: unknown) => {
      if (!controller.signal.aborted) setError(explain(problem));
    });
    return () => controller.abort();
  }, [selection, session.token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!instruction.trim() || disabled || oldRevision || (selection && !artifact)) return;
    setBusy(true); setError(""); setNotice("");
    const payload = {
      instruction: instruction.trim(), focus: artifact?.focus ?? focus,
      artifact_id: artifact?.id ?? null, expected_revision: artifact?.revision ?? 0,
    };
    const storageKey = `leornian.artifact-command.v1:${session.actor.id}:${conversation.id}`;
    let previous: { key: string; payload: string } | null = null;
    try { previous = JSON.parse(localStorage.getItem(storageKey) ?? "null"); } catch { /* New command. */ }
    const serialized = JSON.stringify(payload);
    const command = previous?.payload === serialized ? previous : {
      key: crypto.randomUUID(), payload: serialized,
    };
    localStorage.setItem(storageKey, JSON.stringify(command));
    try {
      await request<ArtifactJob>(`/v1/conversations/${conversation.id}/artifact-requests`,
        session.token, { method: "POST", headers: { "Idempotency-Key": command.key }, body: serialized });
      localStorage.removeItem(storageKey);
      setInstruction(""); setNotice("已接收工件任务，合格后才会出现新版本。"); onUpdated();
    } catch (problem) {
      if (problem instanceof ApiError && ["stale_version", "idempotency_conflict"].includes(problem.code)) {
        localStorage.removeItem(storageKey); onUpdated();
      }
      setError(explain(problem));
    } finally { setBusy(false); }
  }

  async function action(job: ArtifactJob, verb: "cancel" | "resume") {
    setBusy(true); setError("");
    try {
      await request(`/v1/artifact-jobs/${job.id}/${verb}`, session.token, { method: "POST" });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="artifact-workspace" aria-labelledby="artifact-heading">
    <div className="section-heading">
      <h3 id="artifact-heading">教学工件</h3>
      <button type="button" className="text-button" disabled={busy} onClick={() => {
        setSelection(null); setError(""); setNotice("");
      }}>新建工件</button>
    </div>
    <p>将当前目标或节点的讲解整理成可修订的讲义、对照表和代码示例。新版本独立检查，旧版不覆盖。</p>
    {items.length > 0 ? <ul className="artifact-list">
      {items.map((item) => <li key={item.id}>
        <button type="button" className="text-button" disabled={busy}
          onClick={() => { setSelection({ id: item.id, revision: item.revision }); setError(""); }}>
          打开 {item.title} · v{item.revision}
        </button>
      </li>)}
    </ul> : <p className="empty">当前教学范围还没有已交付工件。</p>}
    {selection && !artifact && !error && <p role="status">正在读取指定版本…</p>}
    {artifact && <>
      <div className="artifact-version-controls">
        <button type="button" className="text-button" disabled={busy || artifact.revision <= 1}
          onClick={() => setSelection({ id: artifact.id, revision: artifact.revision - 1 })}>查看上一版</button>
        {head && artifact.revision < head.revision && <button type="button" className="text-button"
          onClick={() => setSelection({ id: head.id, revision: head.revision })}>读取当前版本 v{head.revision}</button>}
      </div>
      <ArtifactDocumentView artifact={artifact} />
    </>}
    <form className="artifact-form" onSubmit={(event) => void submit(event)}>
      <label htmlFor="artifact-instruction">{artifact ? `基于第 ${artifact.revision} 版提出修订` : "希望生成什么教学工件"}</label>
      <textarea id="artifact-instruction" value={instruction} maxLength={4000} rows={3}
        disabled={busy || disabled || oldRevision}
        onChange={(event) => setInstruction(event.target.value)} />
      {oldRevision && <p role="status">正在查看历史版本；请读取当前版本后再请求修订。</p>}
      <button className="primary" disabled={busy || disabled || oldRevision || !instruction.trim()
        || Boolean(selection && !artifact)}>{busy ? "正在提交…" : artifact ? "提交修订任务" : "生成教学工件"}</button>
    </form>
    {notice && <p role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {jobs.length > 0 && <ul className="artifact-jobs" aria-label="工件交付任务">
      {jobs.map((job) => {
        const task = snapshot.delivery_tasks?.find((item) => item.run_id === job.run_id);
        const status = task?.status ?? job.status;
        const terminal = ["accepted", "cancelled", "superseded"].includes(status);
        return <li key={job.id}>
          <p>{job.instruction}</p>
          <p role="status">{jobLabels[status] ?? status}</p>
          {!terminal && <button className="text-button" disabled={busy}
            onClick={() => void action(job, "cancel")}>取消工件任务</button>}
          {(job.status === "waiting_config" || (task?.can_resume && status !== "waiting_input"))
            && <button className="text-button" disabled={busy}
              onClick={() => void action(job, "resume")}>承接工件任务</button>}
        </li>;
      })}
    </ul>}
  </section>;
}
