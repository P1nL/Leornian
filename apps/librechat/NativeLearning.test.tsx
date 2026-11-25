import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { NativeArtifacts, NativeComposer, NativeConversationContent, NativeLearningScope, NativeSourcePanel, NativeSync, NativeTasks, NativeThreadTail, useNativePaneView } from './NativeLearning';
import { isNativeEmptyConversation } from './native-client.mjs';
import { practiceReceipts, submittedReviewReceipts } from './native-practice';

const native = vi.hoisted(() => ({
  state: { snapshot: { actor: { id: 'owner' }, turns: [] as { conversation_id: string; turns: unknown[] }[] }, epoch: 0, pending: [] as { path: string }[], reader: null as Record<string, unknown> | null,
    teaching: { actorId: 'owner', conversationId: 'conversation', session: null, branches: [], loading: false, error: '' } },
  request: vi.fn(),
  write: vi.fn(),
  refresh: vi.fn(),
  openTeaching: vi.fn(),
  start: vi.fn(() => () => {}),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {},
    getSnapshot: () => native.state,
    write: native.write,
    refresh: native.refresh,
    openTeaching: native.openTeaching,
    start: native.start,
  },
}));
vi.mock('react-router-dom', () => ({
  useParams: () => ({ conversationId: 'conversation' }),
  useNavigate: () => vi.fn(),
  useLocation: () => ({ search: '' }),
}));

