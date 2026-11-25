// The category is for style discovery, not a new public artifact type.
export const componentCatalog = [
  { id: 'content', title: '题干与引用', examples: [
    { id: 'explanation', title: '题干与操作要求', components: ['Explanation'], selectors: '.demo-explanation', artifacts: ['code', 'choice'] },
    { id: 'source-reference', title: '共享来源入口', components: ['SourceReference'], selectors: '[data-learning-component="source-reference"]', artifacts: [], previewOnly: true },
  ] },
  { id: 'code', title: '代码与文件', examples: [
    { id: 'code-block', title: '只读代码', components: ['CodeBlock'], selectors: '.demo-pre', artifacts: ['prediction', 'sql'] },
    { id: 'code-editor', title: '多文件编辑与只读文件', components: ['CodeEditor'], selectors: '.demo-code-field, .demo-editor', artifacts: ['code', 'project', 'sql'] },
    { id: 'code-diff', title: '代码修改对照', components: ['CodeDiff'], selectors: '.demo-inline-editor, .demo-inline-added, .demo-inline-removed', artifacts: ['code'] },
  ] },
  { id: 'data', title: '结构化数据', examples: [
    { id: 'data-table', title: '数据表格', components: ['DataTable'], selectors: '.demo-table-wrap', artifacts: ['result', 'sql'] },
    { id: 'key-values', title: '输入与预期值', components: ['KeyValueList'], selectors: '.demo-case-values', artifacts: ['code', 'project'] },
  ] },
  { id: 'visual', title: '图形与预览', examples: [
    { id: 'isolated-preview', title: 'HTML / CSS 隔离预览', components: ['IsolatedPreview'], selectors: '.demo-preview', artifacts: ['preview'] },
    { id: 'tree-view', title: '树与文件结构', components: ['TreeView'], selectors: '.demo-tree, .demo-tree-node', artifacts: [], previewOnly: true },
    { id: 'relation-graph', title: '关系图', components: ['RelationGraph'], selectors: '.demo-relation-node, .demo-relation-edge', artifacts: [], previewOnly: true },
    { id: 'sequence-diagram', title: '调用时序图', components: ['SequenceDiagram', 'StepPlayer'], selectors: '.demo-sequence, .demo-sequence-step', artifacts: [], previewOnly: true },
    { id: 'algorithm-sequence', title: '算法 · 序列与指针', components: ['AlgorithmSequence', 'AlgorithmPlayer'], selectors: '.algo-sequence, .algo-pointer', artifacts: [], previewOnly: true },
    { id: 'algorithm-container', title: '算法 · 容器与数据操作', components: ['AlgorithmContainer', 'AlgorithmPlayer'], selectors: '.algo-container, .algo-cell', artifacts: [], previewOnly: true },
    { id: 'algorithm-graph', title: '算法 · 节点与连线', components: ['AlgorithmGraph', 'AlgorithmContainer', 'AlgorithmPlayer'], selectors: '.algo-graph, .algo-node, .algo-edge', artifacts: [], previewOnly: true },
    { id: 'algorithm-grid', title: '算法 · 网格与状态表', components: ['AlgorithmGrid', 'AlgorithmPlayer'], selectors: '.algo-grid, .algo-cell', artifacts: [], previewOnly: true },
    { id: 'algorithm-recursion', title: '算法 · 递归与搜索过程', components: ['AlgorithmRecursion', 'AlgorithmPlayer'], selectors: '.algo-recursion, .algo-call-tree, .algo-call-stack', artifacts: [], previewOnly: true },
    { id: 'algorithm-intervals', title: '算法 · 区间与事件扫描', components: ['AlgorithmIntervals', 'AlgorithmPlayer'], selectors: '.algo-interval, .algo-scan-line', artifacts: [], previewOnly: true },
    { id: 'algorithm-bits', title: '算法 · 位与数值变化', components: ['AlgorithmBits', 'AlgorithmPlayer'], selectors: '.algo-bits, .algo-bit-row', artifacts: [], previewOnly: true },
    { id: 'algorithm-geometry', title: '算法 · 坐标与几何', components: ['AlgorithmGeometry', 'AlgorithmPlayer'], selectors: '.algo-geometry, .algo-coordinate-point, .algo-edge', artifacts: [], previewOnly: true },
  ] },
  { id: 'answer', title: '输入与作答', examples: [
    { id: 'single-answer', title: '单选', components: ['ChoiceAnswer'], selectors: '.demo-choice', artifacts: ['choice'] },
    { id: 'multiple-answer', title: '多选', components: ['ChoiceAnswer'], selectors: '.demo-choice', artifacts: ['multiple'] },
    { id: 'prediction-answer', title: '预测输出', components: ['TextAnswer'], selectors: '.demo-textarea', artifacts: ['prediction'] },
    { id: 'short-answer', title: '简答', components: ['TextAnswer'], selectors: '.demo-textarea', artifacts: ['short'] },
    { id: 'ordering-answer', title: '排序', components: ['OrderingAnswer'], selectors: '.demo-step', artifacts: ['ordering'] },
    { id: 'line-range-answer', title: '代码行批注', components: ['LineRangeAnswer', 'ArtifactAction', 'AnswerFeedback'], selectors: '.demo-selectable-line, .demo-line-reason', artifacts: ['range'] },
    { id: 'parameter-control', title: '参数输入与滑块', components: ['ParameterControl'], selectors: '.demo-parameter, .demo-parameter-trace', artifacts: [], previewOnly: true },
  ] },
  { id: 'process', title: '步骤与过程', examples: [
    { id: 'step-player', title: '逐步观察与播放', components: ['StepPlayer'], selectors: '.demo-steps, .demo-step-value', artifacts: ['animation'] },
  ] },
  { id: 'feedback', title: '反馈与评审', examples: [
    { id: 'answer-feedback', title: '作答反馈', components: ['AnswerFeedback'], selectors: '[data-learning-component="answer-feedback"]', artifacts: ['choice', 'short'] },
    { id: 'result-feedback', title: '公开检查结果', components: ['ResultFeedback'], selectors: '[data-learning-component="result-feedback"]', artifacts: ['result', 'code', 'sql'] },
    { id: 'review-finding', title: '逐行评审反馈', components: ['ReviewFinding'], selectors: '[data-learning-component="review-finding"], .demo-line-reason', artifacts: ['review'] },
  ] },
  { id: 'actions', title: '动作与确认', examples: [
    { id: 'action-states', title: '按钮状态与过渡', components: ['ArtifactAction'], selectors: '.demo-motion-button, .demo-command-label', artifacts: ['code', 'choice', 'preview'] },
    { id: 'action-group', title: '明确确认与取消', components: ['ActionGroup', 'ArtifactAction'], selectors: '.demo-actions', artifacts: ['choice', 'animation'] },
  ] },
];

