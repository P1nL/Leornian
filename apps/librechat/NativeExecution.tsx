import { useEffect, useState, useSyncExternalStore } from 'react';
import { RefreshCw } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import { NativeApiError, nativeRequest, nativeStore } from './native-client.mjs';
import './native-models.css';

type Overview = components['schemas']['ExecutionEnvironments'];
type Demand = components['schemas']['EnvironmentDemand'];
type Requirement = components['schemas']['EnvironmentRequirement'];
type Decision = components['schemas']['EnvironmentDecisionInput']['decision'];
type LocalState = {
  application: string; controller: string; frontend: string; frontend_url: string;
  engine: { status: string; detail: string };
};
type LocalInvoke = (command: string, arguments_: { action: string }) => Promise<LocalState>;
function localInvoke(): LocalInvoke | undefined {
  return (window as Window & { __TAURI_INTERNALS__?: { invoke?: LocalInvoke } }).__TAURI_INTERNALS__?.invoke;
}
const labels: Record<Demand['status'], string> = {
  waiting_authorization: '等待你允许', waiting_engine: '等待本机隔离引擎',
  queued: '等待准备', preparing: '下载 / 构建中', verifying: '正在实际验证',
  ready: '环境已就绪', deferred: '稍后准备', declined: '已拒绝安装', revoked: '已撤销使用',
  failed: '准备未完成', blocked_unknown: '准备结果未知，保留原任务',
};
function failure(error: unknown) {
  if (error instanceof NativeApiError) {
    if (error.code === 'stale_version') return '需求或决定已更新。请重新读取，再按当前版本决定。';
    if (error.code === 'precondition_failed') return '先允许当前需求并完成实际准备，再使用这个环境。';
    if (error.status === 404) return '当前后台尚未提供该环境或命令回执，请核对本机后台版本和当前身份。';
    return error.message;
  }
  return error instanceof Error ? error.message : '连接中断；请核对原提交回执。';
}

export default function NativeExecution() {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot, nativeStore.getSnapshot);
  return <EnvironmentManager key={state.snapshot?.actor.id ?? 'unloaded'} />;
}

export function RequirementDetails({ requirement }: { requirement: Requirement }) {
  const services = requirement.services ?? [];
  return <div className="native-models-endpoint">
    <p>工具链：{requirement.toolchains.join('、')}</p>
    <p>依赖锁：{requirement.dependency_lock.length ? requirement.dependency_lock.join('、') : '本配方不另加课程第三方库'}</p>
    <p>准备范围：仅在本应用的 Docker 镜像和专用卷中下载、构建和验证；不修改全局 SDK。学习者运行时无互联网。</p>
    <p>版本：配方固定语言系列和依赖锁，成品冻结实际版本与镜像。同范围恢复复用缓存，扩大依赖或权限重新确认。</p>
    <p>下载 / 磁盘估算：{typeof requirement.estimated_download_bytes !== 'number' || typeof requirement.estimated_disk_bytes !== 'number'
      ? '来源尚未提供可靠估算，实际下载前不编造用量。'
      : `${requirement.estimated_download_bytes} / ${requirement.estimated_disk_bytes} 字节`}</p>
    <p>准备来源：{[...new Set(requirement.sources)].join('、')}</p>
    <p>本地服务：{services.length ? services.join('、') : '不新增课程服务'}。公开依赖不自动开通付费服务。</p>
  </div>;
}

