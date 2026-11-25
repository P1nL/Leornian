import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import * as Ariakit from '@ariakit/react';
import { Button, DropdownPopup, OGDialog, OGDialogContent, OGDialogHeader, OGDialogTitle } from '@librechat/client';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowUp, Ellipsis, History, Lightbulb, ListTodo, X } from 'lucide-react';
import useScaledMaxWidth from '~/hooks/useScaledMaxWidth';
import { ARTIFACTS_SHEET_MAX_WIDTH } from '~/utils/breakpoints';
import { Action, ArtifactFrame, DemoDialog, Disclosure, Notice } from './LearningUI';
import * as UI from './LearningComponents';
import LearningCompositionV2 from './LearningCompositionV2';
import type { CodeWorkbenchContent, CompositionDraftV2, CompositionIntentV2, CompositionV2, ExampleWorkbench } from './LearningCompositionV2';
import { compositionContentKey, executableCode, initialCompositionDraftV2 } from './composition-v2-runtime.mjs';
import { isNativeEmptyConversation, nativeRequest, nativeStore, readArtifactDraft, NATIVE_CODE_REVIEW_CAPABILITY } from './native-client.mjs';
import { sendTeachingTurn } from './native-intake.mjs';
import { practiceChanged, practiceCommand, practiceReceipts, programAnswer, restorePracticeDraft, submittedReviewReceipts } from './native-practice';
import type { PracticeCommand } from './native-practice';
import { NativePracticeAttempts, NativePracticeProgress, NativePracticePrompt, NativePracticeRecord, NativePracticeSample } from './NativePractice';
import { NativeProgramLanguage } from './NativeProgramPractice';
import NativeExampleRun from './NativeExampleRun';
import { NativeAssistance } from './NativeAssistance';
import NativeModels from './NativeModels';
import NativeMaterialUpdates from './NativeMaterialUpdates';
import NativeCourse from './NativeCourse';
import NativeRouteConfirmation from './NativeRouteConfirmation';
import NativeExecution from './NativeExecution';
import NativeMaterialIntake from './NativeMaterialIntake';
import NativeMaterialSources from './NativeMaterialSources';
import NativeGoalMaterialScope, { goalScopeInput, useGoalScopeDraft, validGoalScope } from './NativeGoalMaterialScope';
import NativeLearningEvidence from './NativeLearningEvidence';
import { NativeReviews, NativeReviewPreferences } from './NativeReviews';
import type { components } from '@leornian/api-contracts';
import { NativeDemo, type DemoCommand } from './NativeDemo';
import { NativeLiveReply, NativeTeachingControls, useTeachingState, writeTeachingControl } from './NativeTeaching';
import { NativeReviewReport, type ReviewReportCommand } from './NativeReviewReport';
import { LearningLoginForm } from './LearningChrome';
import { LearningSourceReader } from './LearningSourceReader';
export { NativeTeachingRows } from './NativeTeaching';
import NativePlanAction from './NativePlanAction';
export { default as NativeThinking } from './NativeThinking';

type Snapshot = components['schemas']['Snapshot'];
type Artifact = components['schemas']['CompositionArtifactView'] | components['schemas']['LearningArtifactView'];
type ArtifactSummary = components['schemas']['CompositionArtifactSummary'] | components['schemas']['LearningArtifactSummary'];
type Source = components['schemas']['CompositionSourceView'];
type Focus = components['schemas']['TeachingFocus'];
const fieldClass = 'border-border-medium bg-surface-primary text-text-primary w-full min-w-0 rounded-lg border px-3 py-2 text-sm';
export const useNative = () => useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
export function useNativePaneView(
  original: { isLanding: boolean; column: 'loading' | 'landing' | 'messages' },
  conversationId: string | undefined, isLoading: boolean,
) {
  const state = useNative();
  if (!isLoading && isNativeEmptyConversation(state.snapshot, conversationId)) {
    return { isLanding: false, column: 'messages' as const };
  }
  return original;
}
export function NativeConversationContent({ conversationId, children }: {
  conversationId?: string; children: ReactNode;
}) {
  const state = useNative();
  return <>{isNativeEmptyConversation(state.snapshot, conversationId)
    ? <div className="text-text-secondary flex flex-1 items-center justify-center px-6 py-12" role="status">
      从下方开始讨论学习目标与路线。
    </div> : children}
  </>;
}

export function NativeThreadTail({ conversationId }: { conversationId?: string | null }) {
  const state = useNative();
  const goalId = state.snapshot?.conversations?.find((item) => item.id === conversationId)?.goal_id;
  if (!conversationId || conversationId === 'new') return null;
  return <>
    <NativeLiveReply conversationId={conversationId} />
    <NativeRouteConfirmation conversationId={conversationId} />
    {goalId && <NativeReviews conversationId={conversationId} goalId={goalId} presentedOnly />}
  </>;
}
const statuses: Record<string, string> = {
  queued: '已接收，等待处理', running: '正在处理', generating: '准备候选中', checking: '独立检查中',
  repairing: '根据检查修订中', accepted: '已检查并交付', succeeded: '已保存',
  blocked_unknown: '结果未知，不会自动重发', failed: '未完成，保留历史',
  cancelled: '已取消，保留历史', superseded: '绑定已变化', waiting_config: '等待本人模型配置',
  waiting_input: '等待补充信息', waiting_dependency: '等待依赖恢复',
  blocked_protocol: '检查修复没有取得新进展，已暂停',
};
const supplyActions: Record<string, string> = {
  yield_foreground: '等待当前对话结束', yield_exam: '等待当前考核结束',
  generate: '准备题目中', review: '独立审核中', qualify: '验证执行题中',
  repair_output: '修复已知格式问题', published: '已发布，可回到对话继续',
  deliverable: '供题目标已完成，不代表通过正式考核', check_transfer: '检查候选关系中',
  await_receipt: '外部结果未知，不会自动重发', recover: '等待依赖恢复',
  configure_model: '等待核对本人模型配置',
};
const responseFormats: Record<string, string> = {
  multiple: '多选', prediction: '预测输出', short: '简答参考',
  ordering: '步骤排序', line_review: '逐行定位',
};

