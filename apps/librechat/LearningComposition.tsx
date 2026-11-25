import { useMemo, useState } from 'react';
import type { ComponentProps, ReactNode } from 'react';
import { Play, Send } from 'lucide-react';
import {
  ActionGroup, ArtifactAction, CodeDiff, DataTable, Explanation, LineRangeAnswer, ResultFeedback,
} from './LearningComponents';
import { AlgorithmContainer, AlgorithmGraph, AlgorithmPlayer } from './AlgorithmVisuals';
import { Notice } from './LearningUI';
import { PhosphorDiff } from './PhosphorIcons';
import { breadthFirstDemo } from './algorithm-demos.mjs';
import { currentCodeResult, parseComposition, savedReviewAnnotations } from './composition-runtime.mjs';
import type { components } from './composition-types.generated';

export type Composition = components['schemas']['LearningComposition'];
export type CompositionDraft = { code: string; reasons: Record<number, string>; drafts: Record<number, string> };
export type CompositionIntent =
  | { type: 'submit_review'; annotations: { line: number; reason: string }[] }
  | { type: 'check_code'; code: string };
export type CompositionReceipt =
  | { type: 'review'; feedback: Record<number, ReactNode>; message: string }
  | { type: 'code'; code: string; message: string; rows: string[][] };
type GraphScene = ComponentProps<typeof AlgorithmGraph> & { queue: ComponentProps<typeof AlgorithmContainer>['items'] };

export type LearningCompositionProps = {
  definition: unknown;
  draft: CompositionDraft;
  onDraftChange: (draft: CompositionDraft) => void;
  onAction?: (intent: CompositionIntent) => void;
  receipt?: CompositionReceipt;
  status?: 'ready' | 'busy' | 'submitted' | 'unknown';
  readOnly?: boolean;
  active?: boolean;
};

// No demo store, network, grading or execution: the host owns drafts and action receipts.
export default function LearningComposition(props: LearningCompositionProps) {
  const parsed = useMemo(() => {
    try { return { value: parseComposition(props.definition), error: '' }; }
    catch (error) { return { value: null, error: error instanceof Error ? error.message : '配置格式无效' }; }
  }, [props.definition]);
  return parsed.value ? <CompositionBody {...props} definition={parsed.value} />
    : <Notice>无法展示此组合：{parsed.error}</Notice>;
}

function CompositionBody({ definition, draft, onDraftChange, onAction, receipt,
  status = 'ready', readOnly = false, active = true }: LearningCompositionProps & { definition: Composition }) {
  const [diff, setDiff] = useState(false);
  const scene = definition.scene;
  const bfs = useMemo(() => scene.type === 'bfs' ? breadthFirstDemo(scene) : null, [scene]);
  const blocked = readOnly || status !== 'ready';
  const codeReceipt = receipt?.type === 'code' ? currentCodeResult(receipt, draft.code) : null;
  if (scene.type === 'bfs') return <AlgorithmPlayer<GraphScene> {...bfs!} title={definition.title}
    active={active} showCode={scene.views.includes('code')} showVariables={scene.views.includes('variables')}
    renderScene={(frame) => <div className="algo-bfs-scene">
      <AlgorithmGraph nodes={frame.nodes} edges={frame.edges} label="BFS 图，按输入边的顺序访问相邻节点" />
      {scene.views.includes('queue') && <AlgorithmContainer items={frame.queue} mode="queue" label="BFS 队列" />}
    </div>} />;
  const lines = scene.code.split('\n');
  const annotations = savedReviewAnnotations(draft, lines.length);
  return <section aria-label={definition.title} data-learning-composition={scene.type}>
    <Explanation title={definition.title}><p>{scene.prompt}</p></Explanation>
    {scene.type === 'code_review' ? <>
      <LineRangeAnswer lines={lines} value={Object.keys(draft.reasons).map(Number)}
        reasons={draft.reasons} drafts={draft.drafts} disabled={blocked}
        feedback={status === 'submitted' && receipt?.type === 'review' ? receipt.feedback : {}}
        onDraftChange={(line, text) => {
          const drafts = { ...draft.drafts };
          if (text === null) delete drafts[line]; else drafts[line] = text;
          onDraftChange({ ...draft, drafts });
        }}
        onSave={(line) => {
          const reason = draft.drafts[line]?.trim();
          if (!reason) return;
          const drafts = { ...draft.drafts }; delete drafts[line];
          onDraftChange({ ...draft, drafts, reasons: { ...draft.reasons, [line]: reason } });
        }}
        onRemove={(line) => {
          const reasons = { ...draft.reasons }; delete reasons[line];
          onDraftChange({ ...draft, reasons });
        }} />
      <ActionGroup><ArtifactAction icon={Send} label="提交审查" primary
        phase={status === 'submitted' ? 'completed' : status === 'busy' ? 'busy' : status === 'unknown' ? 'unknown' : 'idle'}
        disabled={blocked || !onAction || !annotations}
        onClick={() => { if (annotations) onAction?.({ type: 'submit_review', annotations }); }} /></ActionGroup>
      {status === 'submitted' && receipt?.type === 'review' && <Notice>{receipt.message}</Notice>}
    </> : <>
      {scene.views.includes('cases') && scene.cases.length > 0 && <DataTable label="公开测试用例"
        columns={['输入', '预期输出']} rows={scene.cases.map((item) => [item.input, item.expected])} />}
      <CodeDiff before={scene.code} after={draft.code} label="修复代码" readOnly={blocked} hideToggle
        open={diff && scene.views.includes('diff')} onChange={(code) => onDraftChange({ ...draft, code })} />
      <ActionGroup>
        {scene.views.includes('diff') && <ArtifactAction icon={PhosphorDiff} label="切换修复代码修改对照"
          aria-pressed={diff} onClick={() => setDiff(!diff)} />}
        <ArtifactAction icon={Play} label="检查代码" primary
          phase={status === 'busy' ? 'busy' : status === 'unknown' ? 'unknown' : 'idle'}
          disabled={blocked || !onAction}
          onClick={() => onAction?.({ type: 'check_code', code: draft.code })} />
      </ActionGroup>
      {codeReceipt && <ResultFeedback label={codeReceipt.message} rows={codeReceipt.rows} />}
      {receipt?.type === 'code' && !codeReceipt && <Notice>代码已修改，之前的结果不适用于当前草稿。</Notice>}
    </>}
    {status === 'unknown' && <Notice>结果未知，等待宿主核对；不会自动重试。</Notice>}
  </section>;
}
