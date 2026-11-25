import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeMaterialUpdates from './NativeMaterialUpdates';

const native = vi.hoisted(() => ({
  state: { snapshot: { actor: { id: 'owner' }, goals: [{ id: 'goal', title: 'Python 学习' }] },
    epoch: 0, pending: [] as { key: string; path: string; body: unknown; lookup: string; status: string }[] },
  listeners: new Set<() => void>(), request: vi.fn(), write: vi.fn(), reconcile: vi.fn(),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: {
    subscribe: (listener: () => void) => { native.listeners.add(listener); return () => native.listeners.delete(listener); },
    getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile,
  },
}));
const notification = {
  id: 'notification', offer_id: 'offer', state: 'unread', kind: 'material_update',
  payload: { goal_id: 'goal', baseline_revision: 1, candidate_revision: 2, node_key: 'node' },
};
const offer = {
  id: 'offer', revision: 3, binding_id: 'binding', binding_revision: 4, baseline_revision: 1, candidate_revision: 2,
  summary: '循环边界条件已变化', migration_cost: 'dependent_content_requires_reprepare',
  impact: { dependencies: [{ kind: 'plan', id: 'plan', revision: 1 }, { kind: 'lesson', id: 'lesson', revision: 1 }] },
};
const decision = {
  id: 'decision', offer_id: 'offer', decision: 'accept_update', binding_id: 'binding', binding_revision: 4,
  successor_binding_id: 'binding', successor_binding_revision: 5, requires_reprepare: [{ kind: 'plan', id: 'plan', revision: 1 }],
};
const emit = () => { native.state = { ...native.state }; for (const listener of native.listeners) listener(); };
beforeEach(() => {
  native.state = { snapshot: { actor: { id: 'owner' }, goals: [{ id: 'goal', title: 'Python 学习' }] }, epoch: 0, pending: [] };
  native.request.mockReset().mockImplementation(async (path: string) => {
    if (path.startsWith('/v1/notifications?')) return [{ ...notification }];
    if (path === '/v1/notifications/notification/read') return { ...notification, state: 'read' };
    if (path === '/v1/material-update-offers/offer') return structuredClone(offer);
    if (path === '/v1/material-update-decisions/decision/repreparations') return [];
    throw new Error('unexpected read');
  });
  native.write.mockReset().mockResolvedValue(decision);
  native.reconcile.mockReset().mockResolvedValue(decision);
});
afterEach(cleanup);
async function openOffer() {
  render(<NativeMaterialUpdates />);
  fireEvent.click(await screen.findByRole('button', { name: '查看更新详情' }));
  await screen.findByRole('button', { name: '接受此更新' });
}
test('opening and reading an update never chooses or migrates it', async () => {
  await openOffer();
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/notifications/notification/read', { method: 'POST' }));
  expect(native.write).not.toHaveBeenCalled();
  expect(screen.getByText('循环边界条件已变化')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '关闭详情' }));
  expect(native.write).not.toHaveBeenCalled();
});
test('accept carries the exact offer and binding revisions and a durable receipt lookup', async () => {
  await openOffer();
  fireEvent.click(screen.getByRole('button', { name: '接受此更新' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/material-update-offers/offer/decisions');
  expect(body).toEqual({ decision: 'accept_update', expected_offer_revision: 3, expected_binding_revision: 4 });
  expect(options.lookup).toBe(`${path}/${options.key}`);
  await screen.findByText(/已保存后继绑定修订 5/);
});
test.each([
  ['本轮保留旧版', 'keep_current_for_track'],
  ['稍后决定', 'decide_later'],
])('%s sends only its explicit non-migration choice', async (label, choice) => {
  native.write.mockResolvedValue({ ...decision, decision: choice, successor_binding_id: null, successor_binding_revision: null });
  await openOffer();
  fireEvent.click(screen.getByRole('button', { name: label }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1].decision).toBe(choice);
  await screen.findByText(/当前绑定保持/);
});
test('an uncertain decision is reconciled by its original GET without a replacement decision', async () => {
  native.write.mockImplementation(async (path, body, options) => {
    native.state.pending = [{ path, body, key: options.key, lookup: options.lookup, status: 'unknown' }];
    emit(); throw new Error('回执中断');
  });
  native.reconcile.mockImplementation(async () => { native.state.pending = []; emit(); return decision; });
  await openOffer();
  fireEvent.click(screen.getByRole('button', { name: '接受此更新' }));
  await screen.findByText('回执中断');
  const key = native.write.mock.calls[0][2].key;
  fireEvent.click(screen.getByRole('button', { name: '读取原决定回执' }));
  await screen.findByText(/已保存后继绑定修订 5/);
  expect(native.reconcile).toHaveBeenCalledWith(key);
  expect(native.write).toHaveBeenCalledTimes(1);
});
test('switching identity discards previously opened update details', async () => {
  await openOffer();
  act(() => {
    native.state = { snapshot: { actor: { id: 'other' }, goals: [] }, epoch: 0, pending: [] };
    emit();
  });
  await waitFor(() => expect(screen.queryByText('循环边界条件已变化')).toBeNull());
  expect(native.write).not.toHaveBeenCalled();
});

test('an accepted update reads original preparation status and keeps route confirmation explicit', async () => {
  const original = native.request.getMockImplementation()!;
  native.request.mockImplementation(async (path: string, init) =>
    path === '/v1/material-update-decisions/decision/repreparations' ? [
      { id: 'plan-preparation', kind: 'plan', state: 'ready', output_plan_revision: 2, run_id: 'plan-run' },
      { id: 'lesson-preparation', kind: 'lesson', node_key: 'loops', state: 'waiting_confirmation',
        output_plan_revision: null, run_id: null },
    ] : original(path, init));
  await openOffer();
  fireEvent.click(screen.getByRole('button', { name: '接受此更新' }));
  await screen.findByRole('region', { name: '已接受更新的内容准备' });
  await screen.findByText('课时 · loops · 等待明确确认新路线');
  expect(screen.getByText('原任务 plan-run')).toBeTruthy();
  expect(screen.getByText(/明确确认对应的新路线/)).toBeTruthy();
  expect(native.write).toHaveBeenCalledTimes(1);
  expect(native.request.mock.calls.some(([path]) =>
    path === '/v1/material-update-decisions/decision/repreparations')).toBe(true);
});
