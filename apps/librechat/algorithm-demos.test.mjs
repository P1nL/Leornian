import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  binarySearchDemo, bracketDemo, breadthFirstDemo, gridPathsDemo, backtrackingDemo,
  intervalDemo, bitCountDemo, closestPairDemo,
} from './algorithm-demos.mjs';
import { componentCatalog } from './component-catalog.mjs';

test('eight algorithm scenes share replayable snapshots with valid code highlights', () => {
  const demos = [binarySearchDemo(17), bracketDemo(), breadthFirstDemo(), gridPathsDemo(),
    backtrackingDemo(), intervalDemo(), bitCountDemo(), closestPairDemo()];
  const scenes = componentCatalog.find((category) => category.id === 'visual').examples
    .filter((example) => example.id.startsWith('algorithm-'));
  assert.equal(scenes.length, 8);
  assert.ok(scenes.every((example) => example.previewOnly && example.components.includes('AlgorithmPlayer')));
  for (const demo of demos) {
    assert.ok(demo.steps.length > 2);
    for (const frame of demo.steps) {
      assert.ok(frame.line >= 1 && frame.line <= demo.code.length);
      assert.ok(frame.note && frame.variables && frame.scene);
    }
    assert.deepEqual(JSON.parse(JSON.stringify(demo)), demo);
    // A later state must not mutate an earlier state when scrubbing backward.
    const first = JSON.stringify(demo.steps[0]);
    demo.steps.at(-1).scene.testOnly = true;
    assert.equal(JSON.stringify(demo.steps[0]), first);
  }
});

test('binary search covers left, right, midpoint and missing targets', () => {
  for (const [target, index] of [[2, 0], [17, 5], [11, 3], [12, -1]]) {
    const demo = binarySearchDemo(target);
    assert.equal(demo.steps.at(-1).variables.index, index);
    if (index < 0) assert.equal(demo.steps.at(-1).scene.pointers.length, 0);
    else assert.equal(demo.steps.at(-1).scene.items[index].tone, 'done');
  }
  assert.equal(binarySearchDemo(17).steps[0].scene.items.filter((item) => item.tone === 'muted').length, 0);
});

test('stack snapshots preserve pushes and pops and stop at a mismatched bracket', () => {
  const matched = bracketDemo();
  assert.equal(matched.steps.at(-1).variables.valid, 'True');
  assert.equal(matched.steps.at(-1).scene.items.length, 0);
  assert.equal(Math.max(...matched.steps.map((step) => step.scene.items.length)), 2);
  const mismatch = bracketDemo('([)]');
  assert.equal(mismatch.steps.at(-1).variables.valid, 'False');
  assert.equal(mismatch.steps.at(-1).scene.input[2].tone, 'rejected');
  assert.equal(bracketDemo('(').steps.at(-1).variables.valid, 'False');
});

test('BFS marks at enqueue time and does not enqueue the shared neighbor twice', () => {
  const demo = breadthFirstDemo();
  assert.equal(demo.steps.at(-1).variables.order, 'A → B → C → D → E');
  assert.ok(demo.steps.some((step) => step.line === 5));
  for (const step of demo.steps) {
    const ids = step.scene.queue.map((item) => item.id);
    assert.equal(new Set(ids).size, ids.length);
  }
  assert.equal(demo.steps[0].scene.nodes.filter((node) => node.tone === 'done').length, 0);
  assert.ok(demo.steps.at(-1).scene.nodes.every((node) => node.tone === 'done'));
});

test('grid recurrence excludes the obstacle and produces four paths', () => {
  const demo = gridPathsDemo();
  assert.equal(demo.steps.at(-1).variables.paths, 4);
  const values = demo.steps.at(-1).scene.cells.map((row) => row.map((cell) => cell.value));
  assert.deepEqual(values, [[1, 1, 1, 1], [1, '×', 1, 2], [1, 1, 2, 4]]);
  assert.equal(demo.steps[0].scene.cells[0][0].value, '·');
});

test('backtracking exposes pruning, a retained solution and an empty returned call stack', () => {
  const demo = backtrackingDemo();
  assert.ok(demo.steps.some((step) => step.line === 3));
  assert.equal(demo.steps.at(-1).variables.solutions, 1);
  assert.deepEqual(demo.steps.at(-1).scene.stack, []);
  const found = demo.steps.at(-1).scene.calls.filter((call) => call.tone === 'done');
  assert.deepEqual(found.map((call) => call.label), ['[1, 3] = 4']);
  assert.equal(demo.steps[0].scene.calls.length, 1);
  assert.equal(demo.steps[0].scene.calls[0].tone, 'active');
});

test('greedy interval selection allows adjoining endpoints and rejects overlaps', () => {
  const demo = intervalDemo();
  assert.equal(demo.steps.at(-1).variables.selected, 'A, C, D');
  const selected = demo.steps.at(-1).scene.intervals.filter((interval) => interval.tone === 'done');
  assert.ok(selected.every((interval, index) => index === 0 || interval.start >= selected[index - 1].end));
  assert.equal(demo.steps[0].scene.intervals.filter((interval) => interval.tone === 'done').length, 0);
});

test('bit trace clears one bit at a time and preserves the operands for comparison', () => {
  const demo = bitCountDemo();
  assert.equal(demo.steps.at(-1).variables.count, 3);
  const operations = demo.steps.filter((step) => step.line === 3);
  assert.deepEqual(operations.map((step) => step.variables.after), [12, 8, 0]);
  for (const step of operations) {
    const [a, b, result] = step.scene.rows.map((row) => row.value);
    assert.equal(a & b, result);
  }
});

test('geometry compares all six pairs and keeps the closest pair B-C', () => {
  const demo = closestPairDemo();
  assert.equal(demo.steps.filter((step) => step.line === 3).length, 6);
  assert.deepEqual(demo.steps.at(-1).variables, { pair: 'B–C', distance: 1 });
  assert.equal(demo.steps[0].scene.links.length, 0);
});
