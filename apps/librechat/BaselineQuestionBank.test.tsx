import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { BaselineQuestionBank } from './BaselineQuestionBank';
import { generationMessages } from './generation-relay';

const live = vi.hoisted(() => ({ state: {} as any, request: vi.fn() }));
vi.mock('./NativeLearning', () => ({ useNative: () => live.state }));
vi.mock('./native-client.mjs', () => ({ nativeRequest: live.request }));
const route = { id: 'route', goal_id: 'goal', active: { revision: 2, document: { title: 'Python 入门' } },
  latest: { revision: 2, document: { title: 'Python 入门' } } };
const pack = { id: 'published', revision: 2, plan_revision: 2, node_key: 'loop', kind: 'choice',
  status: 'published', predecessor_id: 'draft', supply_task_id: 'task', created_at: '2026-11-25T01:00:00Z' };
const old = { ...pack, id: 'draft', revision: 1, predecessor_id: null, status: 'changes_required' };
const nodes = [{ title: '循环', node_key: 'loop', position: 1, plan_revision: 2, packs: [pack, old] },
  { title: '函数', node_key: 'func', position: 2, plan_revision: 2, packs: [] }];
const notes = ['检查题目条件是否有多种解释。'];
const report = { pack_id: 'published', status: 'published', published_at: pack.created_at, qualifications: {},
  stages: [{ role: 'ambiguity', status: 'succeeded', started_at: pack.created_at, completed_at: pack.created_at,
    public_notes: notes, independence: 'supported', decisions: { practice_1: 'pass' } }] };
const titles = () => live.request.mock.calls.map(([path]) => path);

