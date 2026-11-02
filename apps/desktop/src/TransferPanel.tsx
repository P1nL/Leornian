import { useEffect, useState } from "react";
import { explain, request } from "./api";
import type { Session, TransferSummary, TransferView } from "./api";
import { PythonTask } from "./PythonTask";

const states: Record<TransferSummary["status"], string> = {
  preparing: "正在比较已发布候选与实际已见内容",
  ready: "已选定一个不同情境的后继",
  opened: "回答这道新情境检查",
  submitted: "程序已锁定，等待隔离执行与服务端评分",
  passed: "新情境检查已通过，仍需相应的独立 Gate",
  not_passed: "本次新情境检查未通过，答案已锁定",
  blocked: "当前候选未满足新情境或有效性要求",
  cancelled: "这次后继检查已取消",
  error: "本次执行未能有效评分，保留回执，不自动重跑",
};

function pendingKey(storage: string, body: string) {
  try {
    const old = JSON.parse(localStorage.getItem(storage) ?? "null") as { body: string; key: string } | null;
    if (old?.body === body) return old.key;
  } catch { /* Server ownership and immutable receipts remain authoritative. */ }
  const key = crypto.randomUUID();
  localStorage.setItem(storage, JSON.stringify({ body, key }));
  return key;
}

export function TransferPanel({ session, remediation, revision, transfers, modelReady,
  hasActiveRun, examActive, sourcesCurrent, kind = "choice", onUpdated }: {
  session: Session; remediation: { id: string }; revision: number; transfers: TransferSummary[];
  kind?: "choice" | "python_io";
  modelReady: boolean; hasActiveRun: boolean; examActive: boolean; sourcesCurrent: boolean;
  onUpdated: () => void;
}) {
  const history = transfers.filter((item) => item.kind === kind &&
    (kind === "python_io" ? item.python_remediation_id : item.remediation_id) === remediation.id);
  const transfer = history[0];
  const used = history.some((item) => Boolean(item.opened_at));
  const [view, setView] = useState<TransferView | null>(null);
  const [selected, setSelected] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    setView(null); setSelected(""); setCode(null); setError("");
    if (!transfer) return;
    const controller = new AbortController();
    void request<TransferView>(`/v1/transfers/${transfer.id}`, session.token, { signal: controller.signal })
      .then(setView).catch((problem: unknown) => {
        if (!controller.signal.aborted) setError(explain(problem));
      });
    return () => controller.abort();
  }, [transfer?.id, transfer?.status, session.token, refresh]);

  async function prepare() {
    const body = JSON.stringify({ expected_plan_revision: revision });
    const storage = `leornian.pending-transfer.v1:${session.actor.id}:${remediation.id}`;
    setBusy(true); setError("");
    try {
      const origin = kind === "python_io" ? "python-attempts" : "remediations";
      await request<TransferSummary>(`/v1/${origin}/${remediation.id}/transfer-requests`, session.token, {
        method: "POST", body, headers: { "Idempotency-Key": pendingKey(storage, body) },
      });
      localStorage.removeItem(storage); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function action(verb: "open" | "submissions" | "cancel") {
    if (!transfer) return;
    const question = view?.question;
    const body = JSON.stringify(kind === "python_io" ? {
      code: code ?? (question && "starter_code" in question ? question.starter_code : ""),
    } : { selected_key: selected });
    const storage = `leornian.pending-transfer-answer.v1:${session.actor.id}:${transfer.id}`;
    setBusy(true); setError("");
    try {
      const action = verb === "submissions" && kind === "python_io" ? "execution-submissions" : verb;
      const result = await request<TransferView>(`/v1/transfers/${transfer.id}/${action}`, session.token, {
        method: "POST", ...(verb === "submissions" ? {
          body, headers: { "Idempotency-Key": pendingKey(storage, body) },
        } : {}),
      });
      if (verb === "submissions") localStorage.removeItem(storage);
      setView(result); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  const pythonQuestion = view?.question && "starter_code" in view.question ? view.question : null;
  const sourceCode = view?.python_attempt?.code ?? code ?? pythonQuestion?.starter_code ?? "";
  const canSubmit = kind === "choice" ? Boolean(selected)
    : Boolean(sourceCode.trim()) && new TextEncoder().encode(sourceCode).length <= 12000;
  return <section className="concept-gate" aria-label="不同情境后继检查">
    <div className="section-heading"><h4>换个情境，再检验理解</h4>
      {transfer && <button className="text-button" disabled={busy}
        onClick={() => setRefresh((value) => value + 1)}>同步后继状态</button>}</div>
    <p>原补救作答保持锁定。服务端从同一节点的已发布、未见练习中选择不同情境，不重置原题，也不直接记录掌握度。</p>
    {kind === "python_io" && <p>这次提交仍由隔离 Runner 执行。全部三组绑定用例通过只解除原补救阻断，不替代执行 Gate。</p>}
    {transfer && <p role="status">{states[transfer.status]}</p>}
    {view?.blocked_reason && <p className="plan-version-note">来源、计划或实际曝光已变化，请取消失效检查。</p>}
    {(!transfer || ["blocked", "cancelled"].includes(transfer.status)) && !used &&
      <button className="primary" disabled={busy || !sourcesCurrent || !modelReady || hasActiveRun || examActive}
        onClick={() => void prepare()}>选择不同情境的后继题</button>}
    {view?.allowed_actions.includes("open") && <button className="primary"
      disabled={busy || !sourcesCurrent || examActive} onClick={() => void action("open")}>打开已分配的新情境题</button>}
    {view?.question && "options" in view.question && <div className="choice-question">
      <h4>{view.question.title}</h4><p className="choice-prompt">{view.question.prompt}</p>
      <fieldset disabled={busy || !sourcesCurrent || examActive || !view.allowed_actions.includes("submit")}>
        <legend>选择一个答案</legend>
        {view.question.options.map((option) => <label className="choice-option" key={option.key}>
          <input type="radio" name={`transfer-${transfer!.id}`} value={option.key}
            checked={(view.result?.selected_key ?? selected) === option.key}
            onChange={() => setSelected(option.key)} /><span>{option.key} · {option.text}</span>
        </label>)}
      </fieldset>
      {view.result && <div className="choice-feedback"><strong>{view.result.correct ? "这道题回答正确" : "本题未通过"}</strong>
        <p>{view.result.explanation}</p><small>这是后继训练反馈，不是独立掌握证据。</small></div>}
    </div>}
    {pythonQuestion && <PythonTask question={pythonQuestion} scope={`transfer-${transfer!.id}`}
      code={sourceCode} onChange={setCode}
      locked={busy || !sourcesCurrent || examActive || !view?.allowed_actions.includes("submit")} />}
    {view?.python_attempt && <p role="status">{view.python_attempt.status === "queued"
      ? "等待隔离执行，尚未判分"
      : `${view.python_attempt.passed_cases}/${view.python_attempt.total_cases} · ${view.python_attempt.feedback}`}</p>}
    {view?.allowed_actions.includes("submit") && <button className="primary"
      disabled={busy || !sourcesCurrent || examActive || !canSubmit}
      onClick={() => void action("submissions")}>{kind === "python_io"
        ? "锁定并提交这道新情境程序" : "提交这道新情境检查"}</button>}
    {view?.allowed_actions.includes("cancel") && <button className="text-button" disabled={busy}
      onClick={() => void action("cancel")}>取消后继检查</button>}
    {used && ["not_passed", "cancelled", "error"].includes(transfer?.status ?? "") &&
      <p className="plan-version-note">这个精确后继已使用，不原题重试，也不自动再抽一道题。</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
