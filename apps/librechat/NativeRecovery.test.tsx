import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeRecovery from './NativeRecovery';

const native = vi.hoisted(() => ({ state: {} as any, request: vi.fn(), write: vi.fn(), reconcile: vi.fn() }));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request, nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile,
  },
}));
const summary = (status = 'ready', kind = 'project_stdio') => ({
  id: 'transfer', source_pack_id: 'pack', plan_id: 'plan', plan_revision: 2, node_key: 'node',
  kind, program_remediation_id: 'failed', status, created_at: '2026-11-07T00:00:00Z',
});
const task = () => ({
  slot: 'practice_1', language: 'project_stdio', title: '新的文本处理情境', prompt: '读取一行并返回长度。',
  environment: { profile: 'project-stdio.v1', language: 'java', runtime_version: '21', environment_release_id: 'release' },
  files: [{ path: 'Main.java', content: 'class Main {}', read_only: false }],
  sample: { input: 'abc', expected: '3' },
});
const view = (status = 'ready') => ({
  transfer: summary(status), question: status === 'opened' ? task() : null,
  allowed_actions: status === 'ready' ? ['open', 'cancel'] : status === 'opened' ? ['submit', 'cancel'] : [],
});
beforeEach(() => {
  sessionStorage.clear();
  native.state = { snapshot: {
    actor: { id: 'actor' }, packs: [{ id: 'pack', plan_id: 'plan', plan_revision: 2, node_key: 'node', status: 'published' }],
    program_attempts: [{ id: 'failed', pack_id: 'pack', slot: 'remediation_1',
      status: 'not_passed', created_at: '2026-11-07T00:00:00Z' }],
    transfers: [], supply_demands: [],
  }, pending: [], epoch: 1 };
  native.request.mockReset().mockResolvedValue(view());
  native.reconcile.mockReset().mockResolvedValue(summary());
  native.write.mockReset().mockImplementation(async (path: string) =>
    path.endsWith('/transfer-requests') ? summary() : path.endsWith('/open') ? view('opened') : view('passed'));
});
afterEach(cleanup);
const mount = () => {
  render(<NativeRecovery planId="plan" planRevision={2} nodeKey="node" />);
  fireEvent.click(screen.getByText('补救后的新情境检查'));
};

test('program recovery explicitly prepares, opens and submits one complete answer with exact original-key lookups', async () => {
  mount();
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '准备新情境检查' }));
  await screen.findByRole('button', { name: '明确开题' });
  expect(native.write.mock.calls[0][0]).toBe('/v2/program-attempts/failed/transfer-requests');
  expect(native.write.mock.calls[0][1]).toEqual({ expected_plan_revision: 2 });
  expect(screen.queryByText('新的文本处理情境')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '明确开题' }));
  const editor = await screen.findByRole('textbox', { name: '新情境 · Main.java' });
  fireEvent.change(editor, { target: { value: 'class Main { public static void main(String[] args) {} }' } });
  fireEvent.click(screen.getByRole('button', { name: '一次提交新情境答案' }));
  await screen.findByText('本次新情境检查通过');
  expect(native.write).toHaveBeenCalledTimes(3);
  expect(native.write.mock.calls[1][2].lookup).toBe('/v1/transfers/transfer/opening');
  const [path, body, options] = native.write.mock.calls[2];
  expect(path).toBe('/v2/transfers/transfer/program-submissions');
  expect(body).toEqual({ answer: { type: 'stdio', files: [{
    path: 'Main.java', content: 'class Main { public static void main(String[] args) {} }', read_only: false,
  }] } });
  expect(options.lookup).toBe(`/v1/transfers/transfer/submissions/${options.key}`);
  expect(screen.queryByRole('button', { name: '一次提交新情境答案' })).toBeNull();
});

