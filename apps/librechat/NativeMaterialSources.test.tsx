import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeMaterialSources from './NativeMaterialSources';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), write: vi.fn(), reconcile: vi.fn(),
  sources: [] as any[], observation: {} as any,
}));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request, nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile,
  },
}));
const source = {
  id: 'source', revision: 2, goal_id: 'goal', title: '明确批准的教程',
  entry_url: 'https://docs.example.org/tutorial/start',
  allowed_prefixes: ['https://docs.example.org/tutorial/'], admission: 'allowed',
  purposes: ['reference', 'indexing', 'planning'], use_until: null, retain_until: null,
};
beforeEach(() => {
  localStorage.clear();
  native.state = { snapshot: { actor: { id: 'owner' } }, pending: [], epoch: 1 };
  native.sources = [];
  native.observation = {
    id: 'observation', source_id: 'source', status: 'queued', job_id: null,
    document_id: null, document_revision: null,
  };
  native.request.mockReset().mockImplementation(async (path: string) => {
    if (path === '/v1/material-sources?goal_id=goal') return [...native.sources];
    if (path === '/v1/material-source-observations/observation') return { ...native.observation };
    throw new Error(`Unexpected source read ${path}`);
  });
  native.write.mockReset().mockImplementation(async (path: string) => {
    if (path === '/v1/material-sources') { native.sources = [source]; return source; }
    if (path.endsWith('/revoke')) {
      native.sources = [{ ...source, revision: 3, admission: 'revoked' }];
      return native.sources[0];
    }
    return { ...native.observation };
  });
  native.reconcile.mockReset().mockResolvedValue(native.observation);
});
afterEach(cleanup);

test('a source registers only explicit URL scope and permissions without inventing language versions', async () => {
  render(<NativeMaterialSources goalId="goal" />);
  await waitFor(() => expect(native.request).toHaveBeenCalled());
  fireEvent.click(screen.getByText('登记可读取的教材来源'));
  fireEvent.change(screen.getByLabelText('来源名称'), { target: { value: source.title } });
  fireEvent.change(screen.getByLabelText('原文入口 URL'), { target: { value: source.entry_url } });
  fireEvent.change(screen.getByLabelText('允许读取的 URL 前缀（每行一个，最多20个）'), {
    target: { value: source.allowed_prefixes[0] },
  });
  expect(screen.getByRole('button', { name: '登记来源授权' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('checkbox', { name: '学习路线' }));
  fireEvent.click(screen.getByRole('checkbox', { name: /我有权使用该来源/ }));
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '登记来源授权' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/material-sources');
  expect(body).toMatchObject({
    goal_id: 'goal', title: source.title, entry_url: source.entry_url,
    allowed_prefixes: source.allowed_prefixes, authorized_use: true,
    purposes: ['reference', 'indexing', 'planning'], discover_links: false,
    language: null, language_version: null, framework: null, framework_version: null,
    use_until: null, retain_until: null,
  });
  expect(options.lookup).toBe(`/v1/material-sources/commands/${options.key}`);
  await screen.findByText('明确批准的教程 · 已授权来源');
  expect(native.write).toHaveBeenCalledTimes(1);
});

test('checking and revoking use exact revisions and keep observation progress separate from readiness', async () => {
  native.sources = [source];
  render(<NativeMaterialSources goalId="goal" />);
  fireEvent.click(await screen.findByRole('button', { name: '检查来源更新' }));
  await screen.findByText('来源检查：等待检查');
  expect(native.write.mock.calls[0][0]).toBe('/v1/material-sources/source/checks');
  expect(native.write.mock.calls[0][1]).toEqual({ expected_revision: 2 });
  expect(native.write.mock.calls[0][2].lookup).toBe(
    `/v1/material-sources/source/checks/${native.write.mock.calls[0][2].key}`,
  );
  expect(screen.queryByText(/已准备合格/)).toBeNull();
  expect(screen.getByRole('button', { name: '检查来源更新' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '撤销此来源授权' }));
  await screen.findByText('明确批准的教程 · 已撤销来源授权');
  expect(native.write.mock.calls[1][1]).toEqual({ expected_revision: 2 });
  expect(native.write.mock.calls[1][2].lookup).toBe('/v1/material-sources/source/revocation');
});

test('an unknown original check reconciles only its stored receipt and never submits another check', async () => {
  native.sources = [source];
  native.write.mockImplementation(async (path, body, options) => {
    native.state = { ...native.state, pending: [{ path, body, key: options.key, lookup: options.lookup }] };
    throw new Error('原检查回执中断');
  });
  native.observation.status = 'blocked_unknown';
  native.reconcile.mockImplementation(async () => {
    native.state = { ...native.state, pending: [] };
    return { ...native.observation };
  });
  const shown = render(<NativeMaterialSources goalId="goal" />);
  fireEvent.click(await screen.findByRole('button', { name: '检查来源更新' }));
  await screen.findByText('原检查回执中断');
  shown.rerender(<NativeMaterialSources goalId="goal" />);
  fireEvent.click(screen.getByRole('button', { name: '读取原来源命令回执' }));
  await screen.findByText('来源检查：原结果未知，保留原检查');
  expect(native.reconcile).toHaveBeenCalledWith(native.write.mock.calls[0][2].key);
  expect(native.write).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: '检查来源更新' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '读取原来源检查' }));
  await waitFor(() => expect(native.request).toHaveBeenCalledWith('/v1/material-source-observations/observation'));
  expect(native.write).toHaveBeenCalledTimes(1);
});
