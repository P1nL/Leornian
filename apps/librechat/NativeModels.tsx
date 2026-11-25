import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { FormEvent } from 'react';
import { Save } from 'lucide-react';
import { Action, Disclosure, Notice } from './LearningUI';
import NativeModelProviders from './NativeModelProviders';
import NativeModelCustom from './NativeModelCustom';
import type { ProviderGroup } from './NativeModelProviders';
import { NativeApiError, nativeRequest, nativeStore } from './native-client.mjs';
import type { components } from '@leornian/api-contracts';
import './native-models.css';

type Configuration = components['schemas']['ModelConfiguration'];
type Connection = components['schemas']['ModelConnection'];
type Profile = components['schemas']['ModelProfile'];
type ProfileInput = components['schemas']['ModelProfileInput'];
type Probe = components['schemas']['ModelConnectionTest'];
type Role = Profile['roles'][number];
type Mutate = (operation: () => Promise<unknown>, success: string) => Promise<boolean>;
type Editor = { kind: 'connection'; value: Connection }
  | { kind: 'profile'; connection: Connection; value?: Profile; group: ProviderGroup }
  | { kind: 'delete'; value: Connection }
  | { kind: 'custom'; group: ProviderGroup }
  | { kind: 'tests'; value: Profile };

export const modelRoles: ReadonlyArray<readonly [Role, string]> = [
  ['tutor.v1', '教学对话'], ['planner.v1', '路线规划'], ['lesson.v1', '课时内容'],
  ['delivery_review.v1', '交付检查'], ['material_review.v1', '材料复核'],
  ['material_check.v1', '材料检查'],
  ['evaluation.v1', '作答讲评'], ['artifact.v1', '教学文档'],
  ['item_author.v1', '出题'], ['item_blind.v1', '独立解题'], ['item_review.v1', '题目审核'],
  ['gate_relation.v1', '独立掌握检查'], ['transfer_relation.v1', '迁移检查'],
  ['ocr', '文字识别'], ['embedding', '文本向量'], ['rerank', '检索重排'],
];
const operationLabels = { chat: '教学 / 聊天', ocr: '文字识别', embedding: '文本向量', rerank: '检索重排' };
const probeLabels = {
  queued: '等待测试', dispatching: '测试中', succeeded: '固定协议样例通过',
  failed: '测试未通过', unknown: '结果未知，保留原请求', cancelled: '测试已取消',
};
const probeReasons: Record<string, string> = {
  provider_rejected: '提供方拒绝请求，请核对模型、区域、凭据与账号状态。',
  invalid_probe_response: '返回内容或向量维度不符合固定协议样例。',
  model_unavailable: '连接或模型不可用，请重新读取配置。',
  external_result_unknown: '没有收到完整回执，原请求不会自动重发。',
  configuration_or_session_changed: '配置或会话已经变化，原调用事实仍保留。',
};
export function newModelProfile(connection: Connection): ProfileInput {
  return {
    label: '', connection_id: connection.id, model: '', operation: 'chat', enabled: false,
    allow_private_material: false, roles: modelRoles.filter(([role]) => role.endsWith('.v1')).map(([role]) => role),
    context_tokens: 0, max_output_tokens: 0, embedding_dimensions: 1024, thinking: 'enabled', timeout_seconds: 300,
  };
}
export function modelReady(configuration: Configuration, profile: Profile) {
  const connection = configuration.connections.find((item) => item.id === profile.connection_id);
  return Boolean(profile.enabled && connection?.enabled && !connection.deleted && connection.credential_present);
}
export function probeMetrics(result: Probe['result']) {
  if (!result) return '';
  const elapsed = result.elapsed_seconds;
  const usage = result.usage as { total_tokens?: unknown } | undefined;
  return [
    typeof elapsed === 'number' && Number.isFinite(elapsed) && elapsed >= 0 ? `${elapsed.toFixed(2)} 秒` : '',
    typeof usage?.total_tokens === 'number' && Number.isSafeInteger(usage.total_tokens) && usage.total_tokens >= 0
      ? `${usage.total_tokens} Token` : '',
  ].filter(Boolean).join(' · ');
}
function settingsError(problem: unknown) {
  if (problem instanceof NativeApiError) {
    if (problem.code === 'stale_version') return '配置已更新，请重新打开后保存。';
    if (problem.status === 422) return '请检查必填项和模型参数。';
    if (problem.code === 'precondition_failed') return '连接或模型配置不可用。';
    return problem.message;
  }
  return '连接中断，结果待确认；请重新打开此页。';
}

