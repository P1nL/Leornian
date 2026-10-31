import { useState } from "react";
import { explain, request } from "./api";
import type { GeneratedLesson, LearningPlan, PlanRevision, Session, Source, TurnAccepted } from "./api";
import { LessonReader } from "./LessonReader";

function RevisionBody({ revision }: { revision: PlanRevision }) {
  const document = revision.document;
  return <>
    <h3>{document.title}</h3><p>{document.summary}</p>
    {document.assumptions.length > 0 && <details><summary>这份路线的假设</summary>
      <ul>{document.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
    <ol className="plan-nodes">{document.nodes.map((node) => <li key={node.key}>
      <h4>{node.title}<span>约 {node.estimated_minutes} 分钟</span></h4>
      <p>{node.objective}</p>
      {node.prerequisite_keys.length > 0 && <small>先完成：{node.prerequisite_keys.map((key) =>
        document.nodes.find((item) => item.key === key)?.title ?? key).join("、")}</small>}
      {node.source_refs.length > 0 && <ul className="plan-citations">{node.source_refs.map((ref) => {
        const source = revision.sources.find((item) => item.source_id === ref.source_id && item.revision === ref.revision);
        return source && <li key={`${ref.source_id}:${ref.revision}`}>
          <a href={source.source_url} target="_blank" rel="noreferrer noopener">{source.title} · 来源版本 {source.revision}</a>
        </li>;
      })}</ul>}
    </li>)}</ol>
  </>;
}

const lessonPendingKey = "leornian.pending-lesson.v1";
type PendingLesson = { actorId: string; planId: string; revision: number; nodeKey: string;
  instruction: string; key: string };

function readPendingLesson(): PendingLesson | null {
  try { return JSON.parse(localStorage.getItem(lessonPendingKey) ?? "null") as PendingLesson | null; }
  catch { return null; }
}

export function PlanOutline({ plan, session, sources, lessons, modelReady, hasActiveRun, busy, setBusy, onUpdated }: {
  plan: LearningPlan; session: Session; sources: Source[]; busy: boolean;
  lessons: GeneratedLesson[]; modelReady: boolean; hasActiveRun: boolean;
  setBusy: (busy: boolean) => void; onUpdated: () => void;
}) {
  const [error, setError] = useState("");
  const [history, setHistory] = useState<PlanRevision[] | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [nodeKey, setNodeKey] = useState("");
  const [instruction, setInstruction] = useState("");
  const confirmed = plan.active?.revision === plan.latest.revision;
  const stale = plan.latest.sources.some((ref) => !sources.some((source) =>
    source.id === ref.source_id && source.revision === ref.revision && source.usable));
  const active = plan.active;
  const node = active?.document.nodes.find((item) => item.key === nodeKey) ?? active?.document.nodes[0];
  const nodeSourcesCurrent = Boolean(node?.source_refs.length) && node!.source_refs.every((ref) =>
    sources.some((source) => source.id === ref.source_id && source.revision === ref.revision && source.usable));
  const documents = lessons.filter((lesson) => lesson.plan_id === plan.id
    && lesson.plan_revision === active?.revision && lesson.node_key === node?.key);
  const selectedLesson = documents[0];
  const historicalLessons = lessons.filter((lesson) => lesson.plan_id === plan.id
    && lesson.plan_revision !== active?.revision);

  async function generateLesson() {
    if (!active || !node || !instruction.trim()) return;
    setBusy(true); setError("");
    const previous = readPendingLesson();
    const pending = previous?.actorId === session.actor.id && previous.planId === plan.id
      && previous.revision === active.revision && previous.nodeKey === node.key
      && previous.instruction === instruction.trim() ? previous : {
        actorId: session.actor.id, planId: plan.id, revision: active.revision,
        nodeKey: node.key, instruction: instruction.trim(), key: crypto.randomUUID(),
      };
    localStorage.setItem(lessonPendingKey, JSON.stringify(pending));
    try {
      await request<TurnAccepted>(`/v1/plans/${plan.id}/lesson-requests`, session.token, {
        method: "POST", headers: { "Idempotency-Key": pending.key },
        body: JSON.stringify({ expected_plan_revision: pending.revision,
          node_key: pending.nodeKey, instruction: pending.instruction }),
      });
      localStorage.removeItem(lessonPendingKey); setInstruction(""); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function confirm() {
    setBusy(true); setError("");
    try {
      await request<LearningPlan>(`/v1/plans/${plan.id}/confirm`, session.token, {
        method: "POST", body: JSON.stringify({ expected_revision: plan.latest.revision }),
      });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function showHistory() {
    if (historyOpen) { setHistoryOpen(false); return; }
    setBusy(true); setError("");
    try {
      const revisions = await request<PlanRevision[]>(`/v1/plans/${plan.id}/revisions`, session.token);
      setHistory(revisions); setHistoryOpen(true);
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="plan-outline" aria-label="动态学习路线">
    <div className="goal-heading"><h2>你的学习路线 · 版本 {plan.latest.revision}</h2>
      <span className="saved-state">{confirmed ? "已明确确认" : "新草案 · 等待确认"}</span></div>
    <RevisionBody revision={plan.latest} />
    {plan.active && !confirmed && <p className="plan-version-note">新版本尚未生效，当前确认版本仍为 {plan.active.revision}；历史内容不会被覆盖。</p>}
    {stale && <p className="plan-version-note">这份路线引用的来源已改版、撤销或过期。内容保留作历史参考；确认新路线前，请更新资料并生成新草案。</p>}
    <p className="provenance">这是模型建议的路线，不是已审核课程或完整题包；引用来自你确认使用的摘录，不代表独立事实认证。</p>
    <div className="plan-controls">
      {!confirmed && <button className="primary" disabled={busy || stale} onClick={() => void confirm()}>确认使用版本 {plan.latest.revision}</button>}
      <button className="text-button" disabled={busy} onClick={() => void showHistory()}>
        {historyOpen ? "收起历史版本" : "查看历史版本"}
      </button>
    </div>
    {active && node && <section className="generated-lesson-workspace" aria-label="已确认路线的课时">
      <h3>阅读已确认路线的课时 · 计划版本 {active.revision}</h3>
      <label htmlFor={`lesson-node-${plan.id}`}>选择路线节点</label>
      <select id={`lesson-node-${plan.id}`} value={node.key} disabled={busy}
        onChange={(event) => { setNodeKey(event.target.value); setInstruction(""); setError(""); }}>
        {active.document.nodes.map((item) => <option key={item.key} value={item.key}>{item.title}</option>)}
      </select>
      {selectedLesson ? <LessonReader lesson={selectedLesson} sources={sources} />
        : <p className="empty">这个节点还没有课时正文。生成后会保存引用和版本，不会自动运行代码或创建评测结果。</p>}
      {documents.length > 1 && <details className="lesson-older"><summary>之前生成的正文 · {documents.length - 1} 份</summary>
        {documents.slice(1).map((lesson) => <LessonReader key={lesson.id} lesson={lesson} sources={sources} />)}
      </details>}
      {!nodeSourcesCurrent && <p className="plan-version-note">这个节点还没有可用的精确来源。请添加并确认资料，修订路线中的引用后再生成课时。</p>}
      <label htmlFor={`lesson-instruction-${plan.id}`}>{selectedLesson ? "这次希望如何调整课时" : "这节课希望怎样讲解"}</label>
      <textarea id={`lesson-instruction-${plan.id}`} rows={2} value={instruction} maxLength={4000}
        disabled={busy || hasActiveRun} onChange={(event) => setInstruction(event.target.value)}
        placeholder="例如：先解释概念，再给一个小例子；我还不熟悉文件路径。" />
      <div className="form-footer"><p>仅生成带引用的正文和回想问题；不包含正式 Gate 或掌握度裁决。</p>
        <button className="primary" disabled={busy || hasActiveRun || !modelReady || !nodeSourcesCurrent || !instruction.trim()}
          onClick={() => void generateLesson()}>{hasActiveRun ? "等待当前回合结束" : selectedLesson ? "生成另一份正文" : "生成这个节点的课时"}</button>
      </div>
    </section>}
    {historicalLessons.length > 0 && <details className="lesson-older"><summary>其他计划版本的历史课时 · {historicalLessons.length} 份</summary>
      <p className="plan-version-note">以下课时保留原计划和来源版本，不作为当前路线的进度或执行权限。</p>
      {historicalLessons.map((lesson) => <LessonReader key={lesson.id} lesson={lesson} sources={sources} />)}
    </details>}
    {historyOpen && history && <div className="plan-history">{history.map((revision) => <details key={revision.id}>
      <summary>版本 {revision.revision} · {revision.document.title}{plan.active?.revision === revision.revision ? " · 当前确认版本" : ""}</summary>
      <RevisionBody revision={revision} />
    </details>)}</div>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