const path = '/v2/conversations/conversation/learning-artifacts/artifact';
const summary = {
  id: 'artifact', conversation_id: 'conversation', source_turn_id: 'turn',
  kind: 'learning_composition', revision: 7, state: 'ready',
};
beforeEach(() => {
  sessionStorage.clear();
  native.state = { snapshot: { actor: { id: 'owner' }, turns: [] }, epoch: 0, pending: [], reader: null,
    teaching: { actorId: 'owner', conversationId: 'conversation', session: null, branches: [], loading: false, error: '' } };
  native.request.mockReset().mockImplementation(async (url: string) => {
    if (url.split('?')[0] === path) throw new Error('The exact source permission was revoked.');
    return [summary];
  });
  native.write.mockReset().mockResolvedValue({ state: 'cancelled' });
  native.refresh.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

test('active native session renews while visible and stops with the authenticated shell', async () => {
  vi.useFakeTimers();
  let visible = 'visible';
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visible as DocumentVisibilityState);
  const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
  vi.stubGlobal('fetch', fetcher);
  const client = new QueryClient();
  const view = render(<QueryClientProvider client={client}><NativeSync /></QueryClientProvider>);
  try {
    await vi.advanceTimersByTimeAsync(15 * 60 * 1000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith('/api/auth/refresh', expect.objectContaining({
      method: 'POST', credentials: 'same-origin',
    }));
    visible = 'hidden';
    await vi.advanceTimersByTimeAsync(30 * 60 * 1000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    visible = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
    view.unmount();
    await vi.advanceTimersByTimeAsync(30 * 60 * 1000);
    window.dispatchEvent(new Event('focus'));
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  } finally {
    view.unmount();
    client.clear();
    visibility.mockRestore();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});

test('session renewal does not overlap or create business requests after a transport failure', async () => {
  vi.useFakeTimers();
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  let reject!: (reason: Error) => void;
  const fetcher = vi.fn()
    .mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }))
    .mockResolvedValue(new Response('{}'));
  vi.stubGlobal('fetch', fetcher);
  const client = new QueryClient();
  const view = render(<QueryClientProvider client={client}><NativeSync /></QueryClientProvider>);
  try {
    await vi.advanceTimersByTimeAsync(15 * 60 * 1000);
    window.dispatchEvent(new Event('focus'));
    document.dispatchEvent(new Event('visibilitychange'));
    expect(fetcher).toHaveBeenCalledTimes(1);
    reject(new TypeError('Connection interrupted'));
    await vi.advanceTimersByTimeAsync(15 * 60 * 1000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.every(([path]) => path === '/api/auth/refresh')).toBe(true);
    expect(native.write).not.toHaveBeenCalled();
  } finally {
    view.unmount();
    client.clear();
    visibility.mockRestore();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});

function ownedView(kind = 'code_workspace', result: Record<string, unknown> | null = null) {
  const choice = kind === 'knowledge_check';
  return {
    ...summary, schema_version: 'learning_artifact.v2', title: 'Owned composition',
    state: result ? result.status === 'queued' ? 'running' : 'completed' : 'ready',
    practice_only: !!result && (choice || result.status === 'passed'),
    allowed_actions: ['cancel'],
    content_ref: { owner: 'tutor', id: 'presentation', revision: 1, public_identity: 'digest' },
    presentation: { type: 'learning_composition', definition: {
      schema_version: 'learning_composition.v2', title: 'Bound practice',
      states: { response: choice ? { type: 'choice', value: [] } : { type: 'code', value: 'print(0)' } },
      components: [
        { id: 'response', component: choice ? 'ChoiceAnswer' : 'CodeEditor', props: {
          label: choice ? '选择回答' : '程序', state: 'response',
          ...(choice ? { options: [{ id: 'A', text: 'Published A' }, { id: 'B', text: 'Published B' }] } : {}),
        } },
        { id: 'submit', component: 'ArtifactAction', props: {
          label: choice ? '提交回答' : '运行评测', for_component: 'response',
          event: choice ? 'submit_answer' : 'check_code', primary: true,
        } },
        { id: 'feedback', component: choice ? 'AnswerFeedback' : 'ResultFeedback',
          props: { label: 'Original feedback', for_component: 'response' } },
      ],
    } },
    component_bindings: [{
      component_id: 'response', state: result ? result.status === 'queued' ? 'running' : 'completed' : 'ready',
      action_id: null, result,
      allowed_actions: choice ? result ? [] : ['respond'] : result?.status === 'queued'
        ? ['cancel_run'] : result?.status === 'error' ? ['run', 'retry'] : ['run'],
      source: {
        id: 'source-candidate', kind, title: 'Original published practice',
        content_ref: { owner: 'item_bank', id: 'pack', revision: 1, slot: 'practice_1', public_identity: 'source-digest' },
        presentation: choice ? { type: kind, question: { prompt: 'Actual published choice prompt' } }
          : { type: kind, task: { prompt: 'Actual published Python prompt', sample: { input: [1, 2], expected: 3 } } },
      },
      attempts: choice ? null : { items: result ? [result] : [], latest_attempt_id: result?.id ?? null, next_before: null },
    }],
  };
}

function showView(view: ReturnType<typeof ownedView>) {
  native.request.mockImplementation(async (url: string) => url.split('?')[0] === path ? view : [view]);
  return render(<NativeArtifacts messageId="turn:assistant" />);
}

test.each([false, true])('the same code workbench runs an unbound example without submitting an exercise (named template: %s)', async (named) => {
  const base = ownedView();
  const guide = '运行后输入分钟数，输入 q 退出。';
  const code = 'while (value := input()) != "q":\n    print(int(value))';
  const view = {
    ...base, component_bindings: [], example_runners: { final_editor: ['python'] },
    presentation: { type: 'learning_composition', definition: { schema_version: 'learning_composition.v2',
      title: '收尾工具', states: { code: { type: 'code', value: code } }, components: [
        { id: 'guide', component: 'Explanation', props: { text: guide } },
        { id: 'final_editor', component: 'CodeEditor', props: { label: 'time_tool.py', state: 'code' } },
      ] }, ...(named ? { example_workspace: { editor: 'final_editor', description: 'guide', language: 'python', stdin: '65\nq' } } : {}) },
  };
  native.request.mockImplementation(async (url: string) => url.split('?')[0] === path ? view : [summary]);
  native.write.mockResolvedValue({ status: 'reported', output: { outcome: 'completed', exit_code: 0, stdout: '95', stderr: '' } });
  render(<NativeArtifacts messageId="turn:assistant" />);
  const editor = await screen.findByRole('textbox', { name: 'time_tool.py' });
  const bench = within(editor.closest('.demo-workbench') as HTMLElement);
  expect(bench.getByText(guide)).toBeTruthy();
  expect(screen.getAllByText(guide)).toHaveLength(1);
  expect(bench.queryByRole('tab', { name: '测试用例' })).toBeNull();
  expect(bench.getByRole('region', { name: '终端' })).toBeTruthy();
  expect(bench.queryByRole('textbox', { name: '终端输入' })).toBeNull();
  expect(Boolean(bench.queryByText('可以尝试的输入'))).toBe(named);
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(bench.getByRole('button', { name: '运行' }));
  expect(await bench.findByText('95')).toBeTruthy();
  expect(native.write).toHaveBeenCalledTimes(1);
  expect(native.write.mock.calls[0][0]).toBe(`${path}/example-runs`);
  expect(native.write.mock.calls[0][1]).toMatchObject({ component_id: 'final_editor', language: 'python', code, interactive: true });
  expect(native.write.mock.calls[0][1]).not.toHaveProperty('stdin');
});

function attempt(status = 'passed') {
  return {
    id: 'latest-attempt', code: 'print(3)', status, attempt_number: 2,
    previous_attempt_id: 'old-attempt', retry_requested: false,
    policy_version: 'python-practice.v2', feedback: 'Actual assessment feedback', passed_cases: 3,
    total_cases: 3, created_at: '2026-11-05T01:00:00Z',
  };
}

function reviewView(profile = 'submitted-code-review.v2') {
  const view = ownedView() as any;
  view.presentation.definition = {
    schema_version: 'learning_composition.v2', title: '已提交代码审查',
    states: { code: { type: 'code', value: 'print(0)', read_only: true } },
    components: [
      { id: 'submitted', component: 'CodeBlock', props: { label: '固定代码', state: 'code' } },
      { id: 'notes', component: 'ReviewFinding', props: { label: '独立检查后的批注', for_component: 'submitted' } },
    ],
  };
  view.state = 'ready';
  view.component_bindings = [];
  view.review_bindings = [{
    profile_version: profile, component_id: 'submitted', evaluation_id: 'evaluation',
    attempt: { ...attempt('not_passed'), id: 'old-submitted-attempt', code: 'print(0)', attempt_number: 1, passed_cases: 1 },
    task: { title: '原公开题目', prompt: '按原题要求求和。' }, recorded_correct: false,
    findings: [{ line: 1, source_line: 'print(0)', content: '固定输出忽略了实际输入。' }],
  }];
  if (profile === 'submitted-code-review.v2') view.review_reports = [{
    component_id: 'submitted', state: 'ready', allowed_actions: ['complete_review'], completion: null,
  }];
  return view;
}

const reviewCompletion = {
  id: 'review-completion', artifact_id: 'artifact', component_id: 'submitted',
  presentation_id: 'presentation', content_identity: 'digest', attempt_id: 'old-submitted-attempt',
  evaluation_id: 'evaluation', evidence_kind: 'learner_review_report.v1',
  completed_at: '2026-11-06T09:10:11Z',
};

test('submitted review displays the actual old submission and original result with one read-only annotated code view', async () => {
  const view = reviewView('submitted-code-review.v1');
  const receipts = submittedReviewReceipts(view);
  expect(receipts).toMatchObject([{
    result_id: 'presentation', client_action_id: null, component_id: 'submitted', type: 'review',
  }]);
  const shown = showView(view);
  expect(await screen.findByText('固定输出忽略了实际输入。')).toBeTruthy();
  expect(screen.getByText('按原题要求求和。')).toBeTruthy();
  expect(screen.getByText(/原评测未通过/)).toBeTruthy();
  expect(screen.getByText(/old-submitted-attempt/)).toBeTruthy();
  expect(document.querySelectorAll('[data-learning-component="review-finding"]')).toHaveLength(1);
  expect(screen.getAllByText('print(0)')).toHaveLength(1);
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(native.request.mock.calls.some(([url]) => url.includes('code_review_capability=learning_code_review.v2'))).toBe(true);
  expect(screen.queryByRole('button', { name: '我已阅读本次评审' })).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
  shown.unmount();
  showView(view);
  expect(await screen.findByText('固定输出忽略了实际输入。')).toBeTruthy();
  expect(screen.getAllByText('print(0)')).toHaveLength(1);
  expect(native.write).not.toHaveBeenCalled();
});

test('v2 review confirms through the original action controller and reads back its saved time', async () => {
  let view = reviewView();
  native.request.mockImplementation(async (url: string) => url.split('?')[0] === path ? view : [view]);
  const shown = render(<NativeArtifacts messageId="turn:assistant" />);
  const button = await screen.findByRole('button', { name: '我已阅读本次评审' });
  expect(screen.getByText('固定输出忽略了实际输入。')).toBeTruthy();
  expect(screen.getByText(/原评测未通过/)).toBeTruthy();
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [target, body, options] = native.write.mock.calls[0];
  expect(target).toBe(`${path}/actions`);
  expect(body).toEqual({
    action: 'complete_review', component_id: 'submitted', expected_artifact_revision: 7,
    client_action_id: expect.any(String),
  });
  expect(options).toEqual({ key: body.client_action_id, lookup: `${path}/actions/${body.client_action_id}` });
  expect(screen.queryByText('已确认阅读本次评审')).toBeNull();
  view = { ...view, revision: 8, state: 'completed', review_reports: [{
    component_id: 'submitted', state: 'completed', allowed_actions: [], completion: reviewCompletion,
  }] };
  native.state = { ...native.state, epoch: 1 };
  shown.rerender(<NativeArtifacts messageId="turn:assistant" />);
  expect(await screen.findByText('已确认阅读本次评审')).toBeTruthy();
  expect(document.querySelector('time')?.getAttribute('datetime')).toBe(reviewCompletion.completed_at);
  expect(screen.queryByRole('button', { name: '我已阅读本次评审' })).toBeNull();
  expect(screen.getByText(/原评测未通过/)).toBeTruthy();
  expect(screen.getAllByText('print(0)')).toHaveLength(1);
  expect(screen.queryByRole('textbox')).toBeNull();
  native.state = { ...native.state, epoch: 2 };
  shown.rerender(<NativeArtifacts messageId="turn:assistant" />);
  await waitFor(() => expect(native.request.mock.calls.length).toBeGreaterThanOrEqual(6));
  expect(native.write).toHaveBeenCalledTimes(1);
});

test('unknown review confirmation remains blocked across a read-only refresh', async () => {
  const view = reviewView();
  native.write.mockImplementation(async (_path: string, body: object) => {
    native.state = { ...native.state, pending: [{ path: `${path}/actions`, body }] };
    throw new Error('阅读确认回执连接中断');
  });
  const shown = showView(view);
  fireEvent.click(await screen.findByRole('button', { name: '我已阅读本次评审' }));
  await screen.findByText('阅读确认回执连接中断');
  expect(screen.getByRole('button', { name: '我已阅读本次评审' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText(/阅读确认尚待核对/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '我已阅读本次评审' }));
  native.state = { ...native.state, epoch: 1 };
  shown.rerender(<NativeArtifacts messageId="turn:assistant" />);
  await waitFor(() => expect(native.request.mock.calls.length).toBeGreaterThanOrEqual(4));
  expect(screen.queryByText('已确认阅读本次评审')).toBeNull();
  expect(native.write).toHaveBeenCalledTimes(1);
});

test('an uncertain cancel keeps the saved reading confirmation distinct from the pending action', async () => {
  const view = { ...reviewView(), state: 'completed', review_reports: [{
    component_id: 'submitted', state: 'completed', allowed_actions: [], completion: reviewCompletion,
  }] };
  native.state = { ...native.state, pending: [{
    path: `${path}/actions`, body: { action: 'cancel' },
  }] };
  showView(view);
  expect(await screen.findByText('已确认阅读本次评审')).toBeTruthy();
  expect(document.querySelector('time')?.getAttribute('datetime')).toBe(reviewCompletion.completed_at);
  expect(screen.queryByText(/阅读确认尚待核对/)).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
});

test('review cards have no dismissal action and still read historic cancellations', async () => {
  let view = reviewView();
  native.request.mockImplementation(async (url: string) => url.split('?')[0] === path ? view : [view]);
  const shown = render(<NativeArtifacts messageId="turn:assistant" />);
  await screen.findByRole('button', { name: '我已阅读本次评审' });
  expect(screen.queryByRole('button', { name: '取消此交互' })).toBeNull();
  view = { ...view, revision: 8, state: 'cancelled', allowed_actions: [], review_reports: [{
    component_id: 'submitted', state: 'cancelled', allowed_actions: [], completion: null,
  }] };
  native.state = { ...native.state, epoch: 1 };
  shown.rerender(<NativeArtifacts messageId="turn:assistant" />);
  expect(await screen.findByText('本次评审已取消。')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '我已阅读本次评审' })).toBeNull();
  expect(screen.getByText('固定输出忽略了实际输入。')).toBeTruthy();
  expect(native.write).not.toHaveBeenCalled();
});

test('choosing an already-public exact-node Python receipt is local and only the next explicit Tutor request uses it', async () => {
  native.state.snapshot = {
    actor: { id: 'owner' }, turns: [], runs: [],
    conversations: [{ id: 'conversation', goal_id: 'goal' }],
    plans: [{ id: 'plan', goal_id: 'goal', active: {
      revision: 2, document: { nodes: [{ key: 'N1', title: 'First node' }, { key: 'N2', title: 'Second node' }] },
    } }],
    packs: [
      { id: 'public-pack', plan_id: 'plan', plan_revision: 2, node_key: 'N1' },
      { id: 'old-pack', plan_id: 'plan', plan_revision: 1, node_key: 'N1' },
      { id: 'other-node-pack', plan_id: 'plan', plan_revision: 2, node_key: 'N2' },
    ],
    evaluations: [
      { id: 'feedback', source_kind: 'python', source_id: 'exact-attempt', pack_id: 'public-pack', correct: false },
      { id: 'choice', source_kind: 'choice', source_id: 'choice-result', pack_id: 'public-pack', correct: true },
      { id: 'old', source_kind: 'python', source_id: 'old-version-attempt', pack_id: 'old-pack', correct: true },
      { id: 'other', source_kind: 'python', source_id: 'other-node-attempt', pack_id: 'other-node-pack', correct: true },
    ],
  } as any;
  native.request.mockResolvedValue({ ready: true });
  const shown = render(<><NativeLearningScope /><NativeComposer conversationId="conversation" /></>);
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/tutor/availability'));
  fireEvent.change(screen.getByRole('combobox', { name: '当前范围' }), { target: { value: 'N1' } });
  const choices = screen.getByRole('combobox', { name: /提交代码审查/ }) as HTMLSelectElement;
  expect([...choices.options].map((option) => option.value)).toEqual(['', 'exact-attempt']);
  fireEvent.change(choices, { target: { value: 'exact-attempt' } });
  expect(JSON.parse(sessionStorage.getItem('leornian.native.focus:owner:conversation')!)).toMatchObject({
    kind: 'attempt', assessment_receipt_id: 'exact-attempt', expected_plan_revision: 2, node_key: 'N1',
  });
  expect(native.write).not.toHaveBeenCalled();
  expect(native.request).toHaveBeenCalledTimes(1);
  const composer = screen.getByRole('textbox', { name: '发送给 Tutor' });
  fireEvent.change(composer, { target: { value: '请审查这份已提交的完整代码。' } });
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    focus: { kind: 'attempt', assessment_receipt_id: 'exact-attempt', node_key: 'N1' },
    presentation_capabilities: { actions: ['learning_practice.v2', 'learning_responses.v1', 'learning_code_review.v2', 'learning_programs.v2', 'learning_direct_answers.v1', 'learning_hints.v1', 'learning_demo_events.v1', 'learning_example_runs.v2', 'learning_templates.v1'] },
  });
  shown.unmount();
  render(<NativeLearningScope />);
  expect((screen.getByRole('combobox', { name: /提交代码审查/ }) as HTMLSelectElement).value).toBe('exact-attempt');
  fireEvent.change(screen.getByRole('combobox', { name: '当前范围' }), { target: { value: 'N2' } });
  expect(JSON.parse(sessionStorage.getItem('leornian.native.focus:owner:conversation')!)).toMatchObject({ kind: 'node', node_key: 'N2' });
  expect(JSON.parse(sessionStorage.getItem('leornian.native.focus:owner:conversation')!)).not.toHaveProperty('assessment_receipt_id');
});

