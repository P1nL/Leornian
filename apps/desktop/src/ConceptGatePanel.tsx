import { useEffect, useState } from "react";
import { explain, request } from "./api";
import type { GateSummary, GateView, Session } from "./api";

const status: Record<GateSummary["status"], string> = {
  submitted: "执行程序已提交，等待评分",
  preparing: "正在检查考核与实际曝光的独立性", ready: "独立性检查通过，可以开始",
  in_progress: "概念考核进行中", passed: "本节点概念 Gate 已通过",
  not_passed: "本次未全部通过", blocked: "当前考核不满足独立性或有效性条件",
  cancelled: "本次考核已取消",
};

function storedKey(storage: string, body: string) {
  try {
    const previous = JSON.parse(localStorage.getItem(storage) ?? "null") as { body: string; key: string } | null;
    if (previous?.body === body) return previous.key;
  } catch { /* A corrupt local draft cannot change the server's submission identity. */ }
  const key = crypto.randomUUID();
  localStorage.setItem(storage, JSON.stringify({ body, key }));
  return key;
}

export function ConceptGatePanel({ session, packId, revision, gates, eligible, modelReady,
  hasActiveRun, examActive, sourcesCurrent, onUpdated }: {
  session: Session; packId: string; revision: number; gates: GateSummary[];
  eligible: boolean; modelReady: boolean; hasActiveRun: boolean; examActive: boolean;
  sourcesCurrent: boolean; onUpdated: () => void;
}) {
  const history = gates.filter((item) => item.pack_id === packId);
  const gate = history[0];
  const used = history.some((item) => Boolean(item.started_at));
  const [view, setView] = useState<GateView | null>(null);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    setView(null); setSelected({});
    if (!gate) return;
    const controller = new AbortController();
    void request<GateView>(`/v1/concept-gates/${gate.id}`, session.token, { signal: controller.signal })
      .then(setView).catch((problem: unknown) => {
        if (!controller.signal.aborted) setError(explain(problem));
      });
    return () => controller.abort();
  }, [gate?.id, gate?.status, session.token, refresh]);

  async function prepare() {
    setBusy(true); setError("");
    const storage = `leornian.pending-gate.v1:${session.actor.id}:${packId}`;
    const body = JSON.stringify({ expected_plan_revision: revision });
    try {
      await request<GateSummary>(`/v1/packs/${packId}/gate-requests`, session.token, {
        method: "POST", headers: { "Idempotency-Key": storedKey(storage, body) }, body,
      });
      localStorage.removeItem(storage); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function action(verb: "start" | "cancel" | "submissions") {
    if (!gate) return;
    setBusy(true); setError("");
    const answers = ["assessment_1", "assessment_2"].map((slot) => ({ slot, selected_key: selected[slot] }));
    const body = JSON.stringify({ answers });
    const storage = `leornian.pending-gate-answer.v1:${session.actor.id}:${gate.id}`;
    try {
      const result = await request<GateView>(`/v1/concept-gates/${gate.id}/${verb}`, session.token, {
        method: "POST", ...(verb === "submissions" ? {
          headers: { "Idempotency-Key": storedKey(storage, body) }, body,
        } : {}),
      });
      if (verb === "submissions") localStorage.removeItem(storage);
      setView(result); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="concept-gate" aria-label="节点概念考核">
    <div className="section-heading"><h4>检验这个节点的概念理解</h4>
      {gate && <button className="text-button" disabled={busy}
        onClick={() => setRefresh((value) => value + 1)}>同步考核状态</button>}</div>
    <p>两道保留题一起提交，全部正确才记录本节点的概念证据。它不代表代码执行能力或整门语言掌握。</p>
    {gate && <p role="status">{status[gate.status]}{view?.blocked_reason ? " · 绑定版本或曝光已变化，请取消后重新准备。" : ""}
      {gate.error_code ? ` · ${gate.error_code}` : ""}</p>}
    {gate?.error_code === "assessment_not_independent" && <p className="plan-version-note">
      题目与已学内容不够独立。请修订题包；相同材料的失败报告会保留，不通过重复准备改变结论。</p>}
    {(!gate || ["blocked", "cancelled"].includes(gate.status)) && !used &&
      <button className="primary" disabled={busy || !eligible || !modelReady || hasActiveRun || examActive || !sourcesCurrent}
        onClick={() => void prepare()}>{gate?.status === "blocked" ? "检查变更后的考核上下文" : "准备概念 Gate"}</button>}
    {!eligible && !used && <p className="plan-version-note">先生成本节点课时、提交两道练习，并完成已分配的补救。练习和补救本身不算独立证据。</p>}
    {view?.allowed_actions.includes("start") && <button className="primary" disabled={busy || !sourcesCurrent || hasActiveRun}
      onClick={() => void action("start")}>开始一次性考核</button>}
    {view?.questions.map((question) => {
      const result = view.results.find((item) => item.slot === question.slot);
      return <section className="choice-question" key={question.slot}>
        <h4>{question.title}</h4><p className="choice-prompt">{question.prompt}</p>
        <fieldset disabled={busy || !view.allowed_actions.includes("submit") || !sourcesCurrent}>
          <legend>选择一个答案</legend>
          {"options" in question && question.options.map((option) => <label className="choice-option" key={option.key}>
            <input type="radio" name={`${gate!.id}-${question.slot}`}
              checked={(result?.selected_key ?? selected[question.slot]) === option.key}
              onChange={() => setSelected((previous) => ({ ...previous, [question.slot]: option.key }))} />
            <span>{option.key} · {option.text}</span>
          </label>)}
        </fieldset>
        {result && <div className="choice-feedback"><strong>{result.correct ? "回答正确" : "本题未通过"}</strong>
          <p>{result.explanation}</p></div>}
      </section>;
    })}
    {view?.allowed_actions.includes("submit") && <>
      <p className="plan-version-note">考核期间暂停 Tutor 请求和新的训练题。请独立作答；取消不会恢复这组题的独立性。</p>
      <button className="primary" disabled={busy || !sourcesCurrent || !selected.assessment_1 || !selected.assessment_2}
        onClick={() => void action("submissions")}>一起提交两道考核</button>
    </>}
    {view?.allowed_actions.includes("cancel") && <button className="text-button" disabled={busy}
      onClick={() => void action("cancel")}>取消这次考核</button>}
    {used && ["cancelled", "not_passed"].includes(gate?.status ?? "") &&
      <p className="plan-version-note">这组考核题已曝光，不能原题重考。保留结果，改用新审核题包。</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
