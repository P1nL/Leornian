import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { BaselineRoutes } from './BaselineRoutes';
import { NativeLiveReply, NativeTeachingRows } from './NativeTeaching';
import { BaselineComposer } from './BaselineLearning';
import NativeRouteConfirmation from './NativeRouteConfirmation';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), refresh: vi.fn(), write: vi.fn(), navigate: vi.fn(), finishReply: vi.fn(),
}));
vi.mock('./NativeLearning', () => ({ useNative: () => native.state }));
vi.mock('./NativeReplyParts', () => ({
  default: ({ reasoning, text, status }: { reasoning: string; text: string; status?: string }) =>
    <div data-testid="reply-parts" data-reasoning={reasoning}>{reasoning || text || status}</div>,
}));
vi.mock('@ariakit/react', async (original) => ({
  ...await original<typeof import('@ariakit/react')>(),
  MenuButton: ({ children, ...props }: any) => <button {...props}>{children}</button>,
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state, refresh: native.refresh,
    write: native.write, openTeaching: vi.fn(), finishReply: native.finishReply,
  },
}));
vi.mock('react-router-dom', () => ({
  useParams: () => ({ conversationId: 'conversation' }), useNavigate: () => native.navigate,
  useLocation: () => ({ state: null }),
}));
beforeEach(() => {
  sessionStorage.clear();
  native.state = { pending: [], snapshot: {
    actor: { id: 'actor' }, goals: [{ id: 'goal', title: 'Python' }], plans: [],
    conversations: [{ id: 'conversation', goal_id: 'goal' }], runs: [], turns: [],
  }, teaching: { actorId: 'actor', conversationId: 'conversation', session: null, loading: false } };
  native.request.mockReset().mockImplementation(async (path: string) =>
    path.includes('/environment-requirements/') ? {
      plan_id: 'plan', plan_revision: Number(path.split('/').at(-1)), requirements: [],
      automatic_recipe_ids: [], consent_required: [], demands: [], gaps: [],
      engine: { status: 'ready' },
    } : path.endsWith('/teaching-session') ? null : { ready: true });
  native.refresh.mockReset().mockResolvedValue(undefined);
  native.write.mockReset().mockResolvedValue({ turn_id: 'new-turn' });
  native.navigate.mockReset();
  native.finishReply.mockReset().mockImplementation(() => {
    native.state = { ...native.state, live: {} };
  });
});
afterEach(cleanup);

test('route folders have actions instead of a second create button and rename through the API', async () => {
  render(<BaselineRoutes />);
  expect(screen.queryByRole('button', { name: '创建新学习计划' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Python 操作' }));
  fireEvent.click(screen.getByRole('button', { name: '重命名' }));
  fireEvent.change(screen.getByRole('textbox', { name: '名称' }), { target: { value: ' Python 基础 ' } });
  fireEvent.click(screen.getByRole('button', { name: '保存名称' }));
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/goals/goal',
    { method: 'PATCH', body: JSON.stringify({ title: 'Python 基础' }) }));
  await waitFor(() => expect(native.refresh).toHaveBeenCalledOnce());
});

test('delete requires confirmation, preserves an API error, and navigates after success', async () => {
  render(<BaselineRoutes />);
  fireEvent.click(screen.getByRole('button', { name: 'Python 操作' }));
  fireEvent.click(screen.getByRole('button', { name: '删除' }));
  expect(native.request).not.toHaveBeenCalled();
  native.request.mockRejectedValueOnce(new Error('先结束当前教学'));
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }));
  await screen.findByText('先结束当前教学');
  expect(native.navigate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }));
  await waitFor(() => expect(native.navigate).toHaveBeenCalledWith('/c/new'));
  expect(native.request).toHaveBeenLastCalledWith('/v1/goals/goal', { method: 'DELETE' });
});

