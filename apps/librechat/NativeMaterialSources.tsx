import { useEffect, useState, useSyncExternalStore } from 'react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import { nativeRequest, nativeStore } from './native-client.mjs';

type Source = components['schemas']['MaterialSource'];
type Observation = components['schemas']['MaterialSourceObservation'];
type Input = components['schemas']['MaterialSourceInput'];
const root = '/v1/material-sources';
const field = 'border-border-medium bg-surface-primary text-text-primary w-full rounded-lg border px-3 py-2 text-sm';
const purposes = [
  ['planning', '学习路线'], ['lesson', '节点课时'], ['teaching', '对话教学'],
  ['item_author', '出题'], ['item_review', '独立审题'],
] as const;
const statuses: Record<Observation['status'], string> = {
  queued: '等待检查', fetching: '正在读取原文', processing: '正在比较来源内容',
  unchanged: '原文未变化', noise_only: '只发现排版等非教学变化', changed: '已记录教学内容变化',
  waiting_config: '等待本人模型配置', waiting_dependency: '等待来源或材料依赖',
  blocked_unknown: '原结果未知，保留原检查', cancelled: '检查已取消',
};
const terminal = new Set(['unchanged', 'noise_only', 'changed', 'blocked_unknown', 'cancelled']);
const deadline = (value: string) => value ? new Date(value).toISOString() : null;
const lines = (value: string) => [...new Set(value.split('\n').map((line) => line.trim()).filter(Boolean))];

export default function NativeMaterialSources({ goalId }: { goalId: string }) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  return state.snapshot ? <MaterialSources key={`${state.snapshot.actor.id}:${goalId}`}
    actorId={state.snapshot.actor.id} goalId={goalId} epoch={state.epoch} />
    : <p role="status">正在读取本人来源授权…</p>;
}