test.each(['choice', 'python_io'])('legacy %s recovery retains its original request and single-answer submission contract', async (kind) => {
  native.state.snapshot.program_attempts = [];
  if (kind === 'choice') native.state.snapshot.remediations = [{
    id: 'failed', pack_id: 'pack', status: 'not_passed', transfer_required: true, created_at: '2026-11-07T00:00:00Z',
  }];
  else native.state.snapshot.python_attempts = [{
    id: 'failed', pack_id: 'pack', slot: 'remediation_1', status: 'not_passed', created_at: '2026-11-07T00:00:00Z',
  }];
  const opened = { ...view('opened'), question: kind === 'choice'
    ? { title: '选择新情境', prompt: '如何处理？', options: [{ key: 'A', text: '处理第一项' }] }
    : { title: '实现新情境', prompt: '读取输入。', language: 'python_io', starter_code: 'print(1)' } };
  native.write.mockImplementation(async (path: string) =>
    path.endsWith('/transfer-requests') ? summary('ready', kind) : path.endsWith('/open') ? opened : view('passed'));
  mount();
  fireEvent.click(screen.getByRole('button', { name: '准备新情境检查' }));
  await screen.findByRole('button', { name: '明确开题' });
  expect(native.write.mock.calls[0][0]).toBe(`/v1/${kind === 'choice' ? 'remediations' : 'python-attempts'}/failed/transfer-requests`);
  fireEvent.click(screen.getByRole('button', { name: '明确开题' }));
  if (kind === 'choice') fireEvent.click(await screen.findByRole('radio', { name: 'A. 处理第一项' }));
  else await screen.findByRole('textbox', { name: '新情境整份答案' });
  fireEvent.click(screen.getByRole('button', { name: '一次提交新情境答案' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(3));
  expect(native.write.mock.calls[2][0]).toBe(`/v1/transfers/transfer/${kind === 'choice' ? 'submissions' : 'execution-submissions'}`);
  expect(native.write.mock.calls[2][1]).toEqual(kind === 'choice' ? { selected_key: 'A' } : { code: 'print(1)' });
});

test('missing candidates require explicit supply consent and show actual preparation rather than a made-up ready question', async () => {
  const demand = {
    id: 'supply', program_remediation_id: 'failed', kind: 'project_stdio', allowed_difficulties: [1, 2],
    pack: { id: 'candidate', revision: 1, status: 'qualifying', pending_run_id: 'original-quality-run' },
  };
  native.write.mockImplementation(async (path: string) => {
    if (path.endsWith('/transfer-requests')) throw Object.assign(new Error('没有合格候选'), { code: 'no_transfer_candidate' });
    return demand;
  });
  mount();
  fireEvent.click(screen.getByRole('button', { name: '准备新情境检查' }));
  await screen.findByRole('button', { name: '明确申请补题' });
  expect(native.write).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByPlaceholderText('描述希望练习的新应用情境'), { target: { value: '改用交通记录中的累计应用' } });
  fireEvent.click(screen.getByRole('button', { name: '明确申请补题' }));
  await screen.findByText('补题：固定环境资格验证 · 题包修订 1');
  expect(native.write.mock.calls[1][0]).toBe('/v2/program-attempts/failed/supply-demands');
  expect(native.write.mock.calls[1][1]).toEqual({
    expected_plan_revision: 2, instruction: '改用交通记录中的累计应用', automatic: true,
  });
  const options = native.write.mock.calls[1][2];
  expect(options.lookup).toBe(`/v1/supply-requests/${options.key}`);
  expect(screen.queryByRole('button', { name: '明确开题' })).toBeNull();
});

test('an unknown request is read using its original key and never creates a replacement transfer', async () => {
  native.state.pending = [{ key: 'original', path: '/v2/program-attempts/failed/transfer-requests', status: 'unknown' }];
  mount();
  expect((screen.getByRole('button', { name: '准备新情境检查' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '读取原新情境回执' }));
  await screen.findByRole('button', { name: '明确开题' });
  expect(native.reconcile).toHaveBeenCalledWith('original');
  expect(native.write).not.toHaveBeenCalled();
});

test('a newer passed or still-running remediation supersedes an older failed attempt', () => {
  native.state.snapshot.program_attempts.push({
    id: 'latest', pack_id: 'pack', slot: 'remediation_1', status: 'queued', created_at: '2026-11-07T01:00:00Z',
  });
  render(<NativeRecovery planId="plan" planRevision={2} nodeKey="node" />);
  expect(screen.queryByText('补救后的新情境检查')).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
});
