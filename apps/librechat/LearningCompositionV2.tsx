import { useId, useMemo, useState } from 'react';
import type { ComponentProps, ReactNode } from 'react';
import { Eye, FileCode2, FileText, LockKeyhole, Palette, Play, RefreshCw, Send } from 'lucide-react';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@librechat/client';
import useScaledMaxWidth from '~/hooks/useScaledMaxWidth';
import * as UI from './LearningComponents';
import { Notice } from './LearningUI';
import PracticeWorkbench, { TabBar, TabPanels } from './PracticeWorkbench';
import type { WorkbenchTab } from './PracticeWorkbench';
import { PhosphorDiff } from './PhosphorIcons';
import { compositionAlgorithm } from './algorithm-demos.mjs';
import {
  executableCode, parseCompositionV2, receiptMatches,
} from './composition-v2-runtime.mjs';
import type { components } from './composition-v2-types.generated';
import './composition-v2.css';

export type CompositionV2 = components['schemas']['LearningCompositionV2'];
type Node = CompositionV2['components'][number];
type File = components['schemas']['ProjectFile'];
type Citation = components['schemas']['CitationProps']['citation'];
type Value = string | number | string[] | File[] | null;
export type CompositionDraftV2 = {
  values: Record<string, Value>;
  annotations: Record<string, { saved: Record<number, string>; pending: Record<number, string> }>;
  expanded: Record<string, string[]>;
  selectedFiles: Record<string, string>;
  previews: Record<string, { html: string; css: string }>;
};
export type ContentBinding = {
  id: string;
  content_ref: { owner: 'tutor' | 'item_bank'; id: string; revision: number; public_identity: string };
};
export type CompositionIntentV2 =
  | { type: 'submit_answer'; component_id: string; response: { type: 'choice' | 'order'; value: string[] } | { type: 'text'; value: string } }
  | { type: 'submit_review'; component_id: string; annotations: { line: number; reason: string }[] }
  | { type: 'check_code'; component_id: string; submission: { type: 'code'; code: string } | { type: 'files'; files: File[] } };
type Event = Node extends infer N ? N extends { component: 'ArtifactAction'; props: infer P }
  ? P extends { event: infer E } ? E : never : never : never;
type ReceiptBinding = {
  artifact_id: string; content_ref: ContentBinding['content_ref']; component_id: string;
  client_action_id: string | null; result_id: string;
};
export type CompositionReceiptV2 = ReceiptBinding & (
  | { type: 'answer'; correct: boolean | null; message: string }
  | { type: 'code'; attempt_id: string; submission: Extract<CompositionIntentV2, { type: 'check_code' }>['submission']; message: string; columns: string[]; rows: string[][] }
  | { type: 'review'; message: string; findings: { line: number; content: string }[] }
);
export type CodeWorkbenchContent = Pick<ComponentProps<typeof PracticeWorkbench>,
  'title' | 'language' | 'tests' | 'hasResult' | 'busy' | 'runPhase'> & { tabs: WorkbenchTab[] };
export type ExampleWorkbench = {
  descriptionId?: string;
  render: (editor: ReactNode, description: ReactNode) => ReactNode;
};
export type LearningCompositionV2Props = {
  definition: unknown;
  binding: ContentBinding;
  draft: CompositionDraftV2;
  onDraftChange: (draft: CompositionDraftV2) => void;
  onAction?: (intent: CompositionIntentV2) => void;
  onSource?: (citation: Citation, componentId: string) => void;
  beforeComponent?: (componentId: string) => ReactNode;
  afterComponent?: (componentId: string) => ReactNode;
  codeWorkbenches?: Record<string, CodeWorkbenchContent>;
  exampleWorkbenches?: Record<string, ExampleWorkbench>;
  allowedActions?: { component_id: string; event: Event }[];
  receipts?: CompositionReceiptV2[];
  lockedComponents?: string[];
  status?: 'ready' | 'busy' | 'unknown' | 'cancelled';
  readOnly?: boolean;
  practiceOnly?: boolean;
  active?: boolean;
};

