import validateSchema from './composition-validator.generated.mjs';

/** @typedef {import('./composition-types.generated').components['schemas']['LearningComposition']} Composition */

/** @returns {Composition} */
export function parseComposition(value) {
  if (!validateSchema(value)) {
    const error = validateSchema.errors[0];
    throw new Error(`${error.instancePath || '/'}: ${error.message}`);
  }
  // These relational constraints mirror the Pydantic model validators.
  const scene = value.scene;
  if (scene.views && new Set(scene.views).size !== scene.views.length) throw new Error('展示视图不能重复。');
  if (scene.type === 'bfs') {
    if (!scene.views.includes('graph')) throw new Error('BFS 必须保留图视图。');
    const ids = new Set(scene.nodes);
    if (ids.size !== scene.nodes.length) throw new Error('节点标识不能重复。');
    if (!ids.has(scene.start)) throw new Error('起点必须是图中的节点。');
    const edges = new Set();
    for (const { source, target } of scene.edges) {
      if (!ids.has(source) || !ids.has(target)) throw new Error('连线两端必须是图中的节点。');
      const key = JSON.stringify([source, target]);
      if (edges.has(key)) throw new Error('有向边不能重复。');
      edges.add(key);
    }
  }
  if (scene.type === 'code_repair' && !scene.views.includes('editor')) throw new Error('修复任务必须保留编辑器。');
  return value;
}

/** @param {Composition} definition */
export function initialCompositionDraft(definition) {
  return { code: definition.scene.type === 'bfs' ? '' : definition.scene.code, reasons: {}, drafts: {} };
}

export function savedReviewAnnotations(state, lineCount) {
  if (Object.keys(state.drafts).length) return null;
  const entries = Object.entries(state.reasons);
  if (!entries.length || entries.some(([line, reason]) =>
    !Number.isInteger(Number(line)) || Number(line) < 1 || Number(line) > lineCount ||
    typeof reason !== 'string' || !reason.trim())) return null;
  return entries.map(([line, reason]) => ({ line: Number(line), reason: reason.trim() }))
    .sort((a, b) => a.line - b.line);
}

export function currentCodeResult(result, code) {
  return result?.code === code ? result : null;
}
