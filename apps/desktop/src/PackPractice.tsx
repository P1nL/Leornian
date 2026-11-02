import { useState } from "react";
import { explain, request } from "./api";
import type { ChoiceResult, GateSummary, PackAccepted, PackSummary, PracticeSet, PublicQuestion, Remediation, Session, TransferSummary } from "./api";
import { ConceptGatePanel } from "./ConceptGatePanel";
import { TransferPanel } from "./TransferPanel";
import { PythonPractice } from "./PythonPractice";
import type { PythonAttempt } from "./api";
import { displayedPack, supplyStatus } from "./supply-view";

const statusText: Record<PackSummary["status"], string> = {
  authoring: "正在编写五个题位", blind_solving: "正在独立盲解", reviewing: "正在分角色审核",
  qualifying: "正在隔离运行五份独立盲解程序",
  changes_required: "需要修订，未发布", ready: "审核齐备，等待发布", published: "已发布到你的学习空间",
  failed: "本版未完成", cancelled: "已取消后续生成",
};

function pendingKey(kind: string, actorId: string, target: string) {
  return `leornian.pending-${kind}.v1:${actorId}:${target}`;
}

function sameRequestKey(storageKey: string, body: string): string {
  try {
    const previous = JSON.parse(localStorage.getItem(storageKey) ?? "null") as { body: string; key: string } | null;
    if (previous?.body === body) return previous.key;
  } catch { /* An invalid local draft cannot authorize a different request. */ }
  const key = crypto.randomUUID();
  localStorage.setItem(storageKey, JSON.stringify({ body, key }));
  return key;
}

