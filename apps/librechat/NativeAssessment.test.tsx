import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeAssessment from './NativeAssessment';

const native = vi.hoisted(() => ({ state: {} as any, request: vi.fn(), write: vi.fn(), reconcile: vi.fn() }));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request, nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile,
  },
}));
const gate = (policy = 'program-execution-gate.v1') => ({
  id: 'gate', pack_id: 'pack', plan_id: 'plan', plan_revision: 2, node_key: 'query',
  policy_version: policy, relation_run_id: 'relation', status: 'ready', created_at: '2026-11-07T00:00:00Z',
});
const ready = (policy?: string) => ({ gate: gate(policy), questions: [], results: [], allowed_actions: ['start', 'cancel'] });
const sql = (slot: string) => ({
  slot, title: slot, prompt: '按当前任务查询',
  language: 'sql_query', environment: { profile: 'sql-query.v1', dialect: 'sqlite', runtime_version: '3.46' },
  starter_query: 'SELECT 0', comparison: 'ordered',
  schema_definition: { tables: [] },
  sample: { dataset: { rows: {} }, expected: { columns: ['n'], rows: [['0']], types: [['integer']] } },
});
beforeEach(() => {
  sessionStorage.clear();
  native.state = { snapshot: { actor: { id: 'actor' }, packs: [{
    id: 'pack', plan_id: 'plan', plan_revision: 2, node_key: 'query', status: 'published',
    kind: 'sql_query', revision: 4,
  }], gates: [] }, epoch: 1, pending: [] };
  native.request.mockReset().mockResolvedValue(ready());
  native.write.mockReset().mockImplementation(async (path: string) => {
    if (path.endsWith('program-gate-requests')) return gate();
    if (path.endsWith('/start')) return {
      ...ready(), gate: { ...gate(), status: 'in_progress' },
      questions: ['assessment_1', 'assessment_2'].map(sql), allowed_actions: ['submit', 'cancel'],
    };
    return { ...ready(), gate: { ...gate(), status: 'submitted' }, allowed_actions: ['cancel'] };
  });
});
afterEach(cleanup);

test('formal program gate is explicitly requested, started, and submitted as one exact reserved group', async () => {
  render(<NativeAssessment planId="plan" planRevision={2} nodeKey="query" />);
  fireEvent.click(screen.getByText('正式独立考核'));
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '准备执行考核 · 题包修订 4' }));
  await screen.findByRole('button', { name: '明确开始整组考核' });
  expect(native.write.mock.calls[0][0]).toBe('/v2/packs/pack/program-gate-requests');
  expect(native.write.mock.calls[0][1]).toEqual({ expected_plan_revision: 2 });
  expect(screen.queryByRole('textbox')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '明确开始整组考核' }));
  const first = await screen.findByRole('textbox', { name: 'assessment_1 · assessment_1' });
  const second = screen.getByRole('textbox', { name: 'assessment_2 · assessment_2' });
  fireEvent.change(first, { target: { value: 'SELECT 1' } });
  fireEvent.change(second, { target: { value: 'SELECT 2' } });
  fireEvent.click(screen.getByRole('button', { name: '一次提交整组答案' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(3));
  const [path, body, options] = native.write.mock.calls[2];
  expect(path).toBe('/v2/gates/gate/program-submissions');
  expect(body).toEqual({ programs: [
    { slot: 'assessment_1', answer: { type: 'sql', query: 'SELECT 1' } },
    { slot: 'assessment_2', answer: { type: 'sql', query: 'SELECT 2' } },
  ] });
  expect(options.lookup).toBe(`/v2/gates/gate/program-submissions/${options.key}`);
  expect(native.write.mock.calls[1][2].lookup).toBe('/v1/gates/gate/start-receipt');
});

test.each(['choice', 'python_io'])('legacy %s gate keeps the whole-group answer contract', async (kind) => {
  const policy = kind === 'choice' ? 'concept-gate.v1' : 'python-io-gate.v1';
  native.state.snapshot.packs[0].kind = kind;
  native.state.snapshot.gates = [{ ...gate(policy), status: 'in_progress' }];
  native.request.mockResolvedValue({
    ...ready(policy), gate: { ...gate(policy), status: 'in_progress' },
    questions: ['assessment_1', 'assessment_2'].map((slot) => kind === 'choice' ? {
      slot, title: slot, prompt: '选择答案', options: ['A', 'B', 'C', 'D'].map((key) => ({ key, text: `选项${key}` })),
    } : { slot, title: slot, prompt: '编写程序', language: 'python_io', starter_code: 'print(0)' }),
    allowed_actions: ['submit', 'cancel'],
  });
  render(<NativeAssessment planId="plan" planRevision={2} nodeKey="query" />);
  fireEvent.click(screen.getByText('正式独立考核'));
  if (kind === 'choice') {
    const radios = await screen.findAllByRole('radio', { name: 'A. 选项A' });
    radios.forEach((radio) => fireEvent.click(radio));
  } else {
    await screen.findByRole('textbox', { name: 'assessment_1 · assessment_1' });
  }
  fireEvent.click(screen.getByRole('button', { name: '一次提交整组答案' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][0]).toBe(`/v1/concept-gates/gate/${kind === 'choice' ? 'submissions' : 'execution-submissions'}`);
  expect(native.write.mock.calls[0][1]).toEqual(kind === 'choice' ? {
    answers: ['assessment_1', 'assessment_2'].map((slot) => ({ slot, selected_key: 'A' })),
  } : { programs: ['assessment_1', 'assessment_2'].map((slot) => ({ slot, code: 'print(0)' })) });
});

test('a precondition failure remains visible and creates no invented exam or answers', async () => {
  native.write.mockRejectedValue(new Error('先完成当前节点的正常练习。'));
  render(<NativeAssessment planId="plan" planRevision={2} nodeKey="query" />);
  fireEvent.click(screen.getByText('正式独立考核'));
  fireEvent.click(screen.getByRole('button', { name: '准备执行考核 · 题包修订 4' }));
  await screen.findByText('先完成当前节点的正常练习。');
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByRole('button', { name: '明确开始整组考核' })).toBeNull();
});

test('formal results show independent compilation facts without replacing them with sample output', async () => {
  native.state.snapshot.gates = [{ ...gate(), status: 'not_passed' }];
  native.request.mockResolvedValue({
    ...ready(), gate: { ...gate(), status: 'not_passed' }, allowed_actions: [],
    program_results: [
      { slot: 'assessment_1', status: 'passed', passed_cases: 3, feedback: '已完成三项正式检查',
        compilation: { outcome: 'completed', exit_code: 0, stdout: 'build completed', stderr: '' } },
      { slot: 'assessment_2', status: 'not_passed', passed_cases: 0, feedback: '编译失败，未执行用例',
        compilation: { outcome: 'completed', exit_code: 2, stdout: '', stderr: 'compile failed at Main.java:3' } },
    ],
  });
  render(<NativeAssessment planId="plan" planRevision={2} nodeKey="query" />);
  fireEvent.click(screen.getByText('正式独立考核'));
  const compilations = await screen.findAllByRole('region', { name: '独立编译回执' });
  expect(compilations[0].textContent).toContain('编译通过');
  expect(compilations[0].textContent).toContain('build completed');
  expect(compilations[1].textContent).toContain('编译未通过');
  expect(compilations[1].textContent).toContain('compile failed at Main.java:3');
  expect(compilations[1].textContent).toContain('本次未执行样例和评测用例。');
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
});
