import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativePlanAction from './NativePlanAction';
import NativeTavilySettings from './NativeTavilySettings';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), send: vi.fn(), refresh: vi.fn(),
}));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state, refresh: native.refresh,
  },
}));
vi.mock('./native-intake.mjs', () => ({ sendPlanningTurn: native.send }));
beforeEach(() => {
  native.state = { pending: [], snapshot: { runs: [], turns: [{
    conversation_id: 'conversation', turns: [{
      id: 'turn', purpose: 'planning', completed_at: '2026-11-10T10:00:00Z',
      planning_state: { information_complete: true, missing_information: [],
        requirements_revision: 3, plan_requested: false, material_blocked: false },
    }],
  }] } };
  native.request.mockReset();
  native.send.mockReset().mockResolvedValue(undefined);
  native.refresh.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

test('only a complete latest discussion can start a version-bound plan, once per click sequence', async () => {
  const planning = native.state.snapshot.turns[0].turns[0].planning_state;
  planning.information_complete = false;
  const view = render(<NativePlanAction conversationId="conversation" turnId="turn" />);
  expect(screen.queryByRole('button', { name: '制定计划' })).toBeNull();
  planning.information_complete = true;
  view.rerender(<NativePlanAction conversationId="conversation" turnId="turn" />);
  let release!: () => void;
  native.send.mockImplementation(() => new Promise<void>((resolve) => { release = resolve; }));
  const button = screen.getByRole('button', { name: '制定计划' });
  fireEvent.click(button); fireEvent.click(button);
  expect(native.send).toHaveBeenCalledOnce();
  expect(native.send.mock.calls[0].slice(1)).toEqual([
    'conversation', '制定计划', expect.any(String), planning,
  ]);
  release();
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
});

test('a diagnosed unresolved receipt keeps its error visible and never submits a new plan', async () => {
  native.state.snapshot.turns[0].turns[0].planning_state.material_blocked = true;
  native.request.mockRejectedValue(new Error('请先核对原回执。'));
  render(<NativePlanAction conversationId="conversation" turnId="turn" />);
  fireEvent.click(screen.getByRole('button', { name: '修复并继续' }));
  await screen.findByText('请先核对原回执。');
  expect(native.request).toHaveBeenCalledWith(
    '/v1/conversations/conversation/material-repair', { method: 'POST' },
  );
  expect(native.send).not.toHaveBeenCalled();
});

test('material repair continues the original task without fabricating another learner request', async () => {
  native.state.snapshot.turns[0].turns[0].planning_state.material_blocked = true;
  native.request.mockResolvedValue({ repaired_steps: 1 });
  render(<NativePlanAction conversationId="conversation" turnId="turn" />);
  fireEvent.click(screen.getByRole('button', { name: '修复并继续' }));
  await waitFor(() => expect(native.refresh).toHaveBeenCalledOnce());
  expect(native.request).toHaveBeenCalledOnce();
  expect(native.send).not.toHaveBeenCalled();
});

test('automatic material discovery does not require a learner repair action', () => {
  native.state.snapshot.turns[0].turns[0].planning_state.material_blocked = true;
  native.state.snapshot.conversations = [{ id: 'conversation', goal_id: 'goal' }];
  native.state.snapshot.goals = [{
    id: 'goal', material_scope: { authorized_public_sources: true },
  }];
  render(<NativePlanAction conversationId="conversation" turnId="turn" />);
  expect(screen.queryByRole('button', { name: '修复并继续' })).toBeNull();
  expect(native.request).not.toHaveBeenCalled();
  expect(native.send).not.toHaveBeenCalled();
});

test('Tavily configuration saves an actor-owned key with consent and clears the input', async () => {
  native.request.mockImplementation(async (_path: string, init?: RequestInit) => (
    init?.method === 'PUT'
      ? { revision: 1, enabled: true, credential_present: true }
      : { revision: 0, enabled: false, credential_present: false }
  ));
  render(<NativeTavilySettings available />);
  fireEvent.click(screen.getByRole('button', { name: '教材搜索 · Tavily' }));
  const input = screen.getByLabelText('Tavily API Key') as HTMLInputElement;
  await waitFor(() => expect(native.request).toHaveBeenCalledOnce());
  await waitFor(() => expect((screen.getByRole('button', { name: '保存教材搜索配置' }) as HTMLButtonElement).disabled).toBe(true));
  fireEvent.change(input, { target: { value: 'owned-search-test-value' } });
  fireEvent.click(screen.getByLabelText('启用 Tavily，允许发送检索主题及公开资料网址，费用由本人承担'));
  fireEvent.submit(screen.getByRole('form', { name: 'Tavily 教材搜索配置' }));
  await screen.findByText('Tavily 配置已保存。');
  expect(native.request).toHaveBeenLastCalledWith('/v1/material-search-configuration', {
    method: 'PUT', body: JSON.stringify({
      expected_revision: 0, enabled: true, api_key: 'owned-search-test-value',
    }),
  });
  expect(input.value).toBe('');
});