function responseView(kind = 'short', result: Record<string, unknown> | null = null) {
  const view = ownedView('knowledge_check');
  const options = [{ id: 'A', text: 'Public A' }, { id: 'B', text: 'Public B' }];
  const component = kind === 'multiple' ? 'ChoiceAnswer' : kind === 'ordering' ? 'OrderingAnswer'
    : kind === 'line_review' ? 'LineRangeAnswer' : 'TextAnswer';
  const state = kind === 'multiple' ? { type: 'choice', value: [] }
    : kind === 'ordering' ? { type: 'order', value: ['A', 'B'] }
      : kind === 'line_review' ? { type: 'annotations', value: [] } : { type: 'text', value: '' };
  const definition = view.presentation.definition as any;
  definition.states = { response: state, snapshot: { type: 'code', value: 'print(0)\nprint(1)', read_only: true } };
  definition.components[0] = { id: 'response', component, props: {
    label: '你的回答', state: 'response',
    ...(kind === 'multiple' ? { options, multiple: true } : {}),
    ...(kind === 'ordering' ? { items: options } : {}),
    ...(kind === 'line_review' ? { code_state: 'snapshot' } : {}),
  } };
  definition.components[1].props.event = kind === 'line_review' ? 'submit_review' : 'submit_answer';
  definition.components[1].props.label = kind === 'line_review' ? '提交审查' : '提交回答';
  const binding = view.component_bindings[0] as any;
  binding.source.kind = 'knowledge_response';
  binding.source.presentation = { type: 'knowledge_response', question: {
    prompt: '实际发布的知识检查题面', response_type: kind, options, items: options,
    code: 'print(0)\nprint(1)',
  } };
  binding.result = result;
  binding.state = result ? 'completed' : 'ready';
  binding.allowed_actions = result ? [] : ['respond'];
  view.state = result ? 'completed' : 'ready';
  view.practice_only = !!result;
  return view;
}

