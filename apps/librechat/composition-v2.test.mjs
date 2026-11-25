import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import {
  compositionContentKey, executableCode, initialCompositionDraftV2,
  parseCompositionV2, receiptMatches,
} from './composition-v2-runtime.mjs';
import { componentCatalog } from './component-catalog.mjs';
import { compositionAlgorithm } from './algorithm-demos.mjs';

const config = () => ({
  schema_version: 'learning_composition.v2', title: 'Shared observation',
  states: { step: { type: 'playback' }, target: { type: 'number', value: 4 } },
  inputs: { numbers: { type: 'binary_search', values: [1, 4, 9], target_state: 'target' } },
  components: [
    { id: 'player', component: 'AlgorithmPlayer', props: { label: 'Search', algorithm: 'binary_search', input: 'numbers', state: 'step' } },
    { id: 'view', component: 'AlgorithmSequence', props: { label: 'Values', timeline: 'player' } },
    { id: 'target', component: 'ParameterControl', props: { label: 'Target', state: 'target', minimum: 0, maximum: 10 } },
  ],
});

test('the generated V2 directory covers exactly the incumbent eight categories and 31 components', async () => {
  const directory = JSON.parse(await readFile(new URL('composition-directory.generated.json', import.meta.url)));
  const expected = new Set(componentCatalog.flatMap((category) => category.examples.flatMap((example) => example.components)));
  assert.equal(expected.size, 31);
  assert.equal(new Set(directory.map((entry) => entry.category)).size, 8);
  assert.deepEqual(new Set(directory.map((entry) => entry.component)), expected);
});

test('typed shared data and timeline refs work without a recipe name or model-authored trace', () => {
  const definition = parseCompositionV2(config());
  const draft = initialCompositionDraftV2(definition);
  assert.equal(draft.values.step, 0);
  const input = definition.inputs.numbers;
  assert.equal(compositionAlgorithm(input, draft.values).steps.at(-1).variables.index, 1);
  draft.values.target = 8;
  assert.equal(compositionAlgorithm(input, draft.values).steps.at(-1).variables.index, -1);
  assert.equal(config().states.target.value, 4);
});

test('wrong ports, duplicate ids, unsupported timeline links and arbitrary code fields are rejected', () => {
  for (const mutate of [
    (x) => { x.states.step = { type: 'text' }; },
    (x) => { x.components[1].props.timeline = 'missing'; },
    (x) => { x.components[1].component = 'AlgorithmGraph'; },
    (x) => { x.components[1].id = 'player'; },
    (x) => { x.inputs.numbers.values = [9, 1, 4]; },
    (x) => { x.components[0].props.script = 'fetch("/secret")'; },
    (x) => { x.states.answer = { type: 'text', value: 'model pretending to be learner' }; },
    (x) => { x.allowed_actions = ['run']; },
  ]) {
    const value = config(); mutate(value);
    assert.throws(() => parseCompositionV2(value));
  }
});

test('eight algorithm contracts consume actual dynamic inputs and produce replayable finite snapshots', () => {
  const examples = [
    [{ type: 'binary_search', values: [-10, 6, 21], target_state: 'n' }, { n: 21 }, (last) => assert.equal(last.variables.index, 2)],
    [{ type: 'brackets', text: '{[}]' }, {}, (last) => assert.equal(last.variables.valid, 'False')],
    [{ type: 'bfs', nodes: ['X', 'Y', 'Z'], start: 'Z', edges: [{ source: 'Z', target: 'X' }] }, {}, (last) => assert.equal(last.variables.order, 'Z → X')],
    [{ type: 'grid_paths', rows: 2, columns: 3, blocked: [{ row: 0, column: 1 }] }, {}, (last) => assert.equal(last.variables.paths, 1)],
    [{ type: 'combination_sum', values: [2, 5, 7], target: 7 }, {}, (last) => assert.equal(last.variables.solutions, 2)],
    [{ type: 'interval_scan', intervals: [{ id: 'A', start: 2, end: 4 }, { id: 'B', start: -5, end: -1 }, { id: 'C', start: -1, end: 2 }] }, {}, (last) => assert.equal(last.variables.selected, 'B, C, A')],
    [{ type: 'bitwise', left: 3, right: 6, operation: 'xor', width: 3 }, {}, (last) => assert.equal(last.variables.result, 5)],
    [{ type: 'geometry', points: [{ id: 'A', x: -1, y: -1 }, { id: 'B', x: 0, y: 0 }, { id: 'C', x: 1, y: -1 }] }, {}, (last) => assert.equal(last.variables.orientation, 'clockwise')],
  ];
  for (const [input, values, check] of examples) {
    const trace = compositionAlgorithm(input, values);
    assert.deepEqual(JSON.parse(JSON.stringify(trace)), trace);
    assert.ok(trace.steps.every((frame) => frame.line >= 1 && frame.line <= trace.code.length));
    const first = structuredClone(trace.steps[0]);
    check(trace.steps.at(-1));
    assert.deepEqual(trace.steps[0], first);
  }
});

test('content binding ignores action revision, while another artifact/version cannot supply feedback', () => {
  const artifact = { id: 'artifact', revision: 1, content_ref: { owner: 'tutor', id: 'content', revision: 1, public_identity: 'digest' } };
  const receipt = { artifact_id: artifact.id, component_id: 'answer', content_ref: { ...artifact.content_ref } };
  assert.ok(receiptMatches(artifact, receipt, 'answer'));
  assert.equal(compositionContentKey(artifact), compositionContentKey({ ...artifact, revision: 8 }));
  assert.ok(!receiptMatches({ ...artifact, id: 'another' }, receipt, 'answer'));
  assert.ok(!receiptMatches(artifact, receipt, 'editor'));
  assert.ok(!receiptMatches(artifact, { ...receipt, content_ref: { ...receipt.content_ref, revision: 2 } }, 'answer'));
  assert.ok(!executableCode('汉'.repeat(4001)));
  assert.ok(executableCode('print(1)'));
});