function EnvironmentManager() {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot, nativeStore.getSnapshot);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [local, setLocal] = useState<LocalState | null>(null);
  const [selectedRecipe, setSelectedRecipe] = useState('');
  const [selectedPlan, setSelectedPlan] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const pending = state.pending.filter((item) => item.path.includes('/environment-demands'));
  const blocked = busy || pending.length > 0;
  const plans = state.snapshot?.plans.filter((plan) => plan.active) ?? [];
  const requirement = overview?.recipes.find((item) => item.recipe_id === selectedRecipe);
  const refresh = async () => {
    try {
      setOverview(await nativeRequest('/v1/execution-environments'));
      if (localInvoke()) setLocal(await localInvoke()!('local_services', { action: 'status' }));
      setError('');
    } catch (problem) { setError(failure(problem)); }
  };
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const write = async (path: string, body: object, lookup: (key: string) => string) => {
    setBusy(true); setError(''); setMessage('');
    const key = crypto.randomUUID();
    try {
      await nativeStore.write(path, body, { key, lookup: lookup(key) });
      await refresh(); setMessage('决定已记录，准备与实际可用状态显示在环境需求中。');
    } catch (problem) { setError(failure(problem)); }
    finally { setBusy(false); }
  };
  const request = () => {
    if (!requirement) return;
    const existing = overview?.demands.find((item) =>
      item.plan_id === (selectedPlan || null)
      && item.requirement.profile === requirement.profile
      && item.requirement.language === requirement.language
      && item.requirement.dialect === requirement.dialect);
    const plan = plans.find((item) => item.id === selectedPlan);
    return write('/v1/environment-demands', {
      recipe_id: requirement.recipe_id, plan_id: plan?.id ?? null,
      plan_revision: plan?.active?.revision ?? null,
      expected_requirement_revision: existing?.requirement_revision ?? 0,
    }, (key) => `/v1/environment-demand-requests/${key}`);
  };
  const decide = (demand: Demand, decision: Decision) => write(
    `/v1/environment-demands/${demand.id}/decisions`, {
      decision, expected_requirement_revision: demand.requirement_revision,
      expected_decision_revision: demand.decision_revision,
    }, (key) => `/v1/environment-demands/${demand.id}/decisions/${key}`,
  );
  const rebuild = (demand: Demand) => write(`/v1/environment-demands/${demand.id}/rebuild`, {
    expected_requirement_revision: demand.requirement_revision,
    expected_decision_revision: demand.decision_revision,
  }, (key) => `/v1/environment-demands/${demand.id}/rebuilds/${key}`);
  const management = async (action: string) => {
    setBusy(true); setError('');
    try {
      const result = await localInvoke()!('local_services', { action });
      if (result.application) setLocal(result);
      await refresh();
    } catch (problem) { setError(failure(problem)); }
    finally { setBusy(false); }
  };
  return <section className="native-models" aria-label="本机执行与课程环境">
    <header className="native-models-heading">
      <div><h2>本机执行</h2><p>应用后台、隔离引擎、课程环境分别检查；课程按需求准备。</p></div>
      <Action icon={RefreshCw} disabled={busy} onClick={() => { void refresh(); }}>重新读取</Action>
    </header>
    {error && <Notice>{error}</Notice>}
    {message && <Notice>{message}</Notice>}
    <dl className="native-models-test-list">
      <div className="native-models-assignment"><dt>应用后台</dt><dd>{local
        ? `本应用服务${local.application === 'ready' ? '已就绪' : '尚未运行'}；控制器${local.controller === 'running' ? '已连接' : '未运行'}`
        : overview ? '当前本机 API 已连接；桌面应用管理各本机服务。' : '正在核对本机后台'}</dd></div>
      <div className="native-models-assignment"><dt>本机隔离引擎</dt><dd>{overview?.engine.detail ?? local?.engine?.detail ?? '正在检查'}<br />
        {overview?.engine.version && <small>Docker {overview.engine.version} · {overview.engine.operating_system}</small>}</dd></div>
      <div className="native-models-assignment"><dt>课程环境</dt><dd>{overview
        ? `${overview.demands.filter((item) => item.status === 'ready').length} 个当前就绪环境；基础环境自动准备，课程额外环境经你允许后安装。`
        : '先连接当前后台，再读取你本人的环境需求。'}</dd></div>
    </dl>
    {localInvoke() && <div className="native-models-connection-actions">
      <Action disabled={busy} onClick={() => { void management('start'); }}>启动本机服务</Action>
      <Action disabled={busy} onClick={() => { void management('stop'); }}>停止本机服务</Action>
      <Action disabled={busy} onClick={() => { void management('engine_start'); }}>启动已有隔离引擎</Action>
      <Action disabled={busy} onClick={() => { void management('engine_guide'); }}>查看官方安装说明</Action>
    </div>}
    {overview?.engine.status === 'missing' && <Notice>首次安装 Docker 需要你在系统安装器中明确允许权限与重启；应用不会自动安装系统组件。</Notice>}
    {pending.map((item) => <div key={item.key} className="native-models-connection-actions">
      <span>原提交{item.status === 'unknown' ? '结果未知' : '正在确认'}；只查询原 key 回执。</span>
      <Action disabled={busy} onClick={() => {
        setBusy(true);
        void nativeStore.reconcile(item.key).then(refresh).catch((problem) => setError(failure(problem)))
          .finally(() => setBusy(false));
      }}>核对原提交</Action>
    </div>)}
    <Disclosure title="为真实路线或本机基础学习登记环境需求">
      <div className="native-models-form">
        <label>受控环境配方<select value={selectedRecipe} disabled={!overview || blocked}
          onChange={(event) => setSelectedRecipe(event.target.value)}>
          <option value="">选择这次学习所需的环境</option>
          {overview?.recipes.map((item) => <option key={item.recipe_id} value={item.recipe_id}>{item.title}</option>)}
        </select></label>
        <label>使用范围<select value={selectedPlan} disabled={blocked} onChange={(event) => setSelectedPlan(event.target.value)}>
          <option value="">本用户 · 此电脑的基础环境</option>
          {plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.active!.document.title} · v{plan.active!.revision}</option>)}
        </select></label>
        {requirement && <RequirementDetails requirement={requirement} />}
        <Action disabled={blocked || !requirement} onClick={() => { void request(); }}>{requirement && overview?.automatic_recipe_ids?.includes(requirement.recipe_id)
          ? '准备基础环境' : '登记需求并查看授权'}</Action>
      </div>
    </Disclosure>
    <ul className="native-models-test-list">
      {overview?.demands.map((demand) => <li key={demand.id}>
        <div className="native-models-detail-heading"><h3>{demand.requirement.title}</h3><strong>{labels[demand.status]}</strong></div>
        <p>需求 v{demand.requirement_revision} · 决定 v{demand.decision_revision} · {demand.plan_id ? `路线 v${demand.plan_revision}` : '本用户 / 此电脑'}</p>
        {demand.release && <p>已验证成品：{demand.release.runtime_version} · {Object.entries(demand.release.toolchains).map(([key, value]) => `${key} ${value}`).join(' / ')}</p>}
        {demand.error_code && <Notice>准备记录：{demand.error_code}。按原授权恢复时保留已有失败与未知事实。</Notice>}
        <Disclosure title="查看依赖、来源、权限与版本范围"><RequirementDetails requirement={demand.requirement} /></Disclosure>
        <div className="native-models-connection-actions">
          <Action disabled={blocked || demand.decision === 'allow'} onClick={() => { void decide(demand, 'allow'); }}>允许并准备</Action>
          <Action disabled={blocked} onClick={() => { void decide(demand, 'defer'); }}>稍后</Action>
          <Action disabled={blocked} onClick={() => { void decide(demand, 'decline'); }}>拒绝</Action>
          <Action disabled={blocked || demand.decision !== 'allow'} onClick={() => { void decide(demand, 'revoke'); }}>撤销</Action>
          <Action disabled={blocked || demand.decision !== 'allow'} onClick={() => { void rebuild(demand); }}>按原授权恢复 / 重建</Action>
        </div>
      </li>)}
    </ul>
    {overview && overview.demands.length === 0 && <p className="native-models-empty">尚未登记环境需求。确认路线时自动准备基础工具链，课程额外框架和依赖统一询问。</p>}
    <p className="native-models-footer">Python、JavaScript、TypeScript、Java、Go、C#、三种 SQL 方言及 HTML/CSS 各自使用受控 Profile。Rust / C++ 当前处于评估；环境就绪与课程评分分别记录。</p>
  </section>;
}
