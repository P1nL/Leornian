import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { BaselineComposer, BaselineConversationContent, BaselineMaterials, BaselineSourcePanel, BaselineStart } from './BaselineLearning';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), write: vi.fn(), refresh: vi.fn(), navigate: vi.fn(),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state, write: native.write,
    refresh: native.refresh, openTeaching: vi.fn(),
  },
}));
vi.mock('react-router-dom', () => ({
  useParams: () => ({ conversationId: 'conversation' }), useNavigate: () => native.navigate,
  useLocation: () => ({ state: null }),
}));
beforeEach(() => {
  sessionStorage.clear();
  native.state = { snapshot: { actor: { id: 'actor' }, goals: [], conversations: [], plans: [],
    turns: [], runs: [], sources: [] }, pending: [], epoch: 1,
  teaching: { actorId: 'actor', conversationId: 'conversation', session: null, branches: [],
    loading: false, error: '' } };
  native.request.mockReset().mockImplementation(async (path: string, options?: RequestInit) => {
    if (path === '/v1/tutor/availability') return { ready: true };
    if (path.endsWith('/material-progress')) return { status: 'idle', steps: [], documents: [] };
    if (path === '/v1/jobs/job') return { status: 'succeeded', result_ref: 'goal' };
    if (path === '/v1/conversations') return { id: 'conversation', goal_id: 'goal' };
    if (path === '/v1/runs/plan-run') return { status: 'succeeded' };
    if (path === '/v2/conversations/conversation/teaching-session') return null;
    if (path === '/v1/goals/goal' && options?.method === 'PATCH') return { id: 'goal' };
    if (path.endsWith('/content')) return { id: 'upload', state: 'stored' };
    throw new Error(`Unexpected request ${path}`);
  });
  native.write.mockReset().mockImplementation(async (path: string, body: any) => {
    if (path === '/v1/goals') return { job_id: 'job' };
    if (path === '/v1/material-demands') return { id: 'demand', revision: 1 };
    if (path.endsWith('/uploads')) return { id: 'upload', state: 'pending' };
    if (path.endsWith('/files')) return { id: 'material-job', state: 'queued' };
    if (path.endsWith('/plan-requests')) return { run_id: 'plan-run', turn_id: 'plan-turn' };
    if (path.endsWith('/actions')) return { revision: 1, focus: body.focus };
    return { turn_id: 'turn' };
  });
  native.refresh.mockReset().mockResolvedValue(undefined);
  native.navigate.mockReset();
});
afterEach(cleanup);

test('the welcome area shows only Leornian without guidance, gallery or saved goal buttons', () => {
  native.state.snapshot.goals = [{ id: 'goal', title: 'Python' }];
  const view = render(<BaselineStart />);
  expect(screen.getByRole('heading', { name: 'Leornian' })).toBeTruthy();
  expect(view.container.querySelector('.baseline-welcome')?.textContent).toBe('Leornian');
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
  expect(native.request).not.toHaveBeenCalled();
  expect(native.write).not.toHaveBeenCalled();
});

test('floating composer clearance follows textarea height and is removed with the conversation', () => {
  let height = 140;
  let measure = () => {};
  const disconnect = vi.fn();
  const size = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(() => height);
  const observer = vi.spyOn(globalThis, 'ResizeObserver').mockImplementation(function (callback) {
    measure = () => callback([], {} as ResizeObserver);
    return { observe: vi.fn(), unobserve: vi.fn(), disconnect };
  });
  const view = render(<div data-chat-pane="0">
    <BaselineConversationContent conversationId="conversation"><p>Conversation</p></BaselineConversationContent>
    <div><div className="demo-composer" /></div>
  </div>);
  const pane = view.container.querySelector<HTMLElement>('[data-chat-pane]')!;
  expect(pane.style.getPropertyValue('--baseline-composer-height')).toBe('140px');
  height = 220;
  measure();
  expect(pane.style.getPropertyValue('--baseline-composer-height')).toBe('220px');
  view.unmount();
  expect(disconnect).toHaveBeenCalledOnce();
  expect(pane.style.getPropertyValue('--baseline-composer-height')).toBe('');
  size.mockRestore();
  observer.mockRestore();
});

