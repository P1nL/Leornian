import { useEffect, useState, useSyncExternalStore } from 'react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { useTeachingState, writeTeachingControl } from './NativeTeaching';
import NativeAssessment from './NativeAssessment';

type Focus = components['schemas']['TeachingFocus'];
type Plan = components['schemas']['LearningPlan'];
type Lesson = components['schemas']['GeneratedLesson'];
const field = 'border-border-medium bg-surface-primary text-text-primary w-full rounded-lg border px-3 py-2 text-sm';
const runLabels: Record<string, string> = {
  queued: '已接收，等待准备', running: '正在准备', succeeded: '已保存',
  failed: '本次未完成', cancelled: '已取消', blocked_unknown: '原结果未知，等待核对',
};

export default function NativeCourse({ conversationId, goalId, onFocus }: {
  conversationId: string; goalId: string; onFocus?: (focus: Focus) => void;
}) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const teaching = useTeachingState(conversationId);
  const snapshot = state.snapshot;
  const plan = snapshot?.plans.find((item) => item.goal_id === goalId) as Plan | undefined;
  const [instruction, setInstruction] = useState(''), [lessonInstruction, setLessonInstruction] = useState('');
  const [selectedKey, setSelectedKey] = useState(''), [viewActive, setViewActive] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const shown = viewActive && plan?.active ? plan.active : plan?.latest;
  const selected = shown?.document.nodes.find((node) => node.key === selectedKey);
  const active = Boolean(shown && plan?.active?.revision === shown.revision);
  const foreground = snapshot?.runs.find((run) => run.conversation_id === conversationId &&
    ['queued', 'running', 'blocked_unknown'].includes(run.status));
  const requestRoot = `/v1/conversations/${conversationId}`;
  const unresolved = state.pending.filter((pending) => pending.path === `${requestRoot}/plan-requests` ||
    Boolean(plan && pending.path.startsWith(`/v1/plans/${plan.id}/`)));
  const disabled = busy || Boolean(foreground) || unresolved.length > 0 || !teaching.ready;
  const relatedTurns = snapshot?.turns.find((page) => page.conversation_id === conversationId)?.turns
    .filter((turn) => turn.purpose === 'planning' || turn.purpose === 'lesson') ?? [];
  const lastTurn = [...relatedTurns].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const lastRun = snapshot?.runs.find((run) => run.turn_id === lastTurn?.id);
  const lastDelivery = snapshot?.delivery_tasks?.find((task) => task.run_id === lastRun?.id);
  const currentLesson = snapshot?.lessons.filter((item) => item.plan_id === plan?.id &&
    item.plan_revision === shown?.revision && item.node_key === selectedKey)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  useEffect(() => { setSelectedKey(''); setLesson(null); }, [goalId, shown?.revision]);
  useEffect(() => {
    if (!currentLesson) { setLesson(null); return; }
    let active = true;
    void nativeRequest(`/v1/lessons/${currentLesson.id}`).then((value) => {
      if (active) { setLesson(value); setError(''); }
    }).catch((problem: Error) => { if (active) { setLesson(null); setError(problem.message); } });
    return () => { active = false; };
  }, [currentLesson?.id, state.epoch]);

  const write = async (path: string, body: object, lookup: (key: string) => string) => {
    if (disabled) return;
    const key = crypto.randomUUID();
    setBusy(true); setError('');
    try { await nativeStore.write(path, body, { key, lookup: lookup(key) }); }
    catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  const focusNode = async () => {
    if (!plan || !selected || !shown || !active || disabled) return;
    const focus: Focus = {
      kind: 'node', plan_id: plan.id, expected_plan_revision: shown.revision,
      node_key: selected.key, lesson_id: lesson?.id ?? null,
    };
    setBusy(true); setError('');
    try {
      await writeTeachingControl(conversationId, teaching.session, teaching.session
        ? { action: 'set_topic', focus } : { action: 'open', mode: 'guided', focus });
      onFocus?.(focus);
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };

  return <section aria-label="学习路线与课时" className="space-y-5">
    <header><h2 className="text-text-primary font-semibold">学习路线与课时</h2>
      <p className="demo-muted mt-1">按当前目标和已绑定材料准备路线，确认后选择节点学习。</p></header>
    {error && <Notice>{error}</Notice>}
    {lastRun && <div className="text-sm" role="status">
      {lastTurn?.purpose === 'planning' ? '最近路线请求' : '最近课时请求'}：{runLabels[lastRun.status] ?? lastRun.status}
      {lastDelivery && <span> · 交付检查：{lastDelivery.status}</span>}
      {lastRun.error_code && <p className="demo-muted">{lastRun.error_code}</p>}
    </div>}
    {foreground && <Notice>当前会话任务尚未结束，结束后可提交下一次路线或课时请求。</Notice>}
    {unresolved.length > 0 && <Notice>原提交尚待只读核对。
      {unresolved.map((pending) => <Action key={pending.key} disabled={busy}
        onClick={() => {
          setBusy(true); setError('');
          void nativeStore.reconcile(pending.key).catch((problem: Error) => {
            setError(problem.message);
          }).finally(() => setBusy(false));
        }}>读取原提交回执</Action>)}
    </Notice>}
    <Disclosure title={plan ? '补充或修改路线要求' : '准备学习路线'} defaultOpen={!plan}>
      <label className="block space-y-2 text-sm">
        <span>本次路线要求</span>
        <textarea rows={3} className={field} value={instruction} maxLength={4000}
          placeholder="例如：从基础SQL查询开始，逐步学习聚合与多表关联；每个节点安排可执行练习。"
          onChange={(event) => setInstruction(event.target.value)} />
      </label>
      <Action disabled={disabled || !instruction.trim()} onClick={() => void write(
        `${requestRoot}/plan-requests`, {
          text: instruction.trim(), expected_revision: plan?.latest.revision ?? 0,
          focus: teaching.session?.focus ?? { kind: 'goal' },
          teaching_session_revision: teaching.session?.revision ?? null,
        }, (key) => `${requestRoot}/turn-requests/${key}`,
      )}>{plan ? '按要求准备新修订' : '准备路线草稿'}</Action>
    </Disclosure>
    {plan && shown ? <>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>路线修订 {shown.revision} · {active ? '已明确确认' : '待确认草稿'}</span>
        {plan.active && plan.active.revision !== plan.latest.revision && <button
          className="text-text-secondary underline underline-offset-4"
          onClick={() => setViewActive(!viewActive)}>
          {viewActive ? '查看最新草稿' : `查看已确认修订 ${plan.active.revision}`}
        </button>}
      </div>
      <h3 className="text-text-primary text-lg font-medium">{shown.document.title}</h3>
      <p className="whitespace-pre-wrap text-sm leading-7">{shown.document.summary}</p>
      {shown.document.assumptions.length > 0 && <Disclosure title="路线假设">
        <ul className="list-disc space-y-2 pl-5 text-sm">{shown.document.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
      </Disclosure>}
      {!active && shown.revision === plan.latest.revision && <Action important disabled={disabled}
        aria-label={`明确确认修订 ${shown.revision}`}
        onClick={() => void write(`/v1/plans/${plan.id}/confirm`,
          { expected_revision: shown.revision },
          () => `/v1/plans/${plan.id}/confirmations/${shown.revision}`,
        )}>明确确认修订 {shown.revision}</Action>}
      <ol className="divide-border-light divide-y">
        {shown.document.nodes.map((node, index) => <li key={node.key} className="py-4">
          <button aria-pressed={selectedKey === node.key}
            className="text-text-primary w-full text-left text-sm font-medium underline-offset-4 hover:underline"
            onClick={() => setSelectedKey(node.key)}>{index + 1}. {node.title}</button>
          <p className="demo-muted mt-1">{node.estimated_minutes} 分钟 · {node.objective}</p>
          {node.prerequisite_keys.length > 0 && <p className="demo-muted">前置节点：{node.prerequisite_keys.join('、')}</p>}
        </li>)}
      </ol>
      {selected && <section aria-label={`节点 ${selected.title}`} className="space-y-3">
        <h3 className="font-medium">{selected.title}</h3>
        {!active ? <Notice>确认本修订后可为该节点生成课时。</Notice> : <>
          <label className="block space-y-2 text-sm"><span>这节课希望重点讲解什么</span>
            <textarea rows={2} maxLength={4000} className={field} value={lessonInstruction}
              onChange={(event) => setLessonInstruction(event.target.value)} /></label>
          <div className="flex flex-wrap gap-2">
            <Action disabled={disabled || !lessonInstruction.trim()} onClick={() => void write(
              `/v1/plans/${plan.id}/lesson-requests`, {
                expected_plan_revision: shown.revision, node_key: selected.key,
                instruction: lessonInstruction.trim(),
              }, (key) => `${requestRoot}/turn-requests/${key}`,
            )}>{currentLesson ? '准备新的节点课时' : '准备节点课时'}</Action>
            <Action disabled={disabled} onClick={() => void focusNode()}>回到对话学习此节点</Action>
          </div>
        </>}
        {lesson && <article className="space-y-5" aria-label="已保存课时">
          <header><h4 className="text-lg font-medium">{lesson.document.title}</h4>
            <p className="demo-muted">原计划修订 {lesson.plan_revision} · 节点 {lesson.node_key}</p></header>
          <p className="whitespace-pre-wrap text-sm leading-7">{lesson.document.introduction}</p>
          {lesson.document.sections.map((section, index) => <section key={index} className="space-y-2">
            <h5 className="font-medium">{section.heading}</h5>
            <p className="whitespace-pre-wrap text-sm leading-7">{section.explanation}</p>
            {section.code_example && <pre className="bg-surface-secondary overflow-x-auto rounded-lg p-3 text-sm"><code>{section.code_example}</code></pre>}
            <p className="demo-muted">引用：{section.source_refs.map((source) => `${source.source_id}@${source.revision}`).join('、')}
              {section.material_citations?.map((citation) => ` · ${citation.ref.document_id}@${citation.ref.document_revision}`).join('')}</p>
          </section>)}
          <Disclosure title="课后回忆问题"><ul className="list-disc space-y-2 pl-5 text-sm">
            {lesson.document.recall_prompts.map((prompt) => <li key={prompt}>{prompt}</li>)}
          </ul></Disclosure>
        </article>}
        {active && <NativeAssessment planId={plan.id} planRevision={shown.revision} nodeKey={selected.key} />}
      </section>}
    </> : !lastRun && <p className="demo-muted">当前目标还没有路线草稿。补充路线要求后发起准备。</p>}
  </section>;
}
