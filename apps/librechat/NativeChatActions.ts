import { useCallback, useMemo, useRef, useSyncExternalStore } from 'react';
import { useLocation } from 'react-router-dom';
import type { ChatContract, RegenerateTarget } from '@librechat/chat/react';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { composerDraftKey, sendPlanningTurn, sendTeachingTurn } from './native-intake.mjs';

export async function deleteNativeConversation({ conversationId }: { conversationId?: string }) {
  if (!conversationId) throw new Error('请先选择要删除的对话。');
  await nativeRequest(`/v1/conversations/${encodeURIComponent(conversationId)}/recent-entry`, {
    method: 'DELETE',
  });
  await nativeStore.refresh();
  return { acknowledged: true, deletedCount: 1, messages: { acknowledged: true, deletedCount: 0 } };
}

function blockedReason(conversationId: string | null | undefined) {
  const { snapshot, pending, teaching } = nativeStore.getSnapshot();
  if (!snapshot?.conversations.some((item) => item.id === conversationId)) {
    return '请先从学习或最近入口打开已保存的会话。';
  }
  if (pending.some((item) => item.path.includes(`/conversations/${conversationId}/`) &&
    !item.path.endsWith('/teaching-session/continue'))) {
    return '原提交尚待核对，请在后台任务中读取原回执，不会重复发送。';
  }
  const active = snapshot.runs.find((run) => run.conversation_id === conversationId
    && ['queued', 'running', 'blocked_unknown'].includes(run.status));
  const automatic = active && (teaching?.intents.some((intent) => intent.run_id === active.id)
    || snapshot.turns.some((page) => page.conversation_id === conversationId
      && page.turns.some((turn) => turn.id === active.turn_id && turn.teaching_intent_id != null)));
  if (active && (active.status === 'blocked_unknown' || !automatic)) return '当前请求尚未结束，请先等待结果或核对原请求。';
  if (!teaching || teaching.conversationId !== conversationId || teaching.actorId !== snapshot.actor.id
    || teaching.loading || teaching.error) return '当前学习状态尚未同步，请稍后再发送。';
  return '';
}

export function useNativeChatActions(context: ChatContract): ChatContract {
  const location = useLocation();
  const conversationId = context.conversation?.conversationId;
  const current = useRef(context), inFlight = useRef(false);
  current.current = context;
  const getBusy = useCallback(() => Boolean(blockedReason(conversationId)), [conversationId]);
  const busy = useSyncExternalStore(nativeStore.subscribe, getBusy);
  const planningStage = new URLSearchParams(location.search).get('stage') === 'planning';

  const ask = useCallback<ChatContract['ask']>((input, options) => {
    const state = nativeStore.getSnapshot(), actorId = state.snapshot?.actor.id;
    const text = input.text.trim();
    if (!text || !conversationId || !actorId) return false;
    const session = state.teaching?.session;
    const draftKey = composerDraftKey(actorId, conversationId, planningStage ? null : session?.focus);
    const notify = (error: string) => {
      if (nativeStore.getSnapshot().snapshot?.actor.id === actorId) {
        nativeStore.setComposerNotice({ conversationId, text, error, draftKey });
      }
    };
    const reason = blockedReason(conversationId);
    if (reason || inFlight.current) {
      notify(reason || '正在提交，请勿重复发送。');
      return false;
    }
    if ((input.conversationId && input.conversationId !== conversationId)
      || (input.overrideConvoId && input.overrideConvoId !== conversationId)
      || (current.current.messagesKey && current.current.messagesKey !== conversationId)) {
      notify('会话正在切换，请在目标会话加载完成后再发送。');
      return false;
    }
    if (options?.editedContent) {
      notify('模型回复保留原文，请在输入框中提出修改要求。');
      return false;
    }
    if (text.length > 4000) {
      notify('请将本次消息控制在 4000 字以内。');
      return false;
    }
    const conversation = state.snapshot!.conversations.find((item) => item.id === conversationId)!;
    const plan = state.snapshot!.plans.find((item) => item.goal_id === conversation.goal_id);
    const planning = planningStage || !plan?.active;
    if (!planning && !session) {
      notify('请先进入当前学习节点，再发送教学消息。');
      return false;
    }
    inFlight.current = true;
    nativeStore.setComposerNotice(null);
    try { if (sessionStorage.getItem(draftKey) === null) sessionStorage.setItem(draftKey, text); } catch {}
    // Edits and explicit retries append native turns; accepted history is never rewritten.
    const request = planning
      ? sendPlanningTurn(nativeStore, conversationId, text)
      : sendTeachingTurn(nativeStore, conversationId, text, session!.focus, session);
    void request.then(() => {
      try { if (sessionStorage.getItem(draftKey) === text) sessionStorage.removeItem(draftKey); } catch {}
      notify('');
    }).catch((problem: Error) => notify(problem.message)).finally(() => { inFlight.current = false; });
  }, [conversationId, planningStage]);

  const regenerate = useCallback<ChatContract['regenerate']>((target: RegenerateTarget) => {
    const messages = current.current.getMessages() ?? [];
    const selected = messages.find((message) => message.messageId === target.messageId);
    const user = selected?.isCreatedByUser ? selected
      : messages.find((message) => message.isCreatedByUser
        && message.messageId === (selected?.parentMessageId ?? target.parentMessageId));
    if (user) ask({ text: user.text, conversationId });
  }, [ask, conversationId]);
  const handleRegenerate = useCallback<ChatContract['handleRegenerate']>((event) => {
    event.preventDefault();
    regenerate({ messageId: current.current.latestMessageId });
  }, [regenerate]);
  const handleContinue = useCallback<ChatContract['handleContinue']>((event) => {
    event.preventDefault();
    ask({ text: '请接着上一条回复继续。', conversationId });
  }, [ask, conversationId]);
  return useMemo(() => ({ ...context, ask, regenerate, handleRegenerate, handleContinue,
    isSubmitting: context.isSubmitting || busy }), [context, ask, regenerate, handleRegenerate, handleContinue, busy]);
}