// Presentation only: authority and result binding arrive from the real host.
export default function LearningCompositionV2(props: LearningCompositionV2Props) {
  const parsed = useMemo(() => {
    try { return { value: parseCompositionV2(props.definition), error: '' }; }
    catch (error) { return { value: null, error: error instanceof Error ? error.message : '配置格式无效' }; }
  }, [props.definition]);
  return parsed.value ? <CompositionBody {...props} definition={parsed.value} />
    : <Notice>无法展示此组合：{parsed.error}</Notice>;
}

function AlgorithmView({ node, frame, algorithm }: { node: Node; frame: unknown; algorithm: string }) {
  const label = 'label' in node.props ? node.props.label : '';
  switch (node.component) {
    case 'AlgorithmSequence': return algorithm === 'brackets'
      ? <UI.AlgorithmSequence items={(frame as { input: ComponentProps<typeof UI.AlgorithmSequence>['items'] }).input} label={label} />
      : <UI.AlgorithmSequence {...frame as ComponentProps<typeof UI.AlgorithmSequence>} label={label} />;
    case 'AlgorithmContainer': {
      const scene = frame as { queue?: ComponentProps<typeof UI.AlgorithmContainer>['items']; items?: ComponentProps<typeof UI.AlgorithmContainer>['items']; stack?: string[] };
      return <UI.AlgorithmContainer label={label} mode={algorithm === 'bfs' ? 'queue' : 'stack'}
        items={scene.queue ?? scene.items ?? (scene.stack ?? []).map((value, index) => ({ id: String(index), value }))} />;
    }
    case 'AlgorithmGraph': return <UI.AlgorithmGraph {...frame as ComponentProps<typeof UI.AlgorithmGraph>} label={label} />;
    case 'AlgorithmGrid': return <UI.AlgorithmGrid {...frame as ComponentProps<typeof UI.AlgorithmGrid>} label={label} />;
    case 'AlgorithmRecursion': return <UI.AlgorithmRecursion {...frame as ComponentProps<typeof UI.AlgorithmRecursion>} label={label} />;
    case 'AlgorithmIntervals': return <UI.AlgorithmIntervals {...frame as ComponentProps<typeof UI.AlgorithmIntervals>} label={label} />;
    case 'AlgorithmBits': return <UI.AlgorithmBits {...frame as ComponentProps<typeof UI.AlgorithmBits>} label={label} />;
    case 'AlgorithmGeometry': return <UI.AlgorithmGeometry {...frame as ComponentProps<typeof UI.AlgorithmGeometry>} label={label} />;
    default: return null;
  }
}

function AlgorithmTimeline({ node, definition, draft, change, active }: {
  node: Extract<Node, { component: 'AlgorithmPlayer' }>; definition: CompositionV2; draft: CompositionDraftV2;
  change: (id: string, value: Value) => void; active: boolean;
}) {
  const input = definition.inputs![node.props.input];
  const target = input.type === 'binary_search' ? draft.values[input.target_state] : undefined;
  const trace = useMemo(() => compositionAlgorithm(input, input.type === 'binary_search'
    ? { [input.target_state]: target } : {}), [input, target]);
  const attached = definition.components.filter((child) =>
    'timeline' in child.props && child.props.timeline === node.id);
  return <UI.AlgorithmPlayer {...trace} title={node.props.label} active={active}
    step={Number(draft.values[node.props.state] ?? 0)}
    onStep={(step) => change(node.props.state, step)}
    showCode={node.props.show_code ?? true} showVariables={node.props.show_variables ?? true}
    renderScene={(frame) => <div className="algo-bfs-scene">{attached.map((child) =>
      <AlgorithmView key={child.id} node={child} frame={frame} algorithm={node.props.algorithm} />)}</div>} />;
}

