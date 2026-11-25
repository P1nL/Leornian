import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import NativeModels, { NativeModelRoles, modelReady, newModelProfile, probeMetrics } from './NativeModels';
import { NativeApiError } from './native-client.mjs';

const native = vi.hoisted(() => ({
  state: { snapshot: { actor: { id: 'owner' } } },
  listeners: new Set<() => void>(), request: vi.fn(), refresh: vi.fn(),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: {
    subscribe: (listener: () => void) => { native.listeners.add(listener); return () => native.listeners.delete(listener); },
    getSnapshot: () => native.state, refresh: native.refresh,
  },
}));
const connection = {
  id: 'connection', revision: 3, label: '个人连接', protocol: 'chat_completions' as const,
  base_url: 'https://example.test/v1', region: 'custom', local_endpoint: false,
  enabled: true, deleted: false, credential_version: 1, credential_present: true, created_at: '2026-11-07T00:00:00Z',
};
const profile = {
  ...newModelProfile(connection), id: 'profile', revision: 4, label: '教学模型', model: 'model-a',
  enabled: true, allow_private_material: true, roles: ['tutor.v1', 'planner.v1'],
  context_tokens: 65536, max_output_tokens: 8192, created_at: '2026-11-07T00:00:00Z',
};
const second = { ...profile, id: 'second', revision: 2, label: '另一模型', model: 'model-b' };
let configuration: ReturnType<typeof baseConfiguration>;
let history: Record<string, unknown>[];
function baseConfiguration() {
  return {
    capabilities: ['explicit-role-assignment.v1', 'provider-presets.v1', 'provider-presets.v2', 'provider-presets.v3'],
    credential_storage: 'available', configuration_scope: 'user',
    presets: [
      { id: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com', region: 'global', models: ['deepseek-flash'],
        api_key_url: 'https://platform.deepseek.com/api_keys',
        model_details: [{ model: 'deepseek-flash', operation: 'chat', context_tokens: 1048576 }] },
      { id: 'qwen', label: '千问', base_url: 'https://dashscope.aliyuncs.com', region: 'cn-beijing',
        models: ['qwen-plus', 'qwen3.5-ocr', 'text-embedding-v4', 'qwen3-rerank'],
        model_details: [
          { model: 'qwen-plus', operation: 'chat', context_tokens: 1000000 },
          { model: 'qwen3.5-ocr', operation: 'ocr', context_tokens: 0 },
          { model: 'text-embedding-v4', operation: 'embedding', context_tokens: 0 },
          { model: 'qwen3-rerank', operation: 'rerank', context_tokens: 0 },
        ] },
    ],
    connections: [{ ...connection }], profiles: [{ ...profile }, { ...second }],
    mappings: [{ role: 'tutor.v1', profile_id: 'profile', revision: 7 }, { role: 'planner.v1', profile_id: 'second', revision: 9 }],
  };
}
beforeEach(() => {
  sessionStorage.clear(); localStorage.clear(); configuration = baseConfiguration(); history = [];
  native.state = { snapshot: { actor: { id: 'owner' } } };
  native.refresh.mockReset().mockResolvedValue(undefined);
  native.request.mockReset().mockImplementation(async (path: string, options?: RequestInit) => {
    if (path === '/v1/model-configuration') return structuredClone(configuration);
    if (path === '/v1/model-connection-tests') return structuredClone(history);
    const body = JSON.parse(String(options?.body ?? '{}'));
    if (path.startsWith('/v1/model-role-mappings/')) {
      const role = path.split('/').at(-1)!;
      const mapping = { role, profile_id: body.profile_id, revision: body.expected_mapping_revision + 1 };
      configuration.mappings = configuration.mappings.filter((item) => item.role !== role).concat(mapping);
      return mapping;
    }
    if (path.endsWith('/tests')) {
      const probe = { id: 'probe', connection_id: connection.id, profile_id: body.profile_id, status: 'queued',
        result: null, error_code: null, created_at: '2026-11-07T00:00:00Z' };
      history.push(probe); return probe;
    }
    return { id: 'saved' };
  });
});
afterEach(cleanup);
const writes = () => native.request.mock.calls.filter(([, options]) => options?.method && options.method !== 'GET');
const consentLabel = '同意发送学习对话与材料，费用由本人承担';
async function openModels() {
  render(<NativeModels />);
  await screen.findByRole('button', { name: '添加教学与路线规划提供方' });
}
async function choosePreset(name: 'DeepSeek' | '千问', group: 'teaching' | 'material' = 'teaching') {
  const label = group === 'teaching' ? '教学与路线规划' : '材料处理';
  const groupButton = await screen.findByRole('button', { name: label, exact: true });
  if (groupButton.getAttribute('aria-expanded') !== 'true') fireEvent.click(groupButton);
  fireEvent.click(screen.getByRole('button', { name: `添加${label}提供方` }));
  fireEvent.click(screen.getByRole('button', { name: name === '千问' ? '千问（北京）' : name, exact: true }));
  return screen.getByRole('form', { name: `${name}快捷配置` });
}
async function openPreset(name: 'DeepSeek' | '千问', group: 'teaching' | 'material' = 'teaching') {
  render(<NativeModels />); return choosePreset(name, group);
}
function fillChatModel() {
  fireEvent.change(screen.getByLabelText('配置名称'), { target: { value: '新模型' } });
  fireEvent.change(screen.getByLabelText('模型标识'), { target: { value: 'new-model' } });
  fireEvent.change(screen.getByLabelText('真实上下文容量'), { target: { value: '65536' } });
  fireEvent.change(screen.getByLabelText('最大输出容量'), { target: { value: '8192' } });
}
async function openRoles() {
  render(<NativeModelRoles />); await screen.findByLabelText('教学对话');
}
async function openCustom(group: 'teaching' | 'material') {
  render(<NativeModels />);
  const label = group === 'teaching' ? '教学与路线规划' : '材料处理';
  const button = await screen.findByRole('button', { name: label, exact: true });
  if (button.getAttribute('aria-expanded') !== 'true') fireEvent.click(button);
  fireEvent.click(screen.getByRole('button', { name: `添加${label}提供方` }));
  fireEvent.click(screen.getByRole('button', { name: '自定义', exact: true }));
  return screen.getByRole('form', { name: `自定义${label}` });
}

