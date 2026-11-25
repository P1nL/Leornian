import { useState } from 'react';
import { Play, Plug, Save } from 'lucide-react';
import { Action, DemoDialog, Disclosure, Notice, useDemo } from './DemoUI';
import { demoStore } from './demo-state.mjs';

const providers = [
  {
    id: 'qwen',
    label: '千问 · 北京（演示）',
    baseUrl: 'https://dashscope.aliyuncs.com',
    protocol: 'DashScope',
    region: 'cn-beijing',
  },
  {
    id: 'compatible',
    label: 'OpenAI 兼容（演示）',
    baseUrl: 'https://model-provider.example/v1',
    protocol: 'Chat Completions',
    region: 'custom',
  },
];

const fieldClass =
  'border-border-medium bg-surface-primary text-text-primary w-full min-w-0 rounded-lg border px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2';

function SampleField({ id, label, value, onChange, disabled = false }: {
  id: string; label: string; value: string; onChange?: (value: string) => void; disabled?: boolean;
}) {
  return (
    <label htmlFor={id} className="text-text-primary flex min-w-0 flex-col gap-1.5 text-sm">
      {label}
      <input id={id} className={fieldClass} value={value} readOnly={!onChange} disabled={disabled}
        onChange={(event) => onChange?.(event.target.value)} />
    </label>
  );
}