export default function NativeModels({ view = 'providers' }: { view?: 'providers' | 'roles' } = {}) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot, nativeStore.getSnapshot);
  return <ModelManager key={`${state.snapshot?.actor.id ?? 'unloaded'}:${view}`} view={view} />;
}
export function NativeModelRoles() { return <NativeModels view="roles" />; }
function ModelManager({ view }: { view: 'providers' | 'roles' }) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [tests, setTests] = useState<Probe[]>([]);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [group, setGroup] = useState<ProviderGroup>('teaching');
  const [probeTarget, setProbeTarget] = useState('');
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const alive = useRef(true), generation = useRef(0);
  const explicitRoles = configuration?.capabilities?.includes('explicit-role-assignment.v1') ?? false;
  const refresh = async () => {
    const current = ++generation.current;
    setLoading(true);
    try {
      const [config, history] = await Promise.all([
        nativeRequest('/v1/model-configuration'), nativeRequest('/v1/model-connection-tests'),
      ]);
      if (alive.current && current === generation.current) { setConfiguration(config); setTests(history); }
    } finally { if (alive.current && current === generation.current) setLoading(false); }
  };
  useEffect(() => {
    alive.current = true;
    void refresh().catch((problem) => { if (alive.current) setError(settingsError(problem)); });
    return () => { alive.current = false; generation.current++; };
  }, []);
  useEffect(() => {
    if (!tests.some((test) => ['queued', 'dispatching'].includes(test.status))) return;
    let current = true;
    const timer = window.setTimeout(() => {
      void nativeRequest('/v1/model-connection-tests').then((history) => {
        if (current && alive.current) setTests(history);
      }).catch(() => {
        if (current && alive.current) setError('暂时无法获取测试进度。');
      });
    }, 2000);
    return () => { current = false; window.clearTimeout(timer); };
  }, [tests]);
  const mutate: Mutate = async (operation, success) => {
    setBusy(true); setError(''); setNotice('');
    let saved = false;
    try {
      await operation(); saved = true;
      if (!alive.current) return false;
      setNotice(success); await refresh(); await nativeStore.refresh();
      return true;
    } catch (problem) {
      if (alive.current) setError(saved ? '已保存，显示同步暂未完成。' : settingsError(problem));
      if (!saved && alive.current) await refresh().catch(() => {});
      return saved && alive.current;
    } finally { if (alive.current) setBusy(false); }
  };
  const open = (value: Editor) => { setEditor(value); setError(''); setNotice(''); };
  const close = () => setEditor(null);
  return <section className="native-models native-models-settings" aria-label={view === 'roles' ? '用途分配' : '本人模型配置'}>
    {error && <div role="alert"><Notice>{error}</Notice></div>}
    {notice && <div role="status"><Notice>{notice}</Notice></div>}
    {loading && !configuration && <p role="status">加载中…</p>}
    {error && !configuration && <Action disabled={loading} onClick={() => {
      setError(''); void refresh().catch((problem) => setError(settingsError(problem)));
    }}>重试</Action>}
    {configuration && <>
      {configuration.credential_storage !== 'available' && <Notice>本机凭据保管未就绪。</Notice>}
      {!explicitRoles && <Notice>请先更新后台。</Notice>}
      {view === 'roles' ? <RoleAssignments configuration={configuration} busy={busy} supported={explicitRoles} mutate={mutate} />
        : editor?.kind === 'connection' ? <ConnectionEditor value={editor.value} busy={busy} mutate={mutate}
          close={close} storageReady={configuration.credential_storage === 'available'} />
          : editor?.kind === 'profile' ? <ProfileEditor key={editor.value?.id ?? 'new'}
            value={editor.value} connection={editor.connection} group={editor.group} busy={busy} mutate={mutate} close={close} />
            : editor?.kind === 'custom' ? <NativeModelCustom group={editor.group}
              configuration={configuration} busy={busy} mutate={mutate} close={close} />
              : editor?.kind === 'delete' ? <div className="native-models-form">
                <h3>删除「{editor.value.label}」？</h3>
                <div className="demo-actions"><Action disabled={busy} onClick={close}>取消</Action>
                  <Action disabled={busy} onClick={() => {
                    const value = editor.value;
                    void mutate(() => nativeRequest(`/v1/model-connections/${value.id}`, {
                      method: 'DELETE', body: JSON.stringify({ expected_revision: value.revision }),
                    }), '已删除').then((saved) => { if (saved) close(); });
                  }}>确认删除</Action></div>
              </div> : editor?.kind === 'tests' ? <>
                <Action disabled={busy} onClick={close}>返回</Action>
                <ConnectionTests configuration={configuration} tests={tests}
                  target={probeTarget} setTarget={setProbeTarget} busy={busy} mutate={mutate} />
              </> : <NativeModelProviders configuration={configuration} busy={busy} mutate={mutate}
                initialGroup={group} onGroupChange={setGroup}
                custom={(next) => open({ kind: 'custom', group: next })}
                edit={(value) => open({ kind: 'connection', value })}
                remove={(value) => open({ kind: 'delete', value })}
                profile={(connection, next, value) => open({ kind: 'profile', connection, group: next, value })}
                test={(value) => { setProbeTarget(value.id); open({ kind: 'tests', value }); }} />}
    </>}
  </section>;
}