export function NativeSync() {
  const state = useNative(), query = useQueryClient();
  useEffect(() => nativeStore.start(), []);
  useEffect(() => {
    const controller = new AbortController();
    let renewing = false;
    const renew = async () => {
      if (document.visibilityState !== 'visible' || renewing) return;
      renewing = true;
      try {
        await fetch('/api/auth/refresh', {
          method: 'POST', credentials: 'same-origin', signal: controller.signal,
        });
      } catch { /* Normal synchronization reports offline/expired sessions. */ }
      finally { renewing = false; }
    };
    const timer = setInterval(() => void renew(), 15 * 60 * 1000);
    const onVisible = () => void renew();
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onVisible);
    return () => {
      clearInterval(timer);
      controller.abort();
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onVisible);
    };
  }, []);
  useEffect(() => {
    void query.invalidateQueries({ predicate: (item) => /message|convo/i.test(String(item.queryKey[0])) });
  }, [state.epoch, query]);
  return null;
}

export function NativeLogin() {
  const [name, setName] = useState(''), [token, setToken] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const enter = async () => {
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/auth/local', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(token ? { token } : { display_name: name }),
      });
      setToken('');
      if (!response.ok) throw new Error('未能进入本机会话，请核对当前 API 和身份。');
      window.location.replace('/c/new');
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <LearningLoginForm name={name} token={token} busy={busy} error={error}
    onName={setName} onToken={setToken} onEnter={() => void enter()} />;
}

export function NativeStart() {
  const state = useNative(), navigate = useNavigate();
  const [title, setTitle] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const snapshot = state.snapshot as Snapshot | null;
  const draftKey = snapshot ? `leornian.native.goal-title.v1:${snapshot.actor.id}` : '';
  const scope = useGoalScopeDraft(snapshot?.actor.id);
  const pending = state.pending.filter((entry) => entry.path === '/v1/goals');
  const blocked = !snapshot || busy || pending.length > 0;
  useEffect(() => { setTitle(draftKey ? sessionStorage.getItem(draftKey) ?? '' : ''); }, [draftKey]);
  return <section className="learning-demo mx-auto max-w-2xl space-y-4 px-6" data-learning-demo>
    <h1 className="text-2xl font-semibold">今天想学什么？</h1>
    {snapshot?.goals.map((goal) => <div key={goal.id}><Action onClick={() => {
      void nativeRequest('/v1/conversations', { method: 'POST', body: JSON.stringify({ goal_id: goal.id }) })
        .then(async (conversation) => { await nativeStore.refresh(); navigate(`/c/${conversation.id}`); })
        .catch((problem) => setError(problem.message));
    }}>{goal.title}</Action></div>)}
    <label className="block">新增学习目标<input className={fieldClass} value={title} minLength={3} maxLength={120}
      disabled={blocked} onChange={(event) => {
        setTitle(event.target.value);
        if (draftKey) sessionStorage.setItem(draftKey, event.target.value);
      }} /></label>
    <NativeGoalMaterialScope value={scope.value} onChange={scope.change} disabled={blocked} />
    <Action busy={busy} disabled={blocked || title.trim().length < 3 || !validGoalScope(scope.value)} onClick={() => {
      setBusy(true); setError('');
      const key = crypto.randomUUID(), materialScope = goalScopeInput(scope.value);
      void nativeStore.write('/v1/goals', { title: title.trim(), motivation: '',
        ...(materialScope ? { material_scope: materialScope } : {}) },
      { key, lookup: `/v1/goal-requests/${key}` })
        .then(() => {
          setTitle(''); scope.reset();
          if (draftKey) sessionStorage.removeItem(draftKey);
        }).catch((problem) => setError(problem.message)).finally(() => setBusy(false));
    }}>保存目标</Action>
    <p className="demo-muted">只保存目标；不会因此发送模型请求或安装课程环境。</p>
    {snapshot?.jobs.filter((job) => !['succeeded', 'failed'].includes(job.status)).map((job) =>
      <Notice key={job.id}>{statuses[job.status] ?? job.status}</Notice>)}
    {pending.map((entry) => <Notice key={entry.key}>原目标提交尚待核对，草稿与科目授权保留。
      <Action disabled={busy} onClick={() => {
        setBusy(true);
        void nativeStore.reconcile(entry.key).then(() => {
          setTitle(''); scope.reset();
          if (draftKey) sessionStorage.removeItem(draftKey);
        }).catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
      }}>读取原目标回执</Action>
    </Notice>)}
    {error && <Notice>{error}</Notice>}
  </section>;
}

export function selectedFocus(snapshot: Snapshot | null, conversationId?: string): Focus {
  if (!snapshot || !conversationId) return { kind: 'goal' };
  try {
    const data = JSON.parse(sessionStorage.getItem(`leornian.native.focus:${snapshot.actor.id}:${conversationId}`) ?? 'null');
    const conversation = snapshot.conversations.find((item) => item.id === conversationId);
    const plan = snapshot.plans.find((item) => item.goal_id === conversation?.goal_id);
    if (data?.plan_id === plan?.id && data.expected_plan_revision === plan?.active?.revision &&
      plan?.active?.document.nodes.some((node) => node.key === data.node_key)) return data;
  } catch {}
  return { kind: 'goal' };
}

