import { useEffect, useRef, useState } from 'react';
import type { components } from '@leornian/api-contracts';
import ApiKeyInput from './CCSApiKeyInput';
import { Action, Disclosure, Notice } from './LearningUI';
import { nativeRequest } from './native-client.mjs';

type Configuration = components['schemas']['TavilyConfiguration'];

export default function NativeTavilySettings({ available }: { available: boolean }) {
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [secret, setSecret] = useState(''), [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const submitting = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    void nativeRequest('/v1/material-search-configuration', { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) { setConfiguration(value); setEnabled(value.enabled); } })
      .catch((problem: Error) => { if (!controller.signal.aborted) setError(problem.message); });
    return () => controller.abort();
  }, []);
  return <Disclosure title="教材搜索 · Tavily">
    <form className="native-models-form ccs-preset-form" aria-label="Tavily 教材搜索配置" onSubmit={(event) => {
      event.preventDefault();
      if (submitting.current || !configuration || !available || (!secret.trim() && !configuration.credential_present)) return;
      submitting.current = true; setBusy(true); setError(''); setNotice('');
      const key = secret.trim(); setSecret('');
      void nativeRequest('/v1/material-search-configuration', {
        method: 'PUT', body: JSON.stringify({
          expected_revision: configuration.revision, enabled, ...(key ? { api_key: key } : {}),
        }),
      }).then((value) => {
        setConfiguration(value); setEnabled(value.enabled); setNotice('Tavily 配置已保存。');
      }).catch((problem: Error) => setError(problem.message))
        .finally(() => { submitting.current = false; setBusy(false); });
    }}>
      <p>优先复用已有资料，仅为缺少的主题搜索并提取已授权来源的公开正文。</p>
      <ApiKeyInput id="tavily-material-key" value={secret} onChange={setSecret}
        label="Tavily API Key" disabled={busy || !available}
        required={!configuration?.credential_present} />
      <label className="demo-choice"><input type="checkbox" checked={enabled}
        disabled={busy || !available} onChange={(event) => setEnabled(event.target.checked)} />
        启用 Tavily，允许发送检索主题及公开资料网址，费用由本人承担</label>
      <Action type="submit" busy={busy} disabled={busy || !configuration || !available ||
        (!secret.trim() && !configuration.credential_present)}>保存教材搜索配置</Action>
      {notice && <p role="status">{notice}</p>}
      {error && <Notice>{error}</Notice>}
    </form>
  </Disclosure>;
}
