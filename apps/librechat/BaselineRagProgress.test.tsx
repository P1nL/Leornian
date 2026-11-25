import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import BaselineRagProgress from './BaselineRagProgress';

const native = vi.hoisted(() => ({ request: vi.fn(), state: {} as any }));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request,
  nativeStore: { subscribe: () => () => {}, getSnapshot: () => native.state },
}));
beforeEach(() => {
  native.state = { snapshot: { actor: { id: 'actor' } }, epoch: 1 };
  native.request.mockReset();
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

test('the panel shows the current preparation stage and a collapsible waiting reason', async () => {
  native.request.mockResolvedValue({
    demand_id: 'demand', status: 'waiting_dependency', reason_code: 'html_nontext_content_pending',
    steps: [
      { key: 'sources', status: 'completed' }, { key: 'acquisition', status: 'completed' },
      { key: 'parsing', status: 'waiting' }, { key: 'embedding', status: 'pending' },
    ],
    documents: [],
  });
  const view = render(<BaselineRagProgress conversationId="conversation" />);
  const heading = await screen.findByRole('button', { name: '资料待补齐' });
  expect(screen.getByText('正文中有需要进一步识别的图文内容。')).toBeTruthy();
  expect(view.container.querySelector('[aria-current="step"]')?.textContent).toContain('解析与整理');
  fireEvent.click(heading);
  expect(heading.getAttribute('aria-expanded')).toBe('false');
  expect(screen.queryByRole('list', { name: '资料准备流程' })).toBeNull();
});

test('switching conversations aborts stale progress and completion is shown without a timer', async () => {
  let finish: (value: unknown) => void = () => {};
  native.request.mockImplementation((path: string) => path.includes('/old/')
    ? new Promise((resolve) => { finish = resolve; })
    : Promise.resolve({ demand_id: 'new', status: 'ready', steps: [], documents: [] }));
  const view = render(<BaselineRagProgress conversationId="old" />);
  await waitFor(() => expect(native.request).toHaveBeenCalledOnce());
  const signal = native.request.mock.calls[0][1].signal;
  view.rerender(<BaselineRagProgress conversationId="new-conversation" />);
  expect(signal.aborted).toBe(true);
  await screen.findByText('资料准备完成');
  finish({ demand_id: 'old', status: 'blocked_unknown', steps: [], documents: [] });
  await waitFor(() => expect(screen.queryByText('处理结果待确认')).toBeNull());
  expect(native.request).toHaveBeenCalledTimes(2);
});

test('current dependencies and background documents have separate counts and a real waiting step', async () => {
  native.request.mockResolvedValue({
    demand_id: 'demand', status: 'blocked_unknown', reason_code: 'external_result_unknown',
    current_documents: 2, ready_documents: 2,
    background_documents: 9, background_ready_documents: 7,
    steps: [{ key: 'indexing', status: 'completed', completed: 2, total: 2 },
      { key: 'retrieval', status: 'unknown', completed: 0, total: 2 }],
    documents: [],
  });
  const view = render(<BaselineRagProgress conversationId="conversation" />);
  await screen.findByText('处理结果待确认');
  expect(screen.getByText('本轮资料')).toBeTruthy();
  expect(screen.getByText('2 / 2 份就绪')).toBeTruthy();
  expect(screen.getByText('后台资料')).toBeTruthy();
  expect(screen.getByText('7 / 9 份就绪')).toBeTruthy();
  expect(view.container.querySelector('[aria-current="step"]')?.textContent).toContain('核对本次证据');
});

test('technical work counts are available in details while the main flow stays concise', async () => {
  native.request.mockResolvedValue({
    status: 'processing',
    steps: [
      { key: 'embedding', status: 'completed', completed: 135, total: 135, unit: 'chunks' },
      { key: 'retrieval', status: 'running', completed: 0, total: 1, unit: 'checks', level: 1 },
    ],
    documents: [],
  });
  const view = render(<BaselineRagProgress conversationId="conversation" />);
  const flow = await screen.findByRole('list', { name: '资料准备流程' });
  expect(within(flow).queryByText('生成向量')).toBeNull();
  expect(view.container.querySelector('details')?.open).toBe(false);
  fireEvent.click(screen.getByText('查看处理详情'));
  expect(view.container.querySelector('details')?.open).toBe(true);
  expect(screen.getByText('135 / 135 个片段')).toBeTruthy();
  expect(screen.getByText('0 / 1 组 · 第 1 层汇总')).toBeTruthy();
});

test('ready documents and unavailable sources do not imply evidence is sufficient', async () => {
  native.request.mockResolvedValue({
    status: 'waiting_dependency', preparation: 'complete', reason_code: 'source_http_unavailable',
    current_documents: 2, ready_documents: 2, background_documents: 0,
    steps: [
      { key: 'sources', status: 'completed', completed: 4, total: 4 },
      { key: 'acquisition', status: 'waiting', completed: 2, total: 4 },
      ...['parsing', 'ocr', 'quality', 'chunking', 'indexing'].map((key) =>
        ({ key, status: 'pending', completed: 2, total: 4 })),
      { key: 'embedding', status: 'pending', completed: 88, total: 88, unit: 'chunks' },
      { key: 'retrieval', status: 'waiting', completed: 1, total: 1, unit: 'checks' },
    ],
    documents: [],
  });
  const view = render(<BaselineRagProgress conversationId="conversation" />);
  await screen.findByText('资料待补齐');
  const flow = screen.getByRole('list', { name: '资料准备流程' });
  const groups = within(flow).getAllByRole('listitem');
  expect(groups).toHaveLength(3);
  expect(groups[0].textContent).toContain('已获取 2 / 4 项');
  expect(groups[1].textContent).toContain('已完成');
  expect(groups[2].textContent).toContain('已检查 1 / 1 组');
  expect(groups[2].textContent).toContain('待继续');
  expect(screen.getByText('资料已就绪，仍需确认是否满足本次需求。')).toBeTruthy();
  expect(screen.getByText('部分来源暂不可访问，已就绪资料会保留。')).toBeTruthy();
  expect(view.container.textContent).not.toContain('按退避计划重试');
  expect(view.container.textContent).not.toContain('检查完整路线的资料覆盖');
});

test('cancelled processing has a stopped state and no active spinner', async () => {
  native.request.mockResolvedValue({
    status: 'cancelled', steps: [{ key: 'acquisition', status: 'cancelled', completed: 0, total: 1 }],
    documents: [],
  });
  const view = render(<BaselineRagProgress conversationId="conversation" />);
  await screen.findByText('资料处理已停止');
  expect(view.container.querySelector('.baseline-rag-spinner')).toBeNull();
  expect(view.container.querySelector('[aria-current="step"]')).toBeNull();
});
