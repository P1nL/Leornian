import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { components } from '@leornian/api-contracts';
import { Plus } from 'lucide-react';
import { Action, Disclosure, Notice } from './LearningUI';
import ApiKeyInput from './CCSApiKeyInput';
import { ProviderPresetSelector } from './CCSProviderPresetSelector';
import FetchedModelPicker from './CCSModelPicker';
import { nativeRequest } from './native-client.mjs';
import './ccs-models.css';
import NativeTavilySettings from './NativeTavilySettings';

type Configuration = components['schemas']['ModelConfiguration'];
type Connection = components['schemas']['ModelConnection'];
type Profile = components['schemas']['ModelProfile'];
type Preset = components['schemas']['ModelProviderPreset'];
type Mutate = (operation: () => Promise<unknown>, success: string) => Promise<boolean>;
export type ProviderGroup = 'teaching' | 'material';
export const providerGroupLabels = { teaching: '教学与路线规划', material: '材料处理' };
const inGroup = (operation: Profile['operation'], group: ProviderGroup) =>
  (operation === 'chat') === (group === 'teaching');
const modelsFor = (preset: Preset, group: ProviderGroup) =>
  (preset.model_details ?? []).filter((model) => inGroup(model.operation, group));
const operationLabels = { chat: '教学', ocr: '文字识别', embedding: '文本向量', rerank: '检索重排' };

export default function NativeModelProviders({
  configuration, busy, mutate, initialGroup, onGroupChange, custom, edit, remove, profile, test,
}: {
  configuration: Configuration; busy: boolean; mutate: Mutate; initialGroup: ProviderGroup;
  onGroupChange: (group: ProviderGroup) => void;
  custom: (group: ProviderGroup) => void; edit: (connection: Connection) => void;
  remove: (connection: Connection) => void;
  profile: (connection: Connection, group: ProviderGroup, value?: Profile) => void;
  test: (profile: Profile) => void;
}) {
  const [openGroup, setOpenGroup] = useState<ProviderGroup | null>(initialGroup);
  const [adding, setAdding] = useState<ProviderGroup | null>(null);
  const [presetId, setPresetId] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const connections = configuration.connections.filter((item) => !item.deleted);
  const canSave = configuration.credential_storage === 'available' &&
    Boolean(configuration.capabilities?.includes('provider-presets.v3'));
  const existing = connections.find((item) => item.id === editing);
  const presets = (configuration.presets ?? []).filter((item) => adding && modelsFor(item, adding).length > 0);
  const preset = presets.find((item) => item.id === presetId);
  if (existing) return <KeyEditor key={existing.id} connection={existing}
    available={configuration.credential_storage === 'available'}
    busy={busy} mutate={mutate} close={() => setEditing(null)} />;
  if (adding) return <div className="ccs-models ccs-add-provider" aria-label={`添加${providerGroupLabels[adding]}提供方`}>
    <Action disabled={busy} onClick={() => { setAdding(null); setPresetId(null); }}>返回</Action>
    <h3>{providerGroupLabels[adding]}</h3>
    <ProviderPresetSelector selectedPresetId={preset?.id ?? null} disabled={busy}
      presetEntries={presets.map((item) => ({
        id: item.id, preset: { name: item.id === 'qwen' ? '千问（北京）' : item.label,
          websiteUrl: item.base_url, detail: '', searchTerms: item.id === 'qwen' ? ['Qwen', '千问'] : [] },
      }))}
      onPresetChange={(id) => { if (id === 'custom') custom(adding); else setPresetId(id); }}
      onChange={() => setPresetId(null)} />
    {preset && <PresetForm key={`${adding}:${preset.id}`} preset={preset} group={adding}
      configuration={configuration} busy={busy} available={canSave} mutate={mutate}
      close={() => { setAdding(null); setPresetId(null); }} />}
  </div>;
  return <div className="ccs-models" aria-label="分类提供方">
    {(['teaching', 'material'] as const).map((group) => <Disclosure key={group}
      title={providerGroupLabels[group]} className="model-provider-group"
      open={openGroup === group} onOpenChange={(open) => {
        setOpenGroup(open ? group : null); onGroupChange(group);
      }}>
      <div className="ccs-group-actions">
        <Action icon={Plus} disabled={busy || !canSave} onClick={() => {
          setAdding(group); setPresetId(null);
        }} aria-label={`添加${providerGroupLabels[group]}提供方`}>添加提供方</Action>
      </div>
      {connections.filter((connection) => {
        const owned = configuration.profiles.filter((item) => item.connection_id === connection.id);
        return !owned.length || owned.some((item) => inGroup(item.operation, group));
      }).map((connection) => {
        const profiles = configuration.profiles.filter((item) => item.connection_id === connection.id && inGroup(item.operation, group));
        const assigned = configuration.mappings.some((mapping) => profiles.some((item) => item.id === mapping.profile_id));
        return <article key={connection.id} className="ccs-provider-card" aria-label={`${providerGroupLabels[group]} ${connection.label}`}>
          <div className="native-models-detail-heading">
            <h4>{connection.label}</h4>
            <span>{!connection.credential_present ? '缺少 Key' : !connection.enabled ? '已停用' : assigned ? '使用中' : '已配置'}</span>
          </div>
          <ul className="ccs-provider-profiles">{profiles.map((item) => <li key={item.id}>
            <span>{item.model}{!item.enabled ? '（已停用）' : ''}</span>
            <button type="button" disabled={busy} aria-label={`编辑模型 ${item.label}`}
              onClick={() => profile(connection, group, item)}>编辑</button>
            <button type="button" disabled={busy || !item.enabled || !connection.enabled || !connection.credential_present}
              aria-label={`测试模型 ${item.label}`} onClick={() => test(item)}>测试</button>
          </li>)}</ul>
          <div className="ccs-provider-actions">
            <button type="button" disabled={busy} onClick={() => setEditing(connection.id)}>更新 Key</button>
            <button type="button" disabled={busy} aria-label={`编辑连接 ${connection.label}`} onClick={() => edit(connection)}>编辑连接</button>
            <button type="button" disabled={busy} aria-label={`添加模型 ${connection.label}`} onClick={() => profile(connection, group)}>添加模型</button>
            <button type="button" disabled={busy} aria-label={`删除连接 ${connection.label}`} onClick={() => remove(connection)}>删除</button>
          </div>
        </article>;
      })}
      {group === 'material' && configuration.capabilities?.includes('material-web-search.v1') &&
        <NativeTavilySettings available={configuration.credential_storage === 'available'} />}
    </Disclosure>)}
    {!canSave && <Notice>请先更新后台或检查凭据保管。</Notice>}
  </div>;
}