export const componentSource = 'apps/librechat/LearningComponents.tsx';
/** @type {Record<string, string>} */
export const componentProps = {
  Explanation: 'title?, children',
  SourceReference: 'title, version, section, block, disabled?, onOpen',
  CodeBlock: 'children, label?',
  CodeEditor: 'label, value, onChange?, readOnly?, embedded?',
  CodeDiff: 'before, after, label?, onChange?, readOnly?, embedded?, open?, onOpenChange?, hideToggle?',
  TreeView: 'label, nodes: { id, label, children? }[], expanded, onToggle, selected?, onSelect',
  RelationGraph: 'label, nodes: { id, label, x, y }[], edges: { from, to, label }[], selected, onSelect, width?, height?',
  SequenceDiagram: 'label, participants, steps: { id, from, to, label }[], activeStep, onStep',
  ParameterControl: 'label, value, min, max, step?, onChange, disabled?',
  AlgorithmPlayer: 'title, code: string[], steps: { line, note, variables, scene }[], renderScene, active?, showCode?, showVariables?',
  AlgorithmSequence: 'items: { id, value, tone? }[], pointers?: { label, index }[], label?',
  AlgorithmContainer: 'items: { id, value, tone? }[], mode?: stack | queue, label?',
  AlgorithmGraph: 'nodes: { id, label, x, y, tone? }[], edges: { from, to, tone? }[], directed?, label?',
  AlgorithmGrid: 'cells: { id, value, tone? }[][], columnLabels, rowLabels, label?',
  AlgorithmRecursion: 'calls: { id, label, depth, tone? }[], stack: string[], label?',
  AlgorithmIntervals: 'intervals: { id, start, end, tone? }[], cursor, max, label?',
  AlgorithmBits: 'rows: { label, value }[], width?, label?',
  AlgorithmGeometry: 'points: { id, x, y }[], links: { from, to, tone? }[], extent?, label?',
  DataTable: 'label, columns, rows',
  KeyValueList: 'label, entries: { name, value }[]',
  IsolatedPreview: 'html, css, title?',
  ChoiceAnswer: 'label, options, multiple?, value, onChange, disabled?',
  TextAnswer: 'label, accessibleLabel?, value, onChange, readOnly?, rows?',
  OrderingAnswer: 'label, value, onChange, disabled?',
  LineRangeAnswer: 'label?, lines, value, reasons, drafts, onDraftChange, onSave, onRemove, disabled?, feedback?',
  StepPlayer: 'label, items, step, onStep, feedback?, actions?',
  ResultFeedback: 'label?, columns?, rows?',
  AnswerFeedback: 'kind: correct | incorrect | reference, children',
  ReviewFinding: 'lines, findings: { line, content }[]',
  ArtifactAction: 'icon, label, children?, onClick, primary?, disabled?, phase?',
  ActionGroup: 'children',
};
export const componentCount = new Set(componentCatalog.flatMap((group) =>
  group.examples.flatMap((example) => example.components))).size;
