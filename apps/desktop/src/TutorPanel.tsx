import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, explain, request } from "./api";
import type { Conversation, DeliveryTask, ModelAvailability, Run, Session, Snapshot, TurnAccepted,
  TeachingFocus, Turn } from "./api";
import { PlanOutline } from "./PlanOutline";
import { LearningFollowups } from "./LearningFollowups";
import { ArtifactPanel } from "./ArtifactPanel";
import { ChatPane, getChatPaneView } from "./librechat/ChatPane";

const pendingKey = "leornian.pending-turn.v1";
const toolLabels: Record<string, string> = {
  learning_get_context: "读取当前上下文", list_artifacts: "列出工件",
  read_artifact: "读取指定版本", request_teaching_artifact: "申请生成工件",
  request_artifact_revision: "申请修订工件",
};
type Purpose = "teaching" | "planning";
type Pending = { key: string; actorId: string; goalId: string; text: string;
  purpose?: Purpose; expectedRevision?: number; focus?: TeachingFocus };
export const deliveryStatusText: Record<string, string> = {
  generating: "正在生成候选，尚未正式交付",
  checking: "正在验收候选，尚未正式交付",
  repairing: "正在根据问题修复，将继续推进",
  accepted: "已通过交付检查并保存",
  waiting_input: "需要补充信息",
  waiting_dependency: "等待当前来源或其他依赖恢复",
  waiting_config: "等待会话或模型配置恢复",
  blocked_unknown: "调用结果未知，不会重发；完整回执到达后才能承接",
  cancelled: "任务已取消，迟到结果只留记录",
  superseded: "绑定版本已失效，旧任务不再应用",
};
export function deliveryStatus(task: Pick<DeliveryTask, "status" | "kind">) {
  if (task.status === "accepted" && task.kind === "planning")
    return "路线草案已通过检查并保存，仍需确认使用";
  if (task.status === "accepted" && task.kind === "lesson")
    return "课时已通过检查并保存，不代表学习完成";
  if (task.status === "accepted" && task.kind === "artifact")
    return "教学工件已通过检查并保存，代码未执行";
  return deliveryStatusText[task.status] ?? task.status;
}
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

