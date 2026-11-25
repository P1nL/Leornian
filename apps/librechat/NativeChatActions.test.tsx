import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { ChatContract } from '@librechat/chat/react';
import { deleteNativeConversation, useNativeChatActions } from './NativeChatActions';

const native = vi.hoisted(() => ({
  state: {} as any, write: vi.fn(), notice: vi.fn(), request: vi.fn(), refresh: vi.fn(),
}));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, setComposerNotice: native.notice, refresh: native.refresh,
  },
}));
vi.mock('react-router-dom', () => ({ useLocation: () => ({ search: '' }) }));

beforeEach(() => {
  sessionStorage.clear();
  native.state = {
    snapshot: {
      actor: { id: 'actor' }, conversations: [{ id: 'conversation', goal_id: 'goal' }],
      plans: [{ goal_id: 'goal', latest: { revision: 2 }, active: null }], runs: [], turns: [],
    },
    pending: [],
    teaching: { actorId: 'actor', conversationId: 'conversation', session: null, intents: [],
      loading: false, error: '' },
  };
  native.write.mockReset().mockResolvedValue({ turn_id: 'new-turn' });
  native.notice.mockReset();
  native.request.mockReset().mockResolvedValue({ hidden_from_recents: true });
  native.refresh.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

test('conversation deletion removes the native recent entry and refreshes without deleting its plan', async () => {
  await expect(deleteNativeConversation({ conversationId: 'conversation' })).resolves.toEqual({
    acknowledged: true, deletedCount: 1, messages: { acknowledged: true, deletedCount: 0 },
  });
  expect(native.request).toHaveBeenCalledExactlyOnceWith(
    '/v1/conversations/conversation/recent-entry', { method: 'DELETE' });
  expect(native.refresh).toHaveBeenCalledOnce();
  expect(native.write).not.toHaveBeenCalled();
});

test('a failed conversation deletion retains the backend reason and does not refresh away the row', async () => {
  native.request.mockRejectedValueOnce(new Error('当前身份已失效'));
  await expect(deleteNativeConversation({ conversationId: 'conversation' })).rejects.toThrow('当前身份已失效');
  expect(native.refresh).not.toHaveBeenCalled();
});

function context() {
  const messages = [
    { messageId: 'turn:user', text: '学习 JavaScript', isCreatedByUser: true },
    { messageId: 'turn:assistant', text: '路线讨论', parentMessageId: 'turn:user', isCreatedByUser: false },
  ];
  return {
    conversation: { conversationId: 'conversation' }, messagesKey: 'conversation',
    latestMessageId: 'turn:assistant', isSubmitting: false,
    getMessages: () => messages, setMessages: vi.fn(), ask: vi.fn(),
    regenerate: vi.fn(), handleRegenerate: vi.fn(), handleContinue: vi.fn(),
  } as unknown as ChatContract;
}

test('edited user messages append a public planning turn without upstream sends or optimistic branches', async () => {
  const upstream = context();
  const { result } = renderHook(() => useNativeChatActions(upstream));
  await act(async () => {
    result.current.ask({ text: 'JS吧', conversationId: 'conversation', parentMessageId: 'turn:user' });
    result.current.ask({ text: 'JS吧', conversationId: 'conversation' });
  });
  expect(native.write).toHaveBeenCalledTimes(1);
  expect(native.write).toHaveBeenCalledWith('/v1/conversations/conversation/plan-requests', {
    text: 'JS吧', expected_revision: 2, discussion: true, focus: { kind: 'goal' },
  }, { key: expect.any(String), lookup: expect.stringContaining('/turn-requests/') });
  expect(upstream.ask).not.toHaveBeenCalled();
  expect(upstream.setMessages).not.toHaveBeenCalled();
  expect(upstream.getMessages()).toHaveLength(2);
});

test('regenerate and continue use public contracts instead of upstream closures', async () => {
  const upstream = context();
  const { result } = renderHook(() => useNativeChatActions(upstream));
  await act(async () => { result.current.regenerate({ messageId: 'turn:assistant' }); });
  await act(async () => { result.current.handleContinue({ preventDefault: vi.fn() } as any); });
  expect(native.write.mock.calls.map(([path, body]) => [path, body.text])).toEqual([
    ['/v1/conversations/conversation/plan-requests', '学习 JavaScript'],
    ['/v1/conversations/conversation/plan-requests', '请接着上一条回复继续。'],
  ]);
  expect(upstream.regenerate).not.toHaveBeenCalled();
  expect(upstream.handleContinue).not.toHaveBeenCalled();
});

test('teaching edits preserve the current native focus and teaching-session revision', async () => {
  const focus = { kind: 'node', plan_id: 'plan', expected_plan_revision: 3, node_key: 'first' };
  native.state.snapshot.plans[0].active = { revision: 3 };
  native.state.teaching.session = { revision: 4, focus };
  const { result } = renderHook(() => useNativeChatActions(context()));
  await act(async () => { result.current.ask({ text: '请再解释一下', conversationId: 'conversation' }); });
  expect(native.write).toHaveBeenCalledWith('/v1/conversations/conversation/turns',
    expect.objectContaining({ text: '请再解释一下', focus, teaching_session_revision: 4,
      presentation_capabilities: expect.objectContaining({ versions: ['learning_composition.v2'] }) }),
    expect.objectContaining({ key: expect.any(String), lookup: expect.stringContaining('/turn-requests/') }));
});

test('unknown requests block replays and rejected dispatches retain edited text for composer recovery', async () => {
  native.state.pending = [{ path: '/v1/conversations/conversation/plan-requests', status: 'unknown' }];
  const { result, rerender } = renderHook(() => useNativeChatActions(context()));
  expect(result.current.isSubmitting).toBe(true);
  expect(result.current.ask({ text: 'JS吧', conversationId: 'conversation' })).toBe(false);
  expect(native.write).not.toHaveBeenCalled();
  native.state.pending = [];
  native.write.mockRejectedValueOnce(new Error('当前模型配置不可用'));
  rerender();
  await act(async () => { result.current.ask({ text: 'JS吧', conversationId: 'conversation' }); });
  expect(native.notice).toHaveBeenLastCalledWith({
    conversationId: 'conversation', text: 'JS吧', error: '当前模型配置不可用',
    draftKey: 'leornian.native.composer:actor:conversation',
  });
  expect(sessionStorage.getItem('leornian.native.composer:actor:conversation')).toBe('JS吧');
});
