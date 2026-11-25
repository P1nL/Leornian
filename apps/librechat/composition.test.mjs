import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync, readFileSync } from 'node:fs';
import { parseComposition, initialCompositionDraft, savedReviewAnnotations, currentCodeResult } from './composition-runtime.mjs';
import { breadthFirstDemo } from './algorithm-demos.mjs';

const examples = JSON.parse(readFileSync(new URL('./composition-examples.json', import.meta.url), 'utf8'));

test('all scene examples pass generated schema and relational validation', () => {
  for (const example of examples) assert.equal(parseComposition(example), example);
});

test('invalid versions, component names, dangling and repeated graph bindings are rejected', () => {
  for (const [field, value] of [
    ['nodes', ['A', 'A']], ['nodes', []], ['nodes', Array.from({ length: 13 }, (_, i) => `X${i}`)],
    ['start', 'missing'], ['edges', [{ source: 'A', target: 'missing' }]],
    ['edges', [{ source: 'A', target: 'B' }, { source: 'A', target: 'B' }]],
    ['views', ['queue']], ['views', ['graph', 'graph']], ['views', ['graph', 'browser_script']],
  ]) {
    const valueToCheck = structuredClone(examples[0]);
    valueToCheck.scene[field] = value;
    assert.throws(() => parseComposition(valueToCheck), undefined, field);
  }
  assert.throws(() => parseComposition({ ...examples[0], schema_version: 'learning_composition.v2' }));
  const repair = structuredClone(examples[3]);
  repair.scene.views = ['diff', 'cases'];
  assert.throws(() => parseComposition(repair));
});

test('configuration cannot grant actions, return grades, inject callbacks or carry private answers', () => {
  for (const field of ['onClick', 'endpoint', 'allowed_actions', 'result', 'answer']) {
    const value = structuredClone(examples[2]);
    value.scene[field] = 'not-authorized';
    assert.throws(() => parseComposition(value));
  }
  const value = structuredClone(examples[2]);
  value.scene.code = 'x'.repeat(20001);
  assert.throws(() => parseComposition(value));
  assert.throws(() => parseComposition({ ...examples[0], title: ' ' }));
});

test('BFS consumes custom input, respects edge order, and never enqueues a node twice', () => {
  const definition = structuredClone(examples[1]);
  definition.scene.edges.push({ source: 'C', target: 'C' });
  const input = parseComposition(definition).scene;
  const before = JSON.stringify(input);
  const trace = breadthFirstDemo(input);
  assert.equal(trace.steps.at(-1).variables.order, 'C → A → B');
  assert.equal(trace.steps.at(-1).scene.nodes.find((node) => node.id === 'D').tone, 'idle');
  for (const step of trace.steps) {
    assert.equal(new Set(step.scene.queue.map((item) => item.id)).size, step.scene.queue.length);
    assert.ok(step.line >= 1 && step.line <= trace.code.length);
  }
  assert.equal(trace.steps[0].scene.queue[0].value, 'C');
  assert.equal(JSON.stringify(input), before);
  const one = { nodes: ['Only'], edges: [], start: 'Only' };
  assert.equal(breadthFirstDemo(one).steps.at(-1).variables.order, 'Only');
  const ordered = { nodes: ['A', 'B', 'C'], edges: [{ source: 'A', target: 'C' }, { source: 'A', target: 'B' }], start: 'A' };
  assert.equal(breadthFirstDemo(ordered).steps.at(-1).variables.order, 'A → C → B');
});

test('review save is separate from submission and stale code results do not match new drafts', () => {
  const state = initialCompositionDraft(examples[2]);
  assert.equal(savedReviewAnnotations(state, 5), null);
  state.drafts[4] = 'overwrite';
  assert.equal(savedReviewAnnotations(state, 5), null);
  state.reasons[4] = 'overwrite';
  assert.equal(savedReviewAnnotations(state, 5), null);
  delete state.drafts[4];
  assert.deepEqual(savedReviewAnnotations(state, 5), [{ line: 4, reason: 'overwrite' }]);
  state.reasons[99] = 'invalid';
  assert.equal(savedReviewAnnotations(state, 5), null);
  const receipt = { code: 'original', rows: [['1', '1']] };
  assert.equal(currentCodeResult(receipt, 'original'), receipt);
  assert.equal(currentCodeResult(receipt, 'edited'), null);
  assert.equal(initialCompositionDraft(examples[3]).code, examples[3].scene.code);
});

test('reusable renderer dependency graph excludes demo state and network adapters', () => {
  const seen = new Set();
  const visit = (name) => {
    if (seen.has(name)) return;
    seen.add(name);
    assert.ok(!['DemoUI.tsx', 'demo-state.mjs', 'learning-demo-data.mjs', 'CompositionGallery.tsx'].includes(name), name);
    const text = readFileSync(new URL(name, import.meta.url), 'utf8');
    if (name.endsWith('.css')) return;
    assert.doesNotMatch(text, /\bfetch\s*\(|new\s+(?:WebSocket|EventSource)\s*\(/);
    for (const match of text.matchAll(/(?:from\s+|import\s*)['"]\.\/([^'"]+)['"]/g)) {
      const child = match[1];
      const resolved = [child, `${child}.tsx`, `${child}.ts`, `${child}.mjs`]
        .find((candidate) => existsSync(new URL(candidate, import.meta.url)));
      assert.ok(resolved, child);
      visit(resolved);
    }
  };
  visit('LearningComposition.tsx');
  visit('PracticeWorkbench.tsx');
});