function PresetForm({ preset, group, configuration, busy, available, mutate, close }: {
  preset: Preset; group: ProviderGroup; configuration: Configuration; busy: boolean;
  available: boolean; mutate: Mutate; close: () => void;
}) {
  const allowed = modelsFor(preset, group);
  const [secret, setSecret] = useState('');
  const [models, setModels] = useState(allowed.map((item) => item.model));
  const [consent, setConsent] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const submitting = useRef(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || submitting.current || !available || !secret.trim() || !models.length || !consent || choosing) return;
    submitting.current = true;
    const apiKey = secret.trim(); setSecret('');
    void mutate(() => nativeRequest(`/v1/model-presets/${preset.id}`, {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ group, api_key: apiKey, allow_private_material: true, models,
        expected_mapping_revisions: Object.fromEntries(configuration.mappings.map((item) => [item.role, item.revision])) }),
    }), '已保存').then((saved) => { if (saved) close(); })
      .finally(() => { submitting.current = false; });
  };
  return <form className="native-models-form ccs-preset-form" onSubmit={submit} aria-label={`${preset.label}快捷配置`}>
    <ApiKeyInput id={`preset-key-${preset.id}`} value={secret} onChange={setSecret}
      label={preset.id === 'qwen' ? '千问 Key（北京）' : 'DeepSeek Key'}
      required disabled={busy || !available}
      labelAside={preset.api_key_url && <a href={preset.api_key_url} target="_blank"
        rel="noopener noreferrer">获取 Key</a>} />
    <Disclosure title="模型" open={choosing} onOpenChange={setChoosing}>
      {choosing && <FetchedModelPicker configuredModelIds={models}
        models={allowed.map((item) => ({
          id: item.model, label: operationLabels[item.operation],
        }))}
        onCancel={() => setChoosing(false)} onApply={({ add, remove }) => {
          setModels(allowed.map((item) => item.model)
            .filter((id) => (models.includes(id) && !remove.includes(id)) || add.includes(id)));
          setChoosing(false);
        }} />}
    </Disclosure>
    <label className="demo-choice"><input type="checkbox" checked={consent} disabled={busy || !available}
      onChange={(event) => setConsent(event.target.checked)} />
      同意发送学习对话与材料，费用由本人承担</label>
    <Action type="submit" busy={busy} disabled={!available || !secret.trim() || !models.length || choosing || !consent}>保存并启用</Action>
  </form>;
}

function KeyEditor({ connection, available, busy, mutate, close }: {
  connection: Connection; available: boolean; busy: boolean; mutate: Mutate; close: () => void;
}) {
  const [secret, setSecret] = useState('');
  const submitting = useRef(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || submitting.current || !available || !secret.trim()) return;
    submitting.current = true;
    const apiKey = secret.trim(); setSecret('');
    void mutate(() => nativeRequest(`/v1/model-connections/${connection.id}`, {
      method: 'PATCH', body: JSON.stringify({ expected_revision: connection.revision, api_key: apiKey }),
    }), 'Key 已更新').then((saved) => { if (saved) close(); })
      .finally(() => { submitting.current = false; });
  };
  return <form className="native-models-form ccs-add-provider" onSubmit={submit} aria-label={`更新${connection.label}凭据`}>
    <Action disabled={busy} onClick={close}>返回</Action>
    <h3>{connection.label}</h3>
    <ApiKeyInput id={`connection-key-${connection.id}`} value={secret} onChange={setSecret}
      label="新 Key" required disabled={busy || !available} />
    <Action type="submit" busy={busy} disabled={!available || !secret.trim()}>保存</Action>
  </form>;
}
