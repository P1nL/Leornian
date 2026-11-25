import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import type { ReactNode } from 'react';
import * as Ariakit from '@ariakit/react';
import { Button, DropdownPopup } from '@librechat/client';
import { Ellipsis } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { DemoDialog, Notice } from './LearningUI';
import { LearningComposerFrame, LearningTaskPopover, LearningWelcome } from './LearningChrome';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { composerDraftKey, continueNode, defaultMaterialScope, intakeKey, prepareLearning, readIntake, sendPlanningTurn, sendTeachingTurn } from './native-intake.mjs';
import { NativeConversationContent, NativeSourcePanel, NativeTaskList, selectedFocus, useNative } from './NativeLearning';
import { useTeachingState, writeTeachingControl } from './NativeTeaching';
import NodeTeachingWindow from './NodeTeachingWindow';
import { BaselinePanelContent, baselinePanelTitles } from './BaselinePanels';
import { useBaselineAttachments } from './BaselineAttachments';
import { animateComposerArrival, observeMessageEntrances } from './baseline-motion';
import { beginPlanning } from './learning-routes.mjs';
import BaselineRagProgress from './BaselineRagProgress';
import './baseline-learning.css';
export { BaselineRoutes } from './BaselineRoutes';
export { BaselineQuestionBank } from './BaselineQuestionBank';
export { BaselineMaterials, BaselinePreferences, BaselineEnvironmentSettings } from './BaselinePanels';

