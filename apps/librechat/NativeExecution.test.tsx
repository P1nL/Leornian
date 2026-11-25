import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeExecution from './NativeExecution';

const native = vi.hoisted(() => ({
  state: {} as any, request: vi.fn(), write: vi.fn(), reconcile: vi.fn(),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile,
  },
}));
const requirement = {
  recipe_id: 'javascript-standard.v1', recipe_revision: 1,
  profile: 'project-stdio.v1', language: 'javascript', dialect: null,
  title: 'JavaScript 受控项目', toolchains: ['Node.js 22'], dependency_lock: [],
  sources: ['https://mcr.microsoft.com'], version_policy: 'family and exact release',
  services: [], estimated_download_bytes: null, estimated_disk_bytes: null,
};
function demand() {
  return {
    id: 'demand', local_scope: 'this-device.v1', plan_id: null, plan_revision: null,
    requirement_revision: 4, decision_revision: 2, decision: null,
    status: 'waiting_authorization', requirement, release: null, error_code: null,
  };
}
let overview: any;
beforeEach(() => {
  native.state = {
    snapshot: {
      actor: { id: 'owner' },
      plans: [{ id: 'plan', active: { revision: 7, document: { title: '当前路线' } } }],
    },
    pending: [],
  };
  overview = {
    application_status: 'ready',
    engine: { status: 'ready', detail: '本机引擎已就绪', version: '29.8.0', operating_system: 'linux' },
    recipes: [requirement], demands: [],
  };
  native.request.mockReset().mockImplementation(async () => structuredClone(overview));
  native.write.mockReset().mockResolvedValue({ id: 'recorded' });
  native.reconcile.mockReset().mockResolvedValue({ id: 'original' });
});
afterEach(() => {
  cleanup();
  delete (window as any).__TAURI_INTERNALS__;
});

test('opening execution shows three distinct states without installing a course environment', async () => {
  render(<NativeExecution />);
  await screen.findByText('本机引擎已就绪');
  expect(screen.getByText('应用后台')).toBeTruthy();
  expect(screen.getByText('课程环境')).toBeTruthy();
  expect(screen.getByText(/尚未登记环境需求/)).toBeTruthy();
  expect(native.write).not.toHaveBeenCalled();
});

test('a new requirement keeps the confirmed plan revision and has an original request receipt', async () => {
  render(<NativeExecution />);
  await screen.findByText('本机引擎已就绪');
  fireEvent.click(screen.getByRole('button', { name: '为真实路线或本机基础学习登记环境需求' }));
  fireEvent.change(screen.getByLabelText('受控环境配方'), { target: { value: requirement.recipe_id } });
  fireEvent.change(screen.getByLabelText('使用范围'), { target: { value: 'plan' } });
  fireEvent.click(screen.getByRole('button', { name: '登记需求并查看授权' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/environment-demands');
  expect(body).toEqual({
    recipe_id: requirement.recipe_id, plan_id: 'plan', plan_revision: 7,
    expected_requirement_revision: 0,
  });
  expect(options).toEqual({ key: expect.any(String), lookup: `/v1/environment-demand-requests/${options.key}` });
  expect(body.decision).toBeUndefined();
});

test.each([
  ['允许并准备', 'allow'], ['稍后', 'defer'], ['拒绝', 'decline'], ['撤销', 'revoke'],
])('explicit %s preserves both CAS revisions and its read-only receipt', async (label, decision) => {
  overview.demands = [{ ...demand(), decision: decision === 'revoke' ? 'allow' : null }];
  render(<NativeExecution />);
  await screen.findByRole('heading', { name: 'JavaScript 受控项目' });
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: label }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/environment-demands/demand/decisions');
  expect(body).toEqual({ decision, expected_requirement_revision: 4, expected_decision_revision: 2 });
  expect(options.lookup).toBe(`${path}/${options.key}`);
});

test('unknown submission blocks new environment writes and only reconciles its original key', async () => {
  overview.demands = [demand()];
  native.state.pending = [{
    path: '/v1/environment-demands/demand/decisions', key: 'original-key', status: 'unknown',
  }];
  render(<NativeExecution />);
  await screen.findByRole('heading', { name: 'JavaScript 受控项目' });
  expect((screen.getByRole('button', { name: '允许并准备' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '核对原提交' }));
  await waitFor(() => expect(native.reconcile).toHaveBeenCalledWith('original-key'));
  expect(native.write).not.toHaveBeenCalled();
});

test('native engine guidance is an explicit fixed action rather than a course installation', async () => {
  const invoke = vi.fn().mockImplementation(async (_command: string, { action }: { action: string }) =>
    action === 'status'
      ? { application: 'ready', controller: 'running', frontend: 'running', engine: overview.engine }
      : { opened: true });
  Object.defineProperty(window, '__TAURI_INTERNALS__', {
    value: { invoke }, configurable: true, writable: true,
  });
  render(<NativeExecution />);
  await screen.findByText('本机引擎已就绪');
  fireEvent.click(screen.getByRole('button', { name: '查看官方安装说明' }));
  await waitFor(() => expect(invoke).toHaveBeenCalledWith('local_services', { action: 'engine_guide' }));
  expect(native.write).not.toHaveBeenCalled();
});