test('short answers keep their original response and reference while free edits survive reopening', async () => {
  const view = responseView();
  const shown = showView(view);
  const input = await screen.findByRole('textbox', { name: '你的回答' });
  fireEvent.change(input, { target: { value: '我的实际解释' } });
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'answer_component', component_id: 'response',
    payload: { type: 'short', text: '我的实际解释' },
  });
  shown.unmount();
  const result = {
    id: 'response-result', response: { type: 'short', text: '原所有者锁定的回答' },
    correct: null, profile_version: 'knowledge-reference.v1', explanation: '只供参考',
    reference: { type: 'short', text: '真实参考解释' }, findings: [],
  };
  const completed = responseView('short', result);
  const reopened = showView(completed);
  const editor = await screen.findByRole('textbox', { name: '你的回答' }) as HTMLTextAreaElement;
  expect(editor.value).toBe('原所有者锁定的回答');
  expect(editor.readOnly).toBe(false);
  fireEvent.change(editor, { target: { value: '另一种解释' } });
  expect(screen.queryByRole('button', { name: '提交回答' })).toBeNull();
  fireEvent.click(screen.getByText('原作答与反馈'));
  expect(screen.queryByText(/回答正确/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '查看参考回答（未自动判分）' }));
  expect(await screen.findByText('真实参考解释')).toBeTruthy();
  reopened.unmount();
  showView(completed);
  expect((await screen.findByRole('textbox', { name: '你的回答' }) as HTMLTextAreaElement).value).toBe('另一种解释');
  expect(native.write).toHaveBeenCalledTimes(1);
});

