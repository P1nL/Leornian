import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeMessageExtras from './NativeMessageExtras';

const native = vi.hoisted(() => ({ state: { snapshot: null as any } }));
vi.mock('./NativeLearning', () => ({
  useNative: () => native.state,
  NativeArtifacts: ({ messageId }: { messageId: string }) => <section data-artifact-turn={messageId}>原工件</section>,
}));
beforeEach(() => { native.state = { snapshot: null }; });
afterEach(cleanup);

test('checked artifacts remain alongside the message regardless of its thinking and text parts', () => {
  render(<NativeMessageExtras message={{ messageId: 'turn:assistant', isCreatedByUser: false }} />);
  expect(document.querySelectorAll('[data-artifact-turn="turn:assistant"]')).toHaveLength(1);
  expect(screen.queryByRole('status')).toBeNull();
});

test('an empty response displays the real input requirement without inventing model prose', () => {
  render(<NativeMessageExtras message={{
    messageId: 'turn:assistant', isCreatedByUser: false,
    leornianOutcome: { status: 'waiting_input', message: '本轮回复等待补充信息，尚未交付正文。',
      requiredInput: ['请补充输入范围。'], errorCode: 'delivery_needs_input' },
  }} />);
  expect(screen.getByRole('status').textContent).toBe('本轮回复等待补充信息，尚未交付正文。');
  expect(screen.getByText('请补充输入范围。')).toBeTruthy();
  expect(screen.getByText('任务代码：delivery_needs_input')).toBeTruthy();
  expect(document.querySelector('[data-reply-outcome="waiting_input"]')).toBeTruthy();
});

test('user messages never acquire assistant artifacts or outcome notices', () => {
  render(<NativeMessageExtras message={{ messageId: 'turn:user', isCreatedByUser: true }} />);
  expect(screen.queryByText('原工件')).toBeNull();
  expect(screen.queryByRole('status')).toBeNull();
});

test('snapshot outcomes refresh even when the parent message text stays empty', async () => {
  const message = { messageId: 'turn:assistant', isCreatedByUser: false };
  const snapshot = {
    turns: [{ turns: [{ id: 'turn', assistant_text: null }] }],
    runs: [{ id: 'run', turn_id: 'turn', status: 'failed' }],
    delivery_tasks: [{ run_id: 'run', status: 'waiting_input', required_input: ['补充输入。'] }],
  };
  native.state.snapshot = snapshot;
  const shown = render(<NativeMessageExtras message={message} />);
  expect(screen.getByText('补充输入。')).toBeTruthy();
  native.state.snapshot = { ...snapshot, delivery_tasks: [{ run_id: 'run', status: 'cancelled' }] };
  shown.rerender(<NativeMessageExtras message={message} />);
  await waitFor(() => expect(screen.getByRole('status').textContent).toBe('本轮回复已取消，没有已交付的正文。'));
  expect(screen.queryByText('补充输入。')).toBeNull();
});