beforeEach(() => {
  vi.spyOn(window.HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => null);
  live.state = { snapshot: { actor: { id: 'learner' }, goals: [{ id: 'goal' }], plans: [route], runs: [], packs: [], gates: [] } };
  live.request.mockReset().mockImplementation(async (path) => {
    if (path === '/v1/plans/route/question-bank') return nodes;
    if (path === '/v1/packs/published/generation') return report;
    if (path === '/v1/packs/draft/generation') return { ...report, pack_id: 'draft', status: 'changes_required', published_at: null,
      stages: [{ ...report.stages[0], public_notes: [], independence: 'revise', decisions: { practice_1: 'revise' } }] };
    if (path === '/v1/packs/published/practice') return { questions: [{ title: '辨认输出', slot: 'practice_1', prompt: '哪一行会先输出？',
      options: [{ key: 'A', text: '第一行' }, { key: 'B', text: '第二行' }] }] };
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function openNode() {
  fireEvent.click(screen.getByRole('button', { name: 'Python 入门' }));
  fireEvent.click((await screen.findByText('1. 循环')).closest('summary')!);
}

test('route and node browsing reads only the catalogue; six-review history never opens an exercise', async () => {
  render(<BaselineQuestionBank />);
  expect(titles()).toEqual([]);
  await openNode();
  expect(titles()).toEqual(['/v1/plans/route/question-bank']);
  fireEvent.click(screen.getByRole('button', { name: '生成过程' }));
  const timeline = await screen.findByRole('region', { name: '题目生成过程' });
  fireEvent.click(within(timeline).getByText('题意与歧义').closest('summary')!);
  expect(within(timeline).getByText(notes[0])).toBeTruthy();
  expect(within(timeline).getByText('练习一')).toBeTruthy();
  expect(screen.queryByText('哪一行会先输出？')).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: /题包版本/ }), { target: { value: 'draft' } });
  await screen.findByText('本版题包：需修订');
  expect(screen.queryByRole('button', { name: '已发布练习' })).toBeNull();
  expect(screen.queryByText(notes[0])).toBeNull();
  expect(titles()).toEqual(['/v1/plans/route/question-bank', '/v1/packs/published/generation', '/v1/packs/draft/generation']);
});

test('only explicitly opening published practice reads the original question body', async () => {
  const view = render(<BaselineQuestionBank />);
  await openNode();
  fireEvent.click(screen.getByRole('button', { name: '查看练习题' }));
  await screen.findByText('哪一行会先输出？');
  expect(screen.getByText('A. 第一行')).toBeTruthy();
  expect(titles()).toEqual(['/v1/plans/route/question-bank', '/v1/packs/published/practice']);
  live.state.snapshot.gates = [{ status: 'in_progress' }];
  view.rerender(<BaselineQuestionBank />);
  expect(screen.queryByText('哪一行会先输出？')).toBeNull();
  expect(screen.getByText('正式考核期间暂停查看练习。')).toBeTruthy();
});

test('generation opens the ten-role relay for this revision; icon controls, seeking and version changes stay local', async () => {
  render(<BaselineQuestionBank />);
  await openNode();
  fireEvent.click(screen.getByRole('button', { name: '生成过程' }));
  const relay = within(await screen.findByRole('region', { name: '题包协作' }));
  expect(relay.getAllByRole('button', { pressed: false })).toHaveLength(10);
  expect(relay.queryByRole('button', { name: '复位' })).toBeNull();
  expect(relay.queryByText('示例回放')).toBeNull();
  const play = relay.getByRole('button', { name: '播放消息' });
  expect(play.textContent).toBe('');
  fireEvent.click(play);
  expect(relay.getByRole('button', { name: '暂停消息' }).dataset.playing).toBe('true');
  fireEvent.click(play);
  const slider = relay.getByRole('slider', { name: '消息时间轴' });
  fireEvent.keyDown(slider, { key: 'End' });
  const history = within(relay.getByRole('list', { name: '已发消息' }));
  expect(history.getAllByRole('listitem')).toHaveLength(3);
  expect(history.getByRole('listitem', { current: 'step' }).textContent).toBe('发布题包');
  expect(within(relay.getByRole('list', { name: '十个角色' })).getByRole('listitem', { current: true }).textContent).toBe('发布');
  fireEvent.click(relay.getByRole('button', { name: '重播消息' }));
  expect(history.getAllByRole('listitem')).toHaveLength(1);
  fireEvent.change(screen.getByRole('combobox', { name: /题包版本/ }), { target: { value: 'draft' } });
  await screen.findByText('本版题包：需修订');
  const draft = within(screen.getByRole('region', { name: '题包协作' }));
  fireEvent.keyDown(draft.getByRole('slider'), { key: 'End' });
  expect(within(draft.getByRole('list', { name: '已发消息' })).getByRole('listitem', { current: 'step' }).textContent).toBe('需修订');
  expect(draft.queryByText('发布题包')).toBeNull();
  expect(titles()).toEqual(['/v1/plans/route/question-bank', '/v1/packs/published/generation', '/v1/packs/draft/generation']);
});

test('empty, unknown and partial sandbox reports never invent a result or publication', () => {
  const base = { pack_id: 'pack', status: 'qualifying' as const, published_at: null, stages: [], qualifications: {} };
  expect(generationMessages(base, true)).toEqual([]);
  const pending = { ...base, stages: [{ role: 'blind' as const, started_at: pack.created_at, completed_at: null,
    status: 'blocked_unknown' as const, public_notes: [] }] };
  expect(generationMessages(pending, true).map(({ to, text }) => [to, text])).toEqual([['blind', '盲解：等待核对原回执。']]);
  const qualified = { ...base, qualifications: { pending: 3, passed: 1, error: 1 } };
  expect(generationMessages(qualified, true).map(({ action, text }) => [action, text])).toEqual([
    ['送交验证', '独立作答进入沙盘验证。'], ['验证回执', '已返回 2/5，通过 1。'],
  ]);
  expect(generationMessages(qualified, false)).toEqual([]);
});

test('changing learner discards an open directory and ignores its late response', async () => {
  let resolveDirectory!: (result: typeof nodes) => void;
  live.request.mockImplementationOnce(() => new Promise((resolve) => { resolveDirectory = resolve; }));
  const view = render(<BaselineQuestionBank />);
  fireEvent.click(screen.getByRole('button', { name: 'Python 入门' }));
  live.state = { snapshot: { actor: { id: 'another' }, goals: [], plans: [], packs: [], gates: [] } };
  view.rerender(<BaselineQuestionBank />);
  resolveDirectory(nodes);
  await waitFor(() => expect(screen.getByText('有了学习路线后，就能在这里按节点查看题目。')).toBeTruthy());
  expect(screen.queryByText('1. 循环')).toBeNull();
});

test('a new revision in review preserves the earlier published practice entry', async () => {
  live.request.mockResolvedValueOnce([{ ...nodes[0], title: '第 1 节：循环', packs: [
    { ...pack, id: 'next', revision: 3, predecessor_id: 'published', status: 'reviewing' }, pack, old,
  ] }]);
  render(<BaselineQuestionBank />);
  fireEvent.click(screen.getByRole('button', { name: 'Python 入门' }));
  fireEvent.click((await screen.findByText('第 1 节：循环')).closest('summary')!);
  fireEvent.click(screen.getByRole('button', { name: '查看练习题（第 2 版）' }));
  await screen.findByText('哪一行会先输出？');
  expect(titles()).toEqual(['/v1/plans/route/question-bank', '/v1/packs/published/practice']);
});
