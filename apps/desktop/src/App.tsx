import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, explain, request } from "./api";
import type { Accepted, PublicEvent, Session, Snapshot } from "./api";
import { listen } from "./stream";
import { TutorPanel } from "./TutorPanel";
import { JourneyPanel } from "./JourneyPanel";
import { SourcesPanel } from "./SourcesPanel";
import { ReviewPanel } from "./ReviewPanel";
import { ModelSettingsPanel } from "./ModelSettingsPanel";

const sessionKey = "leornian.session.v1";
const pendingKey = "leornian.pending-goal.v1";
const date = new Intl.DateTimeFormat("zh-CN", {
  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
});
const labels = {
  "job.queued": "目标已接收，等待后台保存",
  "goal.created": "学习目标已保存到数据库",
  "goal.updated": "学习目标已更新",
  "goal.deleted": "学习目标已从列表移除",
  "job.succeeded": "后台任务完成",
  "job.failed": "后台任务未完成，请检查任务结果",
  "tutor.queued": "教学请求已接收",
  "tutor.running": "Tutor 开始处理",
  "tutor.tool_completed": "Tutor 已通过只读工具读取学习上下文",
  "tutor.succeeded": "教学回复已保存",
  "tutor.failed": "这轮教学未完成",
  "tutor.cancelled": "这轮教学已取消",
  "tutor.blocked_unknown": "模型调用结果未知，已停止自动续行",
  "tutor.result_available": "迟到回执已记录，可明确承接",
  "tutor.thinking": "教学处理进度已更新",
  "tutor.stage_reply": "当前阶段回复已保存",
  "tutor.conversation_hidden": "会话已从最近列表隐藏",
  "learning.plan_drafted": "入门计划草案已保存",
  "learning.plan_confirmed": "已确认当前计划",
  "assessment.queued": "代码作答已接收，等待隔离执行",
  "assessment.completed": "服务端评测已完成",
  "learning.lesson_completed": "本课基础练习进度已更新",
  "knowledge.created": "来源摘录已保存，等待确认使用",
  "knowledge.revised": "来源新版本已保存，旧准入不沿用",
  "knowledge.admitted": "当前来源版本已确认使用",
  "knowledge.revoked": "来源使用资格已撤销",
  "knowledge.material_permission_changed": "材料使用权限已变化，重新核对引用",
  "knowledge.material_update_offered": "教材新版已准备，等待选择是否切换",
  "learning.material_update_decided": "教材更新决定已保存",
  "delivery.notification_updated": "教材更新通知状态已同步",
  "learning.review_scheduled": "本课已加入复习安排",
  "learning.review_recorded": "复习自评已记录，下次时间已更新",
  "learning.review_status_changed": "复习暂停状态已更新",
  "learning.dynamic_plan_drafted": "动态计划新版本已保存，等待确认",
  "learning.dynamic_plan_confirmed": "已确认指定版本的学习路线",
  "learning.lesson_document_created": "节点课时正文与引用已保存，未判定学习完成",
  "item_bank.updated": "节点题包状态已更新",
  "assessment.choice_recorded": "概念练习作答已保存，不代表正式 Gate",
  "assessment.response_recorded": "知识检查回答已保存；参考对照不代表正式考核",
  "assessment.remediation_updated": "补救任务状态已更新",
  "assessment.gate_updated": "概念考核状态已更新",
  "assessment.transfer_updated": "新情境后继状态已更新，不代表学习完成",
  "learning.node_completed": "本节点概念 Gate 通过，已记录服务端证据",
  "tutor.artifact_updated": "教学工件任务或版本已更新，不代表学习通过",
  "tutor.learning_artifact_updated": "学习工件交互已更新，评分以服务端结果为准",
  "tutor.teaching_session_updated": "教学模式或答疑分支已更新，不代表学习完成",
  "tutor.teaching_intent_updated": "结果后续教学意图已更新，未代替作答或学习进度",
};

type Pending = { key: string; actorId: string; title: string; motivation: string };

function readLocal<T>(key: string): T | null {
  try { return JSON.parse(localStorage.getItem(key) ?? "null") as T | null; }
  catch { return null; }
}