test('multiple and ordering responses preserve public ids rather than reuse single-choice keys', async () => {
  const shown = showView(responseView('multiple'));
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Public A' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Public B' }));
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1].payload).toEqual({ type: 'multiple', selected_ids: ['A', 'B'] });
  shown.unmount(); native.write.mockClear(); sessionStorage.clear();
  showView(responseView('ordering'));
  fireEvent.click(await screen.findByRole('button', { name: 'Public B上移' }));
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1].payload).toEqual({ type: 'ordering', ordered_ids: ['B', 'A'] });
});

test('line review saves drafts without dispatch, submits only saved reasons and restores actual annotations', async () => {
  const shown = showView(responseView('line_review'));
  const submit = await screen.findByRole('button', { name: '提交审查' });
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '第 2 行：print(1)' }));
  fireEvent.change(screen.getByRole('textbox', { name: '第 2 行的理由' }), { target: { value: '我的理由' } });
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '保存第 2 行批注' }));
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(submit);
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1].payload).toEqual({
    type: 'line_review', annotations: [{ line: 2, reason: '我的理由' }],
  });
  shown.unmount();
  const view = responseView('line_review', {
    id: 'review-result', response: { type: 'line_review', annotations: [{ line: 2, reason: '原批注' }] },
    correct: true, explanation: '只检查定位', findings: [{ line: 2, content: '原所有者参考' }],
    reference: { type: 'line_review', annotations: [{ line: 2, reason: '参考' }] },
  });
  showView(view);
  expect(await screen.findByText('原批注')).toBeTruthy();
  fireEvent.click(screen.getByText('原作答与反馈'));
  expect(screen.getByText(/原所有者参考/)).toBeTruthy();
  expect(screen.getByText(/批注理由未自动评判/)).toBeTruthy();
  expect(screen.getByRole('button', { name: '编辑第 2 行批注' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '提交审查' })).toBeNull();
});

