import { useEffect, useState } from 'react';
import { ChevronRight, Folder, Layers } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { useNative } from './NativeLearning';
import { nativeRequest } from './native-client.mjs';
import { DemoDialog, Notice } from './LearningUI';
import { NativeProgramPrompt } from './NativeProgramPractice';
import { packStatuses, QuestionBankGeneration } from './QuestionBankGeneration';
import './question-bank.css';

type Schema = components['schemas'];
type Pack = Schema['BankPack'];
type Node = Schema['BankNode'];
type Plan = Schema['LearningPlan'];
type Practice = Schema['PracticeSet']['questions'][number] | Schema['ResponsePracticeSet']['questions'][number]
  | Schema['PythonQuestion'] | Schema['ProgramCandidatePresentation']['task'];
type Mode = 'questions' | 'process';
type Selection = { id: string; mode: Mode };
const kinds: Record<Pack['kind'], string> = { choice: '单选题', response: '知识练习', python_io: 'Python 程序题',
  sql_query: 'SQL 查询题', python_project: 'Python 项目题', project_stdio: '程序题', web_project: '网页项目题', http_project: 'HTTP 项目题' };

function versionGroups(packs: Pack[]) {
  const roots = new Map<string, string>(), groups = new Map<string, Pack[]>();
  for (const pack of [...packs].sort((first, next) => first.revision - next.revision)) {
    roots.set(pack.id, pack.supply_task_id ?? (pack.predecessor_id && roots.get(pack.predecessor_id)) ?? pack.id);
  }
  for (const pack of packs) {
    const root = roots.get(pack.id)!;
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root)!.push(pack);
  }
  return [...groups.values()].map((group) => group.sort((first, next) => next.revision - first.revision));
}

function useBankRead<T>(path: string, version = '') {
  const [value, setValue] = useState<T | null>(null), [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    void nativeRequest(path, { signal: controller.signal }).then((data: T) => {
      if (!controller.signal.aborted) setValue(data);
    }).catch((problem: Error) => {
      if (!controller.signal.aborted) { setValue(null); setError(problem.message); }
    });
    return () => controller.abort();
  }, [path, version, retry]);
  return { value, error, reload: () => setRetry((count) => count + 1) };
}

function ReadError({ error, reload }: { error: string; reload: () => void }) {
  return <Notice>{error} <button type="button" className="underline" onClick={reload}>重新读取</button></Notice>;
}

function PracticeBody({ question }: { question: Practice }) {
  if ('environment' in question) return <><NativeProgramPrompt task={question} />
    {'files' in question && question.files.map((file) => <details key={file.path}><summary>{file.path}</summary>
      <pre>{file.content}</pre></details>)}
    {'starter_query' in question && <pre>{question.starter_query}</pre>}</>;
  return <><p className="whitespace-pre-wrap">{question.prompt}</p>
    {'options' in question && <ul>{question.options.map((option) => <li key={'key' in option ? option.key : option.id}>
      {'key' in option ? `${option.key}. ` : ''}{option.text}</li>)}</ul>}
    {'items' in question && <ul>{question.items.map((item) => <li key={item.id}>{item.text}</li>)}</ul>}
    {'code' in question && <pre>{question.code}</pre>}
    {'starter_code' in question && <><pre>{question.starter_code}</pre>
      <p>公开样例：<code>{JSON.stringify(question.sample.input)}</code> → <code>{question.sample.expected}</code></p></>}
    {'response_type' in question && question.response_type === 'short' && <p className="demo-muted">这道简答题提供参考回答，不自动判分。</p>}
  </>;
}

function PracticeBodies({ pack }: { pack: Pack }) {
  const endpoint = pack.kind === 'choice' ? `v1/packs/${pack.id}/practice`
    : pack.kind === 'response' ? `v2/packs/${pack.id}/response-practice`
      : pack.kind === 'python_io' ? `v1/packs/${pack.id}/execution-practice` : `v2/packs/${pack.id}/program-practice`;
  const { value, error, reload } = useBankRead<Practice[] | { questions: Practice[] }>(`/${endpoint}`);
  if (error) return <ReadError error={error} reload={reload} />;
  if (!value) return <p role="status">正在读取已发布题面…</p>;
  const questions = Array.isArray(value) ? value : value.questions;
  return <section aria-label="已发布练习" className="bank-questions">
    {questions.map((question, index) => <article key={question.slot}>
      <h3>练习 {index + 1}{!('environment' in question) && ` · ${question.title}`}</h3><PracticeBody question={question} />
    </article>)}
    <p className="demo-muted">考核题在正式开考后显示，补救题按练习结果分配。</p>
  </section>;
}

function Process({ pack, version }: { pack: Pack; version: string }) {
  const { value, error, reload } = useBankRead<Schema['GenerationReport']>(`/v1/packs/${pack.id}/generation`, version);
  return error ? <ReadError error={error} reload={reload} /> : value
    ? <QuestionBankGeneration report={value} executable={!['choice', 'response'].includes(pack.kind)} />
    : <p role="status">正在读取阶段记录…</p>;
}

