import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { NativeStart } from './NativeLearning';

const native = vi.hoisted(() => ({ state: {} as any, request: vi.fn(), write: vi.fn(), reconcile: vi.fn() }));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(), nativeRequest: native.request,
  nativeStore: { subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile },
}));
vi.mock('react-router-dom', () => ({ useParams: () => ({}), useNavigate: () => vi.fn() }));
beforeEach(() => {
  sessionStorage.clear();
  native.state = { snapshot: { actor: { id: 'actor' }, goals: [], jobs: [] }, pending: [], epoch: 1 };
  native.write.mockReset().mockResolvedValue({ job_id: 'job' });
  native.reconcile.mockReset().mockResolvedValue({ job_id: 'job' });
});
afterEach(cleanup);
const authorize = () => {
  fireEvent.click(screen.getByText('科目与学习材料（可选）'));
  fireEvent.click(screen.getByRole('checkbox', { name: '指定课程科目并允许自动获取公开学习材料' }));
};

test('new native goals keep the public material scope separate from the explicit subject', async () => {
  render(<NativeStart />);
  fireEvent.change(screen.getByRole('textbox', { name: '新增学习目标' }), { target: { value: '学习关系数据的分组统计' } });
  authorize();
  expect((screen.getByRole('button', { name: '保存目标' }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('textbox', { name: '课程语言或科目（必填）' }) as HTMLInputElement).value).toBe('');
  fireEvent.change(screen.getByRole('textbox', { name: '课程语言或科目（必填）' }), { target: { value: 'SQL' } });
  fireEvent.change(screen.getByRole('textbox', { name: '指定框架版本（可选）' }), { target: { value: '3.46' } });
  expect((screen.getByRole('button', { name: '保存目标' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByRole('textbox', { name: '指定框架（可选）' }), { target: { value: 'SQLite' } });
  fireEvent.click(screen.getByRole('button', { name: '保存目标' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const [path, body, options] = native.write.mock.calls[0];
  expect(path).toBe('/v1/goals');
  expect(body.material_scope).toEqual({
    contract: 'goal-material-scope.v1', language: 'SQL', language_version: null,
    framework: 'SQLite', framework_version: '3.46', authorized_official_sources: true,
    authorized_public_sources: true,
  });
  expect(options.lookup).toBe(`/v1/goal-requests/${options.key}`);
  await waitFor(() => expect((screen.getByRole('textbox', { name: '新增学习目标' }) as HTMLInputElement).value).toBe(''));
  fireEvent.change(screen.getByRole('textbox', { name: '新增学习目标' }), { target: { value: '下一个不指定科目的目标' } });
  fireEvent.click(screen.getByRole('button', { name: '保存目标' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(2));
  expect(native.write.mock.calls[1][1]).toEqual({ title: '下一个不指定科目的目标', motivation: '' });
});

test('an unknown native goal restores the original draft and scope while only its original receipt can reconcile', async () => {
  native.write.mockImplementation(async (path: string, _body: object, options: { key: string }) => {
    native.state = { ...native.state, pending: [{ key: options.key, path, status: 'unknown' }] };
    throw new Error('原响应未知');
  });
  const first = render(<NativeStart />);
  fireEvent.change(screen.getByRole('textbox', { name: '新增学习目标' }), { target: { value: '保留这次明确的课程科目' } });
  authorize();
  fireEvent.change(screen.getByRole('textbox', { name: '课程语言或科目（必填）' }), { target: { value: 'Go' } });
  fireEvent.click(screen.getByRole('button', { name: '保存目标' }));
  await screen.findByText('原响应未知');
  const original = native.write.mock.calls[0][2].key;
  first.unmount();
  render(<NativeStart />);
  expect((screen.getByRole('textbox', { name: '新增学习目标' }) as HTMLInputElement).value).toBe('保留这次明确的课程科目');
  fireEvent.click(screen.getByText('科目与学习材料（可选）'));
  expect((screen.getByRole('textbox', { name: '课程语言或科目（必填）' }) as HTMLInputElement).value).toBe('Go');
  expect((screen.getByRole('button', { name: '保存目标' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '读取原目标回执' }));
  await waitFor(() => expect(native.reconcile).toHaveBeenCalledWith(original));
  expect(native.write).toHaveBeenCalledTimes(1);
});