export function BaselineConversationContent({ conversationId, children }: {
  conversationId?: string; children: ReactNode;
}) {
  const location = useLocation(), state = useNative();
  const contentRef = useRef<HTMLDivElement>(null);
  const entrances = useRef({ conversationId, seen: new Set<string>() });
  const focus = state.snapshot?.teaching_sessions?.find((item) => item.conversation_id === conversationId)?.focus;
  useLayoutEffect(() => {
    const pane = contentRef.current?.closest<HTMLElement>('[data-chat-pane]');
    const composer = pane?.querySelector<HTMLElement>('.demo-composer');
    if (!pane || !composer) return;
    // Reserve scroll space for the floating composer, including textarea resizes.
    const measure = () => pane.style.setProperty('--baseline-composer-height', `${composer.offsetHeight}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(composer);
    return () => {
      observer.disconnect();
      pane.style.removeProperty('--baseline-composer-height');
    };
  }, [conversationId, focus?.node_key]);
  useLayoutEffect(() => {
    if (!contentRef.current) return;
    if (entrances.current.conversationId !== conversationId) {
      entrances.current = { conversationId, seen: new Set<string>() };
    }
    return observeMessageEntrances(contentRef.current, entrances.current.seen);
  }, [conversationId, focus?.node_key]);
  return <div key={`${conversationId}:${focus?.node_key ?? ''}`}
    ref={contentRef} data-baseline-conversation
    className={`flex min-h-0 flex-1 flex-col ${location.state?.learningNodeArrival ? 'baseline-node-arrival' : ''}`}>
    <NativeConversationContent conversationId={conversationId}>{children}</NativeConversationContent>
    <BaselineRagProgress key={conversationId} conversationId={conversationId} />
  </div>;
}

type Snapshot = components['schemas']['Snapshot'];
const gallery = 'http://127.0.0.1:5182/__preview/artifacts';

export function BaselineStart() {
  return <LearningWelcome />;
}

export function BaselineComposer({ conversationId }: { conversationId?: string }) {
  const state = useNative(), snapshot = state.snapshot as Snapshot | null, navigate = useNavigate();
  const isNew = !conversationId || conversationId === 'new';
  const teaching = useTeachingState(isNew ? undefined : conversationId);
  const pageLocation = useLocation();
  const pageKey = useRef(pageLocation.key);
  pageKey.current = pageLocation.key;
  const goalId = snapshot?.conversations.find((item) => item.id === conversationId)?.goal_id;
  const plan = snapshot?.plans.find((item) => item.goal_id === goalId);
  const params = new URLSearchParams(pageLocation.search);
  const planning = !plan?.active || params.get('stage') === 'planning';
  const session = snapshot?.teaching_sessions?.find((item) => item.conversation_id === conversationId) ?? teaching.session;
  const node = !isNew && !planning && session?.focus.kind === 'node' ? session.focus : null;
  const nodeMatches = (!params.get('node') || params.get('node') === node?.node_key) &&
    (!node || plan?.id === node.plan_id && plan?.active?.revision === node.expected_plan_revision);
  const [draft, setDraft] = useState({ key: '', value: '' }), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [progress, setProgress] = useState('');
  const actorId = snapshot?.actor.id;
  const key = actorId ? composerDraftKey(actorId, isNew ? 'new' : conversationId, node) : '';
  const text = draft.key === key ? draft.value : '';
  const setText = (value: string) => setDraft({ key, value });
  const attachments = useBaselineAttachments(isNew ? null : conversationId!, text);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const location = useRef(key);
  location.current = key;
  useLayoutEffect(() => {
    if (isNew || !pageLocation.state?.composerOrigin || !surfaceRef.current) return;
    const animation = animateComposerArrival(surfaceRef.current, pageLocation.state.composerOrigin);
    return () => animation?.cancel();
  }, [isNew, conversationId, pageLocation.key]);
  useEffect(() => {
    const saved = isNew ? readIntake(sessionStorage, actorId) : null;
    const recovered = saved?.attachment_draft && saved.text === '新学习计划' ? '' : saved?.text;
    setDraft({ key, value: key ? sessionStorage.getItem(key) ?? recovered ?? '' : '' });
    setError(key ? sessionStorage.getItem(`${key}:notice`) ?? '' : '');
    return () => { if (location.current === key) location.current = ''; };
  }, [key, isNew, actorId]);
  useEffect(() => {
    const notice = state.composerNotice;
    if (!notice || notice.conversationId !== conversationId || (notice.draftKey && notice.draftKey !== key)) return;
    setError(notice.error);
    if (notice.error) {
      setDraft({ key, value: notice.text });
      try { if (key) sessionStorage.setItem(key, notice.text); } catch {}
    } else setDraft((value) => value.key === key && value.value.trim() === notice.text
      ? { key, value: '' } : value);
  }, [state.composerNotice, conversationId, key]);
  useEffect(() => {
    let current = true;
    void nativeRequest('/v1/tutor/availability').then((value) => { if (current) setReady(value.ready); })
      .catch(() => { if (current) setReady(false); });
    return () => { current = false; };
  }, [actorId, state.epoch]);
  const autoPath = `/v2/conversations/${conversationId}/teaching-session/continue`;
  const unresolved = state.pending.some((item) => isNew ? item.path === '/v1/goals'
    : item.path.includes(`/conversations/${conversationId}/`) && item.path !== autoPath);
  const blocked = !snapshot || busy || attachments.uploading || attachments.pending || unresolved || (!isNew && (!nodeMatches || !teaching.ready ||
    Boolean(teaching.active && !teaching.automaticActive)));
  const submit = async () => {
    if (blocked || !text.trim() || (!isNew && !ready)) return;
    const originalKey = key, input = text.trim();
    const bounds = isNew ? surfaceRef.current?.getBoundingClientRect() : null;
    const composerOrigin = bounds
      ? { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height } : null;
    setBusy(true); setError(''); setProgress('正在创建学习计划…');
    try {
      if (isNew) {
        const original = readIntake(sessionStorage, actorId);
        const result = await prepareLearning(input, {
          store: nativeStore, request: nativeRequest, storage: sessionStorage,
          materialScope: original && (original.text === input || original.discussion_dispatched || original.attachment_draft)
            ? original.material_scope ?? null : defaultMaterialScope,
        });
        if (!('conversation' in result)) { setError('目标已接收，仍在准备。可再次发送以只读查询原任务。'); return; }
        if (location.current !== originalKey || nativeStore.getSnapshot().snapshot?.actor.id !== actorId) return;
        const conversation = result.conversation!;
        const nextKey = `leornian.native.composer:${actorId}:${conversation.id}`;
        sessionStorage.setItem(nextKey, input);
        if (ready) {
          await beginPlanning(conversation, input, {
            store: nativeStore, request: nativeRequest, storage: sessionStorage,
          });
          sessionStorage.removeItem(nextKey);
          sessionStorage.removeItem(intakeKey(actorId));
          sessionStorage.removeItem(originalKey);
          if (location.current === originalKey) navigate(`/c/${conversation.id}?stage=planning`, { state: { composerOrigin } });
        } else {
          sessionStorage.setItem(`${nextKey}:notice`, '学习目标已保存。配置模型后可在这里继续讨论学习路线。');
          sessionStorage.removeItem(intakeKey(actorId));
          sessionStorage.removeItem(originalKey);
          if (location.current === originalKey) navigate(`/c/${conversation.id}`, { state: { composerOrigin } });
        }
      } else {
        if (planning) {
          await sendPlanningTurn(nativeStore, conversationId, input);
          if (readIntake(sessionStorage, actorId)?.conversation_id === conversationId) {
            sessionStorage.removeItem(intakeKey(actorId));
          }
        } else await sendTeachingTurn(nativeStore, conversationId, input,
          session?.focus ?? selectedFocus(snapshot, conversationId), session);
        sessionStorage.removeItem(originalKey);
        sessionStorage.removeItem(`${originalKey}:notice`);
        if (location.current === originalKey) setText('');
      }
    } catch (problem) { if (location.current === originalKey) setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  const status = attachments.uploading ? '正在上传资料…' : busy ? isNew ? progress : '正在提交…' : isNew ? ready ? '' : '先保存目标，再配置自己的模型'
    : ready ? '' : '请在学习菜单中配置自己的模型';
  const handoff = session?.node_window;
  const nodeKey = node && session && handoff ? `${key}:${session.revision}:${handoff.after_turn_id ?? 'opening'}` : '';
  const expired = async () => {
    if (!session || !conversationId) return;
    try { await continueNode(nativeStore, conversationId, session); }
    catch (problem) {
      if ((problem as { status?: number }).status === 409) { await nativeStore.refresh(); return; }
      if (location.current === key) setError((problem as Error).message);
    }
  };
  const eligible = Boolean(nodeKey && nodeMatches && ready && draft.key === key && !text && !busy && !unresolved &&
    !attachments.uploading && !attachments.pending && !state.reader && !state.error && state.connection === '已连接' &&
    !state.pending.some((item) => item.path === autoPath) && !teaching.active && !teaching.teaching?.error &&
    !state.live?.[conversationId!]?.streaming && session?.mode === 'guided' && !session.paused && !session.active_branch_id &&
    (handoff?.next_step === 'opening' || handoff?.next_step === 'can_continue'));
  const ended = snapshot?.conversations.find((item) => item.id === conversationId)?.ended_nodes?.some((item) =>
    item.plan_id === node?.plan_id && item.plan_revision === node.expected_plan_revision && item.node_key === node.node_key);
  const finish = async () => {
    if (!node || !session || !conversationId || !handoff?.after_turn_id || blocked) return;
    const originalPage = pageKey.current;
    setBusy(true); setError('');
    try {
      const next = await writeTeachingControl(conversationId, session, {
        action: 'finish_node', focus: node, after_turn_id: handoff.after_turn_id,
      });
      if (pageKey.current === originalPage && nativeStore.getSnapshot().snapshot?.actor.id === actorId &&
        next.focus.node_key !== node.node_key)
        navigate(`/c/${conversationId}?node=${encodeURIComponent(next.focus.node_key)}`, { state: { learningNodeArrival: true } });
    } catch (problem) { if (location.current === key) setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <LearningComposerFrame value={text} onChange={(value) => {
    setText(value);
    try { if (key) sessionStorage.setItem(key, value); }
    catch { setError('草稿暂时只保存在当前页面，浏览器存储不可用。'); }
  }} onSubmit={() => void submit()} onAttachment={attachments.open} attachments={attachments.content} surfaceRef={surfaceRef}
    placeholder={isNew ? '我想学习……' : planning ? '讨论学习目标、基础和路线安排……' : '围绕当前节点提问……'}
    label="学习目标或问题" sendLabel="发送给 Tutor" status={nodeKey ? <>{status}
      <NodeTeachingWindow key={key} identity={nodeKey} after={handoff!.after_turn_id}
        enabled={eligible} onExpire={() => void expired()} /></> : status} maxLength={isNew ? 1200 : 4000}
    disabled={busy || attachments.uploading || !snapshot} sendDisabled={blocked || (!isNew && !ready)}>
    {unresolved && <Notice>原提交尚待核对。请在后台任务中读取原回执。</Notice>}
    {nodeMatches && node && handoff?.next_step === 'wrap_up' && !session?.active_branch_id && !ended &&
      <button type="button" className="baseline-finish-node" disabled={blocked || !!text}
        onClick={() => void finish()}>{plan?.active?.document.nodes.at(-1)?.key === node.node_key
          ? '结束本节' : '结束本节，进入下一节'}</button>}
    {nodeMatches && node && ended && handoff?.next_step === 'wrap_up' && <p className="demo-muted">本节已结束，仍可继续提问。</p>}
    {teaching.teaching?.error && <Notice>教学状态暂未同步，请重新读取当前学习；草稿保留。</Notice>}
    {error && <Notice>{error}</Notice>}
  </LearningComposerFrame>;
}

export function BaselineTasks(_props: Record<string, unknown>) {
  return <LearningTaskPopover><NativeTaskList /></LearningTaskPopover>;
}

export function BaselineSourcePanel(props: Parameters<typeof NativeSourcePanel>[0]) {
  return <NativeSourcePanel {...props} baseline />;
}

export function BaselineLearningMenu({ className = '' }: { className?: string; [key: string]: unknown }) {
  const [open, setOpen] = useState(false), [dialog, setDialog] = useState('');
  const id = useRef(`baseline-menu-${crypto.randomUUID()}`).current;
  const items = [['route', '查看当前路线'], ['records', '学习记录'], ['reviews', '到期复习'],
    ['materials', '教材与更新'], ['preferences', '学习方式与提醒'], ['models', '我的模型配置'],
    ['environment', '本机执行环境']]
    .map(([value, label]) => ({ id: value, label, onClick: () => { setOpen(false); setDialog(value); } }));
  items.push({ id: 'gallery', label: '学习工件一览', onClick: () => {
    setOpen(false); window.open(gallery, '_blank', 'noopener,noreferrer');
  } });
  return <>
    <DropdownPopup portal menuId={id} focusLoop unmountOnHide isOpen={open} setIsOpen={setOpen} items={items}
      trigger={<Ariakit.MenuButton aria-label="当前学习菜单"
        render={<Button size="icon" variant="header-action" className={`relative size-9 shrink-0 ${className}`} />}>
        <Ellipsis size={20} /></Ariakit.MenuButton>} />
    <DemoDialog open={Boolean(dialog)} onClose={() => setDialog('')} title={baselinePanelTitles[dialog] ?? '当前学习'}>
      <BaselinePanelContent panel={dialog} onClose={() => setDialog('')} />
    </DemoDialog>
  </>;
}
