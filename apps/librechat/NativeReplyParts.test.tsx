import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeReplyParts from './NativeReplyParts';
import NativePlanAction from './NativePlanAction';
import type { ThinkingStep } from './NativeThinking';

const native = vi.hoisted(() => ({ state: {} as any, request: vi.fn(), refresh: vi.fn() }));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state, refresh: native.refresh,
  },
}));
vi.mock('./NativeLearning', () => ({
  useNative: () => native.state,
  NativeArtifacts: ({ messageId }: { messageId: string }) => <div data-artifact-turn={messageId}>
    <NativePlanAction conversationId="conversation" turnId={messageId.replace(/:assistant$/, '')} />
  </div>,
}));
vi.unmock('./NativeReplyParts');
vi.unmock('./NativeThinking');
vi.mock('~/components/Chat/Messages/Content/Parts/Thinking', () => ({
  ThinkingButton: ({ isExpanded, onClick, label, contentId }: any) =>
    <button aria-expanded={isExpanded} aria-controls={contentId} onClick={onClick}>{label}</button>,
}));
vi.mock('~/components/Chat/Messages/Content/Markdown', () => ({
  default: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock('~/Providers/MessagePartsHostContext', () => ({
  appMessagePartsHost: {},
  MessagePartsHostProvider: ({ children }: { children: React.ReactNode }) => children,
}));
beforeEach(() => {
  sessionStorage.clear();
  native.state = { pending: [], snapshot: { runs: [], turns: [] } };
});
afterEach(cleanup);

test('waiting for model thinking is a status, not an expandable placeholder', () => {
  render(<NativeReplyParts turnId="turn" conversationId="conversation"
    reasoning="" text="" generating status="正在整理学习目标与路线要求。" />);
  expect(screen.getByRole('status').textContent).toBe('正在整理学习目标与路线要求。');
  expect(screen.queryByRole('button')).toBeNull();
});

test('expansion receives actual filtered model text and updates as it streams', () => {
  const view = render(<NativeReplyParts turnId="turn" conversationId="conversation"
    reasoning="先了解学习基础。" text="" generating />);
  fireEvent.click(screen.getByRole('button', { name: /正在思考/ }));
  fireEvent.click(within(screen.getByRole('group', { name: '思考步骤' }))
    .getByRole('button', { name: /思考摘要/ }));
  const detail = screen.getByRole('region', { name: '思考摘要详情' });
  expect(within(detail).getByText('先了解学习基础。')).toBeTruthy();
  view.rerender(<NativeReplyParts turnId="turn" conversationId="conversation"
    reasoning="先了解学习基础。再安排循环与查找练习。" text="" generating />);
  expect(within(detail).getByText('先了解学习基础。再安排循环与查找练习。')).toBeTruthy();
  expect(screen.queryByRole('status')).toBeNull();
});

const thinking: ThinkingStep = {
  id: 'model-call', kind: 'thinking', title: '思考', summary: '确认学习基础',
  detail: '先确认已有知识，再安排新的概念。', status: 'running',
  started_at: '2026-11-09T10:00:00Z', completed_at: null, duration_ms: null, tool_name: null,
};
const tool: ThinkingStep = {
  id: 'tool-call', kind: 'tool', title: '读取学习文档', summary: '操作已完成。',
  detail: '工具：read_artifact；文档版本：2；文档章节数量：3。', status: 'completed',
  started_at: '2026-11-09T10:00:01Z', completed_at: '2026-11-09T10:00:02Z',
  duration_ms: 1000, tool_name: 'read_artifact',
};

test('outer disclosure shows real steps and each step expands independently during live updates', () => {
  const props = { actorId: 'owner', turnId: 'turn', conversationId: 'conversation',
    reasoning: '', text: '', generating: true };
  const view = render(<NativeReplyParts {...props} steps={[thinking, tool]} />);
  expect(screen.queryByRole('region')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: /正在思考… · 2 步/ }));
  const group = screen.getByRole('group', { name: '思考步骤' });
  expect(within(group).getAllByRole('button')).toHaveLength(2);
  expect(screen.queryByRole('region')).toBeNull();
  fireEvent.click(within(group).getByRole('button', { name: /确认学习基础/ }));
  fireEvent.click(within(group).getByRole('button', { name: /读取学习文档/ }));
  expect(screen.getByRole('region', { name: '思考详情' })).toBeTruthy();
  expect(screen.getByRole('region', { name: '读取学习文档详情' })).toBeTruthy();
  expect(screen.getByText('耗时 1.0 秒')).toBeTruthy();

  view.rerender(<NativeReplyParts {...props} steps={[
    { ...thinking, detail: `${thinking.detail}\n材料读取后补充练习目标。`, status: 'completed' },
    tool,
    { ...thinking, id: 'review', kind: 'review', title: '检查回复', summary: '检查内容与引用。', detail: '' },
  ]} />);
  expect(within(screen.getByRole('region', { name: '思考详情' }))
    .getByText(/材料读取后补充练习目标/)).toBeTruthy();
  expect(screen.getByRole('region', { name: '读取学习文档详情' })).toBeTruthy();
  expect(view.container.querySelectorAll('[data-thinking-step]')).toHaveLength(3);
});

test('disclosures survive live-to-history remounts but remain isolated by actor and turn', () => {
  const props = { actorId: 'owner', turnId: 'turn', conversationId: 'conversation',
    reasoning: '', text: '', generating: true, steps: [thinking] };
  const view = render(<NativeReplyParts {...props} />);
  fireEvent.click(screen.getByRole('button', { name: /正在思考/ }));
  fireEvent.click(screen.getByRole('button', { name: /确认学习基础/ }));
  view.unmount();
  const history = render(<NativeReplyParts {...props} generating={false}
    steps={[{ ...thinking, status: 'completed' }]} />);
  expect(screen.getByRole('region', { name: '思考详情' })).toBeTruthy();
  history.rerender(<NativeReplyParts {...props} actorId="other" />);
  expect(screen.queryByRole('region')).toBeNull();
  expect(screen.getByRole('button', { name: /正在思考/ }).getAttribute('aria-expanded')).toBe('false');
  history.rerender(<NativeReplyParts {...props} turnId="other-turn" />);
  expect(screen.queryByRole('region')).toBeNull();
});

test('body playback does not keep the earlier waiting-for-thinking status', () => {
  render(<NativeReplyParts turnId="turn" conversationId="conversation"
    reasoning="" text="已经通过检查的正文。" generating status="正在等待模型返回…" />);
  expect(screen.getByText('已经通过检查的正文。')).toBeTruthy();
  expect(screen.queryByRole('status')).toBeNull();
});

test('finished live replies render the same material repair control as message history', () => {
  native.state.snapshot.turns = [{ conversation_id: 'conversation', turns: [{
    id: 'turn', purpose: 'planning', completed_at: '2026-11-14T00:00:00Z',
    planning_state: { information_complete: true, missing_information: [],
      requirements_revision: 1, plan_requested: true, material_blocked: true },
  }] }];
  const view = render(<NativeReplyParts turnId="turn" conversationId="conversation"
    reasoning="" text="资料准备受阻，请使用修复并继续。" generating />);
  expect(screen.queryByRole('button', { name: '修复并继续' })).toBeNull();
  view.rerender(<NativeReplyParts turnId="turn" conversationId="conversation"
    reasoning="" text="资料准备受阻，请使用修复并继续。" generating={false} />);
  expect(screen.getByRole('button', { name: '修复并继续' })).toBeTruthy();
  expect(document.querySelectorAll('[data-artifact-turn="turn:assistant"]')).toHaveLength(1);
});