function setUnknown() {
  native.state.snapshot.runs = [{ id: 'run', conversation_id: 'conversation', turn_id: 'old-turn', status: 'blocked_unknown' }];
  native.state.snapshot.turns = [{ conversation_id: 'conversation',
    turns: [{ id: 'old-turn', user_text: '继续制定路线', context_focus: { kind: 'goal', goal_id: 'goal' } }] }];
}

test('unknown replies only cancel and send a new request after an explicit click', async () => {
  setUnknown();
  render(<NativeLiveReply conversationId="conversation" />);
  expect(native.request).not.toHaveBeenCalled();
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '结束原等待并重新发送此问题' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledOnce());
  expect(native.request).toHaveBeenCalledWith('/v1/runs/run/cancel', { method: 'POST' });
  expect(native.write.mock.calls[0].slice(0, 2)).toEqual(['/v1/conversations/conversation/turns',
    expect.objectContaining({ text: '继续制定路线', focus: { kind: 'goal', goal_id: 'goal' } })]);
});

test('a failed new submission remains visible after the old unknown run is cancelled', async () => {
  setUnknown();
  native.refresh.mockImplementation(async () => {
    native.state = { ...native.state, snapshot: { ...native.state.snapshot, runs: [] } };
  });
  native.write.mockRejectedValueOnce(new Error('新问题未发送'));
  render(<NativeLiveReply conversationId="conversation" />);
  fireEvent.click(screen.getByRole('button', { name: '结束原等待并重新发送此问题' }));
  await screen.findByText('新问题未发送');
});

test('completed thinking leaves no reserved reply area above the composer', () => {
  native.state.live = { conversation: { turnId: 'finished', streaming: false, summaries: ['已完成'] } };
  const view = render(<NativeLiveReply conversationId="conversation" />);
  expect(view.container.innerHTML).toBe('');
});

test('accepted body keeps playing after the run finishes and hands off only to a loaded history row', () => {
  native.state.live = { conversation: { turnId: 'turn', complete: true, streaming: true,
    thinking: '', text: '逐步', fullText: '逐步显示完整正文', summaries: [] } };
  const rows = [{ message: { messageId: 'turn:assistant', conversationId: 'conversation' } }];
  const renderRows = () => <p>逐步显示完整正文</p>;
  const content = () => <>
    <NativeTeachingRows rows={rows} renderRows={renderRows} />
    <NativeLiveReply conversationId="conversation" />
  </>;
  const view = render(content());
  expect(screen.getByText('逐步')).toBeTruthy();
  expect(screen.queryByText('逐步显示完整正文')).toBeNull();
  expect(native.finishReply).not.toHaveBeenCalled();

  native.state.live.conversation = { ...native.state.live.conversation,
    streaming: false, text: '逐步显示完整正文' };
  view.rerender(content());
  expect(native.finishReply).toHaveBeenCalledWith('conversation', 'turn');
  view.rerender(content());
  expect(screen.getAllByText('逐步显示完整正文')).toHaveLength(1);
  expect(screen.queryByTestId('reply-parts')).toBeNull();
});

test('a fully played reply remains visible until its history row has loaded', () => {
  native.state.live = { conversation: { turnId: 'turn', complete: true, streaming: false,
    thinking: '', text: '检查通过的完整正文', summaries: [] } };
  render(<><NativeTeachingRows rows={[]} renderRows={() => null} />
    <NativeLiveReply conversationId="conversation" /></>);
  expect(screen.getByText('检查通过的完整正文')).toBeTruthy();
  expect(native.finishReply).not.toHaveBeenCalled();
});

test('thinking events render model text instead of the fallback phase sentence', () => {
  native.state.snapshot.runs = [{ id: 'run', turn_id: 'turn', conversation_id: 'conversation', status: 'running' }];
  native.state.live = { conversation: { turnId: 'turn', streaming: true,
    summaries: ['正在整理学习目标与路线要求。'], thinking: '先确认基础，再安排查找练习。', text: '' } };
  render(<NativeLiveReply conversationId="conversation" />);
  expect(screen.getByText('先确认基础，再安排查找练习。')).toBeTruthy();
  expect(screen.queryByText('正在整理学习目标与路线要求。')).toBeNull();
});

