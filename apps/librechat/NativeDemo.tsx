import { Check, Flag, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import type { components } from '@leornian/api-contracts';
import type { CompositionDraftV2, CompositionV2 } from './LearningCompositionV2';
import { Action, Disclosure, Notice } from './LearningUI';
import { ActionGroup, CodeBlock } from './LearningComponents';

type Demo = components['schemas']['DemoView'];
type Definition = CompositionV2 | components['schemas']['CompositionArtifactView']['presentation']['definition'];
type Command = components['schemas']['DemoStartAction'] | components['schemas']['DemoEventAction'] |
  components['schemas']['DemoCompleteAction'];
export type DemoCommand = Command extends infer T ? T extends Command
  ? Omit<T, 'client_action_id' | 'expected_artifact_revision'> : never : never;

export function demoInputs(definition: Definition, componentId: string, draft: CompositionDraftV2) {
  const node = definition.components.find((item) => item.id === componentId);
  let keys: string[] = [];
  if (node?.component === 'AlgorithmPlayer') {
    const input = definition.inputs?.[node.props.input];
    if (input?.type === 'binary_search') keys = [input.target_state];
  } else if (node?.component === 'IsolatedPreview') {
    keys = [node.props.html_state, ...(node.props.css_state ? [node.props.css_state] : [])];
  }
  const result: Record<string, string | number> = {};
  for (const key of keys) {
    const value = draft.values[key];
    if (typeof value !== 'string' && typeof value !== 'number') return null;
    result[key] = value;
  }
  return result;
}

export function NativeDemo({ demo, definition, draft, blocked, onCommand, onHistory, practiceOnly = false }: {
  demo: Demo; definition: Definition; draft: CompositionDraftV2;
  blocked: boolean; onCommand: (command: DemoCommand) => void;
  practiceOnly?: boolean;
  onHistory?: (before: number) => Promise<components['schemas']['DemoHistory']>;
}) {
  const [older, setOlder] = useState<components['schemas']['DemoHistory'] | null>(null);
  const [loading, setLoading] = useState(false), [historyError, setHistoryError] = useState('');
  const node = definition.components.find((item) => item.id === demo.component_id);
  if (!node) return null;
  const inputs = demoInputs(definition, demo.component_id, draft);
  const matches = !!inputs && Object.keys(inputs).length === Object.keys(demo.inputs).length &&
    Object.keys(inputs).every((key) => inputs[key] === demo.inputs[key]);
  let atEvent = false;
  if (node.component === 'IsolatedPreview') {
    const shown = draft.previews[node.id];
    const html = shown?.html ?? (definition.states?.[node.props.html_state] as { value?: string })?.value;
    const css = shown?.css ?? (node.props.css_state
      ? (definition.states?.[node.props.css_state] as { value?: string })?.value : '');
    atEvent = matches && html === inputs?.[node.props.html_state] &&
      (!node.props.css_state || css === inputs?.[node.props.css_state]);
  } else if ('state' in node.props) {
    atEvent = matches && Number(draft.values[node.props.state] ?? 0) === demo.last_step;
  }
  const identity = {
    component_id: demo.component_id, generation: demo.generation, nonce: demo.nonce ?? '',
  };
  const completions = [...new Map([
    ...(demo.completions ?? []), ...(older?.items ?? []),
  ].map((item) => [item.id, item])).values()].sort((a, b) => a.generation - b.generation);
  const before = older ? older.next_before : demo.next_completion_before;
  return <section aria-label="演示浏览记录">
    {!practiceOnly && <><p className="demo-muted">明确开始时保存本次演示输入；浏览确认不计评分或掌握。</p>
    {demo.generation > 0 && !matches && <p>输入已改变，先为当前输入开始新记录；之前的记录保留。</p>}
    <ActionGroup>
      {demo.allowed_actions.includes('start_demo') && <Action icon={demo.generation ? RotateCcw : Flag}
        disabled={blocked || !inputs} onClick={() => inputs && onCommand({
          action: 'start_demo', component_id: demo.component_id, inputs,
        })}>{demo.generation ? '为当前输入重新记录' : '开始记录此输入'}</Action>}
      {demo.allowed_actions.includes('acknowledge_demo_event') && <Action icon={Flag}
        disabled={blocked || !atEvent || !demo.nonce} onClick={() => onCommand({
          action: 'acknowledge_demo_event', ...identity, sequence: 1,
          event: demo.event, step_index: demo.last_step,
        })}>{demo.event === 'timeline_end' ? '登记当前末步' : '登记当前预览'}</Action>}
      {demo.allowed_actions.includes('complete_demo') && <Action icon={Check}
        disabled={blocked || !matches || !demo.nonce} onClick={() => onCommand({
          action: 'complete_demo', ...identity, sequence: 2,
        })}>我已浏览，记录完成</Action>}
    </ActionGroup>
    {demo.state === 'started' && matches && !atEvent && <p className="demo-muted">
      {demo.event === 'timeline_end' ? '操作演示到末步后可登记。' : '先明确更新预览，再登记当前画面。'}
    </p>}</>}
    {!!completions.length && <Disclosure title={`浏览确认 · ${demo.completion_count ?? completions.length} 次`}>
      {completions.map((receipt) => <div key={receipt.id}>
        <p>第 {receipt.generation} 次记录 · 用户确认 · {new Date(receipt.completed_at).toLocaleString('zh-CN', { hour12: false })}</p>
        {Object.entries(receipt.inputs).map(([key, value]) => {
          const control = definition.components.find((item) =>
            'state' in item.props && item.props.state === key && 'label' in item.props);
          const label = control && 'label' in control.props ? control.props.label : key;
          return typeof value === 'number' ? <p key={key}>{label}：{value}</p>
            : <CodeBlock key={key} label={label}>{value || '（空）'}</CodeBlock>;
        })}
      </div>)}
      {before && onHistory && <Action busy={loading} onClick={async () => {
        setLoading(true); setHistoryError('');
        try {
          const page = await onHistory(before);
          setOlder({ ...page, items: [...(older?.items ?? []), ...page.items] });
        } catch (problem) { setHistoryError((problem as Error).message); }
        finally { setLoading(false); }
      }}>加载更早浏览记录</Action>}
      {historyError && <Notice>{historyError}</Notice>}
    </Disclosure>}
  </section>;
}