export function TutorPanel({ session, snapshot, onUpdated, presentation = "legacy" }: {
  session: Session; snapshot: Snapshot; onUpdated: () => void;
  presentation?: "legacy" | "chat";
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
  const [nodeKey, setNodeKey] = useState(draft?.actorId === session.actor.id
    ? draft.focus?.node_key ?? "" : "");
  const [receiptId, setReceiptId] = useState(draft?.actorId === session.actor.id
    ? draft.focus?.assessment_receipt_id ?? "" : "");
  const [extraInput, setExtraInput] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<{ conversationId: string; turns: Turn[] }>({
    conversationId: "", turns: [],
  });
  const [historyEnd, setHistoryEnd] = useState("");
  const goal = snapshot.goals.find((item) => item.id === goalId) ?? snapshot.goals[0];
  const conversation = snapshot.conversations.find((item) => item.goal_id === goal?.id);
  const recentTurns = snapshot.turns.find((item) => item.conversation_id === conversation?.id)?.turns ?? [];
  const turns = [
    ...(history.conversationId === conversation?.id
      ? history.turns.filter((old) => !recentTurns.some((t) => t.id === old.id)) : []),
    ...recentTurns,
  ];
  const runs = snapshot.runs.filter((item) => item.conversation_id === conversation?.id);
  const active = runs.find((item) => ["queued", "running", "blocked_unknown"].includes(item.status));
  const plan = snapshot.plans.find((item) => item.goal_id === goal?.id);
  const selectedNode = plan?.active?.document.nodes.find((n) => n.key === nodeKey);
  const feedbackOptions = snapshot.evaluations.filter((evaluation) => snapshot.packs.some((pack) =>
    pack.id === evaluation.pack_id && pack.plan_id === plan?.id &&
    pack.plan_revision === plan?.active?.revision && pack.node_key === selectedNode?.key));
  const examActive = snapshot.gates.some((item) => ["in_progress", "submitted"].includes(item.status));

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
    const focus: TeachingFocus = purpose === "teaching" && selectedNode && plan?.active ? {
      kind: receiptId ? "attempt" : "node", plan_id: plan.id,
      expected_plan_revision: plan.active.revision, node_key: selectedNode.key,
      ...(receiptId ? { assessment_receipt_id: receiptId } : {}),
    } : { kind: "goal" };
    const pending = previous?.actorId === session.actor.id && previous.goalId === goal.id
      && previous.text === text.trim() && (previous.purpose ?? "teaching") === purpose
      && JSON.stringify(previous.focus ?? { kind: "goal" }) === JSON.stringify(focus) ? previous : {
        key: crypto.randomUUID(), actorId: session.actor.id, goalId: goal.id, text: text.trim(),
        purpose, expectedRevision: plan?.latest.revision ?? 0, focus,
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
          ? { expected_revision: pending.expectedRevision ?? plan?.latest.revision ?? 0 }
          : { focus: pending.focus ?? { kind: "goal" } }) }),
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

  async function taskAction(task: DeliveryTask, verb: "cancel" | "resume") {
    setBusy(true); setError("");
    try {
      await request<DeliveryTask>(`/v1/delivery-tasks/${task.id}/${verb}`, session.token, {
        method: "POST", ...(verb === "resume"
          ? { body: JSON.stringify({ additional_instruction: extraInput[task.id] ?? "" }) } : {}),
      });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function earlierHistory() {
    if (!conversation || !turns[0]) return;
    setBusy(true); setError("");
    const conversationId = conversation.id;
    try {
      const page = await request<Turn[]>(
        `/v1/conversations/${conversationId}/history?before=${turns[0].id}&limit=50`, session.token);
      setHistory({ conversationId, turns: [...page.reverse(),
        ...(history.conversationId === conversationId ? history.turns : [])] });
      if (page.length < 50) setHistoryEnd(conversationId);
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  const heading = <>
    <div className="section-heading">
      <h2 id="tutor-heading">和 Tutor 一起开始</h2>
      <button className="text-button" onClick={() => {
        setAvailabilityRefresh((value) => value + 1); onUpdated();
      }}>检查连接</button>
    </div>
    <p className="tutor-description">围绕目标提问，或生成可修订的学习路线。确认路线后，可为有来源的节点生成课时；正文生成不代表练习通过或掌握。</p>
  </>;
  const scope = goal && <>
      <label htmlFor="tutor-goal">本次学习目标</label>
      <select id="tutor-goal" value={goal.id} disabled={busy} onChange={(event) => {
        setGoalId(event.target.value); setNodeKey(""); setReceiptId(""); setError("");
      }}>
        {snapshot.goals.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <p className="model-status" role="status">{!availability ? "正在检查模型配置…" : availability.ready
        ? "独立模型已配置；提交会发送当前目标、路线、课时、反馈、准入摘录及必要对话。"
        : "尚未配置并启用 Leornian 独立模型。不会发送请求，也不会生成模拟教学回复。"}</p>
  </>;
  const messages = <div className="teaching-history" aria-label="教学对话">
        {turns.length > 0 && historyEnd !== conversation?.id && <button className="text-button"
          disabled={busy} onClick={() => void earlierHistory()}>加载更早对话</button>}
        {turns.length === 0 ? <p className="empty">例如，问问 Tutor：为了做出这个小工具，我应该先理解什么？</p>
          : turns.map((turn) => {
            const run = runs.find((item) => item.turn_id === turn.id);
            const task = snapshot.delivery_tasks?.find((item) => item.run_id === run?.id);
            return <article className="teaching-turn" key={turn.id}>
              <h3>{turn.purpose === "planning" ? "你 · 制定计划" : turn.purpose === "lesson" ? "你 · 生成课时" : "你"}</h3><p>{turn.user_text}</p>
              {turn.assistant_text && <><h3>Tutor</h3><p className="teaching-answer">
                {run?.purpose === "artifact" ? "合格工件已保存，请在教学工件区域打开对应版本。" : turn.assistant_text}
              </p></>}
              {run && <div className="run-status" role="status">
                <span>{task ? deliveryStatus(task)
                  : run.purpose === "planning" && run.status === "succeeded" ? "计划草案已保存，确认状态以下方路线为准"
                  : run.purpose === "lesson" && run.status === "succeeded" ? "课时正文已保存，未写学习完成"
                  : run.purpose === "gate" && run.status === "succeeded" ? "考核关系报告已保存，可用动作以 Gate 状态为准"
                  : run.purpose === "transfer" && run.status === "succeeded" ? "新情境后继检查已保存，未写学习完成"
                  : run.purpose === "item_supply" && run.status === "succeeded" ? "题包阶段已保存，整体状态以下方为准" : statusText[run.status]}
                  {run.tool_count > 0 ? ` · 已执行工具 ${run.tool_count} 次` : ""}</span>
                {run.error_code && <small>原因：{run.error_code}</small>}
              </div>}
              {(snapshot.tool_activities ?? []).some((item) => item.run_id === run?.id) &&
                <ul className="tool-activities" aria-label="本轮工具进度">
                  {(snapshot.tool_activities ?? []).filter((item) => item.run_id === run?.id)
                    .slice().reverse().map((item) => <li key={item.id}>
                      {toolLabels[item.name] ?? item.name}
                      {" · "}{item.outcome === "accepted" ? "后台任务已接收，尚未交付"
                        : item.outcome === "completed" ? "已完成"
                        : item.outcome === "conflict" ? "版本或命令冲突，需重新读取"
                        : "未执行，已返回可处理的问题"} · {item.duration_ms} ms
                    </li>)}
                </ul>}
              {task && !["accepted", "cancelled", "superseded"].includes(task.status) &&
                <div className="run-actions">
                  {task.required_input?.map((question, i) => <p key={i}>{question}</p>)}
                  {task.status === "waiting_input" && <>
                    <label htmlFor={`delivery-input-${task.id}`}>补充这次交付需要的信息</label>
                    <textarea id={`delivery-input-${task.id}`} maxLength={4000} rows={2}
                      value={extraInput[task.id] ?? ""} disabled={busy}
                      onChange={(e) => setExtraInput({ ...extraInput, [task.id]: e.target.value })} />
                  </>}
                  {(task.can_resume || run?.can_resume) && <button className="text-button"
                    disabled={busy || (task.status === "waiting_input" && !extraInput[task.id]?.trim())}
                    onClick={() => void taskAction(task, "resume")}>承接原交付任务</button>}
                  <button className="text-button" disabled={busy}
                    onClick={() => void taskAction(task, "cancel")}>取消交付任务</button>
                </div>}
            </article>;
          })}
      </div>;
  const learningContext = <>
      {conversation && <ArtifactPanel key={`${conversation.id}:${nodeKey}:${receiptId}`}
        session={session} snapshot={snapshot} conversation={conversation}
        focus={selectedNode && plan?.active ? {
          kind: receiptId ? "attempt" : "node", plan_id: plan.id,
          expected_plan_revision: plan.active.revision, node_key: selectedNode.key,
          ...(receiptId ? { assessment_receipt_id: receiptId } : {}),
        } : { kind: "goal" }}
        disabled={busy || examActive || !availability?.ready} onUpdated={onUpdated} />}
      {plan && <PlanOutline key={plan.id} plan={plan} session={session} sources={snapshot.sources}
        lessons={snapshot.lessons} packs={snapshot.packs} results={snapshot.choice_results}
        remediations={snapshot.remediations} gates={snapshot.gates} transfers={snapshot.transfers}
        progress={snapshot.node_progress} pythonAttempts={snapshot.python_attempts} examActive={examActive}
        modelReady={Boolean(availability?.ready)} hasActiveRun={Boolean(active)}
        busy={busy} setBusy={setBusy} onUpdated={onUpdated} />}
      {plan?.active && <LearningFollowups key={plan.id} session={session} snapshot={snapshot}
        planId={plan.id} revision={plan.active.revision}
        disabled={busy || Boolean(active) || examActive || !availability?.ready}
        onUpdated={onUpdated} />}
  </>;
  const runActions = active && !snapshot.delivery_tasks?.some((task) => task.run_id === active.id) && <div className="run-actions">
        {active.can_resume && <button className="primary" disabled={busy}
          onClick={() => void action(active, "resume")}>承接已记录的回执</button>}
        <button className="text-button" disabled={busy} onClick={() => void action(active, "cancel")}>取消本轮</button>
        {active.status === "blocked_unknown" && <p>取消只停止本地后续动作，不代表供应商未执行或未计费。</p>}
      </div>;
  const composer = <form onSubmit={submit} className="tutor-composer">
        {examActive && <p className="plan-version-note">概念考核进行中。请先提交或取消考核，再继续 Tutor 对话。</p>}
        <label htmlFor="tutor-purpose">这次想做什么</label>
        <select id="tutor-purpose" value={purpose} disabled={busy || Boolean(active) || examActive}
          onChange={(event) => { setPurpose(event.target.value as Purpose); setError(""); }}>
          <option value="teaching">围绕当前学习提问</option>
          <option value="planning">生成或修订学习路线</option>
        </select>
        {purpose === "teaching" && plan?.active && <>
          <label htmlFor="tutor-node">这次针对哪个节点</label>
          <select id="tutor-node" value={selectedNode?.key ?? ""}
            disabled={busy || Boolean(active) || examActive} onChange={(e) => {
              setNodeKey(e.target.value); setReceiptId("");
            }}>
            <option value="">目标范围问答（不自动选择最新课时）</option>
            {plan.active.document.nodes.map((node) =>
              <option key={node.key} value={node.key}>{node.title}</option>)}
          </select>
          {selectedNode && feedbackOptions.length > 0 && <>
            <label htmlFor="tutor-receipt">关联已公开作答反馈</label>
            <select id="tutor-receipt" value={receiptId}
              disabled={busy || Boolean(active) || examActive}
              onChange={(e) => setReceiptId(e.target.value)}>
              <option value="">只针对节点讲解</option>
              {feedbackOptions.map((feedback) => <option key={feedback.id} value={feedback.source_id}>
                {feedback.source_kind} · {feedback.correct ? "已通过作答" : "未通过作答"} · {feedback.source_id.slice(0, 8)}
              </option>)}
            </select>
          </>}
        </>}
        <label htmlFor="tutor-message">{purpose === "planning" ? "你的基础、时间投入与路线要求" : "想问 Tutor 什么？"}</label>
        <textarea id="tutor-message" required maxLength={4000} rows={3} value={text}
          disabled={busy || Boolean(active) || examActive} onChange={(event) => setText(event.target.value)}
          placeholder={purpose === "planning" ? "例如：会一点循环，每天半小时。先学安全读取文件，再做整理工具。" : "说说你的问题，或希望先弄懂的知识点。"} />
        {error && <p className="error" role="alert">{error}</p>}
        <div className="form-footer"><p>{purpose === "planning"
          ? `从路线版本 ${plan?.latest.revision ?? 0} 生成新草案 · 不自动确认`
          : "精确绑定学习上下文 · 候选验收后交付"}</p>
          <button className="primary" disabled={busy || Boolean(active) || examActive || !availability?.ready || !text.trim()}>
            {busy ? "正在提交…" : purpose === "planning" ? "生成路线草案" : "发送给 Tutor"}
          </button>
        </div>
      </form>;
  if (presentation === "chat" && goal) {
    return <ChatPane labelledBy="tutor-heading"
      view={getChatPaneView({ hasMessages: turns.length > 0, isLoading: false })}
      header={<>{heading}{scope}</>} messages={messages} landing={messages}
      composer={<>{runActions}{composer}</>}
      footer={conversation || plan ? learningContext : null} />;
  }
  return <section className="tutor-workspace" aria-labelledby="tutor-heading">
    {heading}
    {!goal ? <p className="empty">先保存一个学习目标，再开始教学对话。</p> : <>
      {scope}{messages}{learningContext}{runActions}{composer}
    </>}
  </section>;
}