test('reconnection restores saved thinking before the next text frame arrives', () => {
  native.state.snapshot.runs = [{ id: 'run', turn_id: 'turn', conversation_id: 'conversation', status: 'running' }];
  native.state.snapshot.turns = [{ conversation_id: 'conversation',
    turns: [{ id: 'turn', thinking_text: '先理解循环，再讨论查找。' }] }];
  native.state.live = { conversation: { turnId: 'turn', streaming: true,
    summaries: ['正在整理学习目标与路线要求。'], thinking: '', text: '' } };
  render(<NativeLiveReply conversationId="conversation" />);
  expect(screen.getByText('先理解循环，再讨论查找。')).toBeTruthy();
});

test('an active conversation has no status sentence under the composer', async () => {
  native.state.snapshot.runs = [{ conversation_id: 'conversation', status: 'running' }];
  render(<BaselineComposer conversationId="conversation" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  expect(screen.queryByText('当前教学正在处理；可在后台任务中查看或取消。')).toBeNull();
});

test('an existing unconfirmed route conversation sends planning discussion, not a teaching turn', async () => {
  render(<BaselineComposer conversationId="conversation" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '我想先讨论算法学习路线' } });
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledOnce());
  expect(native.write.mock.calls[0].slice(0, 2)).toEqual([
    '/v1/conversations/conversation/plan-requests',
    { text: '我想先讨论算法学习路线', expected_revision: 0, discussion: true, focus: { kind: 'goal' } },
  ]);
});

test('only explicit route confirmation opens the first node and animates into the learning view', async () => {
  native.state.snapshot.plans = [{ id: 'plan', goal_id: 'goal', active: null,
    latest: { revision: 1, document: { nodes: [{ key: 'first', title: '基础' }] } } }];
  render(<NativeRouteConfirmation conversationId="conversation" />);
  expect(native.write).not.toHaveBeenCalled();
  expect(native.navigate).not.toHaveBeenCalled();
  const confirm = screen.getByRole('button', { name: '确认路线，开始学习' }) as HTMLButtonElement;
  await waitFor(() => expect(confirm.disabled).toBe(false));
  fireEvent.click(confirm);
  await waitFor(() => expect(native.navigate).toHaveBeenCalledWith('/c/conversation?node=first',
    { state: { learningNodeArrival: true } }));
  expect(native.write.mock.calls.map(([path]) => path)).toEqual([
    '/v1/plans/plan/confirm', '/v2/conversations/conversation/teaching-session/actions',
  ]);
  expect(native.write.mock.calls[1][1]).toMatchObject({ action: 'open', focus: { kind: 'node', node_key: 'first' } });
  const confirmed = screen.getByRole('button', { name: '路线已确认' });
  expect((confirmed as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(confirmed);
  expect(native.write).toHaveBeenCalledTimes(2);
});

test('a confirmed revision stays disabled after remount while a new draft can be confirmed', async () => {
  const version = { revision: 1, document: { nodes: [{ key: 'first', title: '基础' }] } };
  native.state.snapshot.plans = [{ id: 'plan', goal_id: 'goal', active: version, latest: version }];
  const view = render(<NativeRouteConfirmation conversationId="conversation" />);
  const confirmed = screen.getByRole('button', { name: '路线已确认' });
  expect((confirmed as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(confirmed);
  expect(native.write).not.toHaveBeenCalled();
  expect(native.navigate).not.toHaveBeenCalled();

  native.state = { ...native.state, snapshot: { ...native.state.snapshot,
    plans: [{ ...native.state.snapshot.plans[0], latest: { ...version, revision: 2 } }],
  } };
  view.rerender(<NativeRouteConfirmation conversationId="conversation" />);
  await waitFor(() => expect((screen.getByRole('button', { name: '确认路线，开始学习' }) as HTMLButtonElement).disabled).toBe(false));
});