export function NativeComposer({ conversationId }: { conversationId?: string }) {
  const state = useNative(), snapshot = state.snapshot as Snapshot | null;
  const teaching = useTeachingState(conversationId);
  const [text, setText] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const key = snapshot && conversationId ? `leornian.native.composer:${snapshot.actor.id}:${conversationId}` : '';
  useEffect(() => { setText(key ? sessionStorage.getItem(key) ?? '' : ''); }, [key]);
  useEffect(() => {
    const notice = state.composerNotice;
    if (!notice || notice.conversationId !== conversationId) return;
    setError(notice.error);
    if (notice.error) {
      setText(notice.text);
      try { if (key) sessionStorage.setItem(key, notice.text); } catch {}
    } else setText((value) => value.trim() === notice.text ? '' : value);
  }, [state.composerNotice, conversationId, key]);
  useEffect(() => {
    let current = true;
    void nativeRequest('/v1/tutor/availability').then((value) => { if (current) setReady(value.ready); })
      .catch(() => { if (current) setReady(false); });
    return () => { current = false; };
  }, [snapshot?.actor.id, state.epoch]);
  if (!conversationId || conversationId === 'new') return null;
  const active = teaching.active, blocked = Boolean(active && !teaching.automaticActive);
  const unresolved = state.pending.some((pending) => pending.path.includes(`/conversations/${conversationId}/`));
  const submit = async () => {
    if (!text.trim() || blocked || !ready || !teaching.ready || busy || unresolved) return;
    setBusy(true); setError('');
    const input = text.trim();
    try {
      await sendTeachingTurn(nativeStore, conversationId, input,
        teaching.session?.focus ?? selectedFocus(snapshot, conversationId), teaching.session);
      setText(''); sessionStorage.removeItem(key);
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="learning-demo demo-composer-wrap" data-learning-demo>
    <div className="demo-composer">
      <textarea aria-label="发送给 Tutor" value={text} maxLength={4000} rows={2}
        disabled={busy || blocked || unresolved || !teaching.ready}
        placeholder={ready ? '围绕当前学习提问…' : '先在当前学习菜单中配置并启用自己的模型'}
        onChange={(event) => {
          setText(event.target.value);
          try { if (key) sessionStorage.setItem(key, event.target.value); }
          catch { setError('草稿暂时只保存在当前页面，浏览器存储不可用。'); }
        }}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} />
      <Action primary icon={ArrowUp} aria-label="发送" busy={busy}
        disabled={!ready || !teaching.ready || !text.trim() || blocked || unresolved} onClick={() => void submit()} />
    </div>
    {active && <Notice>{teaching.automaticActive
      ? `自动后续教学：${statuses[active.status] ?? active.status}。你仍可直接提问；服务端会优先取消本次自动任务，不会重发未知调用。`
      : statuses[active.status] ?? active.status}</Notice>}
    {unresolved && <Notice>原提交尚待核对。请从当前学习菜单读取原回执，不会自动重发。</Notice>}
    {teaching.teaching?.error && <Notice>教学状态暂未同步，请在当前学习菜单重读后再发送；草稿保留。</Notice>}
    {error && <Notice>{error}</Notice>}
  </div>;
}

function legacyDefinition(view: Extract<Artifact, { schema_version: 'learning_artifact.v1' }>): CompositionV2 {
  if (view.presentation.type === 'knowledge_check') return {
    schema_version: 'learning_composition.v2', title: view.title, layout: 'stack', states: { answer: { type: 'choice', value: [] } },
    components: [
      { id: 'answer', component: 'ChoiceAnswer', props: { label: view.title, state: 'answer', multiple: false,
        options: view.presentation.question.options.map((option) => ({ id: option.key, text: option.text })) } },
      { id: 'submit', component: 'ArtifactAction', props: { label: '提交回答', event: 'submit_answer', for_component: 'answer', primary: true } },
    ],
  };
  return {
    schema_version: 'learning_composition.v2', title: view.title, layout: 'stack',
    states: { code: { type: 'code', value: view.presentation.task.starter_code, read_only: false } },
    components: [
      ...(view.practice_only ? [] : [{ id: 'sample', component: 'DataTable' as const, props: {
        label: '公开样例，不代替完整评测', columns: ['输入', '样例输出'],
        rows: [[JSON.stringify(view.presentation.task.sample.input), String(view.presentation.task.sample.expected)]] } }]),
      { id: 'editor', component: 'CodeEditor', props: { label: 'Python 代码', state: 'code' } },
      { id: 'run', component: 'ArtifactAction', props: { label: '运行并评测', event: 'check_code', for_component: 'editor', primary: true } },
    ],
  };
}

function NativeArtifact({ view, actorId }: { view: Artifact; actorId: string }) {
  const state = useNative(), [error, setError] = useState('');
  const practiceOnly = view.practice_only;
  const contentKey = compositionContentKey(view);
  const definition = useMemo(() => view.schema_version === 'learning_artifact.v2'
    ? view.presentation.definition : legacyDefinition(view), [contentKey]);
  const saved = useMemo(() => {
    const value = readArtifactDraft(actorId, view, definition, initialCompositionDraftV2);
    if (view.schema_version === 'learning_artifact.v1' && view.result && !(practiceOnly && value.restored)) {
      if ('selected_key' in view.result) value.draft.values.answer = [view.result.selected_key];
      else value.draft.values.code = view.result.code;
    }
    if (view.schema_version === 'learning_artifact.v2' && !(practiceOnly && value.restored)) {
      restorePracticeDraft(definition, view.component_bindings ?? [], value.draft, value.restored);
    }
    return value;
  }, [actorId, contentKey, practiceOnly]);
  const [draft, setDraft] = useState<CompositionDraftV2>(saved.draft);
  const [busy, setBusy] = useState(false);
  const unknown = state.pending.some((pending) => pending.path.includes(`/learning-artifacts/${view.id}/`));
  const root = `/v2/conversations/${view.conversation_id}/learning-artifacts/${view.id}`;
  const terminal = ['cancelled', 'superseded'].includes(view.state);
  const bindings = view.schema_version === 'learning_artifact.v2' ? view.component_bindings ?? [] : [];
  useEffect(() => {
    if (practiceOnly) return;
    setDraft((previous) => {
      const next = { ...previous, values: { ...previous.values } };
      restorePracticeDraft(definition, bindings, next, true);
      return JSON.stringify(next.values) === JSON.stringify(previous.values) ? previous : next;
    });
  }, [view.revision, practiceOnly]);
  const send = async (action: PracticeCommand | DemoCommand | ReviewReportCommand | { action: 'respond' | 'run'; payload?: unknown }) => {
    if (practiceOnly || busy || unknown || terminal) return;
    setBusy(true); setError('');
    const clientActionId = crypto.randomUUID();
    try {
      await nativeStore.write(`${root}/actions`, { ...action, client_action_id: clientActionId, expected_artifact_revision: view.revision },
        { key: clientActionId, lookup: `${root}/actions/${clientActionId}` });
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  const act = (intent: CompositionIntentV2) => {
    let action: Parameters<typeof send>[0] | null;
    if (view.schema_version === 'learning_artifact.v1' && intent.type === 'submit_answer' &&
      intent.response.type === 'choice' && view.allowed_actions.includes('respond')) action = { action: 'respond', payload: { selected_key: intent.response.value[0] } };
    else if (view.schema_version === 'learning_artifact.v1' && intent.type === 'check_code' &&
      intent.submission.type === 'code' && view.allowed_actions.includes('run')) action = { action: 'run', payload: { code: intent.submission.code } };
    else action = practiceCommand(intent, bindings);
    if (action) void send(action);
  };
  const allowed = view.schema_version === 'learning_artifact.v1' ? [
    ...(view.allowed_actions.includes('respond') ? [{ component_id: 'answer', event: 'submit_answer' as const }] : []),
    ...(view.allowed_actions.includes('run') ? [{ component_id: 'editor', event: 'check_code' as const }] : []),
  ] : definition.components.flatMap((node) => {
    if (node.component !== 'ArtifactAction') return [];
    const { event, for_component } = node.props;
    const binding = bindings.find((item) => item.component_id === for_component);
    const target = definition.components.find((item) => item.id === for_component);
    const changed = binding && target && 'state' in target.props
      ? practiceChanged(binding, draft.values[target.props.state]) : true;
    const permitted = event === 'preview' ||
      (event === 'submit_answer' || event === 'submit_review') && binding?.allowed_actions.includes('respond') ||
      event === 'check_code' && changed && binding?.allowed_actions.includes('run');
    return permitted ? [{ component_id: for_component, event }] : [];
  });
  const codeWorkbenches: Record<string, CodeWorkbenchContent> = {};
  const exampleWorkbenches: Record<string, ExampleWorkbench> = {};
  for (const binding of bindings) {
    const presentation = binding.source.presentation;
    if (presentation.type !== 'code_workspace' && presentation.type !== 'program_practice') continue;
    const node = definition.components.find((item) => item.id === binding.component_id);
    if (!node || (node.component !== 'CodeEditor' && node.component !== 'CodeDiff')) continue;
    if (practiceOnly) {
      const value = draft.values[node.props.state];
      const program = presentation.type === 'program_practice';
      const answer = program ? programAnswer(binding, value) :
        typeof value === 'string' && executableCode(value) ? { code: value } : null;
      exampleWorkbenches[node.id] = {
        render: (editor) => <NativeExampleRun root={root} actorId={actorId} revision={view.revision}
          componentId={node.id} title={binding.source.title} code="" languages={[]} editor={editor}
          disabled={busy || unknown} practiceOnly description={<UI.Explanation><p>{presentation.task.prompt}</p></UI.Explanation>}
          sample={{ answer, language: program ? <NativeProgramLanguage task={presentation.task} /> : 'Python',
            tests: <NativePracticeSample binding={binding} />, history: <><NativePracticeAttempts binding={binding} />
              <NativePracticeRecord binding={binding} /></> }} />,
      };
      continue;
    }
    if (!definition.components.some((item) => item.component === 'ArtifactAction' &&
      item.props.event === 'check_code' && item.props.for_component === node.id)) continue;
    const unchanged = !practiceChanged(binding, draft.values[node.props.state]);
    const result = binding.result;
    codeWorkbenches[node.id] = {
      title: binding.source.title,
      language: presentation.type === 'program_practice'
        ? <NativeProgramLanguage task={presentation.task} /> : <span>Python</span>,
      tests: <NativePracticeSample binding={binding} />,
      tabs: [
        { id: 'assistance', label: '提示答疑', icon: Lightbulb, content: <NativeAssistance binding={binding}
          blocked={busy || unknown || terminal} onCommand={(command) => void send(command)} /> },
        { id: 'history', label: '运行记录', icon: History, content: <NativePracticeAttempts binding={binding} /> },
      ],
      hasResult: Boolean(result),
      busy: binding.state === 'running',
      runPhase: unchanged && result && 'status' in result
        ? result.status === 'passed' ? 'completed' : result.status === 'not_passed' ? 'attention' : 'idle' : 'idle',
    };
  }
  if (practiceOnly && view.schema_version === 'learning_artifact.v1' && view.presentation.type === 'code_workspace') {
    const task = view.presentation.task, code = String(draft.values.code ?? '');
    exampleWorkbenches.editor = { render: (editor) => <NativeExampleRun
      root={root} actorId={actorId} revision={view.revision} componentId="editor"
      title={task.title} code="" languages={[]} editor={editor} disabled={busy || unknown} practiceOnly
      description={<p>{task.prompt}</p>} sample={{ answer: executableCode(code) ? { code } : null,
        language: 'Python', tests: <UI.DataTable label="公开样例" columns={['输入', '参考输出']}
          rows={[[JSON.stringify(task.sample.input), String(task.sample.expected)]]} /> }} /> };
  }
  if (view.schema_version === 'learning_artifact.v2') {
    const workspace = view.presentation.example_workspace;
    const editors = new Set([...Object.keys(view.example_runners ?? {}), ...(workspace ? [workspace.editor] : [])]);
    const explanations = definition.components.filter((node) => node.component === 'Explanation');
    const singleGuide = editors.size === 1 && explanations.length === 1 && definition.components.every(
      (node) => editors.has(node.id) || node.component === 'Explanation' || node.component === 'SourceReference');
    for (const node of definition.components) {
      if (!editors.has(node.id) || codeWorkbenches[node.id] || (node.component !== 'CodeEditor' && node.component !== 'CodeDiff')) continue;
      const selected = workspace?.editor === node.id ? workspace : null;
      const props = node.props;
      exampleWorkbenches[node.id] = {
        descriptionId: selected?.description ?? (singleGuide ? explanations[0].id : undefined),
        render: (editor, description) => <NativeExampleRun key={`${actorId}:${root}:${view.revision}:${node.id}`}
          root={root} actorId={actorId} componentId={node.id} revision={view.revision} title={props.label}
          code={String(draft.values[props.state] ?? '')} editor={editor} description={description} workspace={selected}
          surface={view.example_run_surface} languages={view.example_runners?.[node.id] ?? []}
          practiceOnly={practiceOnly} disabled={busy || terminal || unknown} />,
      };
    }
  }
  return <ArtifactFrame id={view.id} title={view.title} kind={view.kind} state={view.state}>
    {practiceOnly && <p className="demo-muted">自由练习 · 可以继续尝试，不计入学习记录。</p>}
    {view.schema_version === 'learning_artifact.v1' && !exampleWorkbenches.editor && <UI.Explanation><p>{view.presentation.type === 'knowledge_check'
      ? view.presentation.question.prompt : view.presentation.task.prompt}</p></UI.Explanation>}
    <LearningCompositionV2 definition={definition} binding={view} draft={draft} allowedActions={allowed}
      codeWorkbenches={codeWorkbenches} exampleWorkbenches={exampleWorkbenches}
      readOnly={terminal} practiceOnly={practiceOnly} status={unknown ? 'unknown' : busy || !practiceOnly && view.schema_version === 'learning_artifact.v1' && view.state === 'running' ? 'busy' : view.state === 'cancelled' ? 'cancelled' : 'ready'}
      lockedComponents={practiceOnly ? [] : bindings.filter((binding) => !binding.allowed_actions.some((action) =>
        action === 'respond' || action === 'run')).map((binding) => binding.component_id)}
      receipts={view.schema_version === 'learning_artifact.v2'
        ? [...(practiceOnly ? [] : practiceReceipts(view)), ...submittedReviewReceipts(view)] : []}
      beforeComponent={(id) => {
        const binding = bindings.find((item) => item.component_id === id);
        if (binding) return <NativePracticePrompt binding={binding} practiceOnly={practiceOnly} showSample={!codeWorkbenches[id]} />;
        const review = view.schema_version === 'learning_artifact.v2'
          ? view.review_bindings?.find((item) => item.component_id === id) : null;
        return review ? <div role="group" aria-label="代码审查的原始提交">
          <UI.Explanation title={review.task.title}><p>{review.task.prompt}</p></UI.Explanation>
          <p>固定第 {review.attempt.attempt_number} 次提交 · {review.attempt.id}</p>
          <UI.ResultFeedback label={review.attempt.status === 'error'
            ? `原执行异常（不是能力结论）：${review.attempt.feedback ?? ''}`
            : `原评测${review.recorded_correct ? '通过' : '未通过'}：${review.attempt.feedback ?? ''}`}
            columns={review.attempt.status === 'error' ? [] : ['通过用例', '总用例']}
            rows={review.attempt.status === 'error' ? [] : [[String(review.attempt.passed_cases), String(review.attempt.total_cases)]]} />
          <p className="demo-muted">批注是教学反馈，不改变原评分。修改或再次运行请回到原练习；此处不运行代码。</p>
        </div> : null;
      }}
      afterComponent={(id) => {
        const report = view.schema_version === 'learning_artifact.v2'
          ? view.review_reports?.find((item) => item.component_id === id) : null;
        if (report) return <NativeReviewReport report={report} blocked={busy || unknown || terminal}
          pending={state.pending.some((pending) => pending.path === `${root}/actions` &&
            'action' in pending.body && pending.body.action === 'complete_review')}
          onCommand={(command) => void send(command)} />;
        const binding = bindings.find((item) => item.component_id === id);
        const node = definition.components.find((item) => item.id === id);
        const demo = view.schema_version === 'learning_artifact.v2'
          ? view.demo_bindings?.find((item) => item.component_id === id) : null;
        if (demo) return <NativeDemo key={`${id}:${demo.completion_count ?? demo.completions?.length ?? 0}`}
          demo={demo} definition={definition} draft={draft} practiceOnly={practiceOnly}
          blocked={busy || unknown || terminal || view.state === 'running'}
          onHistory={(before) => nativeRequest(`${root}/demos/${id}/completions?demo_capability=learning_demo_events.v1&before=${before}&limit=20`)}
          onCommand={(command) => void send(command)} />;
        if (practiceOnly && binding) return <NativePracticeRecord binding={binding} />;
        return binding && node && 'state' in node.props ? <>
          <NativePracticeProgress binding={binding}
            code={String(draft.values[node.props.state] ?? '')} blocked={busy || unknown || terminal}
            value={draft.values[node.props.state]}
            showHistory={!codeWorkbenches[id]}
            onCommand={(command) => void send(command)} />
          {!codeWorkbenches[id] && <NativeAssistance binding={binding} blocked={busy || unknown || terminal}
            onCommand={(command) => void send(command)} />}
        </> : null;
      }}
      onDraftChange={(next) => {
        setDraft(next);
        try { sessionStorage.setItem(saved.key, JSON.stringify(next)); }
        catch { setError('草稿暂时只保存在当前页面，浏览器存储不可用。'); }
      }}
      onAction={(intent) => void act(intent)}
      onSource={(_, componentId) => { void nativeStore.openSource(`${root}/sources/${componentId}`); }} />
    {view.schema_version === 'learning_artifact.v1' && view.result && <Disclosure title="原提交结果">{
      'correct' in view.result ? <UI.AnswerFeedback kind={view.result.correct ? 'correct' : 'incorrect'}>原选择：{view.result.selected_key}。{view.result.explanation}</UI.AnswerFeedback>
        : <UI.ResultFeedback label={view.result.status === 'queued' ? '已接收，等待原本机 Runner'
          : `${view.result.feedback ?? view.result.status} · ${view.result.passed_cases}/${view.result.total_cases}`} />
    }</Disclosure>}
    {error && <Notice>{error}</Notice>}
  </ArtifactFrame>;
}

export function NativeArtifacts({ messageId }: { messageId?: string }) {
  const state = useNative(), { conversationId } = useParams();
  const [views, setViews] = useState<Artifact[]>([]), [error, setError] = useState('');
  const [unavailable, setUnavailable] = useState<{ summary: ArtifactSummary; message: string }[]>([]);
  const turnId = messageId?.endsWith(':assistant') ? messageId.slice(0, -':assistant'.length) : '';
  useEffect(() => {
    if (!conversationId || !turnId) return;
    const controller = new AbortController();
    void (async () => {
      const all: Artifact[] = [];
      const unavailable: { summary: ArtifactSummary; message: string }[] = [];
      let before = '';
      do {
        const page = await nativeRequest(`/v2/conversations/${conversationId}/learning-artifacts?limit=100${before ? `&before=${before}` : ''}`, { signal: controller.signal });
        for (const summary of page.filter((item: { source_turn_id: string }) => item.source_turn_id === turnId)) {
          try {
            all.push(await nativeRequest(`/v2/conversations/${conversationId}/learning-artifacts/${summary.id}?response_capability=learning_responses.v1&code_review_capability=${NATIVE_CODE_REVIEW_CAPABILITY}&program_capability=learning_programs.v2&direct_answer_capability=learning_direct_answers.v1&hint_capability=learning_hints.v1&demo_capability=learning_demo_events.v1&example_capability=learning_example_runs.v2`, { signal: controller.signal }));
          } catch (problem) {
            if (controller.signal.aborted) throw problem;
            unavailable.push({ summary, message: (problem as Error).message });
          }
        }
        before = page.length === 100 ? page.at(-1).id : '';
      } while (before);
      if (!controller.signal.aborted) { setViews(all); setUnavailable(unavailable); setError(''); }
    })().catch((problem) => { if (!controller.signal.aborted) { setViews([]); setUnavailable([]); setError(problem.message); } });
    return () => controller.abort();
  }, [conversationId, turnId, state.epoch]);
  if (!turnId || !state.snapshot) return null;
  const actorId = state.snapshot.actor.id;
  return <><NativePlanAction conversationId={conversationId} turnId={turnId} />
    {views.map((view) => <NativeArtifact key={`${actorId}:${compositionContentKey(view)}:${Boolean(view.practice_only)}`}
    view={view} actorId={actorId} />)}
    {unavailable.map((item) => <UnavailableArtifact key={item.summary.id} {...item} />)}
    {error && <Notice>{error}</Notice>}</>;
}

function UnavailableArtifact({ summary, message }: { summary: ArtifactSummary; message: string }) {
  const state = useNative();
  const path = `/v2/conversations/${summary.conversation_id}/learning-artifacts/${summary.id}`;
  const unknown = state.pending.some((pending) => pending.path === `${path}/actions`);
  return <ArtifactFrame id={summary.id} title="工件内容暂不可读" kind={summary.kind} state={summary.state}>
    <Notice>当前绑定或来源权限需重新核对，不改读其他内容：{message}</Notice>
    {unknown && <Notice>原动作尚待只读核对，不会重发。</Notice>}
  </ArtifactFrame>;
}
export function NativeLearningMenu({ className = '' }: { className?: string; [key: string]: unknown }) {
  const state = useNative(), { conversationId } = useParams();
  const goalId = state.snapshot?.conversations.find((item) => item.id === conversationId)?.goal_id;
  const planId = state.snapshot?.plans.find((item) => item.goal_id === goalId)?.id;
  const [isOpen, setIsOpen] = useState(false), [dialog, setDialog] = useState('');
  const id = useRef(`native-menu-${crypto.randomUUID()}`).current;
  const titles: Record<string, string> = {
    scope: '当前学习与路线', reviews: '到期复习', records: '学习记录', preferences: '学习方式与提醒',
    models: '我的模型配置', updates: '教材与更新', environment: '本机执行环境', tasks: '任务与原提交回执',
  };
  const items = Object.entries(titles)
    .map(([value, label]) => ({ id: value, label, onClick: () => { setIsOpen(false); setDialog(value); } }));
  return <>
    <DropdownPopup portal menuId={id} focusLoop unmountOnHide isOpen={isOpen} setIsOpen={setIsOpen} items={items}
      trigger={<Ariakit.MenuButton aria-label="当前学习菜单" render={<Button size="icon" variant="header-action" className={`relative size-9 shrink-0 ${className}`} />}>
        <Ellipsis size={20} /></Ariakit.MenuButton>} />
    <DemoDialog open={Boolean(dialog)} onClose={() => setDialog('')} title={titles[dialog] ?? '当前学习'}>
      {dialog === 'models' && <NativeModels />}
      {dialog === 'updates' && <><NativeMaterialUpdates />{goalId && <>
        <NativeMaterialIntake goalId={goalId} /><NativeMaterialSources goalId={goalId} /></>}</>}
      {dialog === 'scope' && (conversationId && goalId
        ? <NativeCourse conversationId={conversationId} goalId={goalId} onFocus={() => setDialog('')} />
        : <Notice>进入一个学习目标后准备路线与课时。</Notice>)}
      {dialog === 'records' && <NativeLearningEvidence key={goalId} planId={planId} epoch={state.epoch} />}
      {dialog === 'reviews' && (conversationId && goalId
        ? <NativeReviews conversationId={conversationId} goalId={goalId} />
        : <Notice>进入一个学习目标后查看到期复习。</Notice>)}
      {dialog === 'preferences' && <><NativeLearningScope />{conversationId && goalId &&
        <NativeReviewPreferences conversationId={conversationId} />}</>}
      {dialog === 'environment' && <NativeExecution />}
      {dialog === 'tasks' && <NativeTaskList />}
    </DemoDialog>
  </>;
}

export function NativeLearningScope() {
  const state = useNative(), { conversationId } = useParams(), snapshot = state.snapshot as Snapshot | null;
  const teaching = useTeachingState(conversationId);
  const [error, setError] = useState(''), [focus, setFocus] = useState<Focus>(() => selectedFocus(snapshot, conversationId));
  const [busy, setBusy] = useState(false);
  const conversation = snapshot?.conversations.find((item) => item.id === conversationId);
  const plan = snapshot?.plans.find((item) => item.goal_id === conversation?.goal_id);
  const blocked = Boolean(teaching.session && teaching.active && !teaching.automaticActive);
  useEffect(() => { setFocus(teaching.session?.focus ?? selectedFocus(snapshot, conversationId)); }, [snapshot, conversationId, teaching.session]);
  const receipts = snapshot?.evaluations.filter((item) => item.source_kind === 'python' &&
    snapshot.packs.some((pack) => pack.id === item.pack_id && pack.plan_id === plan?.id &&
      pack.plan_revision === plan?.active?.revision && pack.node_key === focus.node_key)) ?? [];
  const chooseFocus = async (next: Focus) => {
    if (!snapshot || !conversationId || !teaching.ready || busy || teaching.unresolved || blocked) return;
    setBusy(true); setError('');
    try {
      if (teaching.session) await writeTeachingControl(conversationId, teaching.session, { action: 'set_topic', focus: next });
      sessionStorage.setItem(`leornian.native.focus:${snapshot.actor.id}:${conversationId}`, JSON.stringify(next));
      setFocus(next);
      setError(teaching.session ? '教学主题已明确切换，旧内容和答疑保留。' : '范围已选择；只影响下一次请求，不改写已交付内容。');
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <>
        {conversationId && <NativeTeachingControls conversationId={conversationId} focus={focus} />}
        <label>当前范围<select className={fieldClass} value={focus.node_key ?? ''}
          disabled={!teaching.ready || busy || teaching.unresolved || blocked}
          onChange={(event) => {
            void chooseFocus(event.target.value && plan?.active ? { kind: 'node', plan_id: plan.id,
              expected_plan_revision: plan.active.revision, node_key: event.target.value } : { kind: 'goal' });
          }}>
          <option value="">整个目标</option>
          {plan?.active?.document.nodes.map((node) => <option key={node.key} value={node.key}>{node.title}</option>)}
        </select></label>
        {focus.node_key && <><label>提交代码审查<select className={fieldClass}
          disabled={!teaching.ready || busy || teaching.unresolved || blocked}
          value={focus.kind === 'attempt' ? focus.assessment_receipt_id ?? '' : ''}
          onChange={(event) => {
            const { assessment_receipt_id: _receipt, ...node } = focus;
            void chooseFocus(event.target.value ? { ...node, kind: 'attempt',
              assessment_receipt_id: event.target.value } : { ...node, kind: 'node' });
          }}>
          <option value="">不绑定提交，围绕节点提问</option>
          {focus.kind === 'attempt' && !receipts.some((item) => item.source_id === focus.assessment_receipt_id) &&
            <option value={focus.assessment_receipt_id ?? ''}>已固定提交 {focus.assessment_receipt_id}（不在近期列表）</option>}
          {receipts.map((item) => <option key={item.id} value={item.source_id}>
            {item.source_id.slice(0, 8)} · 原评测{item.correct ? '通过' : '未通过'}
          </option>)}
        </select></label><p className="demo-muted">只列当前节点已公开的 Python 提交。选择后在对话中请求审查；选择本身不提交、不调用模型。</p></>}
        {!plan?.active && <Notice>尚未确认动态路线，可先围绕整个目标提问。原入口的路线确认与 Gate 功能保留。</Notice>}
      {error && <Notice>{error}</Notice>}
  </>;
}

export function NativeTaskList() {
  const state = useNative(), { conversationId } = useParams();
  const [error, setError] = useState(''), [busyPack, setBusyPack] = useState<string | null>(null);
  const snapshot = state.snapshot as Snapshot | null;
  const conversation = snapshot?.conversations.find((item) => item.id === conversationId);
  const planIds = new Set(snapshot?.plans.filter((plan) => plan.goal_id === conversation?.goal_id).map((plan) => plan.id));
  const supplyTasks = new Map<string, Snapshot['packs'][number]>();
  for (const pack of snapshot?.packs ?? []) {
    if (!pack.supply_task_id || !planIds.has(pack.plan_id)) continue;
    const prior = supplyTasks.get(pack.supply_task_id);
    if (!prior || prior.revision < pack.revision) supplyTasks.set(pack.supply_task_id, pack);
  }
  const updateSupply = async (packId: string, action: 'cancel' | 'automation-resume') => {
    setBusyPack(packId); setError('');
    try {
      await nativeRequest(`/v1/packs/${packId}/${action}`, { method: 'POST' });
      await nativeStore.refresh();
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusyPack(null); }
  };
  return <div>
    <Notice>{state.connection}{state.error ? ` · ${state.error}` : ''}</Notice>
    {snapshot?.jobs?.filter((job) => job.status === 'queued').map((job) =>
      <div className="demo-task-row" key={job.id}><p>学习目标 · {statuses[job.status]}</p></div>)}
    {snapshot?.runs?.filter((run) => run.conversation_id === conversationId &&
      ['queued', 'running', 'blocked_unknown'].includes(run.status)).map((run) =>
      <div className="demo-task-row" key={run.id}>
        <p>Tutor · {statuses[run.status] ?? run.status}</p>
        <Action disabled={run.cancel_requested} onClick={() => {
          void nativeRequest(`/v1/runs/${run.id}/cancel`, { method: 'POST' })
            .then(() => nativeStore.refresh()).catch((problem) => setError(problem.message));
        }}>{run.cancel_requested ? '已请求取消' : '取消本次教学'}</Action>
      </div>)}
    {[...supplyTasks.values()].map((pack) => <div className="demo-task-row" key={pack.supply_task_id}
      role="group" aria-label={`供题任务 ${pack.supply_task_id}`}>
      <p>{pack.response_formats
        ? [...new Set(Object.values(pack.response_formats))].map((format) => responseFormats[format]).join(' / ')
        : pack.kind === 'python_io' ? 'Python 执行练习' : pack.kind === 'response' ? '响应型练习' : '单选练习'}供题 · 版本 {pack.revision}</p>
      <p>{pack.automation_status === 'cancelled' ? '已取消，保留历史'
        : pack.automation_status === 'completed' ? supplyActions[pack.automation_action ?? ''] ?? '供题目标已完成'
        : supplyActions[pack.automation_action ?? ''] ?? '原供给任务正在推进'}</p>
      {pack.automation_reason && <Notice>待核对：{pack.automation_reason}。不改读其他来源或重发未知调用。</Notice>}
      {!['completed', 'cancelled'].includes(pack.automation_status ?? '') && <Action
        busy={busyPack === pack.id} disabled={busyPack !== null}
        onClick={() => { void updateSupply(pack.id, 'cancel'); }}>取消供题</Action>}
      {pack.automation_status === 'waiting' && pack.automation_reason &&
        pack.automation_reason !== 'external_result_unknown' && <Action
          busy={busyPack === pack.id} disabled={busyPack !== null}
          onClick={() => { void updateSupply(pack.id, 'automation-resume'); }}>核对后恢复原供题任务</Action>}
    </div>)}
    {snapshot?.delivery_tasks.filter((task) => snapshot.runs.some((run) =>
      run.id === task.run_id && run.conversation_id === conversationId)).map((task) =>
      <div className="demo-task-row" key={task.id}><p>{statuses[task.status] ?? task.status}</p>
        {task.reason_code === 'delivery_protocol_stalled' &&
          <Notice>原候选和检查结论已保留，可核对后恢复原任务。</Notice>}
        {task.status === 'blocked_protocol' && task.can_resume && <Action
          busy={busyPack === task.id} disabled={busyPack !== null} onClick={async () => {
            setBusyPack(task.id); setError('');
            try {
              await nativeRequest(`/v1/delivery-tasks/${task.id}/resume`, {
                method: 'POST', body: JSON.stringify({ additional_instruction: '' }),
              });
              await nativeStore.refresh();
            } catch (problem) { setError((problem as Error).message); }
            finally { setBusyPack(null); }
          }}>恢复原任务</Action>}
        {!['accepted', 'cancelled', 'superseded'].includes(task.status) && <Action onClick={() => {
          void nativeRequest(`/v1/delivery-tasks/${task.id}/cancel`, { method: 'POST' }).then(() => nativeStore.refresh()).catch((problem) => setError(problem.message));
        }}>取消任务</Action>}
      </div>)}
    {state.pending.map((pending) => <div className="demo-task-row" key={pending.key}>
      <p>原提交结果尚未确认，不会自动重发。</p>
      <Action disabled={!pending.lookup} onClick={() => {
        void nativeStore.reconcile(pending.key).catch((problem) => setError(problem.message));
      }}>只读核对原回执</Action>
    </div>)}
    {error && <Notice>{error}</Notice>}
  </div>;
}
export function NativeTasks(_props: Record<string, unknown>) {
  const [open, setOpen] = useState(false);
  return <><button type="button" className="demo-icon-button" aria-label="后台任务" onClick={() => setOpen(true)}><ListTodo size={20} /></button>
    <DemoDialog open={open} onClose={() => setOpen(false)} title="后台任务"><NativeTaskList /></DemoDialog></>;
}

export function NativeSourcePanel({ children, panel, NativeGroup, baseline = false }: {
  children: ReactNode; panel: unknown; NativeGroup: React.ComponentType<any>; baseline?: boolean;
}) {
  const state = useNative(), reduced = useReducedMotion();
  const isSmall = useScaledMaxWidth(ARTIFACTS_SHEET_MAX_WIDTH);
  const content = state.reader?.content as Source | null;
  useEffect(() => {
    if (!content?.valid_until) return;
    const deadline = Date.parse(content.valid_until);
    let timer: ReturnType<typeof setTimeout>;
    const check = () => {
      const remaining = deadline - Date.now();
      if (remaining <= 0) nativeStore.expireSource();
      else timer = setTimeout(check, Math.min(remaining, 2147483647));
    };
    check();
    return () => clearTimeout(timer);
  }, [content?.valid_until, state.reader?.path]);
  const body = <LearningSourceReader content={content} error={state.reader?.error} />;
  return <div className="demo-source-layout" data-reader-docked={Boolean(state.reader) && (!baseline || !isSmall)}>
    <div className="demo-source-main"><div className="demo-source-chat-canvas">
      <NativeGroup panel={state.reader ? null : panel}>{children}</NativeGroup>
    </div></div>
    {baseline && isSmall ? <OGDialog open={Boolean(state.reader)}
      onOpenChange={(open) => { if (!open) nativeStore.closeSource(); }}>
      <OGDialogContent title={content?.title ?? '读取精确来源'} className="text-text-primary w-11/12">
        <OGDialogHeader><OGDialogTitle>{content?.title ?? '读取精确来源'}</OGDialogTitle></OGDialogHeader>
        <div className="learning-demo" data-learning-demo>{body}</div>
      </OGDialogContent>
    </OGDialog> : <AnimatePresence>{state.reader && <motion.aside className="learning-demo demo-reader" data-learning-demo data-open="true"
      aria-label="教材阅读面板" initial={{ opacity: 0, x: reduced ? 0 : 28 }} animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: reduced ? 0 : 28 }} transition={{ duration: reduced ? 0 : .28 }}>
      <div className="demo-reader-header"><h3>{content?.title ?? '读取精确来源'}</h3>
        <button type="button" className="demo-icon-button" aria-label="关闭教材阅读" onClick={nativeStore.closeSource}><X size={18} /></button></div>
      {body}
    </motion.aside>}</AnimatePresence>}
  </div>;
}
