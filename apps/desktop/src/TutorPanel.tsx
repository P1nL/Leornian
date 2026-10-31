import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, explain, request } from "./api";
import type { Conversation, ModelAvailability, Run, Session, Snapshot, TurnAccepted } from "./api";
import { PlanOutline } from "./PlanOutline";

const pendingKey = "leornian.pending-turn.v1";
type Purpose = "teaching" | "planning";
type Pending = { key: string; actorId: string; goalId: string; text: string;
  purpose?: Purpose; expectedRevision?: number };
const statusText: Record<Run["status"], string> = {
  queued: "已接收，等待 Tutor",
  running: "Tutor 正在处理",
  succeeded: "教学回复已保存",
  failed: "这轮未完成",
  cancelled: "已取消，不再继续本轮教学",
  blocked_unknown: "模型调用结果未知，已停止；不会自动重发",
};

function pendingDraft(): Pending | null {
  try { return JSON.parse(localStorage.getItem(pendingKey) ?? "null") as Pending | null; }
  catch { return null; }
}

export function TutorPanel({ session, snapshot, onUpdated }: {
  session: Session; snapshot: Snapshot; onUpdated: () => void;
}) {
  const draft = pendingDraft();
  const [goalId, setGoalId] = useState(draft?.actorId === session.actor.id ? draft.goalId : "");
  const [text, setText] = useState(draft?.actorId === session.actor.id ? draft.text : "");
  const [purpose, setPurpose] = useState<Purpose>(draft?.actorId === session.actor.id
    ? draft.purpose ?? "teaching" : "teaching");
  const [availability, setAvailability] = useState<ModelAvailability | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [availabilityRefresh, setAvailabilityRefresh] = useState(0);
  const goal = snapshot.goals.find((item) => item.id === goalId) ?? snapshot.goals[0];
  const conversation = snapshot.conversations.find((item) => item.goal_id === goal?.id);
  const turns = snapshot.turns.find((item) => item.conversation_id === conversation?.id)?.turns ?? [];
  const runs = snapshot.runs.filter((item) => item.conversation_id === conversation?.id);
  const active = runs.find((item) => ["queued", "running", "blocked_unknown"].includes(item.status));
  const plan = snapshot.plans.find((item) => item.goal_id === goal?.id);

  useEffect(() => {
    const controller = new AbortController();
    setAvailability(null);
    void request<ModelAvailability>("/v1/tutor/availability", session.token, {
      signal: controller.signal,
    }).then(setAvailability).catch((problem: unknown) => {
      if (!controller.signal.aborted) setError(explain(problem));
    });
    return () => controller.abort();
  }, [session.token, availabilityRefresh]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!goal || !text.trim() || active) return;
    setBusy(true); setError("");
    const previous = pendingDraft();
    const pending = previous?.actorId === session.actor.id && previous.goalId === goal.id
      && previous.text === text.trim() && (previous.purpose ?? "teaching") === purpose ? previous : {
        key: crypto.randomUUID(), actorId: session.actor.id, goalId: goal.id, text: text.trim(),
        purpose, expectedRevision: plan?.latest.revision ?? 0,
      };
    localStorage.setItem(pendingKey, JSON.stringify(pending));
    try {
      const selected = conversation ?? await request<Conversation>("/v1/conversations", session.token, {
        method: "POST", body: JSON.stringify({ goal_id: goal.id }),
      });
      const endpoint = purpose === "planning" ? "plan-requests" : "turns";
      await request<TurnAccepted>(`/v1/conversations/${selected.id}/${endpoint}`, session.token, {
        method: "POST", headers: { "Idempotency-Key": pending.key },
        body: JSON.stringify({ text: pending.text, ...(purpose === "planning"
          ? { expected_revision: pending.expectedRevision ?? plan?.latest.revision ?? 0 } : {}) }),
      });
      localStorage.removeItem(pendingKey);
      setText("");
      onUpdated();
    } catch (problem) {
      if (problem instanceof ApiError && problem.code === "stale_version") {
        localStorage.removeItem(pendingKey); onUpdated();
      }
      setError(explain(problem));
    }
    finally { setBusy(false); }
  }

  async function action(run: Run, verb: "cancel" | "resume") {
    setBusy(true); setError("");
    try {
      await request<Run>(`/v1/runs/${run.id}/${verb}`, session.token, { method: "POST" });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="tutor-workspace" aria-labelledby="tutor-heading">
    <div className="section-heading">
      <h2 id="tutor-heading">和 Tutor 一起开始</h2>
      <button className="text-button" onClick={() => {
        setAvailabilityRefresh((value) => value + 1); onUpdated();
      }}>检查连接</button>
    </div>
    <p className="tutor-description">围绕目标提问，或生成可修订的学习路线。确认路线后，可为有来源的节点生成课时；正文生成不代表练习通过或掌握。</p>
    {!goal ? <p className="empty">先保存一个学习目标，再开始教学对话。</p> : <>
      <label htmlFor="tutor-goal">本次学习目标</label>
      <select id="tutor-goal" value={goal.id} disabled={busy} onChange={(event) => {
        setGoalId(event.target.value); setError("");
      }}>
        {snapshot.goals.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <p className="model-status" role="status">{!availability ? "正在检查模型配置…" : availability.ready
        ? "独立模型已配置；提交会发送当前目标、路线、课时、反馈、准入摘录及必要对话。"
        : "尚未配置并启用 Leornian 独立模型。不会发送请求，也不会生成模拟教学回复。"}</p>
      <div className="teaching-history" aria-label="教学对话">
        {turns.length === 0 ? <p className="empty">例如，问问 Tutor：为了做出这个小工具，我应该先理解什么？</p>
          : turns.map((turn) => {
            const run = runs.find((item) => item.turn_id === turn.id);
            return <article className="teaching-turn" key={turn.id}>
              <h3>{turn.purpose === "planning" ? "你 · 制定计划" : turn.purpose === "lesson" ? "你 · 生成课时" : "你"}</h3><p>{turn.user_text}</p>
              {turn.assistant_text && <><h3>Tutor</h3><p className="teaching-answer">{turn.assistant_text}</p></>}
              {run && <div className="run-status" role="status">
                <span>{run.purpose === "planning" && run.status === "succeeded" ? "计划草案已保存，确认状态以下方路线为准"
                  : run.purpose === "lesson" && run.status === "succeeded" ? "课时正文已保存，未写学习完成" : statusText[run.status]}
                  {run.tool_count > 0 ? ` · 已读取学习上下文 ${run.tool_count} 次` : ""}</span>
                {run.error_code && <small>原因：{run.error_code}</small>}
              </div>}
            </article>;
          })}
      </div>
      {plan && <PlanOutline key={plan.id} plan={plan} session={session} sources={snapshot.sources}
        lessons={snapshot.lessons} modelReady={Boolean(availability?.ready)} hasActiveRun={Boolean(active)}
        busy={busy} setBusy={setBusy} onUpdated={onUpdated} />}
      {active && <div className="run-actions">
        {active.can_resume && <button className="primary" disabled={busy}
          onClick={() => void action(active, "resume")}>承接已记录的回执</button>}
        <button className="text-button" disabled={busy} onClick={() => void action(active, "cancel")}>取消本轮</button>
        {active.status === "blocked_unknown" && <p>取消只停止本地后续动作，不代表供应商未执行或未计费。</p>}
      </div>}
      <form onSubmit={submit} className="tutor-composer">
        <label htmlFor="tutor-purpose">这次想做什么</label>
        <select id="tutor-purpose" value={purpose} disabled={busy || Boolean(active)}
          onChange={(event) => { setPurpose(event.target.value as Purpose); setError(""); }}>
          <option value="teaching">围绕当前学习提问</option>
          <option value="planning">生成或修订学习路线</option>
        </select>
        <label htmlFor="tutor-message">{purpose === "planning" ? "你的基础、时间投入与路线要求" : "想问 Tutor 什么？"}</label>
        <textarea id="tutor-message" required maxLength={4000} rows={3} value={text}
          disabled={busy || Boolean(active)} onChange={(event) => setText(event.target.value)}
          placeholder={purpose === "planning" ? "例如：会一点循环，每天半小时。先学安全读取文件，再做整理工具。" : "说说你的问题，或希望先弄懂的知识点。"} />
        {error && <p className="error" role="alert">{error}</p>}
        <div className="form-footer"><p>{purpose === "planning"
          ? `从路线版本 ${plan?.latest.revision ?? 0} 生成新草案 · 不自动确认`
          : "唯一原生 Runtime · 仅开放只读学习上下文工具"}</p>
          <button className="primary" disabled={busy || Boolean(active) || !availability?.ready || !text.trim()}>
            {busy ? "正在提交…" : purpose === "planning" ? "生成路线草案" : "发送给 Tutor"}
          </button>
        </div>
      </form>
    </>}
  </section>;
}
