import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeCourse from './NativeCourse';
import { NativeReviewPreferences, NativeReviews } from './NativeReviews';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), write: vi.fn(), reconcile: vi.fn(), control: vi.fn(),
}));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request, nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile,
  },
}));
vi.mock('./NativeTeaching', () => ({
  useTeachingState: () => ({ ready: true, session: null }), writeTeachingControl: native.control,
}));

beforeEach(() => {
  native.state = {
    snapshot: { actor: { id: 'actor' }, plans: [], lessons: [], runs: [], turns: [], delivery_tasks: [],
      packs: [], gates: [], remediations: [], python_attempts: [], program_attempts: [], transfers: [], supply_demands: [] },
    epoch: 1, pending: [],
  };
  native.write.mockReset().mockResolvedValue({});
  native.request.mockReset().mockResolvedValue([]);
  native.reconcile.mockReset().mockResolvedValue({});
  native.control.mockReset().mockResolvedValue({});
});
afterEach(cleanup);

test('course planning uses the real request and original key read without automatically confirming', async () => {
  render(<NativeCourse conversationId="conversation" goalId="goal" />);
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('textbox', { name: '本次路线要求' }), { target: { value: '从SQL过滤与聚合开始学习' } });
  fireEvent.click(screen.getByRole('button', { name: '准备路线草稿' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/conversations/conversation/plan-requests');
  expect(body).toMatchObject({ text: '从SQL过滤与聚合开始学习', expected_revision: 0, focus: { kind: 'goal' } });
  expect(options.lookup).toBe(`/v1/conversations/conversation/turn-requests/${options.key}`);
});

test('course confirmation reads immutable revision facts and lesson requests bind the chosen node', async () => {
  const revision = {
    revision: 3, document: {
      title: 'SQL路线', summary: '按查询目标逐步学习', assumptions: [],
      nodes: [{ key: 'aggregation', title: '分组聚合', objective: '按类别计算汇总', estimated_minutes: 30, prerequisite_keys: [] }],
    },
  };
  native.state.snapshot.plans = [{ id: 'plan', goal_id: 'goal', latest: revision, active: null }];
  const view = render(<NativeCourse conversationId="conversation" goalId="goal" />);
  fireEvent.click(screen.getByRole('button', { name: '明确确认修订 3' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toEqual({ expected_revision: 3 });
  expect(native.write.mock.calls[0][2].lookup).toBe('/v1/plans/plan/confirmations/3');
  native.state.snapshot.plans[0].active = revision;
  view.rerender(<NativeCourse conversationId="conversation" goalId="goal" />);
  fireEvent.click(screen.getByRole('button', { name: '1. 分组聚合' }));
  fireEvent.change(screen.getByRole('textbox', { name: '这节课希望重点讲解什么' }), { target: { value: '解释分组键与SUM的关系' } });
  fireEvent.click(screen.getByRole('button', { name: '准备节点课时' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(2));
  expect(native.write.mock.calls[1][0]).toBe('/v1/plans/plan/lesson-requests');
  expect(native.write.mock.calls[1][1]).toEqual({
    expected_plan_revision: 3, node_key: 'aggregation', instruction: '解释分组键与SUM的关系',
  });
  expect(native.write.mock.calls[1][2].lookup).toBe(
    `/v1/conversations/conversation/turn-requests/${native.write.mock.calls[1][2].key}`,
  );
});

test('review artifacts stay in their conversation and submit actual three-rating receipts', async () => {
  native.request.mockResolvedValue([{
    kind: 'memory_review', id: 'review', goal_id: 'goal', card_id: 'card', card_revision: 7,
    conversation_id: 'conversation', state: 'presented', created_at: '2026-11-07T00:00:00Z',
    presented_at: '2026-11-07T00:00:00Z', source_receipt: null,
    card: { id: 'card', revision: 7, due: true, status: 'scheduled', prompt: '解释GROUP BY的作用', next_due_at: '2026-11-07T00:00:00Z' },
  }, {
    id: 'other', goal_id: 'other', conversation_id: 'other', state: 'presented',
    card: { prompt: '其他会话问题' },
  }]);
  render(<NativeReviews conversationId="conversation" goalId="goal" />);
  await screen.findByText('解释GROUP BY的作用');
  expect(screen.queryByText('其他会话问题')).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '想起来了' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/review-activities/review/responses');
  expect(body).toEqual({ expected_revision: 7, rating: 'good' });
  expect(options.lookup).toBe(`/v1/review-activities/review/commands/${options.key}`);
});

test('proactive preference is explicit and preserves the command receipt lookup', async () => {
  native.request.mockResolvedValue(null);
  native.write.mockResolvedValue({ revision: 1, enabled: true, timezone: 'UTC', start_minute: 540, end_minute: 1260 });
  render(<NativeReviewPreferences conversationId="conversation" />);
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText('允许本会话主动提示'));
  fireEvent.click(screen.getByRole('button', { name: '保存安排' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/conversations/conversation/proactive-preference');
  expect(body).toMatchObject({ expected_revision: 0, enabled: true });
  expect(options.lookup).toBe(`/v1/conversations/conversation/proactive-preference/commands/${options.key}`);
});