export function App({ tutorPresentation = "legacy" }: {
  tutorPresentation?: "legacy" | "chat";
} = {}) {
  const [session, setSession] = useState<Session | null>(() => readLocal(sessionKey));
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<PublicEvent[]>([]);
  const [connection, setConnection] = useState("尚未连接");
  const [name, setName] = useState("");
  const initialPending = useRef(readLocal<Pending>(pendingKey));
  const [title, setTitle] = useState(initialPending.current?.title ?? "");
  const [motivation, setMotivation] = useState(initialPending.current?.motivation ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);

  function applySnapshot(next: Snapshot) {
    setSnapshot((previous) => previous && previous.actor.id === next.actor.id
      && previous.cursor > next.cursor ? previous : next);
  }

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let wake: (() => void) | undefined;
    const valid = () => !controller.signal.aborted;
    async function synchronize() {
      while (valid()) {
        try {
          setConnection("正在同步");
          const current = await request<Snapshot>("/v1/snapshot", session!.token, {
            signal: controller.signal,
          });
          if (!valid()) return;
          applySnapshot(current);
          // Snapshot and cursor are one committed view; stream only newer facts.
          setEvents(current.events);
          await listen(session!.token, current.cursor, controller.signal,
            () => valid() && setConnection("实时连接"),
            async (event) => {
              const latest = await request<Snapshot>("/v1/snapshot", session!.token, {
                signal: controller.signal,
              });
              if (!valid()) return;
              applySnapshot(latest);
              setEvents((previous) => [...previous, event].slice(-12));
            });
        } catch (problem) {
          if (!valid()) return;
          if (problem instanceof ApiError && problem.status === 401) {
            setError(explain(problem));
            localStorage.removeItem(sessionKey);
            setSession(null);
            setSnapshot(null);
            setEvents([]);
            setConnection("会话已失效");
            return;
          }
          setConnection("连接中断，正在重连");
          await new Promise<void>((resolve) => {
            wake = resolve;
            timer = setTimeout(resolve, 2000);
          });
        }
      }
    }
    void synchronize();
    return () => { controller.abort(); clearTimeout(timer); wake?.(); };
  }, [session, refresh]);

  async function enter(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const next = await request<Session>("/v1/local-sessions", undefined, {
        method: "POST", body: JSON.stringify({ display_name: name.trim() }),
      });
      localStorage.setItem(sessionKey, JSON.stringify(next));
      setSession(next);
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true); setError(""); setNotice("");
    const payload = { title: title.trim(), motivation: motivation.trim() };
    const existing = readLocal<Pending>(pendingKey);
    const pending = existing?.actorId === session.actor.id
      && existing.title === payload.title && existing.motivation === payload.motivation
      ? existing : { ...payload, actorId: session.actor.id, key: crypto.randomUUID() };
    localStorage.setItem(pendingKey, JSON.stringify(pending));
    try {
      const accepted = await request<Accepted>("/v1/goals", session.token, {
        method: "POST", headers: { "Idempotency-Key": pending.key }, body: JSON.stringify(payload),
      });
      localStorage.removeItem(pendingKey);
      setTitle(""); setMotivation("");
      setNotice(`已接收任务 ${accepted.job_id.slice(0, 8)}；保存结果以服务端状态为准。`);
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return (
    <div className="workspace">
      <aside className="sidebar">
        <a className="wordmark" href="/">Leornian<span>学习，从一个目标开始。</span></a>
        <nav aria-label="当前工作区"><a href="#goals" aria-current="page">学习目标</a></nav>
        <div className="scope-note">
          <strong>第一步，留下你的方向。</strong>
          <p>保存目标后可与 Tutor 对话，或体验一节固定 Python 入门课。</p>
        </div>
        <div className="identity">
          <span className="avatar" aria-hidden="true">{session?.actor.display_name.slice(0, 1) ?? "L"}</span>
          <div><strong>{session?.actor.display_name ?? "本地学习者"}</strong><small>独立新库 · 本地开发</small></div>
        </div>
      </aside>
      <main id="goals">
        <header className="toolbar">
          <span>我的学习空间</span>
          {tutorPresentation === "chat" &&
            <a className="chat-entry-back" href="/">返回原学习空间</a>}
          <span className={`connection ${connection === "实时连接" ? "connected" : ""}`} role="status">
            <i aria-hidden="true" />{connection}
          </span>
        </header>
        <div className="content">
          <header className="page-heading"><h1>你想学会什么？</h1><p>先写下一个清晰的目标，给下一段学习一个起点。</p></header>
          {error && <div className="error" role="alert">{error}</div>}
          {!session ? (
            <form className="entry-form" onSubmit={enter}>
              <h2>进入本地学习空间</h2>
              <p>设置称呼后，系统会创建独立身份。当前不是正式账号登录；请保留此浏览器的会话数据。</p>
              <label htmlFor="display-name">怎么称呼你</label>
              <input id="display-name" autoComplete="nickname" required maxLength={60}
                value={name} onChange={(event) => setName(event.target.value)} placeholder="你的称呼" />
              <button className="primary" disabled={busy || !name.trim()}>{busy ? "正在进入…" : "进入学习空间"}</button>
            </form>
          ) : (
            <>
              <ModelSettingsPanel key={session.actor.id} session={session}
                onUpdated={() => setRefresh((value) => value + 1)} />
              <form className="goal-form" onSubmit={submit}>
                <label htmlFor="goal-title">学习目标</label>
                <input id="goal-title" required minLength={3} maxLength={120} value={title}
                  onChange={(event) => setTitle(event.target.value)} placeholder="例如：用 Python 写一个整理文件的小工具" />
                <label htmlFor="goal-motivation">为什么想学 <span>选填</span></label>
                <textarea id="goal-motivation" rows={3} maxLength={1200} value={motivation}
                  onChange={(event) => setMotivation(event.target.value)} placeholder="你的使用场景、已有基础，或希望解决的问题。" />
                <div className="form-footer"><p>这里只保存目标，不会自动生成计划或调用模型。</p>
                  <button className="primary" disabled={busy || title.trim().length < 3}>{busy ? "正在提交…" : "保存学习目标"}</button>
                </div>
                {notice && <p className="notice" role="status">{notice}</p>}
              </form>
              <div className="results-grid">
                <section className="goal-list" aria-labelledby="saved-heading">
                  <div className="section-heading"><h2 id="saved-heading">已保存的目标</h2>
                    <button className="text-button" onClick={() => setRefresh((value) => value + 1)}>重新同步</button></div>
                  {!snapshot ? <p className="empty">正在读取服务端状态…</p> : snapshot.goals.length === 0 ? (
                    <p className="empty">还没有保存的目标。提交后，目标会出现在这里。</p>
                  ) : <ul>{snapshot.goals.map((goal) => <li key={goal.id}>
                    <div className="goal-heading"><h3>{goal.title}</h3><span className="saved-state">已保存</span></div>
                    {goal.motivation && <p>{goal.motivation}</p>}
                    <time dateTime={goal.created_at}>{date.format(new Date(goal.created_at))}</time>
                  </li>)}</ul>}
                  {snapshot && snapshot.jobs.some((job) => job.status !== "succeeded") && (
                    <div className="pending-jobs" aria-label="未完成的后台任务">
                      {snapshot.jobs.filter((job) => job.status !== "succeeded").map((job) => (
                        <p key={job.id}><code>{job.id.slice(0, 8)}</code>
                          {job.status === "queued" ? "等待后台处理" : `未完成：${job.error_code}`}</p>
                      ))}
                    </div>
                  )}
                </section>
                <section className="activity" aria-labelledby="activity-heading">
                  <h2 id="activity-heading">处理动态</h2>
                  <p className="activity-caption">来自服务端的已提交事件</p>
                  {events.length === 0 ? <p className="empty">提交目标后，这里会显示处理过程。</p> : (
                    <ol>{events.slice().reverse().map((event) => <li key={event.event_id}>
                      <span>{labels[event.event_type]}</span><time dateTime={event.occurred_at}>{date.format(new Date(event.occurred_at))}</time>
                    </li>)}</ol>
                  )}
                </section>
              </div>
              {snapshot && <TutorPanel session={session} snapshot={snapshot}
                presentation={tutorPresentation}
                onUpdated={() => setRefresh((value) => value + 1)} />}
              {snapshot && <JourneyPanel session={session} snapshot={snapshot}
                onUpdated={() => setRefresh((value) => value + 1)} />}
              {snapshot && <SourcesPanel session={session} snapshot={snapshot}
                onUpdated={() => setRefresh((value) => value + 1)} />}
              {snapshot && <ReviewPanel session={session} snapshot={snapshot}
                onUpdated={() => setRefresh((value) => value + 1)} />}
              {snapshot && <footer className="workspace-footer">显示最近 {snapshot.limit} 个目标与任务 · 状态来自独立 PostgreSQL 数据库</footer>}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