function MaterialSources({ actorId, goalId, epoch }: { actorId: string; goalId: string; epoch: number }) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const storageKey = `leornian.native.material-source-observations.v1:${actorId}:${goalId}`;
  const [ids, setIds] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) ?? '{}'); } catch { return {}; }
  });
  const [sources, setSources] = useState<Source[]>([]), [observations, setObservations] = useState<Record<string, Observation>>({});
  const [title, setTitle] = useState(''), [url, setUrl] = useState(''), [prefixes, setPrefixes] = useState('');
  const [allowed, setAllowed] = useState<Input['purposes']>([]), [authorized, setAuthorized] = useState(false);
  const [discover, setDiscover] = useState(false), [language, setLanguage] = useState(''), [languageVersion, setLanguageVersion] = useState('');
  const [framework, setFramework] = useState(''), [frameworkVersion, setFrameworkVersion] = useState('');
  const [useUntil, setUseUntil] = useState(''), [retainUntil, setRetainUntil] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const pending = state.pending.filter((entry) => entry.path === root || entry.path.startsWith(`${root}/`));
  const load = async () => setSources(await nativeRequest(`${root}?goal_id=${goalId}`));
  useEffect(() => {
    let current = true;
    void nativeRequest(`${root}?goal_id=${goalId}`).then((value) => {
      if (current) setSources(value);
    }).catch((problem: Error) => { if (current) setError(problem.message); });
    return () => { current = false; };
  }, [goalId, epoch]);
  useEffect(() => {
    let current = true, timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const values: Observation[] = await Promise.all(Object.values(ids).map((id) =>
          nativeRequest(`/v1/material-source-observations/${id}`)));
        if (!current) return;
        setObservations(Object.fromEntries(values.map((value) => [value.source_id, value])));
        if (values.some((value) => !terminal.has(value.status))) {
          timer = setTimeout(() => void refresh(), 2500);
        }
      } catch (problem) { if (current) setError((problem as Error).message); }
    };
    if (Object.keys(ids).length) void refresh();
    return () => { current = false; clearTimeout(timer); };
  }, [ids, epoch]);
  const remember = (value: Source | Observation) => {
    if ('source_id' in value) {
      setObservations((previous) => ({ ...previous, [value.source_id]: value }));
      setIds((previous) => {
        const next = { ...previous, [value.source_id]: value.id };
        localStorage.setItem(storageKey, JSON.stringify(next));
        return next;
      });
    }
  };
  const write = async (path: string, body: object, lookup: (key: string) => string) => {
    if (busy || pending.length) return false;
    setBusy(true); setError('');
    const key = crypto.randomUUID();
    try {
      remember(await nativeStore.write(path, body, { key, lookup: lookup(key) }));
      await load();
      return true;
    } catch (problem) { setError((problem as Error).message); return false; }
    finally { setBusy(false); }
  };
  const register = async () => {
    const scope = lines(prefixes);
    if (!authorized || !title.trim() || !url.trim() || !scope.length || !allowed.length) return;
    try {
      const body: Input = {
        goal_id: goalId, title: title.trim(), entry_url: url.trim(), allowed_prefixes: scope,
        authorized_use: true, purposes: ['reference', 'indexing', ...allowed],
        discover_links: discover, use_until: deadline(useUntil), retain_until: deadline(retainUntil),
        language: language.trim() || null, language_version: languageVersion.trim() || null,
        framework: framework.trim() || null, framework_version: frameworkVersion.trim() || null,
        topics: [],
      };
      if (await write(root, body, (key) => `${root}/commands/${key}`)) {
        setTitle(''); setUrl(''); setPrefixes(''); setAuthorized(false);
      }
    } catch (problem) { setError((problem as Error).message); }
  };
  return <section aria-label="受控教材来源" className="demo-stack">
    <Disclosure title="登记可读取的教材来源">
      <div className="space-y-3">
        <label className="block text-sm">来源名称<input className={field} maxLength={160} value={title}
          onChange={(event) => setTitle(event.target.value)} /></label>
        <label className="block text-sm">原文入口 URL<input className={field} type="url" maxLength={2048}
          value={url} onChange={(event) => setUrl(event.target.value)} /></label>
        <label className="block text-sm">允许读取的 URL 前缀（每行一个，最多20个）
          <textarea className={field} rows={3} value={prefixes} onChange={(event) => setPrefixes(event.target.value)} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={discover}
          onChange={(event) => setDiscover(event.target.checked)} />允许在以上前缀内发现相关链接</label>
        <fieldset className="space-y-2 text-sm"><legend>来源允许使用的学习环节</legend>
          {purposes.map(([purpose, label]) => <label key={purpose} className="mr-4 inline-flex items-center gap-1">
            <input type="checkbox" checked={allowed.includes(purpose)} onChange={(event) => setAllowed((previous) =>
              event.target.checked ? [...previous, purpose] : previous.filter((value) => value !== purpose))} />{label}
          </label>)}
        </fieldset>
        <Disclosure title="本人明确指定的语言与框架版本（可选）">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">语言<input className={field} value={language} maxLength={80} onChange={(event) => setLanguage(event.target.value)} /></label>
            <label className="text-sm">语言版本<input className={field} value={languageVersion} maxLength={80} onChange={(event) => setLanguageVersion(event.target.value)} /></label>
            <label className="text-sm">框架<input className={field} value={framework} maxLength={100} onChange={(event) => setFramework(event.target.value)} /></label>
            <label className="text-sm">框架版本<input className={field} value={frameworkVersion} maxLength={80} onChange={(event) => setFrameworkVersion(event.target.value)} /></label>
          </div>
        </Disclosure>
        <label className="block text-sm">来源使用截止（留空为未设截止）<input className={field} type="datetime-local"
          value={useUntil} onChange={(event) => setUseUntil(event.target.value)} /></label>
        <label className="block text-sm">来源保留截止（留空为未设截止）<input className={field} type="datetime-local"
          value={retainUntil} onChange={(event) => setRetainUntil(event.target.value)} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={authorized}
          onChange={(event) => setAuthorized(event.target.checked)} />
          我有权使用该来源，允许按上述前缀和用途读取、提取与索引，包括经本人配置并授权的模型处理私有材料。</label>
        <Action disabled={busy || pending.length > 0 || !authorized || !title.trim() ||
          !url.trim() || lines(prefixes).length === 0 || lines(prefixes).length > 20 || !allowed.length ||
          Boolean(languageVersion.trim() && !language.trim() || frameworkVersion.trim() && !framework.trim())}
          onClick={() => void register()}>登记来源授权</Action>
      </div>
    </Disclosure>
    {error && <Notice>{error}</Notice>}
    {pending.map((entry) => <Notice key={entry.key}>原来源命令尚待核对。
      <Action disabled={busy} onClick={() => {
        setBusy(true); setError('');
        void nativeStore.reconcile(entry.key).then(async (receipt) => {
          remember(receipt); await load();
        }).catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
      }}>读取原来源命令回执</Action>
    </Notice>)}
    {sources.map((source) => {
      const observation = observations[source.id];
      return <article className="demo-task-row" key={source.id}>
        <h3>{source.title} · {source.admission === 'allowed' ? '已授权来源' : '已撤销来源授权'}</h3>
        <p className="demo-muted break-all">{source.entry_url}</p>
        <p className="demo-muted">允许前缀：{source.allowed_prefixes.join(' · ')}</p>
        <p className="demo-muted">用途：{source.purposes.join(' · ')}</p>
        <p className="demo-muted">使用至 {source.use_until ? new Date(source.use_until).toLocaleString() : '未设截止'}
          {' · '}保留至 {source.retain_until ? new Date(source.retain_until).toLocaleString() : '未设截止'}</p>
        {observation && <div role="status" className="space-y-1 text-sm">
          <p>来源检查：{statuses[observation.status]}</p>
          {observation.job_id && <p>原文准备任务：{observation.job_id}</p>}
          {observation.document_id && <p>已记录文档版本 {observation.document_revision}</p>}
          {observation.error_code && <p>{observation.error_code}</p>}
        </div>}
        {source.admission === 'allowed' && <div className="demo-actions">
          <Action disabled={busy || pending.length > 0 || Boolean(observation &&
            (!terminal.has(observation.status) || observation.status === 'blocked_unknown'))}
            onClick={() => void write(`${root}/${source.id}/checks`, { expected_revision: source.revision },
              (key) => `${root}/${source.id}/checks/${key}`)}>检查来源更新</Action>
          <Action disabled={busy || pending.length > 0} onClick={() => void write(
            `${root}/${source.id}/revoke`, { expected_revision: source.revision },
            () => `${root}/${source.id}/revocation`,
          )}>撤销此来源授权</Action>
        </div>}
        {observation && <Action disabled={busy} onClick={() => {
          setBusy(true); setError('');
          void nativeRequest(`/v1/material-source-observations/${observation.id}`)
            .then((value: Observation) => setObservations((previous) => ({ ...previous, [source.id]: value })))
            .catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
        }}>读取原来源检查</Action>}
      </article>;
    })}
    {!sources.length && <p className="demo-muted">当前目标尚未登记受控教材来源。</p>}
  </section>;
}
