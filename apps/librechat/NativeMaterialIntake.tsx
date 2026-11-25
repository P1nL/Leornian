import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Action, Disclosure, Notice } from './LearningUI';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { materialCommandLookup, materialFileFormat, materialFileIssue, materialProgress } from './native-material-upload.mjs';

type Demand = { id: string; revision: number; goal_id: string };
type Upload = { id: string; state: 'pending' | 'stored' | 'purged' };
type Job = {
  id: string; demand_id: string; revision: number; state: string; phase: string;
  background_deferred?: boolean;
  title: string; document_id: string | null; document_revision: number | null; reason_code: string | null;
  issues: string[]; prepared_scope: { block_count: number; indexed_characters: number } | null;
  steps: { revision: number; state: string; phase: string; reason_code: string | null; created_at: string }[];
};
type Document = {
  document_id: string; revision: number;
  permission: { revision: number; status: string; purposes: string[]; use_until: string | null; retain_until: string | null };
};
type Journal = {
  stage: 'demand_ready' | 'demand_unknown' | 'upload_ready' | 'upload_unknown' | 'bytes_ready' | 'bytes_unknown' | 'job_ready' | 'job_unknown' | 'done';
  keys: { demand: string; upload: string; job: string };
  format: string; digest: string; byteSize: number; filename: string;
  material: object; demand?: Demand; upload?: Upload; job?: Job;
};
const field = 'border-border-medium bg-surface-primary text-text-primary w-full rounded-lg border px-3 py-2 text-sm';
const purposes = [
  ['planning', '学习路线'], ['lesson', '节点课时'], ['teaching', '对话教学'],
  ['item_author', '出题'], ['item_review', '独立审题'],
] as const;
const dateText = (value: string | null) => value ? new Date(value).toLocaleString() : '未设截止';

export default function NativeMaterialIntake({ goalId }: { goalId: string }) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  return state.snapshot ? <MaterialIntake key={`${state.snapshot.actor.id}:${goalId}`}
    actorId={state.snapshot.actor.id} goalId={goalId} epoch={state.epoch} /> : <p role="status">正在读取本人材料状态…</p>;
}