test('prediction has an explicit empty-output command and never auto-submits on mount', async () => {
  showView(responseView('prediction'));
  const empty = await screen.findByRole('button', { name: '确认没有输出' });
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(empty);
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1].payload).toEqual({ type: 'prediction', text: '' });
});

test('an unreadable artifact keeps only public metadata', async () => {
  render(<NativeArtifacts messageId="turn:assistant" />);
  expect(await screen.findByRole('heading', { name: '工件内容暂不可读' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '取消此交互' })).toBeNull();
  expect(screen.getByText(/The exact source permission was revoked/)).toBeTruthy();
  expect(native.write).not.toHaveBeenCalled();
});

test('an uncertain original cancel is not re-dispatched from the unreadable shell', async () => {
  native.state.pending = [{ path: `${path}/actions` }];
  render(<NativeArtifacts messageId="turn:assistant" />);
  await screen.findByRole('heading', { name: '工件内容暂不可读' });
  expect(screen.queryByRole('button', { name: '取消此交互' })).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
  expect(screen.getByText('原动作尚待只读核对，不会重发。')).toBeTruthy();
});

test('a confirmed empty conversation is an input state, not endless loading or fake messages', () => {
  native.state.snapshot.turns = [{ conversation_id: 'conversation', turns: [] }];
  function Pane({ loading }: { loading: boolean }) {
    const view = useNativePaneView({ isLanding: false, column: 'loading' }, 'conversation', loading);
    return <div data-column={view.column}>
      <NativeConversationContent conversationId="conversation"><p>Original messages</p></NativeConversationContent>
    </div>;
  }
  expect(isNativeEmptyConversation(native.state.snapshot, 'conversation')).toBe(true);
  const view = render(<Pane loading={false} />);
  expect(screen.getByRole('status').textContent).toBe('从下方开始讨论学习目标与路线。');
  expect(view.container.firstElementChild?.getAttribute('data-column')).toBe('messages');
  expect(screen.queryByText('Original messages')).toBeNull();
  view.rerender(<Pane loading />);
  expect(view.container.firstElementChild?.getAttribute('data-column')).toBe('loading');
});

test('a presented memory review is actionable in the real conversation without a model turn', async () => {
  native.state.snapshot = {
    ...native.state.snapshot, conversations: [{ id: 'conversation', goal_id: 'goal' }], plans: [], runs: [],
  } as any;
  native.request.mockResolvedValue([{
    id: 'review', kind: 'memory_review', goal_id: 'goal', conversation_id: 'conversation',
    card_id: 'card', card_revision: 1, state: 'presented', presented_at: '2026-11-07T01:00:00Z',
    created_at: '2026-11-07T01:00:00Z',
    card: { id: 'card', revision: 1, due: true, status: 'scheduled',
      prompt: '回忆当前节点的边界条件', next_due_at: '2026-11-07T01:00:00Z',
      algorithm_version: 'py-fsrs.6.3.2', parameter_version: 'fsrs-default.6.3.2' },
  }]);
  render(<NativeConversationContent conversationId="conversation">
    <p>原对话</p><NativeThreadTail conversationId="conversation" />
  </NativeConversationContent>);
  await screen.findByText('回忆当前节点的边界条件');
  expect(screen.getByText('原对话')).toBeTruthy();
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '想起来了' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][0]).toBe('/v1/review-activities/review/responses');
  expect(native.write.mock.calls[0][1]).toEqual({ expected_revision: 1, rating: 'good' });
});

test('a composed choice shows original owner prose and submits only the exact component action', async () => {
  showView(ownedView('knowledge_check'));
  await screen.findByText('Actual published choice prompt');
  fireEvent.click(screen.getByRole('radio', { name: 'Published B' }));
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [url, body, recovery] = native.write.mock.calls[0];
  expect(url).toBe(`${path}/actions`);
  expect(body).toEqual({
    action: 'respond_component', component_id: 'response',
    payload: { selected_key: 'B' }, client_action_id: expect.any(String), expected_artifact_revision: 7,
  });
  expect(recovery.lookup).toBe(`${path}/actions/${body.client_action_id}`);
  expect(screen.queryByText('回答正确。')).toBeNull();
});

test('a completed choice can be changed locally without submitting or replacing the original choice', async () => {
  const view = ownedView('knowledge_check', { id: 'original', selected_key: 'B', correct: true, explanation: '原选择正确。' });
  const shown = showView(view);
  const option = await screen.findByRole('radio', { name: 'Published A' }) as HTMLInputElement;
  fireEvent.click(option);
  expect(option.checked).toBe(true);
  expect(screen.queryByRole('button', { name: '提交回答' })).toBeNull();
  fireEvent.click(screen.getByText('原作答与反馈'));
  expect(screen.getByText('原选择：B')).toBeTruthy();
  shown.unmount();
  showView(view);
  expect((await screen.findByRole('radio', { name: 'Published A' }) as HTMLInputElement).checked).toBe(true);
  expect(native.write).not.toHaveBeenCalled();
});