function ConnectionEditor({ value, busy, mutate, close, storageReady }: {
  value: Connection; busy: boolean; mutate: Mutate; close: () => void; storageReady: boolean;
}) {
  const [label, setLabel] = useState(value.label), [enabled, setEnabled] = useState(value.enabled);
  const [secret, setSecret] = useState('');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const apiKey = secret; setSecret('');
    void mutate(() => nativeRequest(`/v1/model-connections/${value.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ expected_revision: value.revision, label, enabled, ...(apiKey ? { api_key: apiKey } : {}) }),
    }), '已保存')
      .then((saved) => { if (saved) close(); });
  };
  return <form className="native-models-form" onSubmit={submit} aria-label="编辑提供方连接">
    <div className="native-models-detail-heading"><h3>编辑连接</h3>
      <Action disabled={busy} onClick={close}>返回</Action></div>
    <label>连接名称<input required maxLength={100} value={label} disabled={busy} onChange={(event) => setLabel(event.target.value)} /></label>
    <label>接口地址<input readOnly value={value.base_url} /></label>
    <label>新 Key<input type="password" autoComplete="off" value={secret} disabled={busy || !storageReady}
      placeholder="留空不修改" onChange={(event) => setSecret(event.target.value)} /></label>
    <label className="demo-choice"><input type="checkbox" checked={enabled} disabled={busy}
      onChange={(event) => setEnabled(event.target.checked)} /><span>启用连接</span></label>
    <Action type="submit" icon={Save} busy={busy}>保存</Action>
  </form>;
}

function ProfileEditor({ value, connection, group, busy, mutate, close }: {
  value?: Profile; connection: Connection; group: ProviderGroup; busy: boolean; mutate: Mutate; close: () => void;
}) {
  const [draft, setDraft] = useState<ProfileInput>(() => value ? {
    label: value.label, connection_id: value.connection_id, model: value.model, operation: value.operation,
    enabled: value.enabled, allow_private_material: value.allow_private_material, roles: [...value.roles],
    context_tokens: value.context_tokens, max_output_tokens: value.max_output_tokens,
    embedding_dimensions: value.embedding_dimensions, thinking: value.thinking, timeout_seconds: value.timeout_seconds,
  } : { ...newModelProfile(connection), ...(group === 'material' ? { operation: 'ocr', roles: ['ocr'] } as const : {}) });
  const [problem, setProblem] = useState('');
  const change = <K extends keyof ProfileInput>(key: K, next: ProfileInput[K]) => setDraft((old) => ({ ...old, [key]: next }));
  const submit = (event: FormEvent) => {
    event.preventDefault(); setProblem('');
    if (!draft.roles.length || (draft.operation === 'chat' &&
      (!draft.context_tokens || !draft.max_output_tokens || draft.max_output_tokens > draft.context_tokens))) {
      setProblem('请检查用途和模型容量。'); return;
    }
    const path = value ? `/v1/model-profiles/${value.id}` : '/v1/model-profiles';
    void mutate(() => nativeRequest(`${path}?assign_roles=false`, {
      method: value ? 'PATCH' : 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ ...draft, ...(value ? { expected_revision: value.revision } : {}) }),
    }), '已保存').then((saved) => { if (saved) close(); });
  };
  return <form className="native-models-form" onSubmit={submit} aria-label={value ? '编辑模型配置' : '添加模型配置'}>
    <div className="native-models-detail-heading"><h3>{value ? '编辑模型' : '添加模型'}</h3>
      <Action disabled={busy} onClick={close}>返回</Action></div>
    {problem && <p role="alert">{problem}</p>}
    <label>配置名称<input required maxLength={100} value={draft.label} disabled={busy} onChange={(event) => change('label', event.target.value)} /></label>
    <label>模型标识<input required maxLength={200} value={draft.model} disabled={busy}
      onChange={(event) => change('model', event.target.value)} /></label>
    <label>模型类型<select value={draft.operation} disabled={busy} onChange={(event) => {
      const operation = event.target.value as Profile['operation'];
      setDraft((old) => ({ ...old, operation, roles: operation === 'chat'
        ? modelRoles.filter(([role]) => role.endsWith('.v1')).map(([role]) => role) : [operation],
      thinking: '', context_tokens: 0, max_output_tokens: 0 }));
    }}>{Object.entries(operationLabels).filter(([operation]) => (operation === 'chat') === (group === 'teaching'))
      .map(([operation, label]) => <option key={operation} value={operation}>{label}</option>)}</select></label>
    {draft.operation === 'chat' && <>
      <div className="native-models-field-pair">
        <label>真实上下文容量<input type="number" required min={1} max={10000000} value={draft.context_tokens || ''} disabled={busy}
          onChange={(event) => change('context_tokens', event.target.valueAsNumber || 0)} /></label>
        <label>最大输出容量<input type="number" required min={1} max={2000000} value={draft.max_output_tokens || ''} disabled={busy}
          onChange={(event) => change('max_output_tokens', event.target.valueAsNumber || 0)} /></label>
      </div>
      <Disclosure title="可用用途">
        <div className="native-models-role-options">{modelRoles.filter(([role]) => role.endsWith('.v1')).map(([role, label]) =>
          <label className="demo-choice" key={role}><input type="checkbox" checked={draft.roles.includes(role)} disabled={busy}
            onChange={(event) => change('roles', event.target.checked ? [...draft.roles, role] : draft.roles.filter((item) => item !== role))} /><span>{label}</span></label>)}</div>
      </Disclosure>
    </>}
    {draft.operation === 'embedding' && <label>向量维度<input type="number" required min={1} max={16384} value={draft.embedding_dimensions}
      disabled={busy} onChange={(event) => change('embedding_dimensions', event.target.valueAsNumber)} /></label>}
    {draft.operation === 'rerank' && connection.protocol !== 'dashscope' && <Notice>检索重排需要 DashScope 连接，请返回并选择对应连接。</Notice>}
    <Disclosure title="模型参数">
      {draft.operation === 'chat' && <label>思考模式<select value={draft.thinking} disabled={busy}
        onChange={(event) => change('thinking', event.target.value as Profile['thinking'])}>
        <option value="">默认开启</option><option value="enabled">启用</option><option value="disabled">关闭</option></select></label>}
      <label>总超时（秒）<input type="number" required min={10} max={1800} value={draft.timeout_seconds} disabled={busy}
        onChange={(event) => change('timeout_seconds', event.target.valueAsNumber)} /></label>
    </Disclosure>
    <label className="demo-choice"><input type="checkbox" checked={draft.allow_private_material} disabled={busy}
      onChange={(event) => change('allow_private_material', event.target.checked)} /><span>允许发送学习材料</span></label>
    <label className="demo-choice"><input type="checkbox" checked={draft.enabled} disabled={busy}
      onChange={(event) => change('enabled', event.target.checked)} /><span>启用此模型</span></label>
    <div className="demo-actions"><Action type="submit" icon={Save} busy={busy}
      disabled={draft.operation === 'rerank' && connection.protocol !== 'dashscope'}>保存模型</Action></div>
  </form>;
}

function RoleAssignments({ configuration, busy, supported, mutate }: {
  configuration: Configuration; busy: boolean; supported: boolean; mutate: Mutate;
}) {
  return <div className="native-models-assignments">
    {(['teaching', 'material'] as const).map((group) => <Disclosure key={group}
      title={group === 'teaching' ? '教学与路线规划' : '材料处理'} defaultOpen>
      {modelRoles.filter(([role]) => role.endsWith('.v1') === (group === 'teaching')).map(([role, label]) =>
        <RoleAssignment key={role} configuration={configuration} role={role}
          label={label} busy={busy} supported={supported} mutate={mutate} />)}
    </Disclosure>)}</div>;
}
function RoleAssignment({ configuration, role, label, busy, supported, mutate }: {
  configuration: Configuration; role: Role; label: string; busy: boolean; supported: boolean; mutate: Mutate;
}) {
  const mapping = configuration.mappings.find((item) => item.role === role);
  const current = configuration.profiles.find((item) => item.id === mapping?.profile_id);
  const [choice, setChoice] = useState<string | null>(null);
  const selected = choice ?? current?.id ?? '';
  useEffect(() => { setChoice(null); }, [mapping?.revision, mapping?.profile_id]);
  const candidates = configuration.profiles.filter((profile) => profile.roles.includes(role) && modelReady(configuration, profile));
  const next = candidates.find((profile) => profile.id === selected);
  return <div className="native-models-assignment">
    <label htmlFor={`model-purpose-${role}`}>{label}</label>
    <div className="native-models-assignment-control">
      <select id={`model-purpose-${role}`} value={selected} disabled={busy || !supported} onChange={(event) => setChoice(event.target.value)}>
        <option value="">未配置</option>
        {current && !candidates.some((profile) => profile.id === current.id) && <option value={current.id} disabled>{current.label} · 不可用</option>}
        {candidates.map((profile) => <option key={profile.id} value={profile.id}>
          {configuration.connections.find((item) => item.id === profile.connection_id)?.label} / {profile.label}
          {!profile.allow_private_material ? '（未授权材料）' : ''}</option>)}
      </select>
      <Action disabled={busy || !supported || !next || next.id === current?.id} aria-label={`应用${label}模型`} onClick={() => {
        if (!next) return;
        void mutate(() => nativeRequest(`/v1/model-role-mappings/${role}`, { method: 'PUT',
          body: JSON.stringify({ profile_id: next.id, expected_profile_revision: next.revision,
            expected_mapping_revision: mapping?.revision ?? 0 }) }), '已应用');
      }}>应用</Action>
    </div>
  </div>;
}

function ConnectionTests({ configuration, tests, target, setTarget, busy, mutate }: {
  configuration: Configuration; tests: Probe[]; target: string; setTarget: (id: string) => void; busy: boolean; mutate: Mutate;
}) {
  const [consent, setConsent] = useState(false), pending = useRef<Set<string>>(new Set());
  const candidates = configuration.profiles.filter((profile) => modelReady(configuration, profile));
  const profile = candidates.find((item) => item.id === target) ?? candidates[0];
  useEffect(() => { setConsent(false); }, [target]);
  const unresolved = Boolean(profile && (pending.current.has(profile.id) ||
    tests.some((test) => test.profile_id === profile.id && ['queued', 'dispatching'].includes(test.status))));
  const previousUnknown = tests.some((test) => test.profile_id === profile?.id && test.status === 'unknown');
  return <div className="native-models-tests">
    <form className="native-models-form" onSubmit={(event) => {
      event.preventDefault();
      if (!profile || !consent || unresolved) return;
      const connection = configuration.connections.find((item) => item.id === profile.connection_id)!;
      pending.current.add(profile.id); setConsent(false);
      void mutate(async () => {
        try {
          await nativeRequest(`/v1/model-connections/${connection.id}/tests`, {
            method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
            body: JSON.stringify({ expected_connection_revision: connection.revision, profile_id: profile.id, allow_billable: true }),
          });
          pending.current.delete(profile.id);
        } catch (problem) {
          if (problem instanceof NativeApiError && problem.status < 500) pending.current.delete(profile.id);
          throw problem;
        }
      }, '测试已提交');
    }} aria-label="显式连接测试">
      <h3>连接测试</h3>
      <label>待测模型<select value={profile?.id ?? ''} disabled={busy} onChange={(event) => setTarget(event.target.value)}>
        {!candidates.length && <option value="">请先启用连接和模型</option>}
        {candidates.map((item) => <option key={item.id} value={item.id}>
          {configuration.connections.find((connection) => connection.id === item.connection_id)?.label} / {item.label} · {item.model}</option>)}</select></label>
      {previousUnknown && <Notice>上次结果未知，新测试将另行计费。</Notice>}
      <label className="demo-choice"><input type="checkbox" checked={consent} disabled={busy || !profile || unresolved}
        onChange={(event) => setConsent(event.target.checked)} /><span>同意本次测试计费</span></label>
      <Action type="submit" busy={busy} disabled={!profile || !consent || unresolved}>{previousUnknown ? '开始新的测试' : '开始本次测试'}</Action>
      {unresolved && <Notice>原测试确认中</Notice>}
    </form>
    <h3>测试记录</h3>
    {!tests.length && <p className="native-models-empty">暂无记录</p>}
    <ul className="native-models-test-list">{tests.map((test) => <li key={test.id}>
      <strong>{configuration.profiles.find((item) => item.id === test.profile_id)?.label ?? '原模型'} · {probeLabels[test.status]}</strong>
      <p>{new Date(test.created_at).toLocaleString()} {probeMetrics(test.result)}</p>
      {test.error_code && <p>{probeReasons[test.error_code] ?? test.error_code}</p>}
    </li>)}</ul>
  </div>;
}
