import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure } from './LearningUI';
import ApiKeyInput from './CCSApiKeyInput';
import type { ProviderGroup } from './NativeModelProviders';
import { providerGroupLabels } from './NativeModelProviders';
import { nativeRequest } from './native-client.mjs';

type Configuration = components['schemas']['ModelConfiguration'];
type Operation = components['schemas']['ModelProfile']['operation'];
type Mutate = (operation: () => Promise<unknown>, success: string) => Promise<boolean>;

export default function NativeModelCustom({ group, configuration, busy, mutate, close }: {
  group: ProviderGroup; configuration: Configuration; busy: boolean; mutate: Mutate; close: () => void;
}) {
  const [label, setLabel] = useState('自定义');
  const [base, setBase] = useState(''), [secret, setSecret] = useState(''), [model, setModel] = useState('');
  const [protocol, setProtocol] = useState<'chat_completions' | 'dashscope'>('chat_completions');
  const [region, setRegion] = useState('cn-beijing');
  const [operation, setOperation] = useState<Operation>(group === 'teaching' ? 'chat' : 'ocr');
  const [context, setContext] = useState(0), [output, setOutput] = useState(0), [dimensions, setDimensions] = useState(1024);
  const [local, setLocal] = useState(false), [consent, setConsent] = useState(false);
  const submitting = useRef(false);
  const available = configuration.credential_storage === 'available' &&
    Boolean(configuration.capabilities?.includes('provider-presets.v3'));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy || submitting.current || !available || !secret.trim() || !model.trim() || !base.trim() || !consent ||
      (operation === 'chat' && (!context || !output || output > context))) return;
    submitting.current = true;
    const apiKey = secret.trim(); setSecret('');
    void mutate(() => nativeRequest('/v1/model-providers/custom', {
      method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({
        group, allow_private_material: true,
        connection: { label: label.trim(), protocol, base_url: base.trim(),
          region: protocol === 'dashscope' ? region : 'custom', local_endpoint: local, enabled: true, api_key: apiKey },
        profile: { label: label.trim(), model: model.trim(), operation,
          context_tokens: context, max_output_tokens: output, embedding_dimensions: dimensions },
        expected_mapping_revisions: Object.fromEntries(configuration.mappings.map((item) => [item.role, item.revision])),
      }),
    }), '已保存').then((saved) => { if (saved) close(); })
      .finally(() => { submitting.current = false; });
  };
  return <form className="native-models-form ccs-add-provider" onSubmit={submit} aria-label={`自定义${providerGroupLabels[group]}`}>
    <Action disabled={busy} onClick={close}>返回</Action>
    <h3>自定义{providerGroupLabels[group]}</h3>
    <label>名称<input required maxLength={100} value={label} disabled={busy}
      onChange={(event) => setLabel(event.target.value)} /></label>
    {group === 'material' && <label>用途<select value={operation} disabled={busy}
      onChange={(event) => {
        const next = event.target.value as Operation;
        setOperation(next); if (next === 'rerank') setProtocol('dashscope');
      }}>
      <option value="ocr">文字识别</option><option value="embedding">文本向量</option><option value="rerank">检索重排</option>
    </select></label>}
    <label>接口地址<input type="url" required value={base} disabled={busy}
      placeholder="https://" onChange={(event) => setBase(event.target.value)} /></label>
    <ApiKeyInput value={secret} onChange={setSecret} required disabled={busy || !available} />
    <label>模型<input required maxLength={200} value={model} disabled={busy}
      onChange={(event) => setModel(event.target.value)} /></label>
    {operation === 'chat' && <div className="native-models-field-pair">
      <label>上下文容量<input type="number" required min={1} max={10000000} value={context || ''} disabled={busy}
        onChange={(event) => setContext(event.target.valueAsNumber || 0)} /></label>
      <label>输出上限<input type="number" required min={1} max={context || 2000000} value={output || ''} disabled={busy}
        onChange={(event) => setOutput(event.target.valueAsNumber || 0)} /></label>
    </div>}
    {operation === 'embedding' && <label>向量维度<input type="number" required min={1} max={16384} value={dimensions} disabled={busy}
      onChange={(event) => setDimensions(event.target.valueAsNumber || 0)} /></label>}
    <Disclosure title="接口参数">
      <label>协议<select value={protocol} disabled={busy || operation === 'rerank'}
        onChange={(event) => setProtocol(event.target.value as typeof protocol)}>
        <option value="chat_completions">Chat Completions</option><option value="dashscope">DashScope</option>
      </select></label>
      {protocol === 'dashscope' && <label>区域<select value={region} disabled={busy}
        onChange={(event) => setRegion(event.target.value)}>
        <option value="cn-beijing">北京</option><option value="singapore">新加坡</option><option value="us-virginia">弗吉尼亚</option>
      </select></label>}
      <label className="demo-choice"><input type="checkbox" checked={local} disabled={busy}
        onChange={(event) => setLocal(event.target.checked)} />本机接口</label>
    </Disclosure>
    <label className="demo-choice"><input type="checkbox" checked={consent} disabled={busy || !available}
      onChange={(event) => setConsent(event.target.checked)} />同意发送学习对话与材料，费用由本人承担</label>
    <Action type="submit" busy={busy} disabled={!available || !secret.trim() || !consent}>保存并启用</Action>
  </form>;
}