function Questions({ pack, session, results, remediation, examActive, onUpdated }: {
  pack: PackSummary; session: Session; results: ChoiceResult[]; onUpdated: () => void;
  remediation?: Remediation; examActive: boolean;
}) {
  const [practice, setPractice] = useState<PracticeSet | null>(null);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipts, setReceipts] = useState<ChoiceResult[]>([]);

  async function open() {
    setBusy(true); setError("");
    try {
      setPractice(await request<PracticeSet>(`/v1/packs/${pack.id}/practice`, session.token));
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function answer(slot: string) {
    if (!selected[slot]) return;
    setBusy(true); setError("");
    const body = JSON.stringify({ slot, selected_key: selected[slot] });
    const storage = pendingKey("choice", session.actor.id, `${pack.id}:${slot}`);
    try {
      const result = await request<ChoiceResult>(`/v1/packs/${pack.id}/answers`, session.token, {
        method: "POST", headers: { "Idempotency-Key": sameRequestKey(storage, body) }, body,
      });
      localStorage.removeItem(storage);
      setReceipts((previous) => [...previous.filter((item) => item.slot !== slot), result]);
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function openRemediation() {
    if (!remediation) return;
    setBusy(true); setError("");
    try {
      const question = await request<PublicQuestion>(`/v1/remediations/${remediation.id}/question`, session.token);
      setPractice((previous) => ({ pack_id: pack.id, questions: [
        ...(previous?.questions ?? []).filter((item) => item.slot !== "remediation_1"), question,
      ] }));
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <div className="pack-practice">
    {!practice && <button className="primary" disabled={busy || examActive} onClick={() => void open()}>
      {busy ? "正在读取…" : "打开两道练习"}</button>}
    {practice?.questions.map((question) => {
      const result = [...receipts, ...results].find((item) => item.pack_id === pack.id && item.slot === question.slot);
      return <section className="choice-question" key={question.slot}>
        <h4>{question.title}</h4><p className="choice-prompt">{question.prompt}</p>
        <fieldset disabled={busy || examActive || Boolean(result)}><legend>选择一个答案</legend>
          {question.options.map((option) => <label className="choice-option" key={option.key}>
            <input type="radio" name={`${pack.id}-${question.slot}`} value={option.key}
              checked={(result?.selected_key ?? selected[question.slot]) === option.key}
              onChange={() => setSelected((previous) => ({ ...previous, [question.slot]: option.key }))} />
            <span>{option.key} · {option.text}</span>
          </label>)}
        </fieldset>
        {result ? <div className="choice-feedback" role="status"><strong>{result.correct ? "回答正确" : "这次未答对"}</strong>
          <p>{result.explanation}</p><small>作答已锁定。练习反馈不代表独立掌握度或正式 Gate。</small></div>
          : <button className="text-button" disabled={busy || examActive || !selected[question.slot]}
            onClick={() => void answer(question.slot)}>提交这道练习</button>}
      </section>;
    })}
    {remediation && <div className="remediation-next">
      <h4>换一道题巩固理解</h4>
      <p>补救题沿用同一目标，难度不高于原练习。回答后锁定，不作为独立掌握证据。</p>
      <button className="text-button" disabled={busy || examActive}
        onClick={() => void openRemediation()}>阅读已分配的补救题</button>
      {remediation.transfer_required && <p className="plan-version-note">原补救回执已锁定。继续下方的新情境检查，不重复作答本题。</p>}
    </div>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}

export function PackPractice({ planId, revision, nodeKey, session, packs, results, sourcesCurrent,
  modelReady, hasActiveRun, remediations = [], gates = [], lessonAvailable = false,
  transfers = [], pythonAttempts = [], examActive = false, onUpdated }: {
  planId: string; revision: number; nodeKey: string; session: Session; packs: PackSummary[];
  results: ChoiceResult[]; sourcesCurrent: boolean; modelReady: boolean; hasActiveRun: boolean;
  onUpdated: () => void;
  remediations?: Remediation[]; gates?: GateSummary[]; lessonAvailable?: boolean; examActive?: boolean;
  transfers?: TransferSummary[];
  pythonAttempts?: PythonAttempt[];
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [instruction, setInstruction] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [followLatest, setFollowLatest] = useState(true);
  const [kind, setKind] = useState<PackSummary["kind"]>("choice");
  const versions = packs.filter((item) => item.plan_id === planId
    && item.plan_revision === revision && item.node_key === nodeKey);
  const pack = displayedPack(versions, selectedId, followLatest);
  const gateFailure = gates.find((item) => item.pack_id === pack?.id
    && item.status === "blocked" && item.error_code === "assessment_not_independent");
  const revisionRequired = pack?.status === "changes_required" || Boolean(gateFailure);
  const revisionAllowed = Boolean(pack && !pack.automatic && revisionRequired
    && (pack.status === "changes_required" || pack.status === "published")
    && !versions.some((item) => item.predecessor_id === pack.id));
  const automaticActive = Boolean(pack?.automatic
    && (pack.automation_status === "running" || pack.automation_status === "waiting"
      || (!pack.automation_status && !["published", "cancelled"].includes(pack.status))));
  const automationRunning = Boolean(pack?.automatic
    && (pack.automation_status ? pack.automation_status === "running" : !pack.automation_error));
  const generationBlocked = (revisionRequired && !revisionAllowed && !pack?.automatic) || automaticActive;
  const remediation = remediations.find((item) => item.pack_id === pack?.id);
  const practiceResults = results.filter((item) => item.pack_id === pack?.id && item.slot.startsWith("practice_"));
  const gateEligible = lessonAvailable && practiceResults.length === 2
    && (practiceResults.every((item) => item.correct) || remediation?.status === "passed"
      || transfers.some((item) => item.remediation_id === remediation?.id && item.status === "passed"));

  async function generate() {
    if (generationBlocked) return;
    setBusy(true); setError("");
    const body = JSON.stringify({ expected_plan_revision: revision, node_key: nodeKey,
      instruction: instruction.trim() || "围绕当前节点目标准备完整题包，使用中文，避免重复已见内容。",
      predecessor_id: revisionAllowed ? pack?.id : null,
      gate_feedback_id: revisionAllowed && pack?.status === "published" ? gateFailure?.id : null,
      kind: revisionAllowed ? pack!.kind : kind });
    const storage = pendingKey("pack", session.actor.id, `${planId}:${revision}:${nodeKey}`);
    try {
      const accepted = await request<PackAccepted>(`/v1/plans/${planId}/pack-requests`, session.token, {
        method: "POST", headers: { "Idempotency-Key": sameRequestKey(storage, body) }, body,
      });
      localStorage.removeItem(storage); setInstruction(""); setSelectedId(accepted.pack_id);
      setFollowLatest(true); onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function publish() {
    if (!pack) return;
    setBusy(true); setError("");
    try {
      await request<PackSummary>(`/v1/packs/${pack.id}/publish`, session.token, { method: "POST" });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function correctFormat() {
    if (!pack) return;
    setBusy(true); setError("");
    try {
      await request<PackSummary>(`/v1/packs/${pack.id}/review-format-correction`, session.token, { method: "POST" });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  async function controlSupply(action: "cancel" | "automation-resume") {
    if (!pack) return;
    setBusy(true); setError("");
    try {
      await request(`/v1/packs/${pack.id}/${action}`, session.token, { method: "POST" });
      onUpdated();
    } catch (problem) { setError(explain(problem)); }
    finally { setBusy(false); }
  }

  return <section className="pack-workspace" aria-label="节点概念题包">
    <h3>为这个节点准备练习</h3>
    <p>提出一次需求后，系统自动生成、独立盲解、六角色审核，并按报告修订。合格后自动发布到你的学习空间，无需逐步确认。</p>
    {versions.length > 1 && <><label htmlFor={`pack-version-${planId}`}>题包记录</label>
      <select id={`pack-version-${planId}`} value={pack?.id} disabled={busy}
        onChange={(event) => { setSelectedId(event.target.value); setFollowLatest(false); }}>
        {versions.map((item) => <option key={item.id} value={item.id}>
          {new Date(item.created_at).toLocaleString()} · {item.kind === "python_io" ? "Python 执行" : "概念单选"}
          {" · "}版本 {item.revision} · {statusText[item.status]}</option>)}
      </select>
      {!followLatest && <button className="text-button" disabled={busy}
        onClick={() => { setSelectedId(""); setFollowLatest(true); }}>返回当前供给进度</button>}
    </>}
    {pack && <><p className="pack-status" role="status">
      {automationRunning && pack.status === "ready" ? "审核齐备，系统正在自动发布"
        : automationRunning && pack.status === "changes_required"
          ? "审核要求修改，系统正在准备修订" : statusText[pack.status]} · 版本 {pack.revision}
      {` · 已收到 ${pack.reviewed_roles.length}/6 角色审核`}
      {pack.blind_passed === false ? " · 盲解与标准答案不一致" : pack.blind_passed ? " · 盲解一致" : ""}</p>
      {pack.automatic && <p className="provenance" role="status">自动供给 · {supplyStatus(pack)}。
        每版报告保留，无需手动修订或发布。</p>}
      {pack.status === "ready" && !pack.automatic && <button className="primary" disabled={busy || !sourcesCurrent}
        onClick={() => void publish()}>确认发布到我的学习空间</button>}
      {pack.kind === "choice" && pack.status === "published" && sourcesCurrent && <Questions key={pack.id} pack={pack}
        session={session} results={results} remediation={remediation} examActive={examActive} onUpdated={onUpdated} />}
      {remediation?.transfer_required && <TransferPanel key={remediation.id} session={session}
        remediation={remediation} revision={revision} transfers={transfers} modelReady={modelReady}
        hasActiveRun={hasActiveRun} examActive={examActive} sourcesCurrent={sourcesCurrent}
        onUpdated={onUpdated} />}
      {pack.kind === "python_io" && pack.status === "published" && <PythonPractice key={pack.id}
        session={session} pack={pack} attempts={pythonAttempts} gates={gates} transfers={transfers}
        sourcesCurrent={sourcesCurrent} examActive={examActive} hasActiveRun={hasActiveRun}
        modelReady={modelReady} lessonAvailable={lessonAvailable} onUpdated={onUpdated} />}
      {pack.kind === "python_io" && !pack.automatic && pack.status === "reviewing" && !pack.pending_run_id &&
        <button className="text-button" disabled={busy || hasActiveRun || examActive || !sourcesCurrent}
          onClick={() => { void request(`/v1/packs/${pack.id}/continue-review`, session.token,
            { method: "POST" }).then(onUpdated).catch((problem) => setError(explain(problem))); }}>继续六角色审核</button>}
      {pack.kind === "python_io" && !pack.automatic && pack.status === "qualifying" && <button className="text-button"
        disabled={busy} onClick={() => { void request(`/v1/packs/${pack.id}/cancel`, session.token,
          { method: "POST" }).then(onUpdated).catch((problem) => setError(explain(problem))); }}>停止后续执行与审核</button>}
      {pack.kind === "choice" && pack.status === "published" && <ConceptGatePanel key={pack.id} session={session}
        packId={pack.id} revision={revision} gates={gates} eligible={gateEligible}
        modelReady={modelReady} hasActiveRun={hasActiveRun} examActive={examActive}
        sourcesCurrent={sourcesCurrent} onUpdated={onUpdated} />}
      {gateFailure && <p className="plan-version-note">当前题包未通过实际曝光的独立性检查。
        {pack.automatic ? "系统将依据已保存报告继续实质修订，不开放本次考核。"
          : revisionAllowed ? "填写修订要求，将失败关系和原教学上下文交给作者，重新盲解与六审。旧题包和作答不会被覆盖。"
          : "本版已有后继，保留质量阻断和修订记录。"}</p>}
      {pack.gate_feedback_id && <p className="plan-version-note">这是基于 Gate 失败反馈的新版本，仍须重新盲解和完整审核；原失败与作答保留。</p>}
      {automaticActive && <button className="text-button" disabled={busy}
        onClick={() => void controlSupply("cancel")}>停止这次自动供给</button>}
      {pack.automatic && pack.automation_status === "waiting"
        && ["unauthorized", "source_not_current", "stale_version", "model_unavailable", "provider_rejected"]
          .includes(pack.automation_reason ?? "") &&
        <button className="text-button" disabled={busy || !sourcesCurrent || !modelReady}
          onClick={() => void controlSupply("automation-resume")}>条件已更新，恢复原供给</button>}
      {pack.status === "changes_required" && !pack.automatic && <p className="plan-version-note">本版保留全部报告，不会自动刷审。
        {revisionAllowed ? "填写调整要求可追加修订版，再重新盲解与审核。" : "这条修订链已结束或已有后继。"}</p>}
      {pack.status === "failed" && !pack.automatic && pack.pending_role && !["author", "blind"].includes(pack.pending_role) && <>
        <p className="plan-version-note">如果失败仅因审核理由超长，可继续追加格式补正，不按次数停止。原回执保留，已有拒绝结论不能改成通过。</p>
        <button className="text-button" disabled={busy || hasActiveRun || !modelReady || !sourcesCurrent}
          onClick={() => void correctFormat()}>尝试补正超长审核格式</button></>}
    </>}
    {!sourcesCurrent && <p className="plan-version-note">先更新这个节点的来源引用。来源失效时，不再生成、发布或打开题目。</p>}
    {!revisionAllowed && <><label htmlFor={`pack-kind-${planId}`}>新题包类型</label>
      <select id={`pack-kind-${planId}`} value={kind} disabled={busy || hasActiveRun}
        onChange={(event) => setKind(event.target.value as PackSummary["kind"])}>
        <option value="choice">概念单选 · 先理解规则</option>
        <option value="python_io">Python 执行 · JSON 数组输入、整数输出</option>
      </select>
      {kind === "python_io" && <p>五份独立盲解程序先在隔离 Runner 上验证，再进入六审。隐藏用例不发给学习者；不是任意语言或公开恶意代码生产沙箱。</p>}
    </>}
    <label htmlFor={`pack-instruction-${planId}`}>{revisionAllowed ? "修订要求" : "练习偏好（可选）"}</label>
    <textarea id={`pack-instruction-${planId}`} rows={2} maxLength={2000} value={instruction}
      disabled={busy || hasActiveRun || generationBlocked} onChange={(event) => setInstruction(event.target.value)}
      placeholder="例如：用容易混淆的真实场景检验概念，避免只换数字的重复题。" />
    <div className="form-footer"><p>后台执行八个独立角色调用。补救按错误分配，保留考核需通过曝光关系检查后明确开启。</p>
      <button className="primary" disabled={busy || hasActiveRun || generationBlocked || examActive || !sourcesCurrent || !modelReady}
        onClick={() => void generate()}>{generationBlocked ? automaticActive ? "查看当前供给进度" : "本版已有后继"
          : hasActiveRun ? "等待当前回合结束" : revisionAllowed ? "生成修订版" : "自动准备题包"}</button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
