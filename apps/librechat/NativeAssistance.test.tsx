import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { NativeArtifacts } from './NativeLearning';
import { NativeAssistance } from './NativeAssistance';

const native = vi.hoisted(() => ({
  state: { snapshot: { actor: { id: 'assistance-owner' }, turns: [] }, epoch: 0, pending: [], reader: null },
  request: vi.fn(), write: vi.fn(),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: { subscribe: () => () => {}, getSnapshot: () => native.state, write: native.write, refresh: vi.fn() },
}));
vi.mock('react-router-dom', () => ({ useParams: () => ({ conversationId: 'assistance-conversation' }), useNavigate: () => vi.fn() }));
beforeEach(() => { sessionStorage.clear(); native.write.mockReset().mockResolvedValue({}); native.state.epoch = 0; });
afterEach(cleanup);

function practiceView(receipt: any = null) {
  return {
    schema_version: 'learning_artifact.v2', id: 'assistance-artifact',
    conversation_id: 'assistance-conversation', source_turn_id: 'assistance-turn',
    kind: 'learning_composition', title: '辅助与作答分离', revision: receipt ? 2 : 1, state: 'ready',
    allowed_actions: ['cancel'],
    content_ref: { owner: 'tutor', id: 'assistance-presentation', revision: 1, public_identity: 'same-content' },
    presentation: { type: 'learning_composition', definition: {
      schema_version: 'learning_composition.v2', title: '辅助与作答分离',
      states: { code: { type: 'code', value: 'print(0)' } },
      components: [{ id: 'editor', component: 'CodeEditor', props: { label: '我的程序', state: 'code' } }],
    } },
    component_bindings: [{
      component_id: 'editor', state: 'ready', action_id: null, result: null, attempts: null,
      assistance_profile: 'practice-direct-answer.v1', assistance_receipt: receipt,
      allowed_actions: receipt ? ['run'] : ['run', 'request_direct_answer'],
      source: {
        id: 'source', kind: 'code_workspace', title: '原题目',
        content_ref: { owner: 'item_bank', id: 'pack', revision: 1, slot: 'practice_1', public_identity: 'question' },
        presentation: { type: 'code_workspace', task: {
          title: '原题目', prompt: '计算输入之和。', starter_code: 'print(0)',
          language: 'python_io', sample: { input: [1, 2], expected: 3 },
        } },
      },
    }],
  };
}

function show(view: ReturnType<typeof practiceView>) {
  native.request.mockReset().mockImplementation(async (path: string) =>
    path.split('?')[0].endsWith('/assistance-artifact') ? view : [view]);
  return render(<NativeArtifacts messageId="assistance-turn:assistant" />);
}

const receipt = (content: object) => ({
  id: 'original-assistance', profile_version: 'practice-direct-answer.v1',
  assistance_kind: 'direct_answer', pack_id: 'pack', pack_revision: 1, slot: 'practice_1',
  public_identity: 'question', created_at: '2026-11-06T01:00:00Z', content,
});

test('explicit assistance uses original action identity without submitting or replacing the draft', async () => {
  const shown = show(practiceView());
  const editor = await screen.findByRole('textbox', { name: '我的程序' });
  expect(native.request.mock.calls.some(([path]) =>
    path.includes('direct_answer_capability=learning_direct_answers.v1'))).toBe(true);
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.change(editor, { target: { value: 'print(123)' } });
  fireEvent.click(screen.getByRole('button', { name: '请求直接答案' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'request_direct_answer', component_id: 'editor', expected_artifact_revision: 1,
  });
  expect(native.write.mock.calls[0][1]).not.toHaveProperty('payload');
  shown.unmount();
  show(practiceView(receipt({
    type: 'python', code: 'print(sum(xs))', explanation: '已审参考，不是本次作答。',
  })));
  expect((await screen.findByRole('textbox', { name: '我的程序' }) as HTMLTextAreaElement).value).toBe('print(123)');
  fireEvent.click(screen.getByRole('button', { name: '参考答案（已记辅助）' }));
  expect(screen.getByText('print(sum(xs))')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '请求直接答案' })).toBeNull();
  expect(native.write).toHaveBeenCalledTimes(1);
});

test.each([
  { type: 'choice', correct_key: 'B', explanation: '选择参考。' },
  { type: 'response', response: { type: 'prediction', text: '' }, findings: [], explanation: '输出参考。' },
  { type: 'response', response: { type: 'short', text: '参考说法，不自动评分。' }, explanation: '简答参考。' },
  { type: 'response', response: { type: 'ordering', ordered_ids: ['B', 'A'] }, findings: [], explanation: '排序参考。' },
  { type: 'response', response: { type: 'line_review', annotations: [{ line: 2, reason: '公开参考理由。' }] }, findings: [], explanation: '定位参考。' },
  { type: 'program', answer: { type: 'sql', query: 'SELECT SUM(n) FROM records' }, explanation: '查询参考。' },
  { type: 'program', answer: { type: 'project', files: [{ path: 'main.py', content: 'print(7)', read_only: true }] }, explanation: '文件参考。' },
])('recorded reference is read-only and never issues another command: $explanation', (content) => {
  const onCommand = vi.fn();
  const binding = practiceView(receipt(content)).component_bindings[0] as any;
  render(<NativeAssistance binding={binding} blocked={false} onCommand={onCommand} />);
  fireEvent.click(screen.getByRole('button', { name: '参考答案（已记辅助）' }));
  expect(screen.getByText(content.explanation)).toBeTruthy();
  expect(onCommand).not.toHaveBeenCalled();
  expect(screen.queryByRole('textbox')).toBeNull();
});

