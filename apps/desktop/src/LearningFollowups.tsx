import { useState } from "react";
import { explain, request } from "./api";
import type { Evaluation, Session, Snapshot, SupplyDemand, TransferSummary } from "./api";
import { supplyStatus } from "./supply-view";

function SupplyNeed({ session, origin, demand, revision, transfer, disabled, onUpdated }: {
  session: Session; origin: { id: string; kind: "choice" | "python_io" }; demand?: SupplyDemand; revision: number;
  transfer?: TransferSummary; disabled: boolean; onUpdated: () => void;
}) {
  const [instruction, setInstruction] = useState("保持同一目标，用不同情境检验理解，避免重复已见答案。");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pack = demand?.pack;
  const failedRelation = transfer?.status === "blocked"
    && transfer.error_code === "no_independent_transfer";
  const canRevise = pack && !pack.automatic
    && (pack.status === "changes_required" || (pack.status === "published" && failedRelation));

  async function act(verb: "request" | "revise" | "publish") {
    setBusy(true); setError("");
    try {
      if (verb === "publish" && pack) {
        await request(`/v1/packs/${pack.id}/publish`, session.token, { method: "POST" });
      } else {
        const body = JSON.stringify(verb === "request" ? {
          expected_plan_revision: revision, instruction: instruction.trim(),
        } : {
          expected_pack_revision: pack!.revision, instruction: instruction.trim(),
          transfer_feedback_id: failedRelation ? transfer!.id : null,
        });
        const storage = `leornian.pending-supply.v1:${session.actor.id}:${origin.id}`;
        const saved = JSON.parse(localStorage.getItem(storage) ?? "null") as { body: string; key: string } | null;
        const key = saved?.body === body ? saved.key : crypto.randomUUID();
        localStorage.setItem(storage, JSON.stringify({ body, key }));
        const source = origin.kind === "python_io" ? "python-attempts" : "remediations";
        await request<SupplyDemand>(verb === "request"
          ? `/v1/${source}/${origin.id}/supply-requests`
          : `/v1/supply-demands/${demand!.id}/revisions`, session.token, {
          method: "POST", body, headers: { "Idempotency-Key": key },
        });
        localStorage.removeItem(storage);
      }
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <div className="followup-row">
    <h4>{demand ? "不同情境供给记录" : "没有可用后继题时，补充供给"}</h4>
    {!demand && <p>先尝试从已发布题目选择。确实缺题时，按这次错误绑定难度、来源与已见内容，持续供给到有合格后继。</p>}
    {origin.kind === "python_io" && <p>这份需求绑定已锁定的代码补救失败。新题包须通过五份盲解程序的隔离执行和六审；自动供给通过后由系统发布。</p>}
    {pack && <p role="status">供给版本 {pack.revision} · 六审 {pack.reviewed_roles.length}/6
      {pack.automatic ? ` · ${supplyStatus(pack)}`
        : pack.status === "ready" ? " · 等待你确认发布" : pack.status === "published" ? " · 已发布"
        : pack.status === "changes_required" ? " · 需要修订" : pack.status === "failed" || pack.status === "cancelled"
          ? " · 生成已停止，保留原回执" : " · 正在准备"}</p>}
    {(!demand || canRevise) && <>
      <label htmlFor={`supply-${origin.id}`}>{canRevise ? "供给修订要求" : "不同情境要求"}</label>
      <textarea id={`supply-${origin.id}`} rows={2} maxLength={1600} value={instruction}
        disabled={busy || disabled} onChange={(event) => setInstruction(event.target.value)} />
      <button className="text-button" disabled={busy || disabled || !instruction.trim()}
        onClick={() => void act(canRevise ? "revise" : "request")}>
        {busy ? "正在提交…" : canRevise ? "追加供给修订版" : "缺题时启动供给"}</button>
    </>}
    {pack?.status === "ready" && !pack.automatic && <button className="primary" disabled={busy || disabled}
      onClick={() => void act("publish")}>确认发布这版供给题包</button>}
    {pack?.status === "published" && <p>发布不等于分配。回到原错误题包的“选择不同情境的后继题”，由服务端比较实际曝光后精确分配。</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}

function ReceiptEvaluation({ session, evaluation, disabled, onUpdated }: {
  session: Session; evaluation: Evaluation; disabled: boolean; onUpdated: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function teach() {
    setBusy(true); setError("");
    try {
      await request(`/v1/evaluations/${evaluation.id}/run`, session.token, { method: "POST" });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }
  return <div className="followup-row">
    <p>{evaluation.source_kind === "transfer" ? "新情境作答" : "练习作答"} · {evaluation.correct ? "已判定正确" : "本次未通过"}
      {" · "}{new Date(evaluation.created_at).toLocaleString()}</p>
    {evaluation.document ? <>
      <p className="teaching-answer">{evaluation.document.explanation}</p>
      <p>{evaluation.document.reflection}</p>
    </> : evaluation.run_id ? <p role="status">讲评已建立；处理结果、取消和未知回执请查看上方教学回合。</p>
      : <button className="text-button" disabled={busy || disabled} onClick={() => void teach()}>
        {busy ? "正在提交…" : "请 Tutor 讲评这次作答"}</button>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}

export function LearningFollowups({ session, snapshot, planId, revision, disabled, onUpdated }: {
  session: Session; snapshot: Snapshot; planId: string; revision: number;
  disabled: boolean; onUpdated: () => void;
}) {
  const packIds = new Set(snapshot.packs.filter((p) =>
    p.plan_id === planId && p.plan_revision === revision).map((p) => p.id));
  const needs = [
    ...snapshot.remediations.filter((r) => r.transfer_required && packIds.has(r.pack_id)
      && !snapshot.transfers.some((t) => t.remediation_id === r.id && t.status === "passed"))
      .map((r) => ({ id: r.id, kind: "choice" as const })),
    ...snapshot.python_attempts.filter((a) => a.slot === "remediation_1" && !a.gate_id
      && !a.transfer_id && a.status === "not_passed" && packIds.has(a.pack_id)
      && !snapshot.transfers.some((t) => t.python_remediation_id === a.id && t.status === "passed"))
      .map((a) => ({ id: a.id, kind: "python_io" as const })),
  ];
  const evaluations = snapshot.evaluations.filter((e) => packIds.has(e.pack_id));
  if (!needs.length && !evaluations.length) return null;
  return <section className="learning-followups" aria-label="作答后的教学衔接">
    <h3>从这次作答继续</h3>
    {needs.map((r) => <SupplyNeed key={r.id} session={session} origin={r}
      demand={snapshot.supply_demands.find((d) =>
        (r.kind === "python_io" ? d.python_remediation_id : d.remediation_id) === r.id)}
      transfer={snapshot.transfers.find((t) =>
        (r.kind === "python_io" ? t.python_remediation_id : t.remediation_id) === r.id)}
      revision={revision} disabled={disabled} onUpdated={onUpdated} />)}
    {evaluations.length > 0 && <details><summary>作答讲评 · {evaluations.length} 次已锁定反馈</summary>
      <p>由你启动讲评，不抢占当前提问。建议先讲评、再选择后继题：新增教学内容会使旧后继关系报告失效。Tutor 不更改评分，也不自动打开下一题。</p>
      {evaluations.map((e) => <ReceiptEvaluation key={e.id} session={session}
        evaluation={e} disabled={disabled} onUpdated={onUpdated} />)}
    </details>}
  </section>;
}