function PreviewWorkbench({ tabs, preview, actions }: {
  tabs: WorkbenchTab[]; preview: ReactNode; actions: ReactNode;
}) {
  const id = useId();
  const [tab, setTab] = useState(tabs[0].id);
  const narrow = useScaledMaxWidth(640);
  const editor = <section className="demo-workbench-pane" aria-label="HTML CSS 编辑区">
    <div className="demo-workbench-pane-heading">
      <TabBar id={id} label="网页代码" tabs={tabs} selected={tab} onSelect={setTab} />
    </div>
    <TabPanels id={id} selected={tab} panelClassName="demo-html-editor-panel" tabs={tabs} />
    <div className="demo-workbench-runbar">{actions}</div>
  </section>;
  const result = <section className="demo-workbench-pane demo-html-result" aria-label="HTML CSS 预览区">
    <div className="demo-workbench-pane-heading"><Eye size={16} aria-hidden="true" /><strong>效果预览</strong></div>
    {preview}
  </section>;
  return <div className={`demo-html-workbench${narrow ? ' demo-html-workbench-stacked' : ''}`}>
    {narrow ? <>{editor}{result}</> : <ResizablePanelGroup orientation="horizontal">
      <ResizablePanel defaultSize="50%" minSize="30%" className="demo-workbench-resizable">{editor}</ResizablePanel>
      <ResizableHandle className="demo-workbench-resizer" aria-label="调整网页编辑与预览区宽度" />
      <ResizablePanel defaultSize="50%" minSize="30%" className="demo-workbench-resizable">{result}</ResizablePanel>
    </ResizablePanelGroup>}
  </div>;
}

