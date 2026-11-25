import { useId, useState } from 'react';
import { ChevronDown, FileText, Lightbulb, LoaderCircle, Search, ShieldCheck, Wrench } from 'lucide-react';
import { ThinkingButton } from '~/components/Chat/Messages/Content/Parts/Thinking';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import type { components } from '@leornian/api-contracts';

export type ThinkingStep = components['schemas']['ThinkingStep'];
type Disclosure = { open: boolean; expanded: string[] };
type Props = { scopeKey: string; steps?: ThinkingStep[]; reasoning?: string; generating?: boolean };

function savedDisclosure(key: string): Disclosure {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    return { open: saved?.open === true, expanded: Array.isArray(saved?.expanded) ? saved.expanded : [] };
  } catch { return { open: false, expanded: [] }; }
}

const statuses: Record<ThinkingStep['status'], string> = {
  running: '进行中', completed: '已完成', waiting: '等待依赖',
  failed: '未完成', cancelled: '已取消', unknown: '结果未知',
};

function ThinkingSteps({ scopeKey, steps = [], reasoning = '', generating = false }: Props) {
  const contentId = useId(), storageKey = `leornian.thinking-disclosure.v1:${scopeKey}`;
  const [disclosure, setDisclosure] = useState(() => savedDisclosure(storageKey));
  const onlyThought = steps.filter((step) => step.kind === 'thinking').length === 1;
  const items: ThinkingStep[] = steps.length ? steps.map((step) =>
    onlyThought && step.kind === 'thinking' && !step.detail && reasoning
      ? { ...step, detail: reasoning, summary: reasoning.trim().split('\n')[0] } : step) : reasoning ? [{
    id: 'legacy', kind: 'thinking', title: '思考摘要', summary: reasoning.trim().split('\n')[0],
    detail: reasoning, status: generating ? 'running' : 'completed',
    started_at: '', completed_at: null, duration_ms: null, tool_name: null,
  }] : [];
  if (!items.length) return null;
  const change = (next: Disclosure) => {
    setDisclosure(next);
    try { sessionStorage.setItem(storageKey, JSON.stringify(next)); } catch {}
  };
  const running = generating && items.some((step) => step.status === 'running');
  return <div className="group/reasoning mb-4">
    <div className="py-2">
      <ThinkingButton isExpanded={disclosure.open} contentId={contentId}
        label={`${running ? '正在思考…' : '思考过程'} · ${items.length} 步`}
        shimmerLabel={running}
        content={items.map((step) => `${step.title} · ${step.summary}\n${step.detail}`).join('\n\n')}
        onClick={() => change({ ...disclosure, open: !disclosure.open })} />
    </div>
    <div id={contentId} role="group" aria-label="思考步骤" hidden={!disclosure.open}>
      {items.map((step) => {
        const expanded = disclosure.expanded.includes(step.id);
        const detailId = `${contentId}-${step.id}`;
        const Icon = step.kind === 'review' ? ShieldCheck : step.kind === 'thinking' ? Lightbulb
          : step.tool_name?.startsWith('list_') ? Search
            : step.tool_name?.startsWith('read_') || step.tool_name === 'learning_get_context'
              ? FileText : Wrench;
        return <div key={step.id} className="py-1" data-thinking-step={step.id}>
          <button type="button" className="tool-status-text text-text-secondary flex w-full min-w-0 items-center gap-2 rounded-lg py-1 text-start hover:text-text-primary focus-visible:outline focus-visible:outline-2"
            aria-expanded={expanded} aria-controls={detailId}
            onClick={() => change({ ...disclosure, expanded: expanded
              ? disclosure.expanded.filter((id) => id !== step.id) : [...disclosure.expanded, step.id] })}>
            <Icon size={16} className="shrink-0" aria-hidden="true" />
            <span className="shrink-0">{step.title}</span>
            <span className="min-w-0 flex-1 truncate">{step.summary}</span>
            {step.status === 'running' && generating
              ? <LoaderCircle size={14} className="shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              : <span className="shrink-0 text-xs">{statuses[step.status]}</span>}
            <ChevronDown size={14} aria-hidden="true"
              className={`shrink-0 transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} />
          </button>
          {expanded && <div id={detailId} role="region" aria-label={`${step.title}详情`}
            className="border-border-light bg-surface-secondary text-text-secondary my-2 min-w-0 rounded-lg border p-3">
            {step.detail ? <Markdown content={step.detail} isLatestMessage={generating} />
              : <p className="text-sm">{step.kind === 'thinking'
                ? '此步骤尚无可展示的思考摘要。' : step.summary}</p>}
            <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
              <span>{statuses[step.status]}</span>
              {step.started_at && <time dateTime={step.started_at}>
                {new Date(step.started_at).toLocaleTimeString()}
              </time>}
              {step.duration_ms != null && <span>耗时 {step.duration_ms < 1000
                ? `${step.duration_ms} ms` : `${(step.duration_ms / 1000).toFixed(1)} 秒`}</span>}
            </p>
          </div>}
        </div>;
      })}
    </div>
  </div>;
}

export default function NativeThinking(props: Props) {
  return <ThinkingSteps key={props.scopeKey} {...props} />;
}