function RouteContents({ plan, version, examActive }: { plan: Plan; version: string; examActive: boolean }) {
  const { value: nodes, error, reload } = useBankRead<Node[]>(`/v1/plans/${plan.id}/question-bank`, version);
  const [selection, setSelection] = useState<Selection | null>(null);
  const selectedNode = selection && nodes?.find((node) => node.packs.some((pack) => pack.id === selection.id));
  const pack = selectedNode?.packs.find((item) => item.id === selection?.id);
  const versions = selectedNode && versionGroups(selectedNode.packs).find((group) => group.some((item) => item.id === pack?.id));
  const activeRevision = plan.active?.revision;
  if (error) return <ReadError error={error} reload={reload} />;
  if (!nodes) return <p role="status" className="bank-empty">正在读取节点…</p>;
  return <><ol className="bank-nodes">{nodes.map((node) => {
    const historical = node.plan_revision !== (activeRevision ?? plan.latest.revision);
    const groups = versionGroups(node.packs);
    const title = /^(?:第\s*[\d一二三四五六七八九十百零]+\s*[节课講讲章]|\d+\s*[.、])/.test(node.title)
      ? node.title : `${node.position}. ${node.title}`;
    return <li key={`${node.plan_revision}:${node.node_key}`}><details className="bank-node">
      <summary><ChevronRight size={14} /><span>{title}</span>
        <small>{historical ? `路线 v${node.plan_revision} · ` : ''}{groups.length} 份</small></summary>
      {groups.length ? groups.map((group) => {
        const [entry] = group, published = group.find((item) => item.status === 'published');
        return <div key={entry.id} className="bank-entry">
          <p>{kinds[entry.kind]} · 第 {entry.revision} 版</p>
          <small>{packStatuses[entry.status]} · {new Date(entry.created_at).toLocaleDateString()}</small>
          <div>{published && node.plan_revision === activeRevision &&
            <button type="button" disabled={examActive} onClick={() => setSelection({ id: published.id, mode: 'questions' })}>
              查看练习题{entry.id !== published.id && `（第 ${published.revision} 版）`}</button>}
            <button type="button" onClick={() => setSelection({ id: entry.id, mode: 'process' })}>生成过程</button></div>
        </div>;
      }) : <p className="bank-empty">本节还没有生成题目。</p>}
    </details></li>;
  })}</ol>
    {pack && selectedNode && selection && <DemoDialog open title={`${kinds[pack.kind]} · 第 ${pack.revision} 版`} onClose={() => setSelection(null)}>
      <div className="bank-detail">
        <p className="demo-muted">{plan.active?.document.title ?? plan.latest.document.title} / {selectedNode.title}
          {' · '}路线 v{pack.plan_revision}</p>
        {versions && versions.length > 1 && <label className="bank-versions">题包版本 <select value={pack.id}
          onChange={(event) => setSelection({ id: event.target.value, mode: 'process' })}>
          {versions.map((entry) => <option key={entry.id} value={entry.id}>第 {entry.revision} 版 · {packStatuses[entry.status]}</option>)}
        </select></label>}
        <div role="group" aria-label="题包视图" className="bank-switch">
          {pack.status === 'published' && pack.plan_revision === activeRevision && <button type="button"
            disabled={examActive} aria-pressed={selection.mode === 'questions'}
            onClick={() => setSelection({ ...selection, mode: 'questions' })}>已发布练习</button>}
          <button type="button" aria-pressed={selection.mode === 'process'}
            onClick={() => setSelection({ ...selection, mode: 'process' })}>生成过程</button>
        </div>
        {selection.mode === 'process' ? <Process key={pack.id} pack={pack} version={version} />
          : examActive ? <Notice>正式考核期间暂停查看练习。</Notice> : <PracticeBodies key={pack.id} pack={pack} />}
      </div>
    </DemoDialog>}
  </>;
}

function BankLibrary({ snapshot }: { snapshot: Schema['Snapshot'] }) {
  const [routeId, setRouteId] = useState('');
  const plans = snapshot.plans.filter((plan) => snapshot.goals.some((goal) => goal.id === plan.goal_id));
  const routePacks = (snapshot.packs ?? []).filter((pack) => pack.plan_id === routeId);
  const version = JSON.stringify(routePacks.map((pack) => [pack.id, pack.status, pack.reviewed_roles, pack.pending_role,
    pack.blind_passed, pack.automation_action, pack.automation_status, pack.pending_run_id &&
    snapshot.runs?.find((run) => run.id === pack.pending_run_id)?.status]));
  const examActive = snapshot.gates?.some((gate) => ['in_progress', 'submitted'].includes(gate.status)) ?? false;
  return <>{plans.map((plan) => {
    const title = (plan.active ?? plan.latest).document.title, open = plan.id === routeId;
    return <section key={plan.id} className="bank-route">
      <button className="bank-route-toggle" aria-expanded={open} onClick={() => setRouteId(open ? '' : plan.id)}>
        <Folder size={17} /><span>{title}</span><ChevronRight size={15} /></button>
      {open && <RouteContents key={`${plan.id}:${plan.active?.revision ?? plan.latest.revision}`} plan={plan} version={version} examActive={examActive} />}
    </section>;
  })}{!plans.length && <p className="bank-empty">有了学习路线后，就能在这里按节点查看题目。</p>}</>;
}

export function BaselineQuestionBank() {
  const { snapshot } = useNative();
  return <section className="baseline-routes question-bank" aria-label="题库">
    <h2><Layers size={17} />题库</h2>
    {snapshot ? <BankLibrary key={snapshot.actor.id} snapshot={snapshot} /> : <p role="status">正在读取路线…</p>}
  </section>;
}