function CompositionBody({ definition, binding, draft, onDraftChange, onAction, onSource,
  beforeComponent, afterComponent,
  codeWorkbenches = {}, exampleWorkbenches = {}, allowedActions = [], receipts = [], lockedComponents = [],
  status = 'ready', readOnly = false, practiceOnly = false, active = true,
}: LearningCompositionV2Props & { definition: CompositionV2 }) {
  const id = useId();
  const [diffs, setDiffs] = useState<Record<string, boolean>>({});
  const nodes = new Map(definition.components.map((node) => [node.id, node]));
  const grouped = new Set(definition.components.flatMap((node) => node.component === 'ActionGroup' ? node.props.members : []));
  const previewWorkbenches = new Map<string, {
    editors: Extract<Node, { component: 'CodeEditor' }>[];
    actions: Extract<Node, { component: 'ArtifactAction' }>[];
  }>();
  const embedded = new Set<string>();
  for (const node of definition.components) {
    if (node.component === 'ArtifactAction' &&
      (node.props.event === 'cancel' || practiceOnly && node.props.event !== 'preview')) embedded.add(node.id);
  }
  // Assemble the established workbench from typed state/target links, not model labels or IDs.
  for (const node of definition.components) {
    if (node.component !== 'IsolatedPreview') continue;
    const editors = [...new Set([node.props.html_state, node.props.css_state])].flatMap((state) => {
      const editor = definition.components.find((item): item is Extract<Node, { component: 'CodeEditor' }> =>
        item.component === 'CodeEditor' && item.props.state === state && !embedded.has(item.id) && !codeWorkbenches[item.id]);
      return editor ? [editor] : [];
    });
    if (!editors.length) continue;
    const actions = definition.components.filter((item): item is Extract<Node, { component: 'ArtifactAction' }> =>
      item.component === 'ArtifactAction' && item.props.event === 'preview' && item.props.for_component === node.id);
    previewWorkbenches.set(node.id, { editors, actions });
    for (const item of [...editors, ...actions]) embedded.add(item.id);
  }
  const practiceWorkbenches = new Map<string, {
    content: CodeWorkbenchContent;
    actions: Extract<Node, { component: 'ArtifactAction' }>[];
    feedback: Extract<Node, { component: 'ResultFeedback' }>[];
    diff?: Extract<Node, { component: 'CodeDiff' }>;
  }>();
  for (const node of definition.components) {
    const content = codeWorkbenches[node.id];
    if (!content || embedded.has(node.id) || (node.component !== 'CodeEditor' && node.component !== 'CodeDiff')) continue;
    const actions = definition.components.filter((item): item is Extract<Node, { component: 'ArtifactAction' }> =>
      item.component === 'ArtifactAction' && item.props.event === 'check_code' && item.props.for_component === node.id);
    if (!actions.length) continue;
    const feedback = definition.components.filter((item): item is Extract<Node, { component: 'ResultFeedback' }> =>
      item.component === 'ResultFeedback' && item.props.for_component === node.id);
    const diff = node.component === 'CodeDiff' ? node : definition.components.find(
      (item): item is Extract<Node, { component: 'CodeDiff' }> => item.component === 'CodeDiff' &&
        item.props.state === node.props.state && !codeWorkbenches[item.id] && !embedded.has(item.id) &&
        !definition.components.some((port) => 'for_component' in port.props && port.props.for_component === item.id));
    practiceWorkbenches.set(node.id, { content, actions, feedback, diff });
    for (const item of [...actions, ...feedback, ...(diff && diff.id !== node.id ? [diff] : [])]) embedded.add(item.id);
  }
  for (const [editor, workbench] of Object.entries(exampleWorkbenches)) {
    if (!embedded.has(editor) && !practiceWorkbenches.has(editor) && workbench.descriptionId &&
      nodes.get(workbench.descriptionId)?.component === 'Explanation') embedded.add(workbench.descriptionId);
  }
  const blocked = (node: Node) => readOnly || status !== 'ready' || lockedComponents.includes(node.id);
  const code = (key: string) => String(draft.values[key] ?? '');
  const value = (key: string) => Array.isArray(draft.values[key]) ? draft.values[key] as string[] : [];
  const patch = (next: Partial<CompositionDraftV2>) => onDraftChange({ ...draft, ...next });
  const change = (key: string, next: Value) => {
    const values = { ...draft.values, [key]: next };
    // A linked input change starts a new observation, never a new business Attempt.
    for (const node of definition.components) {
      if (node.component !== 'AlgorithmPlayer') continue;
      const input = definition.inputs![node.props.input];
      if (input.type === 'binary_search' && input.target_state === key) values[node.props.state] = 0;
    }
    patch({ values });
  };
  const receipt = (target: string) => [...receipts].reverse().find((item) => receiptMatches(binding, item, target));
  const annotations = (key: string) => draft.annotations[key] ?? { saved: {}, pending: {} };
  const saveAnnotations = (key: string, next: ReturnType<typeof annotations>) =>
    patch({ annotations: { ...draft.annotations, [key]: next } });
  const files = (key: string) => draft.values[key] as File[];
  const submission = (target: Extract<Node, { component: 'CodeEditor' | 'CodeDiff' }>) =>
    definition.states![target.props.state].type === 'files'
      ? { type: 'files' as const, files: files(target.props.state) }
      : { type: 'code' as const, code: code(target.props.state) };
  const currentCodeReceipt = (target: Extract<Node, { component: 'CodeEditor' | 'CodeDiff' }>) => {
    const result = receipt(target.id);
    return result?.type === 'code' && JSON.stringify(result.submission) === JSON.stringify(submission(target)) ? result : null;
  };
  const intent = (target: Node, event: Event): CompositionIntentV2 | null => {
    if (event === 'check_code' && (target.component === 'CodeEditor' || target.component === 'CodeDiff')) {
      const data = submission(target);
      if (data.type === 'code' && !executableCode(data.code)) return null;
      return { type: 'check_code', component_id: target.id, submission: data };
    }
    if (event === 'submit_answer') {
      if (target.component === 'TextAnswer') {
        const text = code(target.props.state);
        return text.trim() && text.length <= 4000 ? { type: 'submit_answer', component_id: target.id, response: { type: 'text', value: text } } : null;
      }
      if (target.component === 'ChoiceAnswer' || target.component === 'OrderingAnswer') {
        const items = value(target.props.state);
        return items.length ? { type: 'submit_answer', component_id: target.id, response: { type: target.component === 'ChoiceAnswer' ? 'choice' : 'order', value: items } } : null;
      }
    }
    if (event === 'submit_review' && target.component === 'LineRangeAnswer') {
      const state = annotations(target.props.state);
      if (Object.keys(state.pending).length || !Object.keys(state.saved).length ||
        Object.keys(state.saved).length > 40 || Object.values(state.saved).some((reason) =>
          !reason.trim() || reason.trim().length > 1000)) return null;
      return { type: 'submit_review', component_id: target.id, annotations: Object.entries(state.saved)
        .map(([line, reason]) => ({ line: Number(line), reason: reason.trim() })).sort((a, b) => a.line - b.line) };
    }
    return null;
  };
  const render = (node: Node, inWorkbench = false): ReactNode => {
    switch (node.component) {
      case 'Explanation': return <UI.Explanation title={node.props.title ?? undefined}><p>{node.props.text}</p></UI.Explanation>;
      case 'SourceReference': {
        const c = node.props.citation;
        return <UI.SourceReference title={node.props.label} version={'binding_id' in c ? c.ref.document_revision : c.revision}
          section="引用位置" block={'binding_id' in c ? c.ref.block_id : '全文'} disabled={!onSource} onOpen={() => onSource?.(c, node.id)} />;
      }
      case 'CodeBlock': {
        const state = definition.states![node.props.state] as components['schemas']['CodeState'];
        const source = state.read_only ? state.value : code(node.props.state), result = receipt(node.id);
        return result?.type === 'review'
          ? <div role="group" aria-label={node.props.label}>
            <UI.ReviewFinding lines={source.split('\n')} findings={result.findings} />
          </div>
          : <UI.CodeBlock label={node.props.label}>{source}</UI.CodeBlock>;
      }
      case 'CodeEditor': {
        const state = definition.states![node.props.state];
        if (state.type !== 'files') return <UI.CodeEditor embedded={inWorkbench} label={node.props.label} value={code(node.props.state)}
          readOnly={blocked(node) || (state.type === 'code' && state.read_only)}
          onChange={(text) => change(node.props.state, text)} />;
        const list = files(node.props.state), path = draft.selectedFiles[node.id] ?? list[0].path;
        const current = list.find((file) => file.path === path) ?? list[0];
        return <div>
          <TabBar id={`${id}-${node.id}`} label={node.props.label} tabs={list.map((file) => ({ id: file.path, label: file.path }))}
            selected={current.path} onSelect={(selected) => patch({ selectedFiles: { ...draft.selectedFiles, [node.id]: selected } })} />
          <UI.CodeEditor label={current.path} value={current.content} readOnly={blocked(node) || current.read_only}
            onChange={(text) => change(node.props.state, list.map((file) => file.path === current.path ? { ...file, content: text } : file))} />
        </div>;
      }
      case 'CodeDiff': return <UI.CodeDiff embedded={inWorkbench} label={node.props.label} before={node.props.before} after={code(node.props.state)}
        readOnly={blocked(node) || Boolean((definition.states![node.props.state] as components['schemas']['CodeState']).read_only)}
        onChange={(text) => change(node.props.state, text)} />;
      case 'DataTable': return <UI.DataTable {...node.props} />;
      case 'KeyValueList': return <UI.KeyValueList {...node.props} />;
      case 'IsolatedPreview': {
        const preview = draft.previews[node.id] ?? {
          html: String((definition.states![node.props.html_state] as components['schemas']['CodeState']).value),
          css: node.props.css_state ? String((definition.states![node.props.css_state] as components['schemas']['CodeState']).value) : '',
        };
        const changed = preview.html !== code(node.props.html_state) ||
          preview.css !== (node.props.css_state ? code(node.props.css_state) : '');
        return <><UI.IsolatedPreview {...preview} title={node.props.title} />
          {changed && <Notice>草稿已修改，点击预览更新；旧画面不代表当前草稿。</Notice>}</>;
      }
      case 'TreeView': return <UI.TreeView label={node.props.label} nodes={node.props.nodes}
        expanded={draft.expanded[node.id] ?? []} selected={code(node.props.state)}
        onToggle={(key) => patch({ expanded: { ...draft.expanded, [node.id]: (draft.expanded[node.id] ?? []).includes(key)
          ? draft.expanded[node.id].filter((item) => item !== key) : [...draft.expanded[node.id] ?? [], key] } })}
        onSelect={(key) => change(node.props.state, key)} />;
      case 'RelationGraph': {
        const xs = node.props.nodes.map((n) => n.x), ys = node.props.nodes.map((n) => n.y);
        const minX = Math.min(...xs), minY = Math.min(...ys);
        return <UI.RelationGraph label={node.props.label} nodes={node.props.nodes.map((n) => ({
          ...n, x: 100 + (n.x - minX) / (Math.max(...xs) - minX || 1) * 560,
          y: 55 + (n.y - minY) / (Math.max(...ys) - minY || 1) * 210,
        }))} edges={node.props.edges.map((e) => ({ from: e.source, to: e.target, label: e.label ?? '' }))}
          selected={draft.values[node.props.state] as string | null} onSelect={(key) => change(node.props.state, key)} />;
      }
      case 'SequenceDiagram': return <UI.SequenceDiagram label={node.props.label} participants={node.props.participants}
        steps={node.props.steps.map((s) => ({ id: s.id, from: s.source, to: s.target, label: s.label }))}
        activeStep={Math.min(Number(draft.values[node.props.state] ?? 0), node.props.steps.length - 1)}
        onStep={(step) => change(node.props.state, step)} />;
      case 'AlgorithmPlayer': return <AlgorithmTimeline node={node} definition={definition} draft={draft} change={change} active={active && status !== 'cancelled'} />;
      case 'AlgorithmSequence': case 'AlgorithmContainer': case 'AlgorithmGraph': case 'AlgorithmGrid':
      case 'AlgorithmRecursion': case 'AlgorithmIntervals': case 'AlgorithmBits': case 'AlgorithmGeometry':
        return null; // These views are rendered inside their single shared player.
      case 'ChoiceAnswer': return node.props.multiple
        ? <UI.ChoiceAnswer label={node.props.label} options={node.props.options} multiple value={value(node.props.state)}
          disabled={blocked(node)} onChange={(ids) => change(node.props.state, ids)} />
        : <UI.ChoiceAnswer label={node.props.label} options={node.props.options} value={value(node.props.state)[0] ?? ''}
          disabled={blocked(node)} onChange={(key) => change(node.props.state, [key])} />;
      case 'TextAnswer': return <UI.TextAnswer label={node.props.label} value={code(node.props.state)}
        readOnly={blocked(node)} onChange={(text) => change(node.props.state, text)} />;
      case 'OrderingAnswer': return <UI.OrderingAnswer label={node.props.label} disabled={blocked(node)}
        value={value(node.props.state)} labels={Object.fromEntries(node.props.items.map((item) => [item.id, item.text]))}
        onChange={(items) => change(node.props.state, items)} />;
      case 'LineRangeAnswer': {
        const state = annotations(node.props.state), result = receipt(node.id);
        return <UI.LineRangeAnswer label={node.props.label}
          lines={(definition.states![node.props.code_state] as components['schemas']['CodeState']).value.split('\n')}
          value={Object.keys(state.saved).map(Number)} reasons={state.saved} drafts={state.pending}
          disabled={blocked(node)} feedback={result?.type === 'review'
            ? Object.fromEntries(result.findings.map((finding) => [finding.line, finding.content])) : {}}
          onDraftChange={(line, text) => {
            const pending = { ...state.pending };
            if (text === null) delete pending[line]; else pending[line] = text;
            saveAnnotations(node.props.state, { ...state, pending });
          }}
          onSave={(line) => {
            const reason = state.pending[line]?.trim();
            if (!reason) return;
            const pending = { ...state.pending }; delete pending[line];
            saveAnnotations(node.props.state, { saved: { ...state.saved, [line]: reason }, pending });
          }}
          onRemove={(line) => {
            const saved = { ...state.saved }; delete saved[line];
            saveAnnotations(node.props.state, { ...state, saved });
          }} />;
      }
      case 'ParameterControl': return <UI.ParameterControl label={node.props.label}
        value={Number(draft.values[node.props.state])} min={node.props.minimum} max={node.props.maximum}
        step={node.props.step ?? 1} disabled={status === 'cancelled'}
        onChange={(number) => change(node.props.state, number)} />;
      // V2 shares zero-based indices; the incumbent player counts revealed items.
      case 'StepPlayer': return <UI.StepPlayer label={node.props.label} items={node.props.items}
        step={Math.min(Number(draft.values[node.props.state] ?? 0) + 1, node.props.items.length)}
        onStep={(step) => change(node.props.state, step - 1)} active={active && status !== 'cancelled'} />;
      case 'AnswerFeedback': {
        const result = receipt(node.props.for_component);
        return result?.type === 'answer' ? <UI.AnswerFeedback kind={result.correct === null ? 'reference' : result.correct ? 'correct' : 'incorrect'}>{result.message}</UI.AnswerFeedback> : null;
      }
      case 'ResultFeedback': {
        const target = nodes.get(node.props.for_component)!;
        if (target.component !== 'CodeEditor' && target.component !== 'CodeDiff') return null;
        const result = currentCodeReceipt(target);
        return result ? <UI.ResultFeedback label={result.message} columns={result.columns} rows={result.rows} />
          : receipt(target.id) ? <Notice>草稿已修改，之前的结果不适用于当前内容。</Notice> : null;
      }
      case 'ReviewFinding': {
        const target = nodes.get(node.props.for_component)!, result = receipt(target.id);
        return result?.type === 'review' && target.component === 'LineRangeAnswer' ? <UI.ReviewFinding
          lines={(definition.states![target.props.code_state] as components['schemas']['CodeState']).value.split('\n')}
          findings={result.findings} /> : null;
      }
      case 'ArtifactAction': {
        const target = nodes.get(node.props.for_component)!, preview = node.props.event === 'preview';
        const request = intent(target, node.props.event);
        const permitted = allowedActions.some((a) => a.component_id === target.id && a.event === node.props.event);
        const disabled = blocked(target) || !permitted || (!preview && (!onAction || !request));
        const applied = preview && target.component === 'IsolatedPreview' ? draft.previews[target.id] : null;
        const updated = status === 'ready' && applied && target.component === 'IsolatedPreview' &&
          applied.html === code(target.props.html_state) &&
          applied.css === (target.props.css_state ? code(target.props.css_state) : '');
        return <UI.ArtifactAction label={node.props.label} primary={node.props.primary}
          icon={preview ? RefreshCw : node.props.event === 'check_code' ? Play : Send}
          phase={status === 'busy' ? 'busy' : status === 'unknown' ? 'unknown' : updated ? 'completed' : 'idle'} disabled={disabled}
          onClick={() => {
            if (preview && target.component === 'IsolatedPreview') patch({ previews: { ...draft.previews, [target.id]: {
              html: code(target.props.html_state), css: target.props.css_state ? code(target.props.css_state) : '',
            } } });
            else if (request) onAction?.(request);
          }} />;
      }
      case 'ActionGroup': {
        const members = node.props.members.filter((key) => !embedded.has(key));
        return members.length ? <UI.ActionGroup>{members.map((key) =>
          <span key={key}>{render(nodes.get(key)!)}</span>)}</UI.ActionGroup> : null;
      }
    }
    const unsupported: never = node;
    throw new Error(`Unsupported component: ${String(unsupported)}`);
  };
  const component = (node: Node) => <div className="learning-composition-node" key={node.id} data-component-id={node.id}>
    {beforeComponent?.(node.id)}{render(node)}{afterComponent?.(node.id)}
  </div>;
  const practiceWorkbench = (node: Extract<Node, { component: 'CodeEditor' | 'CodeDiff' }>,
    workbench: NonNullable<ReturnType<typeof practiceWorkbenches.get>>) => {
    const { content, actions, feedback, diff } = workbench;
    const state = definition.states![node.props.state];
    const run = actions.find((item) => item.props.primary) ?? actions[0];
    const request = intent(node, 'check_code');
    const permitted = allowedActions.some((item) => item.component_id === node.id && item.event === 'check_code');
    const readonly = blocked(node) || state.type === 'code' && state.read_only;
    const list = state.type === 'files' ? files(node.props.state) : [];
    const selected = list.find((file) => file.path === draft.selectedFiles[node.id])?.path ?? list[0]?.path;
    return <div className="learning-composition-node learning-composition-code-workbench" key={node.id} data-component-id={node.id}>
      <PracticeWorkbench {...content} tabs={[
        { id: 'description', label: '题目描述', icon: FileText, content: beforeComponent?.(node.id) },
        ...content.tabs,
      ]} editor={diff ? <div className="learning-composition-workbench-editor"
        data-component-id={diff.id === node.id ? undefined : diff.id}>
        <UI.CodeDiff embedded hideToggle label={node.props.label} before={diff.props.before}
          after={code(node.props.state)} open={Boolean(diffs[node.id])} readOnly={readonly}
          onChange={(text) => change(node.props.state, text)} />
      </div> : <UI.CodeEditor embedded label={node.props.label} value={code(node.props.state)}
        readOnly={readonly} onChange={(text) => change(node.props.state, text)} />}
        files={state.type === 'files' ? {
          selected, onSelect: (path) => patch({ selectedFiles: { ...draft.selectedFiles, [node.id]: path } }),
          tabs: list.map((file) => ({
            id: file.path, label: file.path, icon: file.read_only ? LockKeyhole : FileCode2,
            content: <UI.CodeEditor embedded label={file.path} value={file.content} readOnly={readonly || file.read_only}
              onChange={(text) => change(node.props.state, list.map((item) =>
                item.path === file.path ? { ...item, content: text } : item))} />,
          })),
        } : undefined}
        tools={<>{diff && <UI.ArtifactAction icon={PhosphorDiff} label={`切换${node.props.label}修改对照`}
          aria-pressed={Boolean(diffs[node.id])} onClick={() => setDiffs({ ...diffs, [node.id]: !diffs[node.id] })} />}
          {actions.filter((item) => item.id !== run.id).map(component)}</>}
        result={<>{feedback.map(component)}{afterComponent?.(node.id)}
          {!content.hasResult && <p className="demo-muted">明确运行后，此处显示原执行方返回的结果。</p>}</>}
        runPhase={status === 'unknown' ? 'unknown' : status === 'busy' ? 'busy' : content.runPhase}
        runLabel={run.props.label} busy={status === 'busy' || content.busy}
        runDisabled={blocked(node) || !permitted || !onAction || !request}
        onRun={() => { if (request && permitted && !blocked(node)) onAction?.(request); }} />
    </div>;
  };
  return <section className="learning-composition-v2" data-layout={definition.layout ?? 'stack'}
    aria-label={definition.title} data-learning-composition="v2">
    {definition.components.filter((node) => !grouped.has(node.id) && !embedded.has(node.id) && !('timeline' in node.props))
      .map((node) => {
        const practice = practiceWorkbenches.get(node.id);
        if (practice && (node.component === 'CodeEditor' || node.component === 'CodeDiff')) {
          return practiceWorkbench(node, practice);
        }
        const example = exampleWorkbenches[node.id];
        if (example && (node.component === 'CodeEditor' || node.component === 'CodeDiff')) {
          const description = example.descriptionId && nodes.get(example.descriptionId);
          return <div className="learning-composition-node learning-composition-code-workbench" key={node.id} data-component-id={node.id}>
            {example.render(render(node, true), description && description.component === 'Explanation' ? component(description) : null)}
          </div>;
        }
        const workbench = previewWorkbenches.get(node.id);
        return node.component === 'IsolatedPreview' && workbench
          ? <div className="learning-composition-node learning-composition-preview" key={node.id} data-component-id={node.id}>
            {beforeComponent?.(node.id)}
            <PreviewWorkbench tabs={workbench.editors.map((editor) => ({
              id: editor.id, label: editor.props.state === node.props.html_state ? 'HTML' : 'CSS',
              icon: editor.props.state === node.props.html_state ? FileCode2 : Palette, content: component(editor),
            }))} preview={render(node)} actions={workbench.actions.map(component)} />
            {afterComponent?.(node.id)}
          </div> : component(node);
      })}
    {status === 'unknown' && <Notice>结果未知，先核对原动作；不会自动重试。</Notice>}
  </section>;
}
