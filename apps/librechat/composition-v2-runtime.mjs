import validateSchema from './composition-v2-validator.generated.mjs';
import directory from './composition-directory.generated.json' with { type: 'json' };

/** @typedef {import('./composition-v2-types.generated').components['schemas']['LearningCompositionV2']} Composition */
const ports = new Map(directory.map((item) => [item.component, item.state_kinds]));
const views = {
  AlgorithmSequence: ['binary_search', 'brackets'], AlgorithmContainer: ['bfs', 'brackets', 'combination_sum'],
  AlgorithmGraph: ['bfs'], AlgorithmGrid: ['grid_paths'], AlgorithmRecursion: ['combination_sum'],
  AlgorithmIntervals: ['interval_scan'], AlgorithmBits: ['bitwise'], AlgorithmGeometry: ['geometry'],
};
const targets = {
  submit_answer: ['ChoiceAnswer', 'TextAnswer', 'OrderingAnswer'], submit_review: ['LineRangeAnswer'],
  check_code: ['CodeEditor', 'CodeDiff'], preview: ['IsolatedPreview'],
};
const fail = (message) => { throw new Error(message); };
const distinct = (values) => new Set(values).size === values.length;

/** @returns {Composition} */
export function parseCompositionV2(value) {
  if (!validateSchema(value)) {
    const error = validateSchema.errors[0];
    fail(`${error.instancePath || '/'}: ${error.message}`);
  }
  const states = value.states ?? {}, inputs = value.inputs ?? {};
  const nodes = new Map(value.components.map((node) => [node.id, node]));
  if (nodes.size !== value.components.length) fail('组件标识不能重复。');
  const grouped = new Set();
  for (const node of value.components) {
    const p = node.props, kinds = ports.get(node.component);
    if (kinds.length && !kinds.includes(states[p.state]?.type)) fail(`${node.id} 的状态端口类型不匹配。`);
    if (node.component === 'OrderingAnswer' &&
      (!distinct(p.items.map((item) => item.id)) ||
       [...states[p.state].value].sort().join('\0') !== p.items.map((item) => item.id).sort().join('\0'))) fail('排序状态必须包含全部且不重复的项目。');
    if (node.component === 'ChoiceAnswer' && !distinct(p.options.map((item) => item.id))) fail('选项标识不能重复。');
    if (node.component === 'ParameterControl' &&
      (!(p.minimum < p.maximum) || states[p.state].value < p.minimum || states[p.state].value > p.maximum)) fail('参数状态必须在有效范围内。');
    if (node.component === 'LineRangeAnswer' &&
      (states[p.code_state]?.type !== 'code' || !states[p.code_state].read_only)) fail('批注必须引用只读代码快照。');
    if (node.component === 'IsolatedPreview' &&
      [p.html_state, p.css_state].some((id) => id && states[id]?.type !== 'code')) fail('预览必须引用代码状态。');
    if (node.component === 'AlgorithmPlayer') {
      const input = inputs[p.input];
      if (!input || input.type !== p.algorithm) fail('算法与输入类型不匹配。');
      if (input.type === 'binary_search' && states[input.target_state]?.type !== 'number') fail('查找目标必须引用数字状态。');
    }
    if (views[node.component]) {
      const player = nodes.get(p.timeline);
      if (player?.component !== 'AlgorithmPlayer' || !views[node.component].includes(player.props.algorithm)) fail('画面必须引用兼容的共享时间线。');
    }
    if (['ArtifactAction', 'AnswerFeedback', 'ResultFeedback', 'ReviewFinding'].includes(node.component)) {
      const target = nodes.get(p.for_component);
      if (!target || target.id === node.id) fail('动作和反馈必须引用其他组件。');
      if (node.component === 'ArtifactAction' && (p.event === 'cancel'
        ? ['ActionGroup', 'ArtifactAction'].includes(target.component)
        : !targets[p.event]?.includes(target.component))) fail('动作目标不支持此意图。');
    }
    if (node.component === 'ActionGroup') {
      if (!distinct(p.members)) fail('动作组成员不能重复。');
      for (const id of p.members) {
        if (nodes.get(id)?.component !== 'ArtifactAction' || grouped.has(id)) fail('动作只能归属一个组，不能嵌套。');
        grouped.add(id);
      }
    }
    if (node.component === 'DataTable' && p.rows.some((row) => row.length !== p.columns.length)) fail('表格各行必须与列数一致。');
    if (node.component === 'TreeView') {
      const ids = new Set();
      const walk = (items, depth) => {
        if (depth > 8) fail('树最多八层。');
        for (const item of items) {
          if (ids.has(item.id) || ids.size >= 200) fail('树节点标识必须唯一且不超过 200 个。');
          ids.add(item.id); walk(item.children ?? [], depth + 1);
        }
      };
      walk(p.nodes, 1);
    }
    if (node.component === 'RelationGraph' || node.component === 'SequenceDiagram') {
      const graph = node.component === 'RelationGraph';
      const items = graph ? p.nodes : p.participants, edges = graph ? p.edges : p.steps;
      const ids = new Set(items.map((item) => item.id));
      if (ids.size !== items.length || edges.some((edge) => !ids.has(edge.source) || !ids.has(edge.target)) ||
        (!graph && !distinct(edges.map((step) => step.id)))) fail('图/时序标识及连线端点无效。');
    }
  }
  for (const state of Object.values(states)) {
    if (state.type !== 'files') continue;
    if (!distinct(state.files.map((file) => file.path)) ||
      state.files.some((file) => file.path.split('/').includes('..')) ||
      state.files.reduce((size, file) => size + new TextEncoder().encode(file.content).length, 0) > 100000) fail('项目文件路径或总大小无效。');
  }
  for (const input of Object.values(inputs)) {
    if (input.type === 'binary_search' && input.values.some((n, i) => i > 0 && n < input.values[i - 1])) fail('二分查找输入必须有序。');
    if (input.type === 'bfs') {
      const ids = new Set(input.nodes);
      if (ids.size !== input.nodes.length || !ids.has(input.start) ||
        input.edges.some((e) => !ids.has(e.source) || !ids.has(e.target)) ||
        !distinct(input.edges.map((e) => `${e.source}\0${e.target}`))) fail('BFS 节点、起点或连线无效。');
    }
    if (input.type === 'grid_paths' &&
      (!distinct((input.blocked ?? []).map((c) => `${c.row},${c.column}`)) ||
      (input.blocked ?? []).some((c) => c.row >= input.rows || c.column >= input.columns))) fail('障碍格必须唯一且位于网格内。');
    if (input.type === 'interval_scan' && (!distinct(input.intervals.map((item) => item.id)) ||
      input.intervals.some((item) => item.start >= item.end))) fail('区间标识必须唯一，起点必须小于终点。');
    if (input.type === 'bitwise' && Math.max(input.left, input.right) >= 2 ** input.width) fail('操作数必须在位宽内。');
    if (input.type === 'geometry' && (!distinct(input.points.map((p) => p.id)) ||
      !distinct(input.points.map((p) => `${p.x},${p.y}`)))) fail('几何点标识和位置必须各不相同。');
  }
  return { ...value, states, inputs, layout: value.layout ?? 'stack' };
}

export function initialCompositionDraftV2(definition) {
  const defaults = { choice: [], annotations: [], playback: 0, selection: null, text: '' };
  return {
    values: Object.fromEntries(Object.entries(definition.states ?? {}).map(([id, state]) =>
      [id, structuredClone(state.type === 'files' ? state.files : state.value ?? defaults[state.type])])),
    annotations: {}, expanded: {}, selectedFiles: {}, previews: {},
  };
}

export function compositionContentKey(artifact) {
  const ref = artifact.content_ref;
  return `${artifact.id}:${ref.owner}:${ref.id}:${ref.revision}:${ref.public_identity}`;
}

export function receiptMatches(artifact, receipt, componentId) {
  return receipt?.artifact_id === artifact.id && receipt?.component_id === componentId &&
    receipt?.content_ref?.owner === artifact.content_ref.owner &&
    receipt?.content_ref?.id === artifact.content_ref.id &&
    receipt?.content_ref?.revision === artifact.content_ref.revision &&
    receipt?.content_ref?.public_identity === artifact.content_ref.public_identity;
}

export function executableCode(code) {
  return typeof code === 'string' && code.trim().length > 0 &&
    code.length <= 12000 && new TextEncoder().encode(code).length <= 12000;
}
