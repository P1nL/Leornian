import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { NativeDemo } from './NativeDemo';
import { initialCompositionDraftV2 } from './composition-v2-runtime.mjs';

afterEach(cleanup);
const definition = {
  schema_version: 'learning_composition.v2', title: '分步演示', layout: 'stack',
  states: { cursor: { type: 'playback' } },
  components: [{ id: 'player', component: 'StepPlayer', props: {
    label: '观察步骤', state: 'cursor', items: ['准备', '比较', '结束'],
  } }],
} as const;

function props(state: 'ready' | 'started' | 'acknowledged' | 'completed' = 'started') {
  return {
    definition: definition as any, draft: initialCompositionDraftV2(definition),
    blocked: false, onCommand: vi.fn(),
    demo: {
      component_id: 'player', profile_version: 'demo-report.v1', event: 'timeline_end',
      state, generation: 1, nonce: 'exact-server-nonce', sequence: state === 'acknowledged' ? 1 : 0,
      inputs: {}, last_step: 2, completions: [],
      allowed_actions: state === 'ready' ? ['start_demo'] : state === 'started'
        ? ['start_demo', 'acknowledge_demo_event'] : state === 'acknowledged'
          ? ['start_demo', 'complete_demo'] : ['start_demo'],
    } as any,
  };
}

test('only explicit start reports current inputs; mount and refresh never post', () => {
  const value = props('ready'), shown = render(<NativeDemo {...value} />);
  expect(value.onCommand).not.toHaveBeenCalled();
  shown.rerender(<NativeDemo {...value} />);
  expect(value.onCommand).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '为当前输入重新记录' }));
  expect(value.onCommand).toHaveBeenCalledWith({
    action: 'start_demo', component_id: 'player', inputs: {},
  });
});

test('endpoint report and browsing completion are separate pinned user actions', () => {
  const value = props(), shown = render(<NativeDemo {...value} />);
  expect((screen.getByRole('button', { name: '登记当前末步' }) as HTMLButtonElement).disabled).toBe(true);
  value.draft = { ...value.draft, values: { cursor: 2 } };
  shown.rerender(<NativeDemo {...value} />);
  fireEvent.click(screen.getByRole('button', { name: '登记当前末步' }));
  expect(value.onCommand).toHaveBeenCalledWith({
    action: 'acknowledge_demo_event', component_id: 'player', generation: 1,
    nonce: 'exact-server-nonce', sequence: 1, event: 'timeline_end', step_index: 2,
  });
  const next = { ...value, demo: props('acknowledged').demo };
  shown.rerender(<NativeDemo {...next} />);
  expect(value.onCommand).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: '我已浏览，记录完成' }));
  expect(value.onCommand).toHaveBeenLastCalledWith({
    action: 'complete_demo', component_id: 'player', generation: 1,
    nonce: 'exact-server-nonce', sequence: 2,
  });
});

test('changed preview draft requires a new generation and actual matching preview snapshot', () => {
  const value = props(), preview = {
    schema_version: 'learning_composition.v2', title: '隔离预览', layout: 'stack',
    states: { html: { type: 'code', value: '<p>old</p>' }, css: { type: 'code', value: '' } },
    components: [{ id: 'player', component: 'IsolatedPreview', props: {
      title: '预览', html_state: 'html', css_state: 'css',
    } }],
  } as any;
  value.definition = preview;
  value.demo = { ...value.demo, event: 'preview_snapshot', inputs: { html: '<p>new</p>', css: '' }, last_step: null };
  value.draft = initialCompositionDraftV2(preview);
  value.draft.values.html = '<p>new</p>';
  const shown = render(<NativeDemo {...value} />);
  expect((screen.getByRole('button', { name: '登记当前预览' }) as HTMLButtonElement).disabled).toBe(true);
  value.draft.previews.player = { html: '<p>new</p>', css: '' };
  shown.rerender(<NativeDemo {...value} />);
  expect((screen.getByRole('button', { name: '登记当前预览' }) as HTMLButtonElement).disabled).toBe(false);
  value.draft.values.html = '<p>third</p>';
  shown.rerender(<NativeDemo {...value} />);
  expect((screen.getByRole('button', { name: '登记当前预览' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/输入已改变/)).toBeTruthy();
  expect(value.onCommand).not.toHaveBeenCalled();
});

test.each(['ready', 'started', 'acknowledged', 'completed'] as const)(
  'pending, cancelled or unknown host blocks %s writes without changing drafts', (state) => {
    const value = props(state);
    const before = JSON.stringify(value.draft);
    render(<NativeDemo {...value} blocked />);
    for (const button of screen.getAllByRole('button')) {
      if ((button as HTMLButtonElement).disabled) fireEvent.click(button);
    }
    expect(value.onCommand).not.toHaveBeenCalled();
    expect(JSON.stringify(value.draft)).toBe(before);
  },
);

test('older input history loads only by explicit read and never becomes a write or draft', async () => {
  const value = props('completed');
  const fact = (generation: number) => ({
    id: `completion-${generation}`, generation, inputs: {},
    completed_at: '2026-11-06T03:00:00Z',
  });
  value.demo = {
    ...value.demo, completion_count: 6, completions: [fact(6)],
    next_completion_before: 6,
  };
  const onHistory = vi.fn().mockResolvedValue({
    items: [fact(5), fact(4), fact(3), fact(2), fact(1)], next_before: null,
  });
  render(<NativeDemo {...value} onHistory={onHistory} />);
  fireEvent.click(screen.getByRole('button', { name: '浏览确认 · 6 次' }));
  expect(onHistory).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '加载更早浏览记录' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: '加载更早浏览记录' })).toBeNull());
  expect(onHistory).toHaveBeenCalledWith(6);
  expect(screen.getByText(/第 1 次记录/)).toBeTruthy();
  expect(value.onCommand).not.toHaveBeenCalled();
  expect(value.draft.values.cursor ?? 0).toBe(0);
});
