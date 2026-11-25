import { useEffect, useState, useSyncExternalStore } from 'react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import * as UI from './LearningComponents';
import { NativeCompilation, NativeProgramPrompt } from './NativeProgramPractice';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { programTaskAnswer } from './native-practice';

type View = components['schemas']['TransferView'];
type Summary = components['schemas']['TransferSummary'];
type Demand = components['schemas']['SupplyDemand'];
type Files = components['schemas']['ProgramFile'][];
type Answer = string | Files;
type Origin = { id: string; pack_id: string; kind: 'choice' | 'python_io' | 'program'; created_at: string };
const statuses: Record<Summary['status'], string> = {
  preparing: '正在检查新情境与已见内容的关系', ready: '新情境已准备，等待明确开题',
  opened: '已开题，整份答案只能提交一次', submitted: '提交已接收，等待本机执行',
  passed: '本次新情境检查通过', not_passed: '本次新情境检查未通过',
  error: '新情境检查未完成', blocked: '等待新情境依赖', cancelled: '本次检查已取消',
};
const packStatuses: Record<string, string> = {
  authoring: '编制题目', blind_solving: '独立盲解', qualifying: '固定环境资格验证',
  reviewing: '独立审查', changes_required: '等待内容修订', ready: '等待正常发布',
  published: '已发布，可明确申请新情境检查', failed: '本次题目准备失败', cancelled: '本次题目准备已取消',
};
const initialAnswer = (question: NonNullable<View['question']>): Answer => 'options' in question ? ''
  : question.language === 'python_io' ? question.starter_code
    : question.language === 'sql_query' ? question.starter_query : question.files;
const originId = (value: Summary | Demand) =>
  value.remediation_id ?? value.python_remediation_id ?? value.program_remediation_id;