test('landing starts a planning discussion without confirming a route or starting teaching', async () => {
  const view = render(<BaselineComposer conversationId="new" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  expect(view.container.querySelector('[data-testid="composer-surface"] .demo-composer-actions')).toBeTruthy();
  fireEvent.change(screen.getByRole('textbox', { name: '学习目标或问题' }), { target: { value: '我想学习 Python 循环' } });
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await waitFor(() => expect(native.navigate).toHaveBeenCalled());
  expect(native.write.mock.calls[0][0]).toBe('/v1/goals');
  expect(native.write.mock.calls[1][0]).toBe('/v1/conversations/conversation/plan-requests');
  expect(native.write).toHaveBeenCalledTimes(2);
  expect(native.write.mock.calls[1][1]).toMatchObject({ discussion: true, expected_revision: 0, focus: { kind: 'goal' } });
  expect(native.navigate).toHaveBeenCalledWith('/c/conversation?stage=planning',
    { state: { composerOrigin: expect.objectContaining({ left: expect.any(Number), top: expect.any(Number) }) } });
  expect(screen.queryByText('本机学习 · 原生 Tutor')).toBeNull();
  expect(sessionStorage.getItem('leornian.native.composer:actor:conversation')).toBeNull();
});

test('normal conversation drafts restore without writes and unknown submissions stay disabled', async () => {
  sessionStorage.setItem('leornian.native.composer:actor:conversation', '保留的真实问题');
  const view = render(<BaselineComposer conversationId="conversation" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('保留的真实问题');
  expect(native.write).not.toHaveBeenCalled();
  native.state = { ...native.state, pending: [{ path: '/v1/conversations/conversation/turns', status: 'unknown' }] };
  view.rerender(<BaselineComposer conversationId="conversation" />);
  expect((screen.getByRole('button', { name: '发送给 Tutor' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(native.write).not.toHaveBeenCalled();
});

test('guided nodes restore only their own draft and do not count a timer request as a learner submission', async () => {
  const focus = { kind: 'node', plan_id: 'plan', expected_plan_revision: 1, node_key: 'one' };
  const teaching = { conversation_id: 'conversation', revision: 1, mode: 'guided', focus,
    node_window: { next_step: 'wait_for_action', after_turn_id: 'delivered' } };
  native.state.snapshot.conversations = [{ id: 'conversation', goal_id: 'goal' }];
  native.state.snapshot.plans = [{ id: 'plan', goal_id: 'goal', active: { revision: 1, document: { nodes: [] } } }];
  native.state.snapshot.teaching_sessions = [teaching]; native.state.teaching.session = teaching;
  const view = render(<BaselineComposer conversationId="conversation" />);
  const editor = screen.getByRole('textbox') as HTMLTextAreaElement;
  fireEvent.change(editor, { target: { value: '这个例子呢？' } });
  native.state.snapshot.teaching_sessions = [{ ...teaching, revision: 2, focus: { ...focus, node_key: 'two' } }];
  view.rerender(<BaselineComposer conversationId="conversation" />);
  await waitFor(() => expect(editor.value).toBe(''));
  native.state.snapshot.teaching_sessions = [teaching];
  native.state.pending = [{ path: '/v2/conversations/conversation/teaching-session/continue', status: 'dispatching' }];
  view.rerender(<BaselineComposer conversationId="conversation" />);
  await waitFor(() => expect(editor.value).toBe('这个例子呢？'));
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledOnce());
  expect(native.write.mock.calls[0][1]).toMatchObject({ node_pacing: true, text: '这个例子呢？', focus });
});

test('a rejected message action restores the edited text and native error in the existing composer', async () => {
  native.state.composerNotice = {
    conversationId: 'conversation', text: 'JS吧', error: '当前模型配置不可用',
  };
  render(<BaselineComposer conversationId="conversation" />);
  await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('JS吧'));
  expect(screen.getByText('当前模型配置不可用')).toBeTruthy();
  expect(sessionStorage.getItem('leornian.native.composer:actor:conversation')).toBe('JS吧');
  expect(native.write).not.toHaveBeenCalled();
});

test('new goals may be saved without a model while the question remains an unsent conversation draft', async () => {
  native.request.mockImplementation(async (path: string) => path === '/v1/tutor/availability'
    ? { ready: false } : path === '/v1/jobs/job' ? { status: 'succeeded', result_ref: 'goal' }
      : { id: 'conversation', goal_id: 'goal' });
  render(<BaselineComposer conversationId="new" />);
  await screen.findByText('先保存目标，再配置自己的模型');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '我想学习 SQL 查询' } });
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await waitFor(() => expect(native.navigate).toHaveBeenCalledWith('/c/conversation', expect.objectContaining({ state: expect.any(Object) })));
  expect(native.write).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem('leornian.native.composer:actor:conversation')).toBe('我想学习 SQL 查询');
  expect(sessionStorage.getItem('leornian.native.intake.v1:actor')).toBeNull();
  expect(sessionStorage.getItem('leornian.native.composer:actor:new')).toBeNull();
});

test('continuing a legacy saved goal retires only its matching intake after planning is accepted', async () => {
  native.state.snapshot.conversations = [{ id: 'conversation', goal_id: 'goal' }];
  sessionStorage.setItem('leornian.native.intake.v1:actor', JSON.stringify({
    actor_id: 'actor', text: '我想学习 SQL 查询', conversation_id: 'conversation',
  }));
  render(<BaselineComposer conversationId="conversation" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '每天十五分钟，先学查询。' } });
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await waitFor(() => expect(sessionStorage.getItem('leornian.native.intake.v1:actor')).toBeNull());
  expect(native.write).toHaveBeenCalledTimes(1);
  expect(native.write.mock.calls[0][0]).toBe('/v1/conversations/conversation/plan-requests');
});

