import { useEffect, useState, useSyncExternalStore } from 'react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import * as UI from './LearningComponents';
import { NativeCompilation, NativeProgramPrompt } from './NativeProgramPractice';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { programTaskAnswer } from './native-practice';
import NativeRecovery from './NativeRecovery';

type View = components['schemas']['GateView'];
type Question = View['questions'][number];
type ProgramQuestion = components['schemas']['ProgramCandidatePresentation']['task'];
type Files = components['schemas']['ProgramFile'][];
type Answers = Record<string, string | Files>;
const statuses: Record<string, string> = {
  preparing: '正在检查独立性', ready: '准备完成，等待明确开始', in_progress: '正式考核进行中',
  submitted: '整组提交已接收，等待实际执行', passed: '本次考核通过',
  not_passed: '本次考核未通过', blocked: '等待考核依赖', cancelled: '本次考核已取消',
};
const slots = ['assessment_1', 'assessment_2'] as const;
const program = (question: Question): question is ProgramQuestion =>
  'language' in question && question.language !== 'python_io';
const initial = (question: Question): string | Files => 'options' in question ? ''
  : 'starter_code' in question ? question.starter_code
    : question.language === 'sql_query' ? question.starter_query : question.files;

export default function NativeAssessment({ planId, planRevision, nodeKey }: {
  planId: string; planRevision: number; nodeKey: string;
}) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const packs = state.snapshot?.packs?.filter((pack) => pack.plan_id === planId &&
    pack.plan_revision === planRevision && pack.node_key === nodeKey && pack.status === 'published') ?? [];
  const gates = state.snapshot?.gates?.filter((gate) => gate.plan_id === planId &&
    gate.plan_revision === planRevision && gate.node_key === nodeKey) ?? [];
  const [selected, setSelected] = useState(''), [view, setView] = useState<View | null>(null);
  const [answers, setAnswers] = useState<Answers>({}), [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const gateId = selected || [...gates].sort((a, b) => b.created_at.localeCompare(a.created_at))[0]?.id;
  const actorId = state.snapshot?.actor.id;
  const storage = gateId && actorId ? `leornian.native.gate-draft.v1:${actorId}:${gateId}` : null;
  const pending = state.pending.filter((entry) => packs.some((pack) => entry.path.includes(`/packs/${pack.id}/`)) ||
    Boolean(gateId && entry.path.includes(`/gates/${gateId}/`)) ||
    Boolean(gateId && entry.path.includes(`/concept-gates/${gateId}/`)));
  const adopt = (value: View) => {
    setView(value);
    setAnswers((current) => Object.fromEntries(value.questions.map((question) =>
      [question.slot, current[question.slot] ?? initial(question)])));
  };
  const load = async (id = gateId) => {
    if (id) adopt(await nativeRequest(`/v1/gates/${id}`));
  };
  useEffect(() => {
    setView(null); setAnswers({}); setError('');
    if (!gateId) return;
    let current = true;
    void nativeRequest(`/v1/gates/${gateId}`).then((value: View) => {
      if (!current) return;
      setView(value);
      let saved: Answers = {};
      try { saved = JSON.parse(sessionStorage.getItem(storage!) ?? '{}'); } catch { saved = {}; }
      setAnswers(Object.fromEntries(value.questions.map((question) =>
        [question.slot, saved[question.slot] ?? initial(question)])));
    }).catch((problem: Error) => { if (current) setError(problem.message); });
    return () => { current = false; };
  }, [gateId, storage, state.epoch]);
  useEffect(() => {
    if (!view || !['preparing', 'submitted'].includes(view.gate.status)) return;
    const timer = setTimeout(() => void load().catch((problem: Error) => setError(problem.message)), 2500);
    return () => clearTimeout(timer);
  }, [view]);
  const change = (slot: string, value: string | Files) => {
    const next = { ...answers, [slot]: value }; setAnswers(next);
    if (storage) sessionStorage.setItem(storage, JSON.stringify(next));
  };
  const write = async (path: string, body: object, lookup: (key: string) => string) => {
    if (busy || pending.length) return;
    setBusy(true); setError('');
    const key = crypto.randomUUID();
    try {
      const result = await nativeStore.write(path, body, { key, lookup: lookup(key) });
      if ('gate' in result) adopt(result);
      else if (result.id) {
        if (result.id === gateId) await load(result.id); else setSelected(result.id);
      }
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  const request = (pack: typeof packs[number]) => {
    const suffix = pack.kind === 'choice' ? 'gate-requests' : pack.kind === 'python_io'
      ? 'execution-gate-requests' : 'program-gate-requests';
    const root = `/v${suffix === 'program-gate-requests' ? 2 : 1}/packs/${pack.id}/${suffix}`;
    return write(root, { expected_plan_revision: planRevision }, (key) => `${root}/${key}`);
  };
  const ready = view?.questions.length === 2 && slots.every((slot) => {
    const question = view.questions.find((item) => item.slot === slot), value = answers[slot];
    if (!question || value == null) return false;
    if ('options' in question) return typeof value === 'string' && ['A', 'B', 'C', 'D'].includes(value);
    if (question.language === 'python_io') return typeof value === 'string' && Boolean(value.trim()) &&
      new TextEncoder().encode(value).length <= 12000;
    return Boolean(programTaskAnswer(question, value));
  });
  const submit = () => {
    if (!view || !ready) return;
    const kind = view.gate.policy_version;
    const root = kind === 'program-execution-gate.v1' ? `/v2/gates/${view.gate.id}/program-submissions`
      : `/v1/concept-gates/${view.gate.id}/${kind === 'python-io-gate.v1' ? 'execution-submissions' : 'submissions'}`;
    const questions = slots.map((slot) => view.questions.find((question) => question.slot === slot)!);
    const body = kind === 'concept-gate.v1' ? {
      answers: slots.map((slot) => ({ slot, selected_key: answers[slot] })),
    } : { programs: questions.flatMap((question) => 'options' in question ? [] : [{
      slot: question.slot, ...(question.language === 'python_io' ? { code: answers[question.slot] }
        : { answer: programTaskAnswer(question, answers[question.slot]) }),
    }]) };
    void write(root, body, (key) => `${root}/${key}`);
  };
  const writable = view?.allowed_actions.includes('submit') && !busy && !pending.length;
  return <Disclosure title="正式独立考核">
    {error && <Notice>{error}</Notice>}
    {!packs.length && <p className="demo-muted">当前节点还没有已发布题包，完成正常练习准备后可进入考核。</p>}
    <div className="flex flex-wrap gap-2">{packs.map((pack) => <Action key={pack.id} disabled={busy || pending.length > 0}
      onClick={() => void request(pack)}>准备{pack.kind === 'choice' ? '概念' : '执行'}考核 · 题包修订 {pack.revision}</Action>)}</div>
    {gates.length > 1 && <label className="block text-sm">考核历史
      <select value={gateId} onChange={(event) => setSelected(event.target.value)}>
        {gates.map((gate) => <option key={gate.id} value={gate.id}>{new Date(gate.created_at).toLocaleString()} · {statuses[gate.status]}</option>)}
      </select></label>}
    {view && <div className="mt-4 space-y-4">
      <p role="status">{statuses[view.gate.status]} · {view.gate.policy_version}</p>
      {view.gate.relation_run_id && <p className="demo-muted">独立性检查原任务：{view.gate.relation_run_id}</p>}
      {(view.blocked_reason || view.gate.error_code) && <Notice>{view.blocked_reason ?? view.gate.error_code}</Notice>}
      {view.allowed_actions.includes('start') && <Action disabled={busy || pending.length > 0}
        onClick={() => void write(`/v1/gates/${view.gate.id}/start`, {},
          () => `/v1/gates/${view.gate.id}/start-receipt`)}>明确开始整组考核</Action>}
      {view.questions.map((question) => <article key={question.slot} className="space-y-3">
        {program(question) ? <NativeProgramPrompt task={question} purpose="assessment" />
          : <UI.Explanation title={question.title}><p>{question.prompt}</p></UI.Explanation>}
        {'options' in question ? <fieldset className="space-y-2"><legend className="sr-only">{question.title}</legend>
          {question.options.map((option) => <label key={option.key} className="flex gap-2 text-sm">
            <input type="radio" name={`${view.gate.id}:${question.slot}`} value={option.key}
              checked={answers[question.slot] === option.key} disabled={!writable}
              onChange={() => change(question.slot, option.key)} />{option.key}. {option.text}
          </label>)}
        </fieldset> : question.language === 'python_io' || question.language === 'sql_query'
          ? <UI.CodeEditor label={`${question.title} · ${question.slot}`} value={String(answers[question.slot] ?? '')}
            readOnly={!writable} onChange={(text) => change(question.slot, text)} />
          : (Array.isArray(answers[question.slot]) ? answers[question.slot] as Files : question.files)
            .map((file) => <Disclosure key={file.path} title={file.path} defaultOpen>
              <UI.CodeEditor label={`${question.slot} · ${file.path}`} value={file.content}
                readOnly={!writable || file.read_only} onChange={(text) => {
                  const files = (answers[question.slot] as Files).map((item) =>
                    item.path === file.path ? { ...item, content: text } : item);
                  change(question.slot, files);
                }} />
            </Disclosure>)}
      </article>)}
      {view.allowed_actions.includes('submit') && <Action disabled={!writable || !ready} onClick={submit}>一次提交整组答案</Action>}
      {view.results.map((result) => <p key={result.slot}>{result.slot} · {result.correct ? '通过' : '未通过'} · {result.explanation}</p>)}
      {view.program_results?.map((result) => <section key={result.slot} className="space-y-2">
        <p>{result.slot} · {result.status} · {result.passed_cases}/3 · {result.feedback ?? result.error_code}</p>
        <NativeCompilation result={result.compilation} />
      </section>)}
      {view.allowed_actions.includes('cancel') && <Action disabled={busy || pending.length > 0}
        onClick={() => void write(`/v1/gates/${view.gate.id}/cancel`, {},
          () => `/v1/gates/${view.gate.id}/cancellation`)}>取消本次考核</Action>}
    </div>}
    {pending.map((entry) => <Notice key={entry.key}>原考核命令尚待核对。
      <Action disabled={busy} onClick={() => {
        setBusy(true);
        void nativeStore.reconcile(entry.key).then(async (receipt) => {
          if ('gate' in receipt) adopt(receipt);
          else if (receipt.id) {
            if (receipt.id === gateId) await load(receipt.id); else setSelected(receipt.id);
          }
        }).catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
      }}>读取原考核回执</Action>
    </Notice>)}
    <NativeRecovery planId={planId} planRevision={planRevision} nodeKey={nodeKey} />
  </Disclosure>;
}
