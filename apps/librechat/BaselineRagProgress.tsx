import { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { Check, ChevronDown, Circle, CircleAlert, LoaderCircle, Pause } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { nativeRequest, nativeStore } from './native-client.mjs';

type Progress = components['schemas']['MaterialPreparationProgress'];
type Step = components['schemas']['MaterialPreparationStep'];
const labels: Record<string, string> = {
  sources: '选择可用资料', acquisition: '获取资料正文', parsing: '解析正文与结构',
  ocr: '识别图片与扫描内容（如需）', quality: '检查内容完整性', chunking: '生成检索切片',
  embedding: '生成向量', indexing: '建立检索索引', retrieval: '检索、重排与证据检查',
};
const states: Record<string, string> = {
  processing: '正在准备资料', ready: '资料准备完成', waiting_config: '等待模型配置',
  waiting_dependency: '资料待补齐', blocked_unknown: '处理结果待确认', cancelled: '资料处理已停止',
};
const reasons: Record<string, string> = {
  official_material_preparation_pending: '正在获取与本次目标相关的可用资料。',
  uploaded_material_preparation_pending: '正在处理你上传的资料。',
  html_nontext_content_pending: '正文中有需要进一步识别的图文内容。',
  automatic_repair_exhausted: '这份资料需要补充解析或替代来源。',
  material_quality_pending: '这份资料尚未通过内容完整性检查。',
  material_nontext_processing_required: '资料中的部分图示或交互内容尚未解析。',
  material_replacement_source_required: '部分资料暂时无法完整解析，需要可读取的替代资料。',
  material_quality_review_pending: '正在检查资料的解析结果。',
  approved_source_coverage_gap: '现有资料还不能回答本次需要核对的问题。',
  bound_material_coverage_gap: '已选资料尚未满足本次学习需求。',
  approved_source_required: '正在等待本次任务可用的资料来源。',
  semantic_coverage_pending: '正在检索并核对本次所需的正文证据。',
  existing_material_preparation_pending: '正在准备本次讨论需要使用的教材。',
  ocr_configuration_required: '请在模型设置中配置 OCR 用途。',
  source_result_unknown: '读取结果尚未确认，保留原任务等待恢复。',
  source_read_unknown: '部分来源未能完成读取，原始记录已保留。',
  source_http_unavailable: '部分来源暂不可访问，已就绪资料会保留。',
  source_network_unavailable: '部分来源连接失败，已就绪资料会保留。',
  source_response_invalid: '部分来源未返回可用正文，需要继续补充有效资料。',
  source_preparation_pending: '正在获取并解析本次需要的教材。',
  approved_source_fetch_pending: '正在补充与目标缺口相关的章节。',
  indexing_pending: '正在生成切片、向量与检索索引。',
  ocr_pages_pending: '正在识别教材中的图片或扫描页。',
  external_result_unknown: '外部处理结果尚未确认；等待原调用回执，不会重新请求模型。',
  model_unavailable: '请检查模型设置中本步骤的用途配置。',
  material_storage_unavailable: '暂时无法读取教材原文，存储恢复后继续处理。',
  source_depth_not_selected: '该章节超出本轮浅层获取范围，已停止自动扩展。',
  index_rebuild_pending: '正在为当前模型配置准备检索索引。',
  index_rebuild_in_progress: '当前资料的索引仍在准备，继续等待原处理任务。',
  tavily_search_pending: '正在按本次主题搜索已授权的公开资料。',
  tavily_not_configured: '请在材料处理设置中填写并启用 Tavily Key。',
  tavily_configuration_changed: '搜索配置已变化，未发送的请求需要更新后继续。',
  tavily_provider_rejected: '搜索服务未接受请求，请在模型设置中检查 Key 或账户状态。',
  tavily_extraction_failed: '所选页面未返回有效正文，需要继续获取可用内容。',
  tavily_invalid_response: '搜索服务返回的内容未通过校验，等待获取策略更新。',
};

const stepStates: Record<Step['status'], string> = {
  completed: '已完成', pending: '待处理', running: '进行中',
  waiting: '待继续', unknown: '待确认', cancelled: '已停止',
};
const flowGroups = [
  { key: 'acquisition', title: '获取资料', steps: ['sources', 'acquisition'] },
  { key: 'preparation', title: '解析与整理', steps: ['parsing', 'ocr', 'quality', 'chunking', 'embedding', 'indexing'] },
  { key: 'retrieval', title: '核对本次证据', steps: ['retrieval'] },
];

function StepIcon({ state }: { state: Step['status'] }) {
  return state === 'completed' ? <Check size={15} aria-hidden="true" />
    : state === 'running' ? <LoaderCircle size={15} className="baseline-rag-spinner" aria-hidden="true" />
      : state === 'cancelled' ? <Pause size={15} aria-hidden="true" />
        : state === 'waiting' || state === 'unknown' ? <CircleAlert size={15} aria-hidden="true" />
          : <Circle size={15} aria-hidden="true" />;
}

function flowFor(progress: Progress) {
  return flowGroups.flatMap((group) => {
    const steps = (progress.steps ?? []).filter((step) => group.steps.includes(step.key));
    if (!steps.length) return [];
    let status: Step['status'] = steps.every((step) => step.status === 'completed') ? 'completed'
      : (['unknown', 'waiting', 'running'] as const).find(
        (state) => steps.some((step) => step.status === state),
      ) ?? 'pending';
    const current = progress.current_documents ?? 0;
    const ready = progress.ready_documents ?? 0;
    if (group.key === 'preparation' && current > 0 && ready === current) status = 'completed';
    if (progress.status === 'ready') status = 'completed';
    else if (progress.status === 'cancelled' && status !== 'completed') status = 'cancelled';
    const acquisition = steps.find((step) => step.key === 'acquisition');
    const retrieval = steps.find((step) => step.key === 'retrieval');
    const active = steps.find((step) => ['running', 'waiting', 'unknown'].includes(step.status));
    const note = group.key === 'acquisition' && acquisition?.total
      ? `已获取 ${acquisition.completed} / ${acquisition.total} 项`
      : group.key === 'preparation' && current > 0 ? `${ready} / ${current} 份资料就绪`
        : group.key === 'retrieval' && retrieval?.unit === 'checks' && retrieval.total
          ? `已检查 ${retrieval.completed} / ${retrieval.total} 组`
          : active ? labels[active.key] : '';
    return [{ ...group, status, note }];
  });
}

function workCount(step: Step) {
  if (!step.total) return '';
  return step.unit === 'checks'
    ? `${step.completed} / ${step.total} 组${step.level ? ` · 第 ${step.level} 层汇总` : ''}`
    : step.unit === 'chunks' ? `${step.completed} / ${step.total} 个片段`
      : `${step.completed} / ${step.total} 项`;
}

export default function BaselineRagProgress({ conversationId }: { conversationId?: string }) {
  const snapshot = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const actorId = snapshot.snapshot?.actor.id;
  const scope = `${actorId ?? ''}:${conversationId ?? ''}`;
  const [result, setResult] = useState<{ scope: string; progress?: Progress; error?: string }>({ scope: '' });
  const [collapsed, setCollapsed] = useState(() => globalThis.innerWidth < 900);
  const contentId = useId();
  useEffect(() => {
    if (!actorId || !conversationId || conversationId === 'new') return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      try {
        const progress = await nativeRequest(`/v1/conversations/${conversationId}/material-progress`,
          { signal: controller.signal }) as Progress;
        if (controller.signal.aborted) return;
        setResult({ scope, progress });
        if (!['idle', 'ready', 'cancelled'].includes(progress.status)) {
          timer = setTimeout(() => void refresh(), 3000);
        }
      } catch (problem) {
        if (controller.signal.aborted) return;
        setResult((prior) => ({ scope, progress: prior.scope === scope ? prior.progress : undefined,
          error: (problem as Error).message }));
        timer = setTimeout(() => void refresh(), 5000);
      }
    };
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [actorId, conversationId, scope, snapshot.epoch]);
  const data = result.scope === scope ? result : null;
  const progress = data?.progress;
  if (!data || (progress?.status === 'idle' && !data.error) || (!progress && !data.error)) return null;
  const stage = progress?.preparation === 'initial' ? '首批资料'
    : progress?.preparation === 'incremental' ? '补充资料' : '路线补证';
  const title = data.error ? '资料状态暂时无法同步'
    : progress?.reason_code === 'material_nontext_processing_required' ? '资料需要补充解析'
      : states[progress?.status ?? ''] ?? '正在准备资料';
  const flow = progress ? flowFor(progress) : [];
  const activeState = progress?.status === 'blocked_unknown' ? 'unknown'
    : progress?.status === 'processing' ? 'running' : 'waiting';
  const currentStep = progress?.status === 'cancelled' || progress?.status === 'ready'
    ? undefined : flow.find((group) => group.status === activeState)?.key;
  const allCurrentReady = !!progress?.current_documents
    && progress.ready_documents === progress.current_documents;
  const iconState: Step['status'] = data.error ? 'waiting'
    : progress?.status === 'ready' ? 'completed' : progress?.status === 'cancelled' ? 'cancelled'
      : progress?.status === 'processing' ? 'running'
        : progress?.status === 'blocked_unknown' ? 'unknown' : 'waiting';
  return <aside className="baseline-rag-panel border-border-light bg-surface-primary text-text-primary"
    aria-label="资料与证据进度">
    <button type="button" className="baseline-rag-heading" aria-expanded={!collapsed}
      aria-controls={contentId} onClick={() => setCollapsed((value) => !value)}>
      <StepIcon state={iconState} />
      <span role="status">{title}</span>
      <ChevronDown size={15} className={collapsed ? '' : 'baseline-rag-expanded'} aria-hidden="true" />
    </button>
    <div id={contentId} hidden={collapsed} className="baseline-rag-body">
      {data.error && <p role="alert">{data.error}</p>}
      {progress && <p className="baseline-rag-scope text-text-secondary">
        {stage} · {progress.preparation === 'incremental' ? '保留已有资料，补充新增需求' : '按当前任务准备必要资料'}
      </p>}
      {progress && (!!progress.current_documents || !!progress.background_documents) &&
        <dl className="baseline-rag-counts">
          {!!progress.current_documents && <div>
            <dt className="text-text-secondary">本轮资料</dt>
            <dd>{progress.ready_documents} / {progress.current_documents} 份就绪</dd>
          </div>}
          {!!progress.background_documents && <div>
            <dt className="text-text-secondary">后台资料</dt>
            <dd>{progress.background_ready_documents} / {progress.background_documents} 份就绪</dd>
          </div>}
        </dl>}
      {flow.length > 0 && <ol className="baseline-rag-flow" aria-label="资料准备流程">
        {flow.map((group) => <li key={group.key} data-state={group.status}
          aria-current={group.key === currentStep ? 'step' : undefined}>
          <span className="baseline-rag-step-icon"><StepIcon state={group.status} /></span>
          <div className="baseline-rag-step-copy">
            <span className="baseline-rag-step-title">{group.title}</span>
            {group.note && <span className="text-text-secondary">{group.note}</span>}
          </div>
          <span className="baseline-rag-step-state text-text-secondary">{stepStates[group.status]}</span>
        </li>)}
      </ol>}
      {allCurrentReady && progress?.status !== 'ready' && progress?.status !== 'cancelled' &&
        <p className="baseline-rag-explanation text-text-secondary">
          资料已就绪，仍需确认是否满足本次需求。
        </p>}
      {progress?.reason_code && <p className="text-text-secondary">
        {reasons[progress.reason_code] ?? '当前步骤尚未完成，等待处理状态更新。'}
      </p>}
      {progress && (!!progress.steps?.length || !!progress.documents?.length) &&
        <details className="baseline-rag-details">
          <summary>查看处理详情</summary>
          {!!progress.steps?.length && <ol className="baseline-rag-technical" aria-label="资料处理详细步骤">
            {progress.steps.map((step) => <li key={step.key} data-state={step.status}>
              <StepIcon state={step.status} />
              <div className="baseline-rag-step-copy">
                <span>{labels[step.key]}</span>
                {workCount(step) && <span className="text-text-secondary">{workCount(step)}</span>}
              </div>
              <span className="baseline-rag-step-state text-text-secondary">
                {step.status === 'pending' && step.completed > 0 ? '等待后续资料' : stepStates[step.status]}
              </span>
            </li>)}
          </ol>}
          {!!progress.documents?.length && <ul className="baseline-rag-documents" aria-label="资料明细">
            {progress.documents.map((document, index) => <li key={`${index}:${document.title}`}>
              <span>{document.title}</span>
              <span className="text-text-secondary">{document.state === 'ready' ? '已就绪'
                : document.state === 'cancelled' ? '已停止'
                  : document.reason_code ? reasons[document.reason_code] ?? '当前处理尚未完成'
                    : labels[document.phase] ?? '等待处理状态更新'}</span>
            </li>)}
          </ul>}
        </details>}
      {progress?.last_progress_at && <p className="baseline-rag-updated text-text-secondary">
        最近进展 <time dateTime={progress.last_progress_at}
          title={new Date(progress.last_progress_at).toLocaleString('zh-CN')}>
          {new Date(progress.last_progress_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </time>
      </p>}
    </div>
  </aside>;
}