test('a passed Python card reruns only the public sample and keeps its original attempt', async () => {
  const view = ownedView('code_workspace', attempt());
  showView(view);
  const editor = await screen.findByRole('textbox', { name: '程序' }) as HTMLTextAreaElement;
  expect(editor.closest('.demo-workbench')).toBeTruthy();
  expect(screen.getByRole('region', { name: '题目与学习工具' }).textContent).toContain('Actual published Python prompt');
  expect(screen.queryByRole('button', { name: '运行评测' })).toBeNull();
  expect(editor.value).toBe('print(3)');
  expect(editor.readOnly).toBe(false);
  expect(practiceReceipts(view as never)[0].client_action_id).toBeNull();
  fireEvent.change(editor, { target: { value: 'print(4)' } });
  native.write.mockResolvedValue({ status: 'reported', output: { outcome: 'completed', exit_code: 0, stdout: '4', stderr: '' } });
  fireEvent.click(screen.getByRole('button', { name: '运行公开样例' }));
  expect(await screen.findByRole('log')).toHaveProperty('textContent', '4');
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][0]).toBe(`${path}/example-runs`);
  expect(native.write.mock.calls[0][1]).toMatchObject({
    component_id: 'response', expected_artifact_revision: 7, answer: { code: 'print(4)' },
  });
});

test.each(['error', 'queued'])('the %s owner exposes only its explicit retry or exact cancel', async (status) => {
  showView(ownedView('code_workspace', attempt(status)));
  const label = status === 'error' ? '重试同一份代码' : '取消本次运行';
  fireEvent.click(await screen.findByRole('button', { name: label }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const body = native.write.mock.calls[0][1];
  expect(body).toMatchObject(status === 'error' ? {
    action: 'run_component', component_id: 'response',
    payload: { code: 'print(3)', previous_attempt_id: 'latest-attempt', retry: true },
  } : {
    action: 'cancel_component_run', component_id: 'response', expected_attempt_id: 'latest-attempt',
  });
});

test('a queued Python component does not lock a separate unanswered choice', async () => {
  const view = ownedView('code_workspace', attempt('queued'));
  const choice = ownedView('knowledge_check');
  for (const node of choice.presentation.definition.components) {
    node.id = 'choice_' + node.id;
    if ('state' in node.props) node.props.state = 'choice_response';
    if ('for_component' in node.props) node.props.for_component = 'choice_response';
  }
  Object.assign(view.presentation.definition.states, { choice_response: { type: 'choice', value: [] } });
  view.presentation.definition.components.push(...choice.presentation.definition.components);
  view.component_bindings.push({ ...choice.component_bindings[0], component_id: 'choice_response' });
  showView(view);
  const option = await screen.findByRole('radio', { name: 'Published A' });
  expect((option as HTMLInputElement).disabled).toBe(false);
  expect((screen.getByRole('textbox', { name: '程序' }) as HTMLTextAreaElement).readOnly).toBe(true);
  fireEvent.click(option);
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'respond_component', component_id: 'choice_response', payload: { selected_key: 'A' },
  });
});

test('Python drafts survive an action revision refresh without inheriting another current grade', async () => {
  let view = ownedView('code_workspace', attempt());
  showView(view);
  const editor = await screen.findByRole('textbox', { name: '程序' });
  fireEvent.change(editor, { target: { value: 'print(17)' } });
  cleanup();
  view = { ...view, revision: 10 };
  native.state = { ...native.state, epoch: 1 };
  showView(view);
  expect((await screen.findByRole('textbox', { name: '程序' }) as HTMLTextAreaElement).value).toBe('print(17)');
  expect(within(document.querySelector('[data-component-id="feedback"]') as HTMLElement)
    .queryByText('Actual assessment feedback')).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
});

test.each(['running', 'completed'])('unreadable %s compositions have no cancel action', async (state) => {
  native.request.mockImplementation(async (url: string) => {
    if (url.split('?')[0] === path) throw new Error('Source revoked');
    return [{ ...summary, state }];
  });
  render(<NativeArtifacts messageId="turn:assistant" />);
  await screen.findByRole('heading', { name: '工件内容暂不可读' });
  expect(screen.queryByRole('button', { name: '取消此交互' })).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
});

test('the native source host reserves reading width only while its actual reader is open', () => {
  function Group({ children }: { children: React.ReactNode }) { return <div>{children}</div>; }
  const view = render(<NativeSourcePanel panel={null} NativeGroup={Group}><p>Message area</p></NativeSourcePanel>);
  expect(view.container.firstElementChild?.getAttribute('data-reader-docked')).toBe('false');
  native.state = { ...native.state, reader: { path: '/exact-source', content: { title: 'Source', excerpt: 'Exact text' } } };
  view.rerender(<NativeSourcePanel panel={null} NativeGroup={Group}><p>Message area</p></NativeSourcePanel>);
  expect(view.container.firstElementChild?.getAttribute('data-reader-docked')).toBe('true');
  expect(screen.getByRole('complementary', { name: '教材阅读面板' }).getAttribute('data-open')).toBe('true');
});

