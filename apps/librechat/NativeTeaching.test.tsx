import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { NativeTeachingControls, NativeTeachingRows } from './NativeTeaching';
import { NativeComposer, NativeLearningScope } from './NativeLearning';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), write: vi.fn(), openTeaching: vi.fn(), refreshTeaching: vi.fn(),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, openTeaching: native.openTeaching, refreshTeaching: native.refreshTeaching,
  },
}));
vi.mock('react-router-dom', () => ({
  useParams: () => ({ conversationId: 'conversation' }), useNavigate: () => vi.fn(),
  useLocation: () => ({ search: '' }),
}));

const focus = { kind: 'node', plan_id: 'plan', expected_plan_revision: 1, node_key: 'loops' };
const session = {
  conversation_id: 'conversation', revision: 4, generation: 3, mode: 'guided',
  paused: false, focus, active_branch_id: null, updated_at: '2026-11-06T00:00:00Z',
  continuation_policy: 'manual', continuation_generation: 1,
};
function opened() {
  native.state.teaching.session = { ...session };
}
beforeEach(() => {
  sessionStorage.clear();
  native.state = {
    snapshot: {
      actor: { id: 'owner' }, turns: [], runs: [],
      conversations: [{ id: 'conversation', goal_id: 'goal' }],
      plans: [{ id: 'plan', goal_id: 'goal', active: { revision: 1, document: { nodes: [{ key: 'loops', title: '循环' }] } } }],
      evaluations: [], packs: [],
    }, epoch: 1, pending: [], reader: null,
    teaching: { actorId: 'owner', conversationId: 'conversation', session: null, branches: [], intents: [], loading: false, error: '' },
  };
  native.request.mockReset().mockResolvedValue({ ready: true });
  native.write.mockReset().mockResolvedValue({ ...session });
  native.openTeaching.mockReset().mockResolvedValue(undefined);
  native.refreshTeaching.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

test('due review intents without a model run keep their exact cancellation and window reason', async () => {
  opened();
  native.state.teaching.intents = [{
    id: 'due-intent', trigger_kind: 'review_due', state: 'dispatched',
    wait_reason: 'outside_teaching_window', review_activity_id: 'activity',
    run_id: null, run_status: null,
  }, {
    id: 'disabled-intent', trigger_kind: 'review_due', state: 'pending',
    wait_reason: 'proactive_disabled', review_activity_id: 'other-activity',
    run_id: null, run_status: null,
  }];
  render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  fireEvent.click(screen.getByText('后续教学队列（最近20条）'));
  expect(screen.getByText('等待原因：等待允许的教学时段')).toBeTruthy();
  expect(screen.getByText('等待原因：本会话主动提示已关闭')).toBeTruthy();
  expect(screen.getByText('原复习活动：activity')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '取消复习提示 due-intent' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/conversations/conversation/teaching-intents/due-intent/cancel');
  expect(options.lookup).toBe(`${path}/${body.client_action_id}`);
});

test('choosing a teaching mode is explicit, CAS-bound and uses the original read-only receipt', async () => {
  render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  expect(native.openTeaching).toHaveBeenCalledWith('conversation');
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '开启自由阅读' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v2/conversations/conversation/teaching-session/actions');
  expect(body).toEqual({
    action: 'open', mode: 'free_reading', focus, expected_session_revision: 0,
    client_action_id: expect.any(String),
  });
  expect(options).toEqual({ key: body.client_action_id, lookup: `${path}/${body.client_action_id}` });
  expect(native.write.mock.calls.every(([target]) => !target.endsWith('/turns'))).toBe(true);
});

test('pause and resume remain explicit controls and never submit a Tutor turn', async () => {
  opened();
  const view = render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  fireEvent.click(screen.getByRole('button', { name: '暂停引导' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({ action: 'pause', expected_session_revision: 4 });
  native.state.teaching.session = { ...session, revision: 5, paused: true };
  view.rerender(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  await waitFor(() => expect(screen.getByRole('button', { name: '恢复引导' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: '恢复引导' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(2));
  expect(native.write.mock.calls[1][1]).toMatchObject({ action: 'resume', expected_session_revision: 5 });
  expect(native.request).not.toHaveBeenCalled();
});

test('result continuation is off by default and its explicit model-use switch keeps session CAS', async () => {
  const view = render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  expect(screen.getByRole('switch', { name: '结果后续教学' }).getAttribute('aria-checked')).toBe('false');
  expect(screen.getByRole('switch', { name: '结果后续教学' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText(/会使用你配置的模型/)).toBeTruthy();
  expect(native.write).not.toHaveBeenCalled();
  opened();
  view.rerender(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  fireEvent.click(screen.getByRole('switch', { name: '结果后续教学' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(body).toMatchObject({
    action: 'set_continuation_policy', policy: 'after_result.v1', expected_session_revision: 4,
    client_action_id: expect.any(String),
  });
  expect(options).toEqual({ key: body.client_action_id, lookup: `${path}/${body.client_action_id}` });
  native.state.teaching.session = { ...session, revision: 5, continuation_policy: 'after_result.v1' };
  view.rerender(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  await waitFor(() => expect(screen.getByRole('switch', { name: '结果后续教学' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('switch', { name: '结果后续教学' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(2));
  expect(native.write.mock.calls[1][1]).toMatchObject({
    action: 'set_continuation_policy', policy: 'manual', expected_session_revision: 5,
  });
  expect(native.write.mock.calls.every(([target]) => !target.endsWith('/turns'))).toBe(true);
});

test('free reading does not enable automatic continuation but still permits explicitly turning it off', async () => {
  opened();
  native.state.teaching.session.mode = 'free_reading';
  const view = render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  expect(screen.getByText(/自由阅读不会自动续讲/)).toBeTruthy();
  expect(screen.getByRole('switch', { name: '结果后续教学' }).hasAttribute('disabled')).toBe(true);
  native.state.teaching.session.continuation_policy = 'after_result.v1';
  view.rerender(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  expect(screen.getByRole('switch', { name: '结果后续教学' }).getAttribute('aria-checked')).toBe('true');
  fireEvent.click(screen.getByRole('switch', { name: '结果后续教学' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({ action: 'set_continuation_policy', policy: 'manual' });
});

test('recent intents retain wait and original unknown Run facts and cancel through an exact receipt', async () => {
  opened();
  native.state.teaching.intents = [{
    id: 'intent', trigger_kind: 'expected_result', state: 'dispatched', wait_reason: 'paused',
    run_id: 'original-run', run_status: 'blocked_unknown',
  }];
  render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  fireEvent.click(screen.getByRole('button', { name: '后续教学队列（最近20条）' }));
  expect(screen.getByText('等待原因：引导已暂停')).toBeTruthy();
  expect(screen.getByText(/原任务：original-run · 结果未知，不会自动重发/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '取消后续教学 intent' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/conversations/conversation/teaching-intents/intent/cancel');
  expect(body).toEqual({ client_action_id: expect.any(String) });
  expect(options).toEqual({ key: body.client_action_id, lookup: `${path}/${body.client_action_id}` });
  expect(native.request).not.toHaveBeenCalled();
});

test('an unresolved cancellation never offers another cancellation and preserves original Run status', () => {
  opened();
  native.state.teaching.intents = [{
    id: 'intent', trigger_kind: 'artifact_action', state: 'cancelled',
    wait_reason: 'external_result_unknown', run_id: 'original-run', run_status: 'blocked_unknown',
  }];
  native.state.pending = [{
    path: '/v1/conversations/conversation/teaching-intents/intent/cancel', key: 'original', status: 'unknown',
  }];
  render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  fireEvent.click(screen.getByRole('button', { name: '后续教学队列（最近20条）' }));
  expect(screen.queryByRole('button', { name: '取消后续教学 intent' })).toBeNull();
  expect(screen.getByText(/原取消尚待只读核对/)).toBeTruthy();
  expect(screen.getByText(/原任务：original-run · 结果未知，不会自动重发/)).toBeTruthy();
  expect(native.write).not.toHaveBeenCalled();
});

test.each(['queued', 'running', 'blocked_unknown'])('an explicit question may interrupt a known %s automatic Run without a client cancellation', async (status) => {
  opened();
  native.state.snapshot.runs = [{
    id: 'automatic-run', turn_id: 'automatic-turn', conversation_id: 'conversation', status,
  }];
  native.state.snapshot.turns = [{
    conversation_id: 'conversation', turns: [{ id: 'automatic-turn', teaching_intent_id: 'intent' }],
  }];
  render(<NativeComposer conversationId="conversation" />);
  const input = screen.getByRole('textbox', { name: '发送给 Tutor' });
  expect(input.hasAttribute('disabled')).toBe(false);
  fireEvent.change(input, { target: { value: 'I have an explicit question.' } });
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][0]).toBe('/v1/conversations/conversation/turns');
  expect(native.write.mock.calls[0][1]).toMatchObject({
    text: 'I have an explicit question.', teaching_session_revision: 4,
  });
  expect(screen.getByText(/服务端会优先取消本次自动任务/)).toBeTruthy();
});

test('a scoped intent can identify the automatic Run while an ordinary Run still blocks the composer', async () => {
  opened();
  native.state.snapshot.runs = [{
    id: 'automatic-run', turn_id: 'outside-snapshot-window', conversation_id: 'conversation', status: 'running',
  }];
  native.state.teaching.intents = [{ id: 'intent', run_id: 'automatic-run', state: 'dispatched' }];
  const view = render(<NativeComposer conversationId="conversation" />);
  fireEvent.change(screen.getByRole('textbox', { name: '发送给 Tutor' }), { target: { value: 'Keep my question.' } });
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(false));
  native.state.snapshot.runs = [{
    id: 'ordinary-run', turn_id: 'ordinary-turn', conversation_id: 'conversation', status: 'running',
  }];
  view.rerender(<NativeComposer conversationId="conversation" />);
  expect(screen.getByRole('textbox', { name: '发送给 Tutor' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  expect(native.write).not.toHaveBeenCalled();
  expect((screen.getByRole('textbox', { name: '发送给 Tutor' }) as HTMLTextAreaElement).value).toBe('Keep my question.');
});

test('explicit menu controls can preempt an automatic Run through the original session action', async () => {
  opened();
  native.state.teaching.session.continuation_policy = 'after_result.v1';
  native.state.snapshot.runs = [{
    id: 'automatic-run', turn_id: 'automatic-turn', conversation_id: 'conversation', status: 'blocked_unknown',
  }];
  native.state.snapshot.turns = [{
    conversation_id: 'conversation', turns: [{ id: 'automatic-turn', teaching_intent_id: 'intent' }],
  }];
  render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  expect(screen.getByRole('button', { name: '暂停引导' }).hasAttribute('disabled')).toBe(false);
  expect(screen.getByRole('button', { name: '切换为自由阅读' }).hasAttribute('disabled')).toBe(false);
  expect(screen.getByRole('switch', { name: '结果后续教学' }).hasAttribute('disabled')).toBe(false);
  fireEvent.click(screen.getByRole('switch', { name: '结果后续教学' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][0]).toBe('/v2/conversations/conversation/teaching-session/actions');
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'set_continuation_policy', policy: 'manual', expected_session_revision: 4,
  });
  expect(native.write.mock.calls[0][0]).not.toContain('/cancel');
});

test('an explicit topic can preempt only a known automatic foreground Run', async () => {
  opened();
  native.state.snapshot.runs = [{
    id: 'automatic-run', turn_id: 'automatic-turn', conversation_id: 'conversation', status: 'running',
  }];
  native.state.teaching.intents = [{ id: 'intent', run_id: 'automatic-run', state: 'dispatched' }];
  const view = render(<NativeLearningScope />);
  expect(screen.getByRole('combobox', { name: '当前范围' }).hasAttribute('disabled')).toBe(false);
  fireEvent.change(screen.getByRole('combobox', { name: '当前范围' }), { target: { value: '' } });
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'set_topic', focus: { kind: 'goal' }, expected_session_revision: 4,
  });
  native.state.snapshot.runs = [{
    id: 'ordinary-run', turn_id: 'ordinary-turn', conversation_id: 'conversation', status: 'running',
  }];
  view.rerender(<NativeLearningScope />);
  await waitFor(() => expect(screen.getByRole('combobox', { name: '当前范围' }).hasAttribute('disabled')).toBe(true));
});

test('a paused explicit question uses current server focus/revision rather than stale local focus', async () => {
  opened();
  native.state.teaching.session.paused = true;
  sessionStorage.setItem('leornian.native.focus:owner:conversation', JSON.stringify({ kind: 'goal' }));
  render(<NativeComposer conversationId="conversation" />);
  fireEvent.change(screen.getByRole('textbox', { name: '发送给 Tutor' }), { target: { value: 'Explain this loop.' } });
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    text: 'Explain this loop.', focus, teaching_session_revision: 4,
  });
  expect(native.write.mock.calls[0][1]).not.toHaveProperty('branch_id');
  expect(native.write.mock.calls[0][1]).not.toHaveProperty('anchor_artifact_id');
});

test('legacy questions remain unbound until the learner explicitly opens a session', async () => {
  render(<NativeComposer conversationId="conversation" />);
  fireEvent.change(screen.getByRole('textbox', { name: '发送给 Tutor' }), { target: { value: 'A legacy question.' } });
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).not.toHaveProperty('teaching_session_revision');
  expect(native.write.mock.calls[0][0]).toBe('/v1/conversations/conversation/turns');
});

test.each(['loading', 'error', 'other_actor', 'pending'])('unresolved %s teaching state preserves the draft and does not send', async (kind) => {
  opened();
  if (kind === 'loading') native.state.teaching.loading = true;
  if (kind === 'error') native.state.teaching.error = 'Current state is unavailable';
  if (kind === 'other_actor') native.state.teaching.actorId = 'someone-else';
  if (kind === 'pending') native.state.pending = [{
    path: '/v2/conversations/conversation/teaching-session/actions', key: 'original', status: 'unknown',
  }];
  sessionStorage.setItem('leornian.native.composer:owner:conversation', 'Keep this draft.');
  render(<><NativeComposer conversationId="conversation" /><NativeTeachingControls conversationId="conversation" focus={focus} /></>);
  const input = screen.getByRole('textbox', { name: '发送给 Tutor' }) as HTMLTextAreaElement;
  await waitFor(() => expect(input.value).toBe('Keep this draft.'));
  expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: kind === 'other_actor' ? '开启引导学习' : '暂停引导' }).hasAttribute('disabled')).toBe(true);
  expect(native.write).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('leornian.native.composer:owner:conversation')).toBe('Keep this draft.');
});

test('active foreground work blocks mode/return controls instead of cancelling implicitly', () => {
  opened();
  native.state.snapshot.runs = [{ id: 'run', conversation_id: 'conversation', status: 'blocked_unknown' }];
  native.state.teaching.session.active_branch_id = 'branch';
  render(<NativeTeachingControls conversationId="conversation" focus={focus} />);
  expect(screen.getByRole('button', { name: '返回主线' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: '切换为自由阅读' }).hasAttribute('disabled')).toBe(true);
  expect(native.write).not.toHaveBeenCalled();
});

test('an explicit topic selection uses the current session CAS without replacing history', async () => {
  opened();
  render(<NativeLearningScope />);
  fireEvent.change(screen.getByRole('combobox', { name: '当前范围' }), { target: { value: '' } });
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'set_topic', focus: { kind: 'goal' }, expected_session_revision: 4,
  });
  expect(native.write.mock.calls[0][0]).not.toContain('/turns');
});

test('branch grouping delegates unchanged role rows, collapses on return, and only reads when reopened', async () => {
  opened();
  native.state.teaching.session.active_branch_id = 'branch';
  native.state.teaching.branches = [{
    id: 'branch', conversation_id: 'conversation', anchor_artifact_id: 'artifact',
    state: 'active', turn_count: 2,
  }];
  const rows = [
    { message: { messageId: 'anchor:assistant', conversationId: 'conversation', isCreatedByUser: false } },
    ...['first', 'second'].flatMap((id) => [true, false].map((isCreatedByUser) => ({
      message: { messageId: `${id}:${isCreatedByUser ? 'user' : 'assistant'}`, conversationId: 'conversation',
        isCreatedByUser, leornianBranchId: 'branch' },
    }))),
    { message: { messageId: 'next:user', conversationId: 'conversation', isCreatedByUser: true } },
  ].map((row) => ({ ...row, message: { ...row.message, leornianFocus: focus } }));
  const renderRows = vi.fn((items: typeof rows) => items.map((row) =>
    <div key={row.message.messageId} data-original-role={row.message.isCreatedByUser ? 'user' : 'tutor'}>
      {row.message.messageId}
    </div>));
  const view = render(<NativeTeachingRows rows={rows} renderRows={renderRows} />);
  const group = screen.getByRole('region', { name: '答疑 · 2 轮' });
  expect(group.getAttribute('data-anchor-artifact-id')).toBe('artifact');
  expect(screen.getByRole('button', { name: '答疑 · 2 轮' }).getAttribute('aria-expanded')).toBe('true');
  expect(group.querySelectorAll('[data-original-role="user"]').length).toBe(2);
  expect(group.querySelectorAll('[data-original-role="tutor"]').length).toBe(2);
  expect(renderRows.mock.calls[1][0]).toEqual(rows.slice(1, 5));
  fireEvent.click(screen.getByRole('button', { name: '返回主线' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'return_to_main', branch_id: 'branch', expected_session_revision: 4,
  });
  native.state.teaching = { ...native.state.teaching,
    session: { ...session, revision: 5, active_branch_id: null },
    branches: [{ ...native.state.teaching.branches[0], state: 'closed' }],
  };
  view.rerender(<NativeTeachingRows rows={rows} renderRows={renderRows} />);
  await waitFor(() => expect(screen.getByRole('button', { name: '答疑 · 2 轮' }).getAttribute('aria-expanded')).toBe('false'));
  expect(group.querySelector('[aria-hidden="true"][inert]')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '答疑 · 2 轮' }));
  expect(screen.getByRole('button', { name: '答疑 · 2 轮' }).getAttribute('aria-expanded')).toBe('true');
  expect(native.write).toHaveBeenCalledTimes(1);
});
