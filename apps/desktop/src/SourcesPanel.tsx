import { useState } from "react";
import type { FormEvent } from "react";
import { explain, request } from "./api";
import type { Session, Snapshot, Source } from "./api";
import { MaterialUploadPanel } from "./MaterialUploadPanel";

const date = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" });
const pendingKey = "leornian.pending-source.v1";
type Pending = { key: string; actorId: string; body: string; goalId: string };

function readPending(): Pending | null {
  try { return JSON.parse(localStorage.getItem(pendingKey) ?? "null") as Pending | null; }
  catch { return null; }
}

export function SourcesPanel({ session, snapshot, onUpdated }: {
  session: Session; snapshot: Snapshot; onUpdated: () => void;
}) {
  const [goalId, setGoalId] = useState("");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [editing, setEditing] = useState<Source | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const goal = snapshot.goals.find((item) => item.id === goalId) ?? snapshot.goals[0];
  const sources = snapshot.sources.filter((item) => item.goal_id === goal?.id);

  function reset() {
    setEditing(null); setTitle(""); setUrl(""); setExcerpt("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!goal) return;
    setBusy(true); setError(""); setNotice("");
    const fields = { title: title.trim(), source_url: url.trim(), excerpt: excerpt.trim() };
    try {
      if (editing) {
        await request<Source>(`/v1/sources/${editing.id}/revisions`, session.token, {
          method: "POST", body: JSON.stringify({ ...fields, expected_revision: editing.revision }),
        });
      } else {
        const body = JSON.stringify(fields);
        const previous = readPending();
        const current = previous?.actorId === session.actor.id
          && previous.body === body && previous.goalId === goal.id
          ? previous : { key: crypto.randomUUID(), actorId: session.actor.id, body, goalId: goal.id };
        localStorage.setItem(pendingKey, JSON.stringify(current));
        await request<Source>(`/v1/goals/${goal.id}/sources`, session.token, {
          method: "POST", headers: { "Idempotency-Key": current.key }, body,
        });
        localStorage.removeItem(pendingKey);
      }
      reset(); setNotice("摘录已保存。确认使用后，才会进入新的 Tutor 教学上下文。");
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function action(source: Source, verb: "admit" | "revoke") {
    setBusy(true); setError(""); setNotice("");
    try {
      await request<Source>(`/v1/sources/${source.id}/${verb}`, session.token, {
        method: "POST", body: JSON.stringify({ expected_revision: source.revision,
          ...(verb === "admit" ? { valid_until: new Date(Date.now() + 7 * 86400000).toISOString() } : {}),
        }),
      });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="sources-workspace" aria-labelledby="sources-heading">
    <h2 id="sources-heading">把参考资料带进学习</h2>
    <p className="tutor-description">提供你有权使用的材料。现有摘录入口沿用逐版确认和七天准入；文件材料单独声明真实用途与保留期限，系统不独立认证内容。</p>
    {!goal ? <p className="empty">保存目标后，可以为它添加参考摘录。</p> : <>
      <label htmlFor="source-goal">资料关联的目标</label>
      <select id="source-goal" value={goal.id} disabled={busy}
        onChange={(event) => { setGoalId(event.target.value); reset(); setError(""); setNotice(""); }}>
        {snapshot.goals.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <MaterialUploadPanel key={`${session.actor.id}:${goal.id}`} session={session} goal={goal} />
      <form className="source-form" onSubmit={save}>
        <h3>{editing ? `修订摘录 · 当前版本 ${editing.revision}` : "添加一份参考摘录"}</h3>
        <label htmlFor="source-title">资料标题</label>
        <input id="source-title" required maxLength={160} value={title} disabled={busy}
          onChange={(event) => setTitle(event.target.value)} />
        <label htmlFor="source-url">原文链接 · HTTPS</label>
        <input id="source-url" type="url" pattern="https://.*" required maxLength={2048}
          value={url} disabled={busy} onChange={(event) => setUrl(event.target.value)} />
        <label htmlFor="source-excerpt">你想参考的摘录 · 最多 8000 UTF-8 字节</label>
        <textarea id="source-excerpt" required rows={4} maxLength={8000} value={excerpt} disabled={busy}
          onChange={(event) => setExcerpt(event.target.value)} />
        <div className="form-footer"><p>新版本不会沿用旧版的使用确认。旧版保留，可追溯。</p>
          {editing && <button type="button" className="text-button" disabled={busy} onClick={reset}>取消修订</button>}
          <button className="primary" disabled={busy || !title.trim() || !excerpt.trim()}>
            {busy ? "正在保存…" : editing ? "保存新版本" : "保存摘录"}
          </button>
        </div>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      <ul className="source-list">{sources.map((source) => <li key={source.id}>
        <div className="goal-heading"><h3><a href={source.source_url} target="_blank" rel="noreferrer noopener">{source.title}</a></h3>
          <span className="saved-state">版本 {source.revision} · {source.usable ? "可用于教学" : source.admission === "revoked"
            ? "已撤销" : source.admission === "admitted" ? "已过期" : "待确认使用"}</span></div>
        <p className="source-excerpt">{source.excerpt}</p>
        {source.valid_until && <small>本次使用确认至 {date.format(new Date(source.valid_until))} · 学习者提供，非独立网页验证</small>}
        <div className="source-actions">
          {!source.usable && <button className="text-button" disabled={busy} onClick={() => void action(source, "admit")}>确认使用七天</button>}
          {source.admission === "admitted" && <button className="text-button" disabled={busy}
            onClick={() => void action(source, "revoke")}>撤销使用</button>}
          <button className="text-button" disabled={busy} onClick={() => {
            setEditing(source); setTitle(source.title); setUrl(source.source_url); setExcerpt(source.excerpt);
            setError(""); setNotice("");
          }}>修订摘录</button>
        </div>
      </li>)}</ul>
    </>}
  </section>;
}