export default function ModelConfigurationPreview() {
  const models = useDemo().models;
  const providerId = models.providerId ?? providers[0].id;
  const provider = providers.find((item) => item.id === providerId)!;
  const [testOpen, setTestOpen] = useState(false);
  const [testAgreed, setTestAgreed] = useState(false);
  const [outcome, setOutcome] = useState('available');
  const busy = models.state === 'testing';
  const setField = (id: string, value: string) => demoStore.patch('models', {
    fields: { ...models.fields, [id]: value }, saved: false, state: 'unconfigured',
  });
  const field = (id: string, label: string, fallback: string) => <SampleField id={id} label={label}
    value={models.fields?.[id] ?? fallback} disabled={busy} onChange={(value) => setField(id, value)} />;
  const invalidate = (action: string) => {
    demoStore.getSnapshot().tasks.filter((task: any) => task.artifactId === 'models' && task.state === 'running')
      .forEach((task: any) => demoStore.cancelTask(task.id));
    demoStore.patch('models', { credential: false, saved: false, state: 'unconfigured',
      history: [...models.history, { action, revision: models.revision ?? 0 }] });
  };

  return (
    <section aria-label="模型配置演示" className="learning-demo min-w-0 space-y-5" data-learning-demo>
      <p className="text-text-secondary text-sm leading-relaxed" role="status">
        前端交互演示，尚未连接真实模型。不接收真实密钥；下面只保存非秘密样例字段和状态到当前标签页。
      </p>
      <div className="space-y-4">
        <label htmlFor="preview-model-provider" className="text-text-primary flex flex-col gap-1.5 text-sm">
          模型提供方
          <select
            id="preview-model-provider"
            className={fieldClass}
            value={providerId}
            disabled={busy}
            onChange={(event) => demoStore.patch('models', { providerId: event.target.value, fields: {}, saved: false, state: 'unconfigured' })}
          >
            {providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        {field('preview-model-base-url', 'API 地址', provider.baseUrl)}
        <label htmlFor="preview-model-api-key" className="text-text-primary flex flex-col gap-1.5 text-sm">
          API Key
          <input
            id="preview-model-api-key"
            type="password"
            autoComplete="off"
            className={fieldClass}
            placeholder={models.credential ? '示例凭据已占位 · 不是真实密钥' : '未配置 · 演示中请勿填写真实密钥'}
            disabled
            aria-describedby="preview-model-key-note"
          />
        </label>
        <p id="preview-model-key-note" className="text-text-secondary text-xs leading-relaxed">
          正式接入后由本人填写，密钥只交给本机凭据入口，不在浏览器持久保存或回显。
        </p>
        <Action disabled={busy || models.credential} onClick={() => demoStore.patch('models', { credential: true })}>使用示例凭据占位</Action>
        {field('preview-teaching-model', '教学模型', providerId === 'qwen' ? 'qwen-plus（样例）' : 'teaching-model（样例）')}
        <p className="text-text-secondary text-xs leading-relaxed">
          日常教学、路线规划、课时和讲评使用推荐的职责配置；不需要逐个配置内部角色。
        </p>
      </div>
      <Disclosure title="材料处理模型（按需配置）">
        <div className="mt-4 space-y-4">
          <p className="text-text-secondary text-xs leading-relaxed">
            同一提供方可复用本人凭据。以下名称仅演示字段，不表示模型可用或已经授权。
          </p>
          {field('preview-ocr-model', 'OCR / 图文识别', 'qwen3.5-ocr（样例）')}
          {field('preview-embedding-model', '向量模型', 'qwen3.7-text-embedding（样例）')}
          {field('preview-rerank-model', '重排序模型', 'qwen3.7-text-rerank（样例）')}
          <label className="text-text-secondary flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={models.allowMaterial ?? false} disabled={busy}
              onChange={(event) => demoStore.patch('models', { allowMaterial: event.target.checked })} />
            体验私有材料用途授权选项（不会外发材料）
          </label>
        </div>
      </Disclosure>
      <Disclosure title="高级设置">
        <div className="mt-4 space-y-4">
          <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
            <SampleField id="preview-model-protocol" label="连接协议" value={provider.protocol} />
            <SampleField id="preview-model-region" label="账号 / 通道区域" value={provider.region} />
            {field('preview-context-tokens', '上下文容量（样例）', '128000')}
            {field('preview-output-tokens', '输出预留（样例）', '8192')}
          </div>
          {field('preview-model-timeout', '超时（秒，样例）', '300')}
          <p className="text-text-secondary text-xs leading-relaxed">
            职责映射示例：教学、路线规划、课时正文和独立检查使用教学模型。
            正式接入保留各职责的独立配置与版本，不从演示产生调用权限。
          </p>
        </div>
      </Disclosure>
      <div className="border-border-light flex flex-wrap gap-2 border-t pt-4">
        <Action primary icon={Save} completed={models.saved} disabled={busy || !models.credential}
          onClick={() => demoStore.patch('models', { saved: true, revision: (models.revision ?? 0) + 1, state: 'saved',
            history: [...models.history, { action: '保存演示配置', revision: (models.revision ?? 0) + 1 }] })}>{models.saved ? '已保存' : '保存配置'}</Action>
        <Action important icon={Plug} busy={busy} completed={models.state === 'available'}
          phase={models.state === 'unknown' ? 'unknown' : models.state === 'failed' ? 'attention' : undefined}
          disabled={!models.saved || busy || models.state === 'unknown'}
          onClick={() => { setTestAgreed(false); setTestOpen(true); }}>{busy ? '测试中' : '模拟连接测试'}</Action>
        <Action disabled={!models.credential} onClick={() => invalidate('轮换示例凭据')}>轮换示例凭据</Action>
        <Action disabled={!models.credential} onClick={() => invalidate('撤销示例凭据')}>撤销示例凭据</Action>
      </div>
      <Notice>当前样例状态：{({ unconfigured: '未配置', saved: '已保存演示配置，尚未测试', testing: '正在模拟测试', available: '成功结果样例（未真实连通）', failed: '失败结果样例', unknown: '结果未知，保留旧记录且不自动重发', cancelled: '已取消演示测试' })[models.state]}</Notice>
      <p className="text-text-secondary text-xs leading-relaxed">
        正式接入后，保存不自动测试；只有明确同意后才发起可能计费的连接测试。
      </p>
      {models.history.length > 0 && <Disclosure title={`配置与测试历史 · ${models.history.length}`}>
        {models.history.map((entry: any, index: number) => <p key={index}>版本 {entry.revision}：{entry.action}</p>)}</Disclosure>}
      <DemoDialog open={testOpen} onClose={() => setTestOpen(false)} title="显式连接测试的确认样例">
        <p>正式连接测试可能调用本人模型并计费。当前只模拟界面过程，不发送任何请求。</p>
        <label>要查看的结果分支<select aria-label="测试结果样例" value={outcome} onChange={(event) => setOutcome(event.target.value)}>
          <option value="available">成功结果</option><option value="failed">提供方拒绝</option><option value="unknown">结果未知</option>
        </select></label>
        <label className="demo-choice"><input type="checkbox" checked={testAgreed} onChange={(event) => setTestAgreed(event.target.checked)} />
          <span>我理解保存不自动测试，愿意体验这次前端模拟。</span></label>
        <Action primary icon={Play} disabled={!testAgreed} onClick={() => {
          demoStore.patch('models', { state: 'testing' });
          demoStore.task('models', '模型连接测试（界面模拟）', { state: outcome === 'available' ? 'completed' : outcome }, () => {
            const latest = demoStore.getSnapshot().models;
            demoStore.patch('models', { state: outcome, history: [...latest.history, { action: `测试结果样例：${outcome}`, revision: latest.revision }] });
          });
          setTestOpen(false);
        }}>确认并模拟测试</Action>
      </DemoDialog>
    </section>
  );
}
