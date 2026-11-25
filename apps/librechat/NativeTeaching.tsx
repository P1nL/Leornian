import { Fragment, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { GraduationCap } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import { PhosphorBook, PhosphorPause, PhosphorPlay } from './PhosphorIcons';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { sendPlanningTurn, sendTeachingTurn } from './native-intake.mjs';
import NativeReplyParts from './NativeReplyParts';

type Session = components['schemas']['TeachingSession'];
type Branch = components['schemas']['TeachingBranch'];
type Intent = components['schemas']['TeachingIntent'];
type Focus = components['schemas']['TeachingFocus'];
type Control = components['schemas']['OpenTeachingSession']
  | components['schemas']['SetTeachingMode'] | components['schemas']['PauseTeaching']
  | components['schemas']['ResumeTeaching'] | components['schemas']['ReturnToMain']
  | components['schemas']['SetTeachingTopic'] | components['schemas']['SetContinuationPolicy']
  | components['schemas']['FinishTeachingNode'];
type WithoutIdentity<T> = T extends Control ? Omit<T, 'client_action_id' | 'expected_session_revision'> : never;
type TeachingAction = WithoutIdentity<Control>;

export function useTeachingState(conversationId?: string) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  useEffect(() => {
    if (conversationId && conversationId !== 'new') void nativeStore.openTeaching(conversationId);
  }, [conversationId, state.snapshot?.actor.id]);
  const teaching = state.teaching && state.teaching.conversationId === conversationId
    && state.teaching.actorId === state.snapshot?.actor.id ? state.teaching : null;
  const active = state.snapshot?.runs?.find((run) => run.conversation_id === conversationId
    && ['queued', 'running', 'blocked_unknown'].includes(run.status));
  const automaticActive = Boolean(active && (
    state.snapshot?.turns?.some((page) => page.conversation_id === conversationId
      && page.turns.some((turn) => turn.id === active.turn_id && turn.teaching_intent_id != null))
    || teaching?.intents?.some((intent) => intent.run_id === active.id)
  ));
  const unresolved = state.pending.some((pending) =>
    pending.path.startsWith(`/v2/conversations/${conversationId}/teaching-session/actions`));
  return {
    state, teaching, session: teaching?.session ?? null, active, automaticActive, unresolved,
    ready: Boolean(teaching && !teaching.loading && !teaching.error),
  };
}

export async function writeTeachingControl(conversationId: string, session: Session | null, action: TeachingAction) {
  const id = crypto.randomUUID(), path = `/v2/conversations/${conversationId}/teaching-session/actions`;
  return nativeStore.write(path, {
    ...action, client_action_id: id, expected_session_revision: session?.revision ?? 0,
  }, { key: id, lookup: `${path}/${id}` });
}