test('old owners and queued owners do not acquire a reference control; pending writes disable it', () => {
  const binding = practiceView().component_bindings[0] as any;
  const onCommand = vi.fn();
  const shown = render(<NativeAssistance binding={{ ...binding, assistance_profile: undefined }}
    blocked={false} onCommand={onCommand} />);
  expect(screen.queryByRole('button')).toBeNull();
  shown.rerender(<NativeAssistance binding={{ ...binding, allowed_actions: ['cancel_run'] }}
    blocked={false} onCommand={onCommand} />);
  expect(screen.queryByRole('button')).toBeNull();
  shown.rerender(<NativeAssistance binding={binding} blocked={true} onCommand={onCommand} />);
  expect((screen.getByRole('button', { name: '请求直接答案' }) as HTMLButtonElement).disabled).toBe(true);
  expect(onCommand).not.toHaveBeenCalled();
});

const hintTexts = [
  '先观察循环中每轮都会变化的状态，而不是先猜最后的输出。',
  '把每轮开始和结束时的状态列成两列，再跟踪输入如何被处理。',
  '从第一个输入开始填写前后状态，然后按同一个规则继续下一轮。',
];
const hintNames = ['概念线索', '解题策略', '下一步'];
function hintView(level: number) {
  const view = practiceView();
  return { ...view, revision: level + 1, component_bindings: [{
    ...view.component_bindings[0], hint_profile: 'practice-hints.v1',
    hint_receipts: hintTexts.slice(0, level).map((text, index) => ({
      id: `hint-${index + 1}`, level: index + 1, content: { text, level: index + 1 },
    })),
    next_hint_level: level < 3 ? level + 1 : null,
    allowed_actions: ['run', 'request_direct_answer', ...(level < 3 ? ['request_hint'] : [])],
  }] };
}

test('only the next explicit hint action is sent; refresh restores a receipt without changing the draft', async () => {
  const shown = show(hintView(0));
  const editor = await screen.findByRole('textbox', { name: '我的程序' });
  expect(native.request.mock.calls.some(([path]) =>
    path.includes('hint_capability=learning_hints.v1'))).toBe(true);
  hintTexts.forEach((text) => expect(screen.queryByText(text)).toBeNull());
  expect(screen.queryByRole('button', { name: '请求 H2 · 解题策略' })).toBeNull();
  fireEvent.change(editor, { target: { value: 'print(456)' } });
  fireEvent.click(screen.getByRole('button', { name: '请求 H1 · 概念线索' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'request_hint', component_id: 'editor', level: 1, expected_artifact_revision: 1,
  });
  expect(native.write.mock.calls[0][1]).not.toHaveProperty('payload');
  shown.unmount();
  show(hintView(1));
  expect((await screen.findByRole('textbox', { name: '我的程序' }) as HTMLTextAreaElement).value).toBe('print(456)');
  expect(screen.getByText(hintTexts[0])).toBeTruthy();
  expect(screen.queryByText(hintTexts[1])).toBeNull();
  expect(screen.getByRole('button', { name: '请求 H2 · 解题策略' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '请求直接答案' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'H1 · 概念线索（已记辅助）' }));
  expect(native.write).toHaveBeenCalledTimes(1);
});

test('all released hints are read-only; pending writes block the next level and completed series has no request', () => {
  const onCommand = vi.fn();
  const shown = render(<NativeAssistance binding={hintView(2).component_bindings[0] as any}
    blocked={true} onCommand={onCommand} />);
  expect((screen.getByRole('button', { name: '请求 H3 · 下一步' }) as HTMLButtonElement).disabled).toBe(true);
  shown.rerender(<NativeAssistance binding={hintView(3).component_bindings[0] as any}
    blocked={false} onCommand={onCommand} />);
  hintTexts.forEach((text, index) => {
    const button = screen.getByRole('button', { name: `H${index + 1} · ${hintNames[index]}（已记辅助）` });
    if (button.getAttribute('aria-expanded') === 'false') fireEvent.click(button);
    expect(screen.getByText(text)).toBeTruthy();
  });
  expect(screen.queryByRole('button', { name: /^请求 H/ })).toBeNull();
  expect(onCommand).not.toHaveBeenCalled();
  expect(screen.queryByRole('textbox')).toBeNull();
});