test.each([
  [null, '第 4 页'],
  [{ number: 4, location_basis: 'document_page' }, '第 4 页'],
  [{ number: 4, location_basis: 'image_region', region: [1000, 1000, 1191, 1684] }, '图片区域 4'],
  [{ number: 4, location_basis: 'document_part', original_part: 'word/media/image4.png' },
    '文档部件 4（word/media/image4.png）'],
])('source captions retain the verified location basis %#', (location, label) => {
  native.state = { ...native.state, reader: { path: '/exact-image-source', content: {
    title: 'Exact source', location,
    block: { ref: { document_revision: 2 }, section_path: ['Numbers'], source_page: 4,
      text: 'Original recognized text' },
  } } };
  function Group({ children }: { children: React.ReactNode }) { return <div>{children}</div>; }
  render(<NativeSourcePanel panel={null} NativeGroup={Group}><p>Message area</p></NativeSourcePanel>);
  const reader = screen.getByRole('complementary', { name: '教材阅读面板' });
  expect(within(reader).getByText(`固定版本 2 · Numbers · ${label}`)).toBeTruthy();
  expect(within(reader).getByText('Original recognized text')).toBeTruthy();
  if (location && location.location_basis !== 'document_page') {
    expect(within(reader).queryByText(/第 4 页/)).toBeNull();
  }
  expect(native.request).not.toHaveBeenCalled();
});

function showSupplyTasks(packs: Record<string, unknown>[]) {
  native.state = { ...native.state, snapshot: {
    actor: { id: 'owner' }, turns: [], conversations: [{ id: 'conversation', goal_id: 'goal' }],
    plans: [{ id: 'plan', goal_id: 'goal' }], packs, delivery_tasks: [], runs: [],
  } as any };
  const view = render(<NativeTasks />);
  fireEvent.click(screen.getByRole('button', { name: '后台任务' }));
  return view;
}

test('task cancellation targets the exact original active run and never restarts an unknown call', async () => {
  showSupplyTasks([]);
  native.state = { ...native.state, snapshot: { ...native.state.snapshot, runs: [{
    id: 'original-run', conversation_id: 'conversation', status: 'blocked_unknown', cancel_requested: false,
  }] } as any };
  cleanup();
  render(<NativeTasks />);
  fireEvent.click(screen.getByRole('button', { name: '后台任务' }));
  expect(native.request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '取消本次教学' }));
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/runs/original-run/cancel', { method: 'POST' }));
  expect(native.write).not.toHaveBeenCalled();
});

const supplyTask = {
  id: 'root-pack', plan_id: 'plan', supply_task_id: 'supply-task', revision: 1,
  kind: 'response', automation_status: 'waiting', automation_action: 'yield_foreground',
  automation_reason: null, response_formats: { practice_1: 'prediction', practice_2: 'ordering' },
};

test('supply task panel shows only the current goal and latest original lineage, and cancels that owner', async () => {
  showSupplyTasks([
    supplyTask,
    { ...supplyTask, id: 'head-pack', revision: 2 },
    { ...supplyTask, id: 'other-pack', plan_id: 'other-plan', supply_task_id: 'other-task' },
  ]);
  expect(screen.getByText('预测输出 / 步骤排序供题 · 版本 2')).toBeTruthy();
  expect(screen.queryByText(/版本 1/)).toBeNull();
  expect(screen.getByText('等待当前对话结束')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '取消供题' }));
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/packs/head-pack/cancel', { method: 'POST' }));
  await waitFor(() => expect(native.refresh).toHaveBeenCalledTimes(1));
  expect(native.write).not.toHaveBeenCalled();
});

test('unknown supply does not offer retry, while committed publication refresh stays read-only', () => {
  const view = showSupplyTasks([{
    ...supplyTask, automation_action: 'await_receipt', automation_reason: 'external_result_unknown',
  }]);
  expect(screen.getByText('外部结果未知，不会自动重发')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '核对后恢复原供题任务' })).toBeNull();
  native.state = { ...native.state, epoch: 1, snapshot: {
    ...native.state.snapshot, packs: [{
      ...supplyTask, automation_status: 'completed', automation_action: 'published',
    }],
  } as any };
  view.rerender(<NativeTasks />);
  expect(screen.getByText('已发布，可回到对话继续')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '取消供题' })).toBeNull();
  expect(native.request).not.toHaveBeenCalled();
});

test('known supply dependency recovery calls only the original explicit resume endpoint', async () => {
  showSupplyTasks([{ ...supplyTask, automation_reason: 'source_not_current' }]);
  fireEvent.click(screen.getByRole('button', { name: '核对后恢复原供题任务' }));
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/packs/root-pack/automation-resume', { method: 'POST' }));
  await waitFor(() => expect(native.refresh).toHaveBeenCalledTimes(1));
});