function useTeachingControl(conversationId: string) {
  const current = useTeachingState(conversationId);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const disabled = !current.ready || Boolean(current.active && !current.automaticActive)
    || current.unresolved || busy;
  const send = async (action: TeachingAction) => {
    if (disabled) return;
    setBusy(true); setError('');
    try { await writeTeachingControl(conversationId, current.session, action); }
    catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return { ...current, send, disabled, busy, error };
}

export function NativeTeachingControls({ conversationId, focus }: { conversationId: string; focus: Focus }) {
  const control = useTeachingControl(conversationId), session = control.session;
  const continuation = session?.continuation_policy === 'after_result.v1';
  return <section aria-label="教学方式" className="space-y-3">
    <p>{session ? `${session.mode === 'guided' ? '引导学习' : '自由阅读'}${session.paused ? ' · 已暂停引导' : ''}` : '选择学习方式'}</p>
    <div className="demo-action-group">
      <Action important icon={PhosphorPlay} aria-label={session ? '切换为引导学习' : '开启引导学习'}
        disabled={control.disabled || session?.mode === 'guided'} busy={control.busy}
        onClick={() => void control.send(session ? { action: 'set_mode', mode: 'guided' }
          : { action: 'open', mode: 'guided', focus })} />
      <Action important icon={PhosphorBook} aria-label={session ? '切换为自由阅读' : '开启自由阅读'}
        disabled={control.disabled || session?.mode === 'free_reading'} busy={control.busy}
        onClick={() => void control.send(session ? { action: 'set_mode', mode: 'free_reading' }
          : { action: 'open', mode: 'free_reading', focus })} />
      {session && <Action important icon={session.paused ? PhosphorPlay : PhosphorPause}
        aria-label={session.paused ? '恢复引导' : '暂停引导'}
        disabled={control.disabled} busy={control.busy}
        onClick={() => void control.send({ action: session.paused ? 'resume' : 'pause' })} />}
    </div>
    <p className="demo-muted">引导学习会在节点讲解间留出插话时间。自由阅读或暂停时只等你提问。</p>
    <div className="space-y-2">
      <Action role="switch" aria-label="结果后续教学" aria-checked={continuation}
        disabled={control.disabled || !session || (!continuation && session.mode === 'free_reading')}
        busy={control.busy} onClick={() => void control.send({
          action: 'set_continuation_policy', policy: continuation ? 'manual' : 'after_result.v1',
        })}>{continuation ? '关闭结果后续教学' : '开启结果后续教学'}</Action>
      <p className="demo-muted">默认关闭。开启后会使用你配置的模型，在工件结果返回后继续教学。</p>
      {session?.mode === 'free_reading' && <p className="demo-muted">自由阅读不会自动续讲；结果后续教学仅在引导学习中生效。</p>}
      {session?.paused && <p className="demo-muted">暂停期间保留排队的后续教学，恢复后再由服务端处理。</p>}
    </div>
    {!control.teaching || control.teaching.loading ? <p role="status">正在读取教学状态…</p> : null}
    {control.active && <Notice>{control.automaticActive
      ? '当前是自动后续教学；明确暂停、关闭或切换教学状态时，服务端会优先取消原自动任务。'
      : '先完成当前对话，或在任务中明确取消，再切换教学状态。'}</Notice>}
    {control.unresolved && <Notice>原控制尚待只读核对，请在“任务与原提交回执”中读取原回执，不会重发。</Notice>}
    {control.teaching?.error && <Notice>{control.teaching.error}
      <Action onClick={() => void nativeStore.refreshTeaching()}>重读教学状态</Action></Notice>}
    {control.error && <Notice>{control.error}</Notice>}
    {session?.active_branch_id && <NativeReturnToMain conversationId={conversationId} branchId={session.active_branch_id} />}
    {session && <NativeTeachingIntents conversationId={conversationId} />}
  </section>;
}

const intentStates: Record<Intent['state'], string> = {
  pending: '等待后续教学', dispatched: '已交给原教学任务', cancelled: '已取消', superseded: '已撤销',
};
const intentTriggers: Record<Intent['trigger_kind'], string> = {
  artifact_action: '工件动作', expected_result: '预期结果', interaction_event: '交互事件',
  review_due: '到期复习', node_window: '节点续讲',
};
const runStates: Record<string, string> = {
  queued: '已排队', running: '处理中', blocked_unknown: '结果未知，不会自动重发',
  succeeded: '已完成', failed: '未完成，保留历史', cancelled: '已取消，保留历史',
};
const waitReasons: Record<string, string> = {
  paused: '引导已暂停', question_branch: '等待返回主线', foreground: '等待当前对话结束',
  higher_priority_intent: '等待更高优先级的后续教学', active_exam: '等待当前考核结束',
  session_changed: '教学状态已变更', explicit_cancel: '已明确取消', explicit_user_input: '已由明确提问接管',
  stale_version: '原结果或教学绑定已变化', source_not_current: '原材料已不可用',
  unauthorized: '原身份授权已失效',
  model_unavailable: '等待本人模型配置', external_result_unknown: '原外部结果未知，不会重发',
  delivery_protocol_stalled: '检查修复没有取得新进展，原任务已暂停',
  outside_teaching_window: '等待允许的教学时段', proactive_disabled: '本会话主动提示已关闭',
};

function NativeTeachingIntents({ conversationId }: { conversationId: string }) {
  const current = useTeachingState(conversationId);
  const [busy, setBusy] = useState<string | null>(null), [error, setError] = useState('');
  const intents = current.teaching?.intents ?? [];
  const cancellationRoot = `/v1/conversations/${conversationId}/teaching-intents/`;
  const unresolved = current.state.pending.some((pending) => pending.path.startsWith(cancellationRoot));
  const cancel = async (intent: Intent) => {
    if (!current.ready || busy || unresolved) return;
    setBusy(intent.id); setError('');
    const id = crypto.randomUUID(), path = `${cancellationRoot}${intent.id}/cancel`;
    try {
      await nativeStore.write(path, { client_action_id: id }, { key: id, lookup: `${path}/${id}` });
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(null); }
  };
  return <Disclosure title="后续教学队列（最近20条）">
    {!current.teaching?.loading && !intents.length && !current.teaching?.error
      && <p className="demo-muted">最近没有后续教学意图。</p>}
    {intents.length > 0 && <ul className="space-y-3">{intents.map((intent) => {
      const cancellable = intent.state === 'pending' || (intent.state === 'dispatched'
        && (['queued', 'running', 'blocked_unknown'].includes(intent.run_status ?? '') ||
          intent.trigger_kind === 'review_due' && Boolean(intent.review_activity_id)));
      return <li key={intent.id} className="space-y-1 break-words">
        <p>{intentTriggers[intent.trigger_kind]} · {intentStates[intent.state]}</p>
        {intent.wait_reason && <p className="demo-muted">等待原因：{waitReasons[intent.wait_reason] ?? intent.wait_reason}</p>}
        {intent.run_id && <p className="demo-muted">原任务：{intent.run_id} · {intent.run_status
          ? runStates[intent.run_status] ?? intent.run_status : '状态尚未返回'}</p>}
        {intent.review_activity_id && <p className="demo-muted">原复习活动：{intent.review_activity_id}</p>}
        {cancellable && <Action aria-label={`${intent.trigger_kind === 'review_due' ? '取消复习提示' : '取消后续教学'} ${intent.id}`} busy={busy === intent.id}
          disabled={!current.ready || Boolean(busy) || unresolved}
          onClick={() => void cancel(intent)}>{intent.trigger_kind === 'review_due' ? '取消本次复习提示' : '取消本次续讲'}</Action>}
      </li>;
    })}</ul>}
    {unresolved && <Notice>原取消尚待只读核对，请在“任务与原提交回执”中读取原回执，不会重发。</Notice>}
    {error && <Notice>{error}</Notice>}
  </Disclosure>;
}

function NativeReturnToMain({ conversationId, branchId }: { conversationId: string; branchId: string }) {
  const control = useTeachingControl(conversationId);
  return <div className="demo-action-group">
    <Action important icon={PhosphorBook} aria-label="返回主线" busy={control.busy}
      disabled={control.disabled || control.session?.active_branch_id !== branchId}
      onClick={() => void control.send({ action: 'return_to_main', branch_id: branchId })} />
    {control.error && <Notice>{control.error}</Notice>}
  </div>;
}

function QuestionGroup({ id, conversationId, branch, active, count, children }: {
  id: string; conversationId: string; branch?: Branch; active: boolean; count: number; children: ReactNode;
}) {
  const [open, setOpen] = useState(active), previouslyActive = useRef(active);
  useEffect(() => {
    if (active || previouslyActive.current) setOpen(active);
    previouslyActive.current = active;
  }, [active, count]);
  return <section className="mx-auto w-full min-w-0 px-4 sm:px-2 md:max-w-3xl xl:max-w-4xl"
    data-teaching-branch={id} data-anchor-artifact-id={branch?.anchor_artifact_id}
    aria-label={`答疑 · ${count} 轮`}>
    <div className="learning-demo" data-learning-demo>
      <Disclosure title={`答疑 · ${count} 轮`} open={open} onOpenChange={setOpen}>
        {children}
        {active && <NativeReturnToMain conversationId={conversationId} branchId={id} />}
        {branch?.state === 'superseded' && <p className="demo-muted">主题已切换，保留这段答疑历史。</p>}
      </Disclosure>
    </div>
  </section>;
}

type MessageRow = {
  message: { messageId: string; conversationId?: string | null; isCreatedByUser?: boolean; leornianBranchId?: string;
    leornianFocus?: Focus; leornianPurpose?: string };
};

export function NativeLiveReply({ conversationId }: { conversationId?: string }) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const teaching = useTeachingState(conversationId);
  const unknown = state.snapshot?.runs.find((run) => run.conversation_id === conversationId &&
    run.status === 'blocked_unknown');
  const active = state.snapshot?.runs.find((run) => run.conversation_id === conversationId &&
    ['queued', 'running'].includes(run.status));
  const cached = conversationId ? state.live?.[conversationId] : null;
  const live = active && cached?.turnId !== active.turn_id ? null
    : cached?.streaming || (cached?.complete && (cached.text || cached.steps?.length)) ? cached : null;
  const currentTurn = state.snapshot?.turns.find((page) => page.conversation_id === conversationId)
    ?.turns.find((turn) => turn.id === (active?.turn_id ?? unknown?.turn_id ?? cached?.turnId));
  if (!live && !active && !unknown && !error) return null;
  const original = state.snapshot?.turns.find((page) => page.conversation_id === conversationId)
    ?.turns.find((turn) => turn.id === unknown?.turn_id);
  const repeat = async () => {
    if (!unknown || !original || !conversationId || busy || !teaching.ready) return;
    setBusy(true); setError('');
    try {
      await nativeRequest(`/v1/runs/${unknown.id}/cancel`, { method: 'POST' });
      await nativeStore.refresh();
      if (original.purpose === 'planning') await sendPlanningTurn(nativeStore, conversationId, original.user_text);
      else await sendTeachingTurn(nativeStore, conversationId, original.user_text,
        teaching.session?.focus ?? original.context_focus, teaching.session);
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="baseline-thinking mx-auto w-full px-4 sm:px-2 md:max-w-3xl xl:max-w-4xl"
    data-live-message={live?.messageId ?? ((live?.turnId ?? active?.turn_id ?? unknown?.turn_id)
      ? `${live?.turnId ?? active?.turn_id ?? unknown?.turn_id}:assistant` : undefined)}
    aria-label="Tutor 思考与回复">
    <span className="baseline-reply-avatar" aria-hidden="true"><GraduationCap size={16} /></span>
    <div className="min-w-0 flex-1"><p className="baseline-reply-author">Tutor</p>
    {unknown ? <div role="alert" className="space-y-3 text-sm">
      <p>上次回复在接收过程中中断，结果未知。</p>
      {original?.teaching_intent_id ? <p>可在后台任务中核对或停止原续讲，也可以直接提出新问题。</p>
        : <Action disabled={busy || !teaching.ready || !original} busy={busy}
          onClick={() => void repeat()}>结束原等待并重新发送此问题</Action>}
    </div> : null}
    {(live || active || (unknown && currentTurn?.thinking_steps?.length)) && <NativeReplyParts
      key={live?.messageId ?? live?.turnId ?? active?.turn_id ?? unknown?.turn_id}
      turnId={live?.turnId ?? active?.turn_id ?? unknown?.turn_id ?? ''}
      replyId={live?.messageId}
      conversationId={conversationId ?? ''} actorId={state.snapshot?.actor.id}
      steps={live?.steps ?? currentTurn?.thinking_steps ?? []}
      generating={Boolean(!unknown && (active || live?.streaming))} text={live?.text ?? ''}
      reasoning={live?.thinking || currentTurn?.thinking_text || ''}
      status={live?.summaries.at(-1) ?? (active?.purpose === 'planning'
        ? '正在整理学习目标与路线要求。' : '正在读取当前学习节点与上下文。')} />}
    {error && <Notice>{error}</Notice>}
    </div>
  </section>;
}

export function NativeTeachingRows<T extends MessageRow>({ rows, renderRows }: {
  rows: T[]; renderRows: (rows: T[]) => ReactNode;
}) {
  const conversationId = rows[0]?.message.conversationId ?? undefined;
  const location = useLocation();
  const planning = new URLSearchParams(location.search).get('stage') === 'planning';
  const { teaching, session, state } = useTeachingState(conversationId);
  const focus = session?.focus;
  const live = conversationId ? state.live?.[conversationId] : null;
  const liveMessageId = live?.messageId ?? (live ? `${live.turnId}:assistant` : undefined);
  const replyInHistory = Boolean(live && rows.some((row) =>
    row.message.messageId === liveMessageId));
  useEffect(() => {
    if (conversationId && replyInHistory && live?.complete && !live.streaming) {
      nativeStore.finishReply(conversationId, live.turnId);
    }
  }, [conversationId, replyInHistory, live?.turnId, liveMessageId, live?.complete, live?.streaming]);
  const groups: { id: string | null; rows: T[] }[] = [];
  for (const row of rows) {
    if (live && (live.streaming || live.complete) &&
      row.message.messageId === liveMessageId) continue;
    if (planning && row.message.leornianFocus?.kind && row.message.leornianFocus.kind !== 'goal') continue;
    if (!planning && focus?.kind === 'node' && (row.message.leornianFocus?.plan_id !== focus.plan_id ||
      row.message.leornianFocus?.expected_plan_revision !== focus.expected_plan_revision ||
      row.message.leornianFocus?.node_key !== focus.node_key)) continue;
    const id = row.message.leornianBranchId ?? null;
    if (groups.at(-1)?.id === id) groups.at(-1)!.rows.push(row);
    else groups.push({ id, rows: [row] });
  }
  return <>{groups.map((group) => {
    if (!group.id) return <Fragment key={group.rows[0].message.messageId}>{renderRows(group.rows)}</Fragment>;
    const branch = teaching?.branches.find((item) => item.id === group.id);
    return <QuestionGroup key={group.id} id={group.id} conversationId={conversationId!} branch={branch}
      active={session?.active_branch_id === group.id && branch?.state === 'active'}
      count={branch?.turn_count ?? group.rows.filter((row) => row.message.isCreatedByUser).length}>
      {renderRows(group.rows)}
    </QuestionGroup>;
  })}</>;
}