export default function NativeRecovery({ planId, planRevision, nodeKey }: {
  planId: string; planRevision: number; nodeKey: string;
}) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const snapshot = state.snapshot;
  const packs = snapshot?.packs.filter((pack) => pack.plan_id === planId &&
    pack.plan_revision === planRevision && pack.node_key === nodeKey && pack.status === 'published') ?? [];
  const packIds = new Set(packs.map((pack) => pack.id));
  const origins: Origin[] = [
    ...(snapshot?.remediations ?? []).filter((item) => packIds.has(item.pack_id) &&
      item.status === 'not_passed' && item.transfer_required).map((item) => ({ ...item, kind: 'choice' as const })),
    ...packs.flatMap<Origin>((pack) => {
      const program = [...(snapshot?.program_attempts ?? [])]
        .filter((item) => item.pack_id === pack.id && item.slot === 'remediation_1')
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
      const python = [...(snapshot?.python_attempts ?? [])]
        .filter((item) => item.pack_id === pack.id && item.slot === 'remediation_1' &&
          !item.gate_id && !item.transfer_id)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
      return program?.status === 'not_passed' ? [{ ...program, kind: 'program' as const }]
        : python?.status === 'not_passed' ? [{ ...python, kind: 'python_io' as const }] : [];
    }),
  ].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const [chosen, setChosen] = useState('');
  const origin = origins.find((item) => item.id === chosen) ?? origins[0];
  const summary = [...(snapshot?.transfers ?? [])].filter((item) => originId(item) === origin?.id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const initialDemand = [...(snapshot?.supply_demands ?? [])].filter((item) => originId(item) === origin?.id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const [view, setView] = useState<View | null>(null), [demand, setDemand] = useState<Demand | null>(null);
  const [answer, setAnswer] = useState<Answer>(''), [instruction, setInstruction] = useState('');
  const [error, setError] = useState(''), [noCandidate, setNoCandidate] = useState(false);
  const [busy, setBusy] = useState(false);
  const actorId = snapshot?.actor.id;
  const storage = actorId && summary ? `leornian.native.transfer-draft.v1:${actorId}:${summary.id}` : null;
  const pending = state.pending.filter((entry) => origins.some((item) => entry.path.includes(`/${item.id}/`)) ||
    (snapshot?.transfers ?? []).some((item) => item.plan_id === planId && item.plan_revision === planRevision &&
      item.node_key === nodeKey && entry.path.includes(`/transfers/${item.id}/`)));
  const blocked = busy || pending.length > 0;
  const adopt = (value: View) => {
    setView(value);
    if (value.question) setAnswer((current) => current || initialAnswer(value.question!));
  };
  const readView = async (id: string) => adopt(await nativeRequest(`/v1/transfers/${id}`));
  useEffect(() => {
    setView(null); setDemand(initialDemand ?? null); setAnswer(''); setError(''); setNoCandidate(false);
    let current = true;
    if (summary) void nativeRequest(`/v1/transfers/${summary.id}`).then((value: View) => {
      if (!current) return;
      setView(value);
      if (value.question) {
        let saved: Answer | null = null;
        try { saved = JSON.parse(sessionStorage.getItem(storage!) ?? 'null'); } catch { saved = null; }
        setAnswer(saved ?? initialAnswer(value.question));
      }
    }).catch((problem: Error) => { if (current) setError(problem.message); });
    return () => { current = false; };
  }, [actorId, origin?.id, summary?.id, state.epoch]);
  useEffect(() => {
    const transferPending = view && ['preparing', 'submitted', 'blocked'].includes(view.transfer.status);
    const supplyPending = demand && ['authoring', 'blind_solving', 'qualifying', 'reviewing'].includes(demand.pack.status);
    if (!transferPending && !supplyPending) return;
    const timer = setTimeout(() => {
      const reads = [
        ...(transferPending ? [readView(view!.transfer.id)] : []),
        ...(supplyPending ? [nativeRequest(`/v1/supply-demands/${demand!.id}`).then(setDemand)] : []),
      ];
      void Promise.all(reads).catch((problem: Error) => setError(problem.message));
    }, 2500);
    return () => clearTimeout(timer);
  }, [view, demand]);
  const change = (value: Answer) => {
    setAnswer(value);
    if (storage) sessionStorage.setItem(storage, JSON.stringify(value));
  };
  const receive = async (value: Summary | View | Demand) => {
    if ('transfer' in value) adopt(value);
    else if ('pack' in value) { setDemand(value); setNoCandidate(false); }
    else await readView(value.id);
  };
  const write = async (path: string, body: object, lookup: (key: string) => string) => {
    if (blocked) return;
    setBusy(true); setError('');
    const key = crypto.randomUUID();
    try { await receive(await nativeStore.write(path, body, { key, lookup: lookup(key) })); }
    catch (problem) {
      setError((problem as Error).message);
      if ((problem as { code?: string }).code === 'no_transfer_candidate') setNoCandidate(true);
    } finally { setBusy(false); }
  };
  const originRoot = origin?.kind === 'choice' ? `/v1/remediations/${origin.id}`
    : origin?.kind === 'python_io' ? `/v1/python-attempts/${origin.id}` : `/v2/program-attempts/${origin?.id}`;
  const request = () => void write(`${originRoot}/transfer-requests`,
    { expected_plan_revision: planRevision }, (key) => `/v1/transfer-requests/${key}`);
  const question = view?.question;
  const valid = question && ('options' in question ? typeof answer === 'string' && ['A', 'B', 'C', 'D'].includes(answer)
    : question.language === 'python_io' ? typeof answer === 'string' && Boolean(answer.trim()) &&
      new TextEncoder().encode(answer).length <= 12000 : Boolean(programTaskAnswer(question, answer)));
  const writable = Boolean(view?.allowed_actions.includes('submit')) && !blocked;
  const submit = () => {
    if (!question || !view || !valid) return;
    const root = 'options' in question ? `/v1/transfers/${view.transfer.id}/submissions`
      : question.language === 'python_io' ? `/v1/transfers/${view.transfer.id}/execution-submissions`
        : `/v2/transfers/${view.transfer.id}/program-submissions`;
    const body = 'options' in question ? { selected_key: answer }
      : question.language === 'python_io' ? { code: answer } : { answer: programTaskAnswer(question, answer) };
    void write(root, body, (key) => `/v1/transfers/${view.transfer.id}/submissions/${key}`);
  };
  if (!origin) return null;
  return <Disclosure title="补救后的新情境检查">
    <p className="demo-muted">沿最近一次未通过的补救，检查同一目标在不同情境中的应用。通过后可继续准备正式独立考核。</p>
    {origins.length > 1 && <label className="block text-sm">补救记录<select value={origin.id} disabled={blocked}
      onChange={(event) => setChosen(event.target.value)}>
      {origins.map((item) => <option key={item.id} value={item.id}>
        {item.kind === 'choice' ? '概念' : '执行'}补救 · {new Date(item.created_at).toLocaleString()}
      </option>)}
    </select></label>}
    {error && <Notice>{error}</Notice>}
    {(!view || ['cancelled', 'error', 'blocked'].includes(view.transfer.status)) &&
      <Action disabled={blocked} onClick={request}>准备新情境检查</Action>}
    {(noCandidate || demand) && <section className="space-y-3">
      {noCandidate && <Notice>当前没有合格的新情境候选。可以明确申请同级或更低难度题目，沿原质量流程准备。</Notice>}
      {!demand && <>
        <label className="block text-sm">补题要求<textarea className="w-full" value={instruction} maxLength={1600}
          onChange={(event) => setInstruction(event.target.value)} placeholder="描述希望练习的新应用情境" /></label>
        <Action disabled={blocked || !instruction.trim()} onClick={() => void write(
          `${originRoot}/${origin.kind === 'program' ? 'supply-demands' : 'supply-requests'}`,
          { expected_plan_revision: planRevision, instruction: instruction.trim(), automatic: true },
          (key) => `/v1/supply-requests/${key}`,
        )}>明确申请补题</Action>
      </>}
      {demand && <>
        <p role="status">补题：{packStatuses[demand.pack.status]} · 题包修订 {demand.pack.revision}</p>
        <p className="demo-muted">允许难度：{demand.allowed_difficulties.join('、')}；类型：{demand.kind}</p>
        {demand.pack.pending_run_id && <p className="demo-muted">原准备任务：{demand.pack.pending_run_id}</p>}
        <Action disabled={busy} onClick={() => {
          setBusy(true);
          void nativeRequest(`/v1/supply-demands/${demand.id}`).then(setDemand)
            .catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
        }}>读取补题进度</Action>
      </>}
    </section>}
    {view && <section className="space-y-4">
      <p role="status">{statuses[view.transfer.status]}</p>
      {(view.blocked_reason || view.transfer.error_code) && <Notice>{view.blocked_reason ?? view.transfer.error_code}</Notice>}
      {view.allowed_actions.includes('open') && <Action disabled={blocked} onClick={() => void write(
        `/v1/transfers/${view.transfer.id}/open`, {}, () => `/v1/transfers/${view.transfer.id}/opening`,
      )}>明确开题</Action>}
      {question && <>
        {'options' in question ? <>
          <UI.Explanation title={question.title}><p>{question.prompt}</p></UI.Explanation>
          <fieldset><legend className="sr-only">{question.title}</legend>
            {question.options.map((option) => <label key={option.key} className="flex gap-2 text-sm">
              <input type="radio" name={`transfer:${view.transfer.id}`} checked={answer === option.key}
                disabled={!writable} onChange={() => change(option.key)} />{option.key}. {option.text}
            </label>)}
          </fieldset>
        </> : <>
          {question.language === 'python_io'
            ? <UI.Explanation title={question.title}><p>{question.prompt}</p></UI.Explanation>
            : <NativeProgramPrompt task={question} purpose="transfer" />}
          {question.language === 'python_io' || question.language === 'sql_query'
            ? <UI.CodeEditor label="新情境整份答案" value={typeof answer === 'string' ? answer : ''}
              readOnly={!writable} onChange={change} />
            : (Array.isArray(answer) ? answer : question.files).map((file) =>
              <Disclosure key={file.path} title={file.path} defaultOpen>
                <UI.CodeEditor label={`新情境 · ${file.path}`} value={file.content}
                  readOnly={!writable || file.read_only} onChange={(text) =>
                    change((Array.isArray(answer) ? answer : question.files).map((item) =>
                      item.path === file.path ? { ...item, content: text } : item))} />
              </Disclosure>)}
        </>}
        {view.allowed_actions.includes('submit') && <Action disabled={!writable || !valid} onClick={submit}>一次提交新情境答案</Action>}
      </>}
      {view.result && <p>{view.result.correct ? '本次通过' : '本次未通过'} · {view.result.explanation}</p>}
      {(view.program_attempt ?? view.python_attempt) && <p>
        {(view.program_attempt ?? view.python_attempt)!.status} · 通过用例 {(view.program_attempt ?? view.python_attempt)!.passed_cases}/3
        {' · '}{(view.program_attempt ?? view.python_attempt)!.feedback}
      </p>}
      <NativeCompilation result={view.program_attempt?.compilation} />
      {view.allowed_actions.includes('cancel') && <Action disabled={blocked} onClick={() => void write(
        `/v1/transfers/${view.transfer.id}/cancel`, {}, () => `/v1/transfers/${view.transfer.id}/cancellation`,
      )}>取消本次新情境检查</Action>}
    </section>}
    {pending.map((entry) => <Notice key={entry.key}>原新情境命令尚待核对。
      <Action disabled={busy} onClick={() => {
        setBusy(true);
        void nativeStore.reconcile(entry.key).then(receive)
          .catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
      }}>读取原新情境回执</Action>
    </Notice>)}
  </Disclosure>;
}
