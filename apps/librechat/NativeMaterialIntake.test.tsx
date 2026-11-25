import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeMaterialIntake from './NativeMaterialIntake';
import {
  continueMaterialFileUpload, materialCommandLookup, materialFileFormat, materialFileIssue, materialProgress, newMaterialFileJournal,
} from './native-material-upload.mjs';

const native = vi.hoisted(() => ({ state: {} as any, request: vi.fn(), write: vi.fn(), reconcile: vi.fn() }));
vi.mock('./native-client.mjs', () => ({
  nativeRequest: native.request, nativeStore: {
    subscribe: () => () => {}, getSnapshot: () => native.state,
    write: native.write, reconcile: native.reconcile,
  },
}));
beforeEach(() => {
  localStorage.clear();
  native.state = { snapshot: { actor: { id: 'actor' } }, epoch: 1, pending: [] };
  native.request.mockReset().mockImplementation(async (path: string) =>
    path.endsWith('/content') ? { id: 'upload', state: 'stored' } : []);
  native.write.mockReset().mockImplementation(async (path: string) => {
    if (path === '/v1/material-demands') return { id: 'demand', revision: 1 };
    if (path.endsWith('/uploads')) return { id: 'upload', state: 'pending' };
    return { id: 'job', state: 'queued' };
  });
  native.reconcile.mockReset();
});
afterEach(cleanup);

test('deferred background preparation remains distinct from an unresolved model result', () => {
  expect(materialProgress({ state: 'queued', background_deferred: true })).toContain('已暂停自动处理');
  expect(materialProgress({ state: 'blocked_unknown', background_deferred: true })).toContain('原处理结果未知');
});

async function choose() {
  const bytes = new TextEncoder().encode('same original bytes').buffer;
  const file = new File([bytes], 'SQL教材.pdf', { type: 'application/pdf' });
  render(<NativeMaterialIntake goalId="goal" />);
  fireEvent.change(screen.getByLabelText('原文件'), { target: { files: [file] } });
  fireEvent.click(screen.getByLabelText('节点课时'));
  fireEvent.click(screen.getByText('我有权使用该材料，并允许按所选用途处理、经本人配置的模型识别和索引。'));
  fireEvent.click(screen.getByRole('button', { name: '上传并准备原文' }));
  return bytes;
}

test('normal intake freezes whole original scope with explicit purposes and original command lookups', async () => {
  await choose();
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(3));
  const [demand, upload, job] = native.write.mock.calls;
  expect(demand[1]).toEqual({ goal_id: 'goal', purpose: 'reference', scope_mode: 'whole_source', required_facets: [] });
  expect(demand[2].lookup).toBe(`/v1/material-demands/commands/${demand[2].key}`);
  expect(upload[1].material).toMatchObject({ authorized_use: true, purposes: ['reference', 'indexing', 'lesson'], use_until: null, retain_until: null });
  expect(upload[1]).toMatchObject({ expected_demand_revision: 1, byte_size: 19 });
  expect(upload[2].lookup).toBe(`/v1/material-demands/demand/uploads/commands/${upload[2].key}`);
  const put = native.request.mock.calls.find(([path]) => path.endsWith('/content'));
  expect(put?.[1]).toMatchObject({ method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' } });
  expect(job[1]).toEqual({ expected_demand_revision: 1, upload_id: 'upload' });
  expect(job[2].lookup).toBe(`/v1/material-demands/demand/files/commands/${job[2].key}`);
  expect(localStorage.getItem('leornian.native.material-upload.v1:actor:goal')).toBeNull();
  expect(screen.queryByLabelText(/required_facets/)).toBeNull();
});

test('binary UNKNOWN keeps the exact upload ticket and only reads status before continuing', async () => {
  let stored = false;
  native.request.mockImplementation(async (path: string) => {
    if (path.endsWith('/content')) throw new Error('Network interrupted');
    if (path === '/v1/material-uploads/upload') return { id: 'upload', state: stored ? 'stored' : 'pending' };
    return [];
  });
  await choose();
  await screen.findByText('Network interrupted');
  const persisted = JSON.parse(localStorage.getItem('leornian.native.material-upload.v1:actor:goal')!);
  expect(persisted.stage).toBe('bytes_unknown');
  expect(persisted.upload.id).toBe('upload');
  fireEvent.click(screen.getByRole('button', { name: '读取原提交并继续' }));
  await screen.findByText('原文件上传尚未确认，保留原上传票据；稍后读取原状态。');
  expect(native.write).toHaveBeenCalledTimes(2);
  expect(native.request.mock.calls.filter(([path]) => path.endsWith('/content'))).toHaveLength(1);
  stored = true;
  fireEvent.click(screen.getByRole('button', { name: '读取原提交并继续' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(3));
  expect(native.write.mock.calls[2][1]).toEqual({ expected_demand_revision: 1, upload_id: 'upload' });
  expect(native.request.mock.calls.filter(([path]) => path.endsWith('/content'))).toHaveLength(1);
});

test('intake accepts only contracted formats and keeps each command lookup scope exact', () => {
  expect(materialFileFormat('chapter.DOCX')).toBe('docx');
  expect(materialFileFormat('scan.JPEG')).toBe('jpeg');
  expect(materialFileFormat('scan.png')).toBe('png');
  expect(materialFileIssue({ name: 'book.pdf', size: 20_000_001 })).toContain('20 MB');
  expect(materialFileIssue({ name: 'run.exe', size: 100 })).toContain('请选择');
  expect(materialCommandLookup({ stage: 'job_unknown', demand: { id: 'owned' }, keys: { job: 'original-key' } }))
    .toBe('/v1/material-demands/owned/files/commands/original-key');
});

test('direct composer upload resumes an unknown binary receipt without uploading the original bytes twice', async () => {
  const file = new File(['original chapter'], 'chapter.md');
  let journal: any = await newMaterialFileJournal(file, 'goal');
  native.request.mockImplementation(async (path: string) => {
    if (path.endsWith('/content')) throw new Error('Interrupted');
    return { id: 'upload', state: 'stored' };
  });
  const options = {
    actorId: 'actor', store: {
      getSnapshot: () => native.state, write: native.write, reconcile: native.reconcile,
    }, request: native.request, persist: (next: any) => { journal = next; },
  };
  await expect(continueMaterialFileUpload(file, journal, options)).rejects.toThrow('Interrupted');
  const originalKey = journal.keys.job;
  expect(journal.stage).toBe('bytes_unknown');
  await continueMaterialFileUpload(file, journal, options);
  expect(journal.stage).toBe('done');
  expect(native.request.mock.calls.filter(([path]) => path.endsWith('/content'))).toHaveLength(1);
  expect(native.write).toHaveBeenCalledTimes(3);
  expect(native.write.mock.calls[2][2].key).toBe(originalKey);
});