test('the baseline source reader uses the small-screen sheet while preserving the exact source', () => {
  native.state = { ...native.state, reader: {
    path: '/v2/conversations/conversation/learning-artifacts/artifact/sources/exact',
    content: { title: 'Pinned source', excerpt: 'Exact original excerpt' },
  } };
  const view = render(<BaselineSourcePanel panel={null} NativeGroup={({ children }) => <div>{children}</div>}>
    <p>Conversation</p>
  </BaselineSourcePanel>);
  expect(view.container.firstElementChild?.getAttribute('data-reader-docked')).toBe('false');
  expect(screen.getByText('Exact original excerpt')).toBeTruthy();
  expect(screen.queryByRole('complementary')).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
});

test('an unknown plan request keeps the original creation draft and does not navigate or resend', async () => {
  native.write.mockImplementation(async (path: string) => path === '/v1/goals'
    ? { job_id: 'job' } : Promise.reject(new Error('Original request awaits its receipt')));
  render(<BaselineComposer conversationId="new" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '我想学习 Python 字典' } });
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await screen.findByText('Original request awaits its receipt');
  expect(native.navigate).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('leornian.native.composer:actor:conversation')).toBe('我想学习 Python 字典');
  expect(sessionStorage.getItem('leornian.native.composer:actor:new')).toBe('我想学习 Python 字典');
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await waitFor(() => expect(native.request).toHaveBeenCalledWith(expect.stringContaining('/turn-requests/')));
  expect(native.write).toHaveBeenCalledTimes(2);
});

test('the baseline materials position exposes normal upload for the exact current goal', async () => {
  native.state.snapshot.conversations = [{ id: 'conversation', goal_id: 'goal' }];
  native.state.snapshot.goals = [{ id: 'goal', title: '当前学习目标' }];
  native.request.mockResolvedValue([]);
  render(<BaselineMaterials />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/material-demands?goal_id=goal&limit=100'));
  expect(screen.getByRole('region', { name: '上传与准备教材' })).toBeTruthy();
  expect(screen.getByLabelText('原文件')).toBeTruthy();
  expect(screen.getByRole('button', { name: '上传并准备原文' }).hasAttribute('disabled')).toBe(true);
  expect(native.write).not.toHaveBeenCalled();
});

test('new plans enable public learning materials automatically without the old opt-in controls', async () => {
  render(<BaselineComposer conversationId="new" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  fireEvent.change(screen.getByRole('textbox', { name: '学习目标或问题' }), { target: { value: '学习分组统计' } });
  expect(screen.queryByText('科目与官方材料（可选）')).toBeNull();
  expect(screen.queryByRole('checkbox')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '发送给 Tutor' }));
  await waitFor(() => expect(native.navigate).toHaveBeenCalled());
  expect(native.write.mock.calls[0][1].material_scope).toEqual({
    contract: 'goal-material-scope.v1', language: null, language_version: null,
    framework: null, framework_version: null, authorized_official_sources: true,
    authorized_public_sources: true,
  });
});

test('the attachment button opens the picker and uploads before planning; Enter reuses the same draft goal', async () => {
  render(<BaselineComposer conversationId="new" />);
  const picker = screen.getByLabelText('选择学习资料') as HTMLInputElement;
  const open = vi.spyOn(picker, 'click');
  fireEvent.click(screen.getByRole('button', { name: '添加学习材料' }));
  expect(open).toHaveBeenCalledOnce();
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.change(picker, { target: { files: [new File(['chapter one'], 'Python教材.md')] } });
  await screen.findByText('已上传');
  expect(screen.getByText('Python教材.md')).toBeTruthy();
  expect(native.navigate).not.toHaveBeenCalled();
  expect(native.write.mock.calls.some(([path]) => path.includes('plan-requests'))).toBe(false);
  const upload = native.write.mock.calls.find(([path]) => path.endsWith('/uploads'));
  expect(upload?.[1].material).toMatchObject({
    goal_id: 'goal', authorized_use: true, purposes: expect.arrayContaining(['planning', 'teaching', 'indexing']),
  });
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '使用教材学习 Python 循环，每天半小时' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  await waitFor(() => expect(native.navigate).toHaveBeenCalled());
  expect(native.write.mock.calls.filter(([path]) => path === '/v1/goals')).toHaveLength(1);
  expect(native.request).toHaveBeenCalledWith('/v1/goals/goal', {
    method: 'PATCH', body: JSON.stringify({
      title: '使用教材学习 Python 循环，每天半小时', motivation: '使用教材学习 Python 循环，每天半小时',
    }),
  });
  expect(native.write.mock.calls.at(-1)?.[0]).toBe('/v1/conversations/conversation/plan-requests');
});
