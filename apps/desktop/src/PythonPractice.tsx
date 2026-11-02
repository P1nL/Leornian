import { useEffect, useState } from "react";
import { explain, request } from "./api";
import type { GateSummary, GateView, PackSummary, PythonAttempt, PythonQuestion, Session } from "./api";
import type { TransferSummary } from "./api";
import { PythonTask } from "./PythonTask";
import { TransferPanel } from "./TransferPanel";

function requestKey(storage: string, body: string) {
  try {
    const previous = JSON.parse(localStorage.getItem(storage) ?? "null") as { body: string; key: string } | null;
    if (previous?.body === body) return previous.key;
  } catch { /* Local drafts cannot authorize another server submission. */ }
  const key = crypto.randomUUID();
  localStorage.setItem(storage, JSON.stringify({ key, body }));
  return key;
}

function ExecutionGate({ session, pack, gate, attempts, eligible, disabled, modelReady, onUpdated }: {
  session: Session; pack: PackSummary; gate?: GateSummary; attempts: PythonAttempt[];
  eligible: boolean; disabled: boolean; modelReady: boolean; onUpdated: () => void;
}) {
  const [view, setView] = useState<GateView | null>(null);
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!gate) { setView(null); return; }
    const controller = new AbortController();
    void request<GateView>(`/v1/concept-gates/${gate.id}`, session.token, { signal: controller.signal })
      .then(setView).catch((problem: unknown) => {
        if (!controller.signal.aborted) setError(explain(problem));
      });
    return () => controller.abort();
  }, [gate?.id, gate?.status, session.token]);
  const questions = view?.questions.filter((q): q is PythonQuestion => "starter_code" in q) ?? [];
  const allCodes = questions.length === 2 && questions.every((q) => {
    const code = codes[q.slot] ?? q.starter_code;
    return code.trim() && new TextEncoder().encode(code).length <= 12000;
  });
  async function act(verb: "prepare" | "start" | "execution-submissions" | "cancel") {
    setBusy(true); setError("");
    const storage = `leornian.pending-python-gate.v1:${session.actor.id}:${gate?.id ?? pack.id}:${verb}`;
    const body = JSON.stringify(verb === "prepare" ? { expected_plan_revision: pack.plan_revision } : {
      programs: questions.map((q) => ({ slot: q.slot, code: codes[q.slot] ?? q.starter_code })),
    });
    try {
      await request(verb === "prepare" ? `/v1/packs/${pack.id}/execution-gate-requests`
        : `/v1/concept-gates/${gate!.id}/${verb}`, session.token, {
        method: "POST", ...(["prepare", "execution-submissions"].includes(verb) ? {
          body, headers: { "Idempotency-Key": requestKey(storage, body) },
        } : {}),
      });
      localStorage.removeItem(storage); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }
  const states: Record<GateSummary["status"], string> = {
    preparing: "正在检查实际曝光与教学内容的独立性", ready: "独立性报告齐备，等待明确开考",
    in_progress: "考核进行中：两份程序须一起提交", submitted: "程序已锁定，等待隔离执行与服务端评分",
    passed: "两道执行考核的全部绑定用例通过", not_passed: "本次执行 Gate 未通过，不原题重考",
    blocked: "考核独立性未通过，需修订材料", cancelled: "本次考核已取消",
  };
  return <section className="concept-gate" aria-label="Python 动态执行 Gate">
    <h4>独立写出程序</h4>
    <p>检查所有已见内容后再开考。开考后暂停 Tutor 与训练，两份程序一起锁定，六组绑定用例全部通过才记录本节点执行证据。</p>
    {gate && <p role="status">{states[gate.status]}</p>}
    {!gate && <button className="text-button" disabled={busy || disabled || !eligible || !modelReady}
      onClick={() => void act("prepare")}>检查执行考核独立性</button>}
    {view?.allowed_actions.includes("start") && <button className="primary" disabled={busy || disabled}
      onClick={() => void act("start")}>开始这次执行 Gate</button>}
    {questions.map((q) => <PythonTask key={q.slot} scope={`gate-${gate!.id}`} question={q} code={
      attempts.find((a) => a.gate_id === gate?.id && a.slot === q.slot)?.code
        ?? codes[q.slot] ?? q.starter_code}
      onChange={(value) => setCodes((old) => ({ ...old, [q.slot]: value }))}
      locked={busy || disabled || !view?.allowed_actions.includes("submit")} />)}
    {view?.allowed_actions.includes("submit") && <button className="primary" disabled={busy || disabled || !allCodes}
      onClick={() => void act("execution-submissions")}>锁定并提交两份考核程序</button>}
    {view?.allowed_actions.includes("cancel") && <button className="text-button" disabled={busy}
      onClick={() => void act("cancel")}>取消本次考核</button>}
    {["passed", "not_passed"].includes(gate?.status ?? "") && attempts.filter((a) => a.gate_id === gate!.id)
      .map((a) => <p key={a.id}>{a.slot} · {a.passed_cases}/{a.total_cases} · {a.feedback}</p>)}
    {view?.blocked_reason && <p className="plan-version-note">材料或教学上下文已变化。保留报告，请取消这次失效考核。</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}

export function PythonPractice({ session, pack, attempts, gates, sourcesCurrent, examActive,
  hasActiveRun, modelReady, lessonAvailable, transfers = [], onUpdated }: {
  session: Session; pack: PackSummary; attempts: PythonAttempt[]; gates: GateSummary[];
  sourcesCurrent: boolean; examActive: boolean; hasActiveRun: boolean; modelReady: boolean;
  lessonAvailable: boolean; onUpdated: () => void;
  transfers?: TransferSummary[];
}) {
  const [questions, setQuestions] = useState<PythonQuestion[]>([]);
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const training = attempts.filter((a) => a.pack_id === pack.id && !a.gate_id && !a.transfer_id);
  const practices = training.filter((a) => a.slot.startsWith("practice_"));
  const remediation = training.find((a) => a.slot === "remediation_1");
  const gate = gates.find((g) => g.pack_id === pack.id);
  const eligible = lessonAvailable && practices.length === 2
    && practices.every((a) => ["passed", "not_passed"].includes(a.status))
    && (practices.every((a) => a.status === "passed")
      || remediation?.status === "passed"
      || (remediation?.status === "not_passed" && transfers.some((t) =>
        t.python_remediation_id === remediation.id && t.status === "passed")));
  async function open(remediation: boolean) {
    setBusy(true); setError("");
    try {
      const result = await request<PythonQuestion[]>(`/v1/packs/${pack.id}/${remediation
        ? "execution-remediation" : "execution-practice"}`, session.token,
      remediation ? { method: "POST" } : {});
      setQuestions((old) => remediation ? [
        ...old.filter((q) => q.slot !== "remediation_1"), ...result,
      ] : result);
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }
  async function submit(question: PythonQuestion) {
    const code = codes[question.slot] ?? question.starter_code;
    const body = JSON.stringify({ slot: question.slot, code });
    const storage = `leornian.pending-python.v1:${session.actor.id}:${pack.id}:${question.slot}`;
    setBusy(true); setError("");
    try {
      await request<PythonAttempt>(`/v1/packs/${pack.id}/execution-submissions`, session.token, {
        method: "POST", body, headers: { "Idempotency-Key": requestKey(storage, body) },
      });
      localStorage.removeItem(storage); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }
  return <div className="python-practice">
    <p>每道训练程序只提交一次。Runner 不持有正确输出；评分在服务端完成，不把 exit 0 当作通过。</p>
    <button className="text-button" disabled={busy || examActive || !sourcesCurrent}
      onClick={() => void open(false)}>打开两道 Python 练习</button>
    {practices.some((a) => a.status === "not_passed") && <button className="text-button"
      disabled={busy || examActive || !sourcesCurrent} onClick={() => void open(true)}>打开分配的执行补救题</button>}
    {questions.map((q) => {
      const attempt = training.find((a) => a.slot === q.slot);
      const code = attempt?.code ?? codes[q.slot] ?? q.starter_code;
      return <div key={q.slot}>
        <PythonTask scope={`practice-${pack.id}`} question={q} code={code}
          onChange={(value) => setCodes((old) => ({ ...old, [q.slot]: value }))}
          locked={busy || examActive || !sourcesCurrent || Boolean(attempt)} />
        {attempt ? <p role="status">{attempt.status === "queued" ? "程序已锁定，等待隔离执行"
          : `${attempt.passed_cases}/${attempt.total_cases} · ${attempt.feedback}`}</p>
          : <button className="primary" disabled={busy || examActive || !sourcesCurrent
            || !code.trim() || new TextEncoder().encode(code).length > 12000}
          onClick={() => void submit(q)}>锁定并提交这道程序</button>}
      </div>;
    })}
    {error && <p className="error" role="alert">{error}</p>}
    {remediation?.status === "not_passed" && <TransferPanel key={remediation.id}
      session={session} remediation={remediation} kind="python_io" revision={pack.plan_revision}
      transfers={transfers} modelReady={modelReady} hasActiveRun={hasActiveRun}
      examActive={examActive} sourcesCurrent={sourcesCurrent} onUpdated={onUpdated} />}
    <ExecutionGate key={gate?.id ?? pack.id} session={session}
      pack={pack} gate={gate} attempts={attempts} eligible={eligible}
      disabled={!sourcesCurrent || hasActiveRun || (examActive && !["in_progress", "submitted"].includes(gate?.status ?? ""))}
      modelReady={modelReady} onUpdated={onUpdated} />
  </div>;
}