function MaterialIntake({ actorId, goalId, epoch }: { actorId: string; goalId: string; epoch: number }) {
  const storageKey = `leornian.native.material-upload.v1:${actorId}:${goalId}`;
  const [journal, setJournal] = useState<Journal | null>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) ?? 'null'); } catch { return null; }
  });
  const [file, setFile] = useState<File | null>(null), [title, setTitle] = useState('');
  const [authorized, setAuthorized] = useState(false), [allowed, setAllowed] = useState<string[]>([]);
  const [useUntil, setUseUntil] = useState(''), [retainUntil, setRetainUntil] = useState('');
  const [demands, setDemands] = useState<Demand[]>([]), [jobs, setJobs] = useState<Job[]>([]);
  const [documents, setDocuments] = useState<Record<string, Document>>({});
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [progress, setProgress] = useState('');
  const mounted = useRef(true);
  const persist = (next: Journal | null) => {
    if (next) localStorage.setItem(storageKey, JSON.stringify(next)); else localStorage.removeItem(storageKey);
    if (mounted.current) setJournal(next);
  };
  const load = async () => {
    const rows: Demand[] = await nativeRequest(`/v1/material-demands?goal_id=${goalId}&limit=100`);
    const pages: Job[][] = await Promise.all(rows.map((demand) => nativeRequest(`/v1/material-demands/${demand.id}/jobs?limit=100`)));
    if (!mounted.current) return;
    setDemands(rows); setJobs(pages.flat());
    const versions: Record<string, Document> = {};
    for (const job of pages.flat()) if (job.document_id && job.document_revision) {
      versions[job.id] = await nativeRequest(`/v1/documents/${job.document_id}/versions/${job.document_revision}`);
    }
    if (mounted.current) setDocuments(versions);
  };
  useEffect(() => {
    mounted.current = true;
    void load().catch((problem: Error) => { if (mounted.current) setError(problem.message); });
    return () => { mounted.current = false; };
  }, [goalId, epoch]);
  useEffect(() => {
    if (!jobs.some((job) => !job.background_deferred && ['queued', 'parsing', 'processing'].includes(job.state))) return;
    const timer = setTimeout(() => void load().catch((problem: Error) => setError(problem.message)), 2500);
    return () => clearTimeout(timer);
  }, [jobs]);

  const continueUpload = async (existing?: Journal) => {
    if (busy) return;
    setBusy(true); setError('');
    try {
      let current = existing ?? journal;
      let bytes: ArrayBuffer | null = null;
      if (!current) {
        const invalid = materialFileIssue(file);
        if (invalid || !file || !authorized || !title.trim()) throw new Error(invalid || '填写材料名称并明确授权用途。');
        bytes = await file.arrayBuffer();
        const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
          .map((value) => value.toString(16).padStart(2, '0')).join('');
        current = {
          stage: 'demand_ready', format: materialFileFormat(file.name)!, digest,
          byteSize: bytes.byteLength, filename: file.name,
          keys: { demand: crypto.randomUUID(), upload: crypto.randomUUID(), job: crypto.randomUUID() },
          material: { goal_id: goalId, title: title.trim(), format: materialFileFormat(file.name),
            authorized_use: true, purposes: ['reference', 'indexing', ...allowed],
            use_until: useUntil ? new Date(useUntil).toISOString() : null,
            retain_until: retainUntil ? new Date(retainUntil).toISOString() : null },
        };
        persist(current);
      }
      if (current.stage.endsWith('_unknown')) {
        const path = materialCommandLookup(current);
        const key = current.stage === 'demand_unknown' ? current.keys.demand
          : current.stage === 'upload_unknown' ? current.keys.upload : current.keys.job;
        const pending = nativeStore.getSnapshot().pending.find((entry) => entry.key === key);
        const receipt = pending && current.stage !== 'bytes_unknown'
          ? await nativeStore.reconcile(key) : await nativeRequest(path!);
        if (current.stage === 'demand_unknown') current = { ...current, demand: receipt, stage: 'upload_ready' };
        else if (current.stage === 'upload_unknown') current = { ...current, upload: receipt, stage: 'bytes_ready' };
        else if (current.stage === 'job_unknown') current = { ...current, job: receipt, stage: 'done' };
        else {
          if (receipt.state !== 'stored') throw new Error('原文件上传尚未确认，保留原上传票据；稍后读取原状态。');
          current = { ...current, upload: receipt, stage: 'job_ready' };
        }
        persist(current);
      }
      if (current.stage === 'demand_ready') {
        setProgress('正在登记原文准备需求'); current = { ...current, stage: 'demand_unknown' }; persist(current);
        const demand = await nativeStore.write('/v1/material-demands', {
          goal_id: goalId, purpose: 'reference', scope_mode: 'whole_source', required_facets: [],
        }, { key: current.keys.demand, lookup: materialCommandLookup(current)! });
        current = { ...current, demand, stage: 'upload_ready' }; persist(current);
      }
      if (current.stage === 'upload_ready') {
        setProgress('正在登记文件与明确用途'); current = { ...current, stage: 'upload_unknown' }; persist(current);
        const upload = await nativeStore.write(`/v1/material-demands/${current.demand!.id}/uploads`, {
          expected_demand_revision: current.demand!.revision, material: current.material,
          content_digest: current.digest, byte_size: current.byteSize,
        }, { key: current.keys.upload, lookup: materialCommandLookup(current)! });
        current = { ...current, upload, stage: 'bytes_ready' }; persist(current);
      }
      if (current.stage === 'bytes_ready') {
        if (!bytes) {
          if (!file) throw new Error(`选择同一原文件「${current.filename}」后继续上传。`);
          bytes = await file.arrayBuffer();
          const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
            .map((value) => value.toString(16).padStart(2, '0')).join('');
          if (digest !== current.digest || bytes.byteLength !== current.byteSize) throw new Error('选择的文件与原上传票据不一致。');
        }
        setProgress('正在上传原文件'); current = { ...current, stage: 'bytes_unknown' }; persist(current);
        const upload = await nativeRequest(`/v1/material-uploads/${current.upload!.id}/content`, {
          method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: bytes,
        });
        current = { ...current, upload, stage: 'job_ready' }; persist(current);
      }
      if (current.stage === 'job_ready') {
        setProgress('正在交给后台解析与准备'); current = { ...current, stage: 'job_unknown' }; persist(current);
        const job = await nativeStore.write(`/v1/material-demands/${current.demand!.id}/files`, {
          expected_demand_revision: current.demand!.revision, upload_id: current.upload!.id,
        }, { key: current.keys.job, lookup: materialCommandLookup(current)! });
        current = { ...current, job, stage: 'done' }; persist(current);
      }
      if (current.stage === 'done') {
        setProgress('原文件已交给后台，解析、识别、检查与索引按真实状态推进。');
        persist(null); setFile(null); setAuthorized(false); await load();
      }
    } catch (problem) { if (mounted.current) setError((problem as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  };

  const command = async (job: Job, revoke = false) => {
    if (busy) return;
    setBusy(true); setError('');
    const version = documents[job.id], key = crypto.randomUUID();
    const root = `/v1/documents/${job.document_id}/versions/${job.document_revision}`;
    try {
      await nativeStore.write(revoke ? `${root}/permissions` : `/v1/material-jobs/${job.id}/cancel`,
        revoke ? { action: 'revoke', expected_revision: version.permission.revision } : {},
        { key, lookup: revoke ? `${root}/revocation` : `/v1/material-jobs/${job.id}/cancellation` });
      await load();
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };

  return <section aria-label="上传与准备教材" className="space-y-4">
    {error && <Notice>{error}</Notice>}
    {progress && <p role="status" className="text-sm">{progress}</p>}
    {journal && <Notice>已保留原上传步骤：{journal.filename}。
      <Action disabled={busy} onClick={() => void continueUpload()}>
        {journal.stage.endsWith('_unknown') ? '读取原提交并继续' : '继续原上传'}
      </Action>
    </Notice>}
    <Disclosure title="上传教材文件" defaultOpen={!demands.length}>
      <div className="space-y-3">
        <label className="block space-y-2 text-sm"><span>原文件</span>
          <input type="file" accept=".pdf,.docx,.txt,.md,.markdown,.html,.htm,.png,.jpg,.jpeg"
            disabled={busy} onChange={(event) => {
              const next = event.target.files?.[0] ?? null; setFile(next);
              if (!journal) setTitle(next?.name.replace(/\.[^.]+$/, '').slice(0, 160) ?? '');
              setError(next ? materialFileIssue(next) : '');
            }} /></label>
        {!journal && <>
          <label className="block space-y-2 text-sm"><span>材料名称</span>
            <input className={field} value={title} maxLength={160} onChange={(event) => setTitle(event.target.value)} /></label>
          <fieldset className="space-y-2 text-sm"><legend>允许使用的学习环节</legend>
            {purposes.map(([purpose, label]) => <label key={purpose} className="mr-4 inline-flex items-center gap-1">
              <input type="checkbox" checked={allowed.includes(purpose)} onChange={(event) => setAllowed((previous) =>
                event.target.checked ? [...previous, purpose] : previous.filter((value) => value !== purpose))} />{label}
            </label>)}
          </fieldset>
          <p className="demo-muted">上传授权包含本人查阅、正文提取与索引；需要的图片或扫描页面会经已配置OCR处理。</p>
          <label className="block space-y-2 text-sm"><span>使用截止（留空为未设截止）</span>
            <input className={field} type="datetime-local" value={useUntil} onChange={(event) => setUseUntil(event.target.value)} /></label>
          <label className="block space-y-2 text-sm"><span>保留截止（留空为未设截止）</span>
            <input className={field} type="datetime-local" value={retainUntil} onChange={(event) => setRetainUntil(event.target.value)} /></label>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={authorized}
            onChange={(event) => setAuthorized(event.target.checked)} />
            我有权使用该材料，并允许按所选用途处理、经本人配置的模型识别和索引。</label>
          <Action disabled={busy || !file || !authorized || !title.trim() || Boolean(materialFileIssue(file))}
            onClick={() => void continueUpload()}>上传并准备原文</Action>
        </>}
      </div>
    </Disclosure>
    {!jobs.length && <p className="demo-muted">当前目标还没有文件准备任务。</p>}
    {jobs.map((job) => {
      const version = documents[job.id];
      const pending = nativeStore.getSnapshot().pending.filter((entry) =>
        entry.path === `/v1/material-jobs/${job.id}/cancel` ||
        entry.path === `/v1/documents/${job.document_id}/versions/${job.document_revision}/permissions`);
      return <article key={job.id} className="border-border-light space-y-2 border-b py-3">
        <h3 className="text-sm font-medium">{job.title}</h3>
        <p role="status" className="text-sm">{materialProgress(job)} · {job.phase}</p>
        {job.reason_code && <p className="demo-muted">{job.reason_code}</p>}
        {job.issues.map((issue) => <p key={issue} className="demo-muted">{issue}</p>)}
        {job.prepared_scope && <p className="text-sm">已准备原文：{job.prepared_scope.block_count} 块 · {job.prepared_scope.indexed_characters} 字符</p>}
        {version && <p className="demo-muted">用途：{version.permission.purposes.join('、')} · {version.permission.status === 'revoked' ? '已撤回' : '已授权'}
          <br />使用截止：{dateText(version.permission.use_until)} · 保留截止：{dateText(version.permission.retain_until)}</p>}
        <div className="flex flex-wrap gap-2">
          {job.state !== 'cancelled' && <Action disabled={busy || pending.length > 0} onClick={() => void command(job)}>取消准备</Action>}
          {version?.permission.status === 'allowed' && <Action disabled={busy || pending.length > 0}
            onClick={() => void command(job, true)}>撤回此版本用途许可</Action>}
          <Action disabled={busy} onClick={() => void load().catch((problem: Error) => setError(problem.message))}>读取当前状态</Action>
        </div>
        {pending.map((entry) => <Notice key={entry.key}>原动作尚待核对。
          <Action onClick={() => void nativeStore.reconcile(entry.key).then(load).catch((problem: Error) => setError(problem.message))}>读取原动作回执</Action>
        </Notice>)}
        <Disclosure title="处理经过"><ol className="space-y-1 text-xs">
          {job.steps.map((step) => <li key={step.revision}>{new Date(step.created_at).toLocaleString()} · {materialProgress(step)} · {step.phase}{step.reason_code ? ` · ${step.reason_code}` : ''}</li>)}
        </ol></Disclosure>
      </article>;
    })}
  </section>;
}