test('settings show two provider groups without advanced, reload or redundant footnotes', async () => {
  await openModels();
  expect(screen.getByRole('button', { name: '教学与路线规划', exact: true }).getAttribute('aria-expanded')).toBe('true');
  expect(screen.getByRole('button', { name: '材料处理', exact: true }).getAttribute('aria-expanded')).toBe('false');
  expect(screen.queryByText('高级配置')).toBeNull();
  expect(screen.queryByText('重新读取')).toBeNull();
  expect(screen.queryByText(/只需填写 API Key/)).toBeNull();
  expect(screen.queryByLabelText('教学对话')).toBeNull();
  expect(writes()).toHaveLength(0);
});

test('adding a model saves capabilities without assigning roles or making a probe', async () => {
  await openModels();
  fireEvent.click(screen.getByRole('button', { name: '添加模型 个人连接' }));
  fillChatModel(); fireEvent.click(screen.getByLabelText('启用此模型'));
  fireEvent.submit(screen.getByRole('form', { name: '添加模型配置' }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe('/v1/model-profiles?assign_roles=false');
  expect(JSON.parse(writes()[0][1].body)).toMatchObject({ model: 'new-model', enabled: true, allow_private_material: false });
  expect(configuration.mappings[0].profile_id).toBe('profile');
});

test('editing a model carries its exact revision without reclaiming purposes', async () => {
  await openModels(); fireEvent.click(screen.getByRole('button', { name: '编辑模型 教学模型' }));
  fireEvent.change(screen.getByLabelText('配置名称'), { target: { value: '更新名称' } });
  fireEvent.submit(screen.getByRole('form', { name: '编辑模型配置' }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe('/v1/model-profiles/profile?assign_roles=false');
  expect(JSON.parse(writes()[0][1].body)).toMatchObject({ expected_revision: 4, label: '更新名称' });
  expect(configuration.mappings.find((item) => item.role === 'planner.v1')?.profile_id).toBe('second');
});

test('standalone usage changes only on Apply and includes both CAS revisions', async () => {
  await openRoles();
  fireEvent.change(screen.getByLabelText('教学对话'), { target: { value: 'second' } });
  expect(writes()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: '应用教学对话模型' }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe('/v1/model-role-mappings/tutor.v1');
  expect(JSON.parse(writes()[0][1].body)).toEqual({
    profile_id: 'second', expected_profile_revision: 2, expected_mapping_revision: 7,
  });
});

test('material profile forms are separated from chat models and preserve embedding dimensions', async () => {
  configuration.profiles.push({ ...profile, id: 'embedding', model: 'embedding-model', operation: 'embedding', roles: ['embedding'] });
  await openModels(); fireEvent.click(screen.getByRole('button', { name: '材料处理', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: '添加模型 个人连接' }));
  fireEvent.change(screen.getByLabelText('配置名称'), { target: { value: '向量模型' } });
  fireEvent.change(screen.getByLabelText('模型标识'), { target: { value: 'embedding-model' } });
  expect(screen.queryByRole('option', { name: '教学 / 聊天' })).toBeNull();
  fireEvent.change(screen.getByLabelText('模型类型'), { target: { value: 'embedding' } });
  expect(screen.queryByLabelText('真实上下文容量')).toBeNull();
  fireEvent.change(screen.getByLabelText('向量维度'), { target: { value: '2048' } });
  fireEvent.submit(screen.getByRole('form', { name: '添加模型配置' }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(JSON.parse(writes()[0][1].body)).toMatchObject({
    operation: 'embedding', roles: ['embedding'], embedding_dimensions: 2048, thinking: '', context_tokens: 0,
  });
});

test('probe requires explicit billable consent and opening Test sends no request', async () => {
  await openModels(); fireEvent.click(screen.getByRole('button', { name: '测试模型 教学模型' }));
  expect(writes()).toHaveLength(0);
  expect((screen.getByRole('button', { name: '开始本次测试' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText('同意本次测试计费'));
  fireEvent.submit(screen.getByRole('form', { name: '显式连接测试' }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe('/v1/model-connections/connection/tests');
  expect(JSON.parse(writes()[0][1].body)).toEqual({
    expected_connection_revision: 3, profile_id: 'profile', allow_billable: true,
  });
  await screen.findByText(/教学模型 · 等待测试/);
  expect((screen.getByRole('button', { name: '开始本次测试' }) as HTMLButtonElement).disabled).toBe(true);
});

test('an interrupted probe is never resent by its read-only recovery', async () => {
  const original = native.request.getMockImplementation()!;
  native.request.mockImplementation(async (path, options) => {
    if (path.endsWith('/tests')) throw new TypeError('offline transport');
    return original(path, options);
  });
  await openModels(); fireEvent.click(screen.getByRole('button', { name: '测试模型 教学模型' }));
  fireEvent.click(screen.getByLabelText('同意本次测试计费'));
  fireEvent.submit(screen.getByRole('form', { name: '显式连接测试' }));
  await screen.findByText(/连接中断/);
  expect(writes()).toHaveLength(1);
  expect(native.request.mock.calls.filter(([path]) => path === '/v1/model-configuration').length).toBeGreaterThan(1);
});

test('old backend capabilities gate model setup and standalone assignments', async () => {
  configuration.capabilities = [];
  await openModels();
  expect((screen.getByRole('button', { name: '添加教学与路线规划提供方' }) as HTMLButtonElement).disabled).toBe(true);
  cleanup(); await openRoles();
  expect((screen.getByRole('button', { name: '应用教学对话模型' }) as HTMLButtonElement).disabled).toBe(true);
  expect(writes()).toHaveLength(0);
});

test('custom teaching setup submits one atomic command and clears the memory-only secret', async () => {
  const form = await openCustom('teaching');
  fireEvent.change(screen.getByLabelText('接口地址'), { target: { value: 'https://custom.example.test/v1' } });
  fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'offline-custom-key' } });
  fireEvent.change(screen.getByLabelText('模型'), { target: { value: 'custom-chat' } });
  fireEvent.change(screen.getByLabelText('上下文容量'), { target: { value: '65536' } });
  fireEvent.change(screen.getByLabelText('输出上限'), { target: { value: '8192' } });
  fireEvent.click(screen.getByLabelText(consentLabel));
  const input = screen.getByLabelText('API Key') as HTMLInputElement;
  fireEvent.submit(form); fireEvent.submit(form);
  expect(input.value).toBe('');
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe('/v1/model-providers/custom');
  expect(JSON.parse(writes()[0][1].body)).toMatchObject({
    group: 'teaching', allow_private_material: true,
    connection: { api_key: 'offline-custom-key', protocol: 'chat_completions', enabled: true },
    profile: { operation: 'chat', model: 'custom-chat', context_tokens: 65536, max_output_tokens: 8192 },
  });
  expect(sessionStorage.length).toBe(0); expect(localStorage.length).toBe(0);
});

test('custom material setup supports independent embedding providers', async () => {
  const form = await openCustom('material');
  fireEvent.change(screen.getByLabelText('用途'), { target: { value: 'embedding' } });
  expect(screen.queryByLabelText('上下文容量')).toBeNull();
  fireEvent.change(screen.getByLabelText('接口地址'), { target: { value: 'https://embedding.example.test/v1' } });
  fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'offline-material-key' } });
  fireEvent.change(screen.getByLabelText('模型'), { target: { value: 'embedding-model' } });
  fireEvent.change(screen.getByLabelText('向量维度'), { target: { value: '2048' } });
  fireEvent.click(screen.getByLabelText(consentLabel)); fireEvent.submit(form);
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(JSON.parse(writes()[0][1].body)).toMatchObject({
    group: 'material', profile: { operation: 'embedding', embedding_dimensions: 2048 },
  });
});

test('switching identity discards a custom credential editor', async () => {
  await openCustom('teaching');
  fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'ephemeral-input' } });
  act(() => {
    native.state = { snapshot: { actor: { id: 'other' } } };
    for (const listener of native.listeners) listener();
  });
  await screen.findByRole('button', { name: '添加教学与路线规划提供方' });
  expect(screen.queryByDisplayValue('ephemeral-input')).toBeNull();
  expect(writes()).toHaveLength(0);
});

test('stale profile revisions report conflict without creating another model', async () => {
  const original = native.request.getMockImplementation()!;
  native.request.mockImplementation(async (path, options) => {
    if (options?.method === 'PATCH') throw new NativeApiError(409, 'stale_version', 'changed');
    return original(path, options);
  });
  await openModels(); fireEvent.click(screen.getByRole('button', { name: '编辑模型 教学模型' }));
  fireEvent.submit(screen.getByRole('form', { name: '编辑模型配置' }));
  await screen.findByText(/配置已更新/);
  expect(writes()).toHaveLength(1);
});

test('readiness checks credentials and public metrics never echo response bodies', () => {
  expect(modelReady(configuration as never, profile)).toBe(true);
  expect(modelReady({ ...configuration, connections: [{ ...connection, credential_present: false }] } as never, profile)).toBe(false);
  expect(probeMetrics({ elapsed_seconds: 1.234, usage: { total_tokens: 12 }, raw: 'not-for-display' })).toBe('1.23 秒 · 12 Token');
});

test('teaching preset needs only a key and consent, makes one atomic write and no probe', async () => {
  const form = await openPreset('DeepSeek');
  const input = screen.getByLabelText('DeepSeek Key') as HTMLInputElement;
  expect(screen.queryByLabelText('接口地址')).toBeNull();
  fireEvent.change(input, { target: { value: 'offline-preset-key' } });
  expect((screen.getByRole('button', { name: '保存并启用' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText(consentLabel));
  fireEvent.submit(form); fireEvent.submit(form);
  expect(input.value).toBe('');
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(JSON.parse(writes()[0][1].body)).toEqual({
    group: 'teaching', api_key: 'offline-preset-key', allow_private_material: true, models: ['deepseek-flash'],
    expected_mapping_revisions: { 'tutor.v1': 7, 'planner.v1': 9 },
  });
  expect(writes()[0][1].headers['Idempotency-Key']).toBeTruthy();
  expect(sessionStorage.length).toBe(0); expect(localStorage.length).toBe(0);
});

test('key rotation targets the explicit connection without changing models or purposes', async () => {
  await openModels();
  const card = screen.getByRole('article', { name: '教学与路线规划 个人连接' });
  fireEvent.click(within(card).getByRole('button', { name: '更新 Key' }));
  fireEvent.change(screen.getByLabelText('新 Key'), { target: { value: 'offline-rotated-key' } });
  fireEvent.submit(screen.getByRole('form', { name: '更新个人连接凭据' }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe('/v1/model-connections/connection');
  expect(JSON.parse(writes()[0][1].body)).toEqual({ expected_revision: 3, api_key: 'offline-rotated-key' });
  expect(configuration.mappings).toEqual(baseConfiguration().mappings);
});

test('interrupted preset setup refreshes its configuration without resending the secret', async () => {
  const original = native.request.getMockImplementation()!;
  native.request.mockImplementation(async (path, options) => {
    if (path === '/v1/model-presets/deepseek') throw new TypeError('offline transport');
    return original(path, options);
  });
  const form = await openPreset('DeepSeek');
  const input = screen.getByLabelText('DeepSeek Key') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'never-persist-this' } });
  fireEvent.click(screen.getByLabelText(consentLabel)); fireEvent.submit(form);
  await screen.findByText(/连接中断/);
  expect(writes()).toHaveLength(1); expect(input.value).toBe('');
  expect(sessionStorage.length).toBe(0); expect(localStorage.length).toBe(0);
});

test('identity and provider switches discard the quick key and its reveal state', async () => {
  await openPreset('DeepSeek');
  fireEvent.change(screen.getByLabelText('DeepSeek Key'), { target: { value: 'temporary-key' } });
  fireEvent.click(screen.getByRole('button', { name: '显示 API Key' }));
  fireEvent.click(screen.getByRole('button', { name: '更换', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: '千问（北京）', exact: true }));
  expect((screen.getByLabelText('千问 Key（北京）') as HTMLInputElement).value).toBe('');
  fireEvent.change(screen.getByLabelText('千问 Key（北京）'), { target: { value: 'second-temporary-key' } });
  act(() => {
    native.state = { snapshot: { actor: { id: 'other' } } };
    for (const listener of native.listeners) listener();
  });
  await screen.findByRole('button', { name: '添加教学与路线规划提供方' });
  expect(screen.queryByDisplayValue('second-temporary-key')).toBeNull();
  expect(screen.queryByRole('button', { name: '隐藏 API Key' })).toBeNull();
  expect(writes()).toHaveLength(0);
});

test('provider search finds Qwen and material category excludes teaching-only providers', async () => {
  await openModels(); fireEvent.click(screen.getByRole('button', { name: '材料处理', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: '添加材料处理提供方' }));
  fireEvent.change(screen.getByRole('textbox', { name: '搜索提供方' }), { target: { value: 'Qwen' } });
  expect(screen.queryByRole('button', { name: 'DeepSeek', exact: true })).toBeNull();
  expect(screen.getByRole('button', { name: '千问（北京）', exact: true })).toBeTruthy();
  expect(screen.getByRole('button', { name: '自定义', exact: true })).toBeTruthy();
  expect(writes()).toHaveLength(0);
});

test('CCS material model drafts cancel locally and only applied model choices are submitted', async () => {
  const form = await openPreset('千问', 'material');
  fireEvent.click(screen.getByRole('button', { name: '模型', exact: true }));
  expect(screen.queryByRole('checkbox', { name: 'qwen-plus' })).toBeNull();
  fireEvent.click(screen.getByRole('checkbox', { name: 'qwen3.5-ocr' }));
  fireEvent.click(screen.getByRole('button', { name: '取消选择' }));
  fireEvent.click(screen.getByRole('button', { name: '模型', exact: true }));
  expect((screen.getByRole('checkbox', { name: 'qwen3.5-ocr' }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole('checkbox', { name: 'qwen3.5-ocr' }));
  fireEvent.click(screen.getByRole('checkbox', { name: '只看已选' }));
  expect(screen.queryByRole('checkbox', { name: 'qwen3.5-ocr' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '应用模型选择' }));
  expect(writes()).toHaveLength(0);
  fireEvent.change(screen.getByLabelText('千问 Key（北京）'), { target: { value: 'offline-selected-key' } });
  fireEvent.click(screen.getByLabelText(consentLabel)); fireEvent.submit(form);
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(JSON.parse(writes()[0][1].body)).toMatchObject({
    group: 'material', models: ['text-embedding-v4', 'qwen3-rerank'],
  });
});

test('adding another account never silently replaces an existing provider key', async () => {
  configuration.connections.push({ ...connection, id: 'another', label: 'DeepSeek',
    base_url: 'https://api.deepseek.com', region: 'global' });
  const form = await openPreset('DeepSeek');
  fireEvent.change(screen.getByLabelText('DeepSeek Key'), { target: { value: 'offline-separate-key' } });
  fireEvent.click(screen.getByLabelText(consentLabel)); fireEvent.submit(form);
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(JSON.parse(writes()[0][1].body).connection_id).toBeUndefined();
});

test('standalone usage double-clicks send one explicit versioned command and no probe', async () => {
  await openRoles(); fireEvent.change(screen.getByLabelText('教学对话'), { target: { value: 'second' } });
  const button = screen.getByRole('button', { name: '应用教学对话模型' });
  fireEvent.click(button); fireEvent.click(button);
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe('/v1/model-role-mappings/tutor.v1');
});

test('a stale standalone usage assignment refreshes without retrying', async () => {
  const original = native.request.getMockImplementation()!;
  native.request.mockImplementation(async (path, options) => {
    if (path.startsWith('/v1/model-role-mappings/')) throw new NativeApiError(409, 'stale_version', 'changed');
    return original(path, options);
  });
  await openRoles(); fireEvent.change(screen.getByLabelText('教学对话'), { target: { value: 'second' } });
  fireEvent.click(screen.getByRole('button', { name: '应用教学对话模型' }));
  await screen.findByText(/配置已更新/); expect(writes()).toHaveLength(1);
});

test('custom entry stays within its category and opens without making a write', async () => {
  await openCustom('material');
  expect(screen.getByLabelText('用途')).toBeTruthy();
  expect(screen.queryByRole('option', { name: '教学 / 聊天' })).toBeNull();
  expect(screen.queryByText('高级配置')).toBeNull();
  expect(writes()).toHaveLength(0);
});
