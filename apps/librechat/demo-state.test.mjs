import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  initialDemoState, createDemoStore, restoreDemoState, demoStorageKey,
  checkResponse, codeExampleResult, sqlExampleResult, workspaceActionState, rangeAnswerReady,
} from './demo-state.mjs';
import {
  artifacts, checks, presentations, brokenCode, fixedCode, sampleSql, messageWidgets, messageReferences,
  artifactById, readingDocuments, extraConversations,
} from './learning-demo-data.mjs';
import { artifactCatalog, galleryGroups, learningInteractionCatalog } from './artifact-catalog.mjs';
import { componentCatalog, componentCount, componentProps } from './component-catalog.mjs';
import { inlineDiffModel, lineDiff, normalizeParameter } from './component-utils.mjs';

function memoryStorage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test('all eight presentation types and six knowledge check forms have concrete example content', () => {
  assert.deepEqual([...new Set(artifacts.map((entry) => entry.presentation.type))].sort(), [...presentations].sort());
  assert.deepEqual(checks.map((check) => check.subtype).sort(), ['single', 'multiple', 'prediction', 'ordering', 'range', 'short'].sort());
  for (const check of checks) {
    assert.ok(check.prompt.length > 5 && check.explanation.length > 5);
  }
  const containers = ['route', 'update', 'exam', 'reviewActivity'];
  for (const widgets of Object.values(messageWidgets)) {
    for (const id of widgets) assert.ok(artifactById.has(id) || containers.includes(id));
  }
});

test('style gallery lists every existing artifact and companion widget without duplicating examples', () => {
  assert.deepEqual(artifactCatalog.map((group) => group.id), presentations);
  const examples = artifactCatalog.flatMap((group) => group.examples);
  assert.equal(examples.length, artifacts.length);
  assert.deepEqual(examples.map((example) => example.id).sort(), artifacts.map((artifact) => artifact.id).sort());
  for (const example of examples) {
    assert.equal(example.conversationId, artifactById.get(example.id).conversationId);
    assert.equal(example.title, artifactById.get(example.id).title);
  }
  const widgets = [...new Set(Object.values(messageWidgets).flat())].sort();
  const galleryExamples = galleryGroups.flatMap((group) => group.examples);
  assert.deepEqual(galleryExamples.filter((example) => !example.previewOnly).map((example) => example.id).sort(), widgets);
  assert.deepEqual(galleryExamples.filter((example) => example.previewOnly).map((example) => example.id), ['source', 'assistance']);
  assert.equal(learningInteractionCatalog.examples.length, 5);
  assert.ok(galleryGroups.every((group) => group.examples.length > 0));
});

test('message citations reuse precise sources without standalone source widgets or repeated question prose', () => {
  assert.ok(!Object.values(messageWidgets).flat().includes('source'));
  assert.deepEqual(messageReferences['demo-python-learning-message-4'], ['source']);
  for (const id of Object.values(messageReferences).flat()) {
    const definition = artifactById.get(id);
    const { documentId, block } = definition.citation;
    assert.equal(definition.presentation.type, 'source_locator');
    assert.ok(readingDocuments[documentId].blocks[block]);
  }
  const source = artifactById.get('source').citation;
  assert.match(readingDocuments[source.documentId].blocks[source.block], /return.*print/);
  const lesson = extraConversations.find((entry) => entry.id === 'demo-knowledge-checks');
  for (const [index, check] of checks.entries()) {
    assert.ok(lesson.entries[index + 1][1].length > 0);
    assert.ok(!lesson.entries[index + 1][1].includes(check.prompt));
  }
});

test('composable gallery has eight categories and thirty-one documented components with honest artifact links', () => {
  assert.deepEqual(componentCatalog.map((group) => group.id),
    ['content', 'code', 'data', 'visual', 'answer', 'process', 'feedback', 'actions']);
  const examples = componentCatalog.flatMap((group) => group.examples);
  assert.equal(new Set(examples.map((example) => example.id)).size, examples.length);
  assert.equal(examples.length, 32);
  assert.equal(componentCount, 31);
  const components = [...new Set(examples.flatMap((example) => example.components))];
  assert.deepEqual(components.sort(), Object.keys(componentProps).sort());
  for (const example of examples) {
    assert.ok(example.components.length && example.selectors);
    assert.ok(example.artifacts.length || example.previewOnly === true);
    for (const id of example.artifacts) assert.ok(artifactById.has(id), `missing original artifact: ${id}`);
  }
  assert.equal(componentCatalog.find((group) => group.id === 'answer').examples.length, 7);
  assert.equal(componentCatalog.find((group) => group.id === 'visual').examples.length, 12);
  assert.deepEqual(artifactCatalog.map((group) => group.id), presentations);
});

test('unified diff keeps unchanged lines and displays removed lines before their replacements', () => {
  const rows = lineDiff(brokenCode, fixedCode);
  assert.deepEqual(rows.filter((row) => row.kind !== 'same').map(({ kind, text, beforeLine, afterLine }) =>
    [kind, text, beforeLine, afterLine]), [
    ['removed', '        result = value', 4, null], ['added', '        result += value', null, 4],
  ]);
  assert.ok(lineDiff(fixedCode, fixedCode).every((row) => row.kind === 'same'));
  assert.deepEqual(lineDiff('', ''), []);
});

test('unified diff preserves both texts across separated edits, repeated lines and empty lines', () => {
  for (const [before, after] of [
    ['a\nb\nc\nd\ne', 'a\nB\nc\nD\ne'],
    ['x\nx\ny\n', 'x\ny\nx\n'],
    ['', 'first\n'], ['last\n', ''], ['a\r\nb', 'a\nb'],
  ]) {
    const rows = lineDiff(before, after);
    assert.equal(rows.filter((row) => row.kind !== 'added').map((row) => row.text).join('\n'), before.replaceAll('\r\n', '\n'));
    assert.equal(rows.filter((row) => row.kind !== 'removed').map((row) => row.text).join('\n'), after);
  }
});

test('large code changes keep exact removed and added content without a quadratic table', () => {
  const before = Array.from({ length: 1001 }, (_, index) => `old ${index}`).join('\n');
  const after = Array.from({ length: 1001 }, (_, index) => `new ${index}`).join('\n');
  const rows = lineDiff(before, after);
  assert.equal(rows.filter((row) => row.kind === 'removed').map((row) => row.text).join('\n'), before);
  assert.equal(rows.filter((row) => row.kind === 'added').map((row) => row.text).join('\n'), after);
});

test('parameter normalization respects limits, negative values and decimal steps', () => {
  assert.equal(normalizeParameter(-5, 0, 8), 0);
  assert.equal(normalizeParameter(99, 0, 8), 8);
  assert.equal(normalizeParameter(-2, -3, 5), -2);
  assert.equal(normalizeParameter(.36, 0, 1, .1), .4);
  assert.equal(normalizeParameter(2.3, 0, 8), 2);
});

test('inline diff positions readonly deletions before the matching current line and preserves current document', () => {
  const model = inlineDiffModel(brokenCode, fixedCode);
  assert.equal(model.deletions.length, 1);
  assert.equal(model.deletions[0].atLine, 4);
  assert.equal(model.deletions[0].rows[0].beforeLine, 4);
  assert.equal(model.lines[3].kind, 'added');
  assert.equal(model.lines.map((line) => line.text).join('\n'), fixedCode);
  const edited = inlineDiffModel(brokenCode, 'def total(values):\n    return sum(values)');
  assert.equal(edited.lines.map((line) => line.text).join('\n'), 'def total(values):\n    return sum(values)');
});

test('inline diff handles deletions at the start, middle, EOF and an empty current file', () => {
  const model = inlineDiffModel('first\nkeep\nmiddle\nend\ntail', 'keep\nend');
  assert.deepEqual(model.deletions.map((group) => group.atLine), [1, 2, null]);
  assert.deepEqual(model.lines.map((line) => line.beforeLine), [2, 4]);
  assert.deepEqual(inlineDiffModel('old', '').deletions.map((group) => group.atLine), [null]);
  assert.equal(inlineDiffModel('', 'new').deletions.length, 0);
  assert.deepEqual(inlineDiffModel('', ''), { lines: [], deletions: [] });
});

test('public check examples distinguish correct, incorrect, ordering, ranges, and unscored short answers', () => {
  for (const check of checks.filter((entry) => !['short', 'range'].includes(entry.subtype))) {
    assert.equal(checkResponse(check, check.answer).kind, 'correct');
  }
  assert.equal(checkResponse(checks[0], '0').kind, 'incorrect');
  assert.equal(checkResponse(checks[1], ['空列表']).kind, 'incorrect');
  assert.equal(checkResponse(checks[3], ['GROUP BY', 'WHERE', 'HAVING']).kind, 'incorrect');
  assert.equal(checkResponse(checks[4], [3]).kind, 'reference');
  assert.match(checkResponse(checks[4], [3]).text, /不一致/);
  assert.match(checkResponse(checks[4], [4]).text, /与参考一致/);
  assert.equal(checkResponse(checks[5], 'a custom answer').kind, 'reference');
});

test('line annotations require reasons, persist drafts, and lock the submitted answer without scoring reasons', () => {
  const storage = memoryStorage();
  const store = createDemoStore(storage);
  const check = checks.find((entry) => entry.id === 'range');
  assert.equal(rangeAnswerReady(check, [], {}), false);
  assert.equal(rangeAnswerReady(check, [4], { 4: '  ' }), false);
  assert.equal(rangeAnswerReady(check, [3, 4], { 4: '覆盖累加器' }), false);
  assert.equal(rangeAnswerReady(check, [99], { 99: '不存在的行' }), false);
  store.artifact('range', { response: [4] });
  store.answerCheck('range', [4]);
  assert.equal(store.getSnapshot().artifacts.range.submitted, undefined);
  store.artifact('range', { lineReasons: { 4: '覆盖已有结果，应保留原值再累加。' } });
  const restored = createDemoStore(storage);
  assert.equal(restored.getSnapshot().artifacts.range.lineReasons[4], '覆盖已有结果，应保留原值再累加。');
  restored.answerCheck('range', [4]);
  const submitted = restored.getSnapshot().artifacts.range;
  assert.equal(submitted.submitted, true);
  assert.equal(submitted.result.kind, 'reference');
  assert.match(submitted.result.text, /不自动评判理由/);
  restored.answerCheck('range', [3]);
  assert.deepEqual(restored.getSnapshot().artifacts.range, submitted);
});

test('review drafts must be explicitly saved before whole-review submission', () => {
  const storage = memoryStorage();
  const store = createDemoStore(storage);
  store.artifact('range', { lineDrafts: { 4: '   ' } });
  store.saveLineAnnotation('range', 4);
  assert.equal(store.getSnapshot().artifacts.range.response, undefined);
  store.artifact('range', { lineDrafts: { 4: '  保留原值再累加  ' } });
  store.answerCheck('range', [4]);
  assert.equal(store.getSnapshot().artifacts.range.submitted, undefined);
  store.saveLineAnnotation('range', 4);
  const saved = store.getSnapshot().artifacts.range;
  assert.deepEqual(saved.response, [4]);
  assert.equal(saved.lineReasons[4], '保留原值再累加');
  assert.deepEqual(saved.lineDrafts, {});
  assert.equal(saved.submitted, undefined);
  store.artifact('range', { lineDrafts: { 4: '未保存的修改', 3: '另一条草稿' } });
  store.answerCheck('range', [4]);
  assert.equal(store.getSnapshot().artifacts.range.submitted, undefined);
  const restored = createDemoStore(storage);
  assert.equal(restored.getSnapshot().artifacts.range.lineReasons[4], '保留原值再累加');
  assert.equal(restored.getSnapshot().artifacts.range.lineDrafts[4], '未保存的修改');
  restored.artifact('range', { lineDrafts: {} });
  restored.answerCheck('range', [4]);
  const submitted = restored.getSnapshot().artifacts.range;
  restored.saveLineAnnotation('range', 4);
  assert.deepEqual(restored.getSnapshot().artifacts.range, submitted);
  assert.equal(submitted.submitted, true);
  assert.equal(submitted.result.kind, 'reference');
});

test('code and SQL only show known public fixture results; arbitrary input is not executed or passed', () => {
  assert.equal(codeExampleResult(brokenCode).passed, false);
  assert.equal(codeExampleResult(fixedCode).passed, true);
  const arbitrary = codeExampleResult('raise RuntimeError("do not execute")');
  assert.equal(arbitrary.passed, undefined);
  assert.deepEqual(arbitrary.rows, []);
  assert.equal(sqlExampleResult(sampleSql).rows.length, 2);
  assert.equal(sqlExampleResult('DROP TABLE orders;').state, 'active');
  assert.deepEqual(sqlExampleResult('DROP TABLE orders;').rows, []);
});

test('button completion requires a current result, not a click, stale draft or unknown outcome', () => {
  const result = { ...codeExampleResult(fixedCode), input: fixedCode };
  const entry = { state: 'completed', result };
  assert.equal(workspaceActionState(entry, fixedCode), 'completed');
  assert.equal(workspaceActionState(entry, brokenCode), 'idle');
  assert.equal(workspaceActionState({ ...entry, state: 'running' }, fixedCode), 'busy');
  assert.equal(workspaceActionState({ ...entry, state: 'unknown' }, fixedCode), 'unknown');
  assert.equal(workspaceActionState({ ...entry, state: 'cancelled' }, fixedCode), 'idle');
  assert.equal(workspaceActionState({ state: 'active', result: { ...codeExampleResult(brokenCode), input: brokenCode } }, brokenCode), 'attention');
  assert.equal(workspaceActionState({ state: 'ready' }, fixedCode), 'idle');
  const sql = { state: 'completed', result: { ...sqlExampleResult(sampleSql), input: sampleSql, dialect: 'SQLite' } };
  assert.equal(workspaceActionState(sql, sampleSql, 'SQLite'), 'completed');
  assert.equal(workspaceActionState(sql, sampleSql, 'MySQL'), 'idle');
});

test('demo draft and assistance changes survive refresh without restoring a reader or executing actions', () => {
  const storage = memoryStorage();
  const store = createDemoStore(storage);
  store.artifact('code', { draft: 'draft text', hints: 2, answerVisible: true });
  store.update({ reader: { id: 'demo-python-functions', block: 2 } });
  const restored = createDemoStore(storage);
  assert.equal(restored.getSnapshot().artifacts.code.draft, 'draft text');
  assert.equal(restored.getSnapshot().artifacts.code.hints, 2);
  assert.equal(restored.getSnapshot().artifacts.code.answerVisible, true);
  assert.equal(restored.getSnapshot().reader, null);
  assert.equal(storage.getItem('model-api-key'), null);
});

test('interrupted runs and tests restore as unknown, never silently resume or retry', () => {
  const storage = memoryStorage();
  const state = initialDemoState();
  state.artifacts.code = { state: 'running', draft: brokenCode };
  state.tasks.push({ id: 'interrupted', artifactId: 'code', state: 'running' });
  state.environment.course = 'preparing';
  state.models.state = 'testing';
  storage.setItem(demoStorageKey, JSON.stringify(state));
  let schedules = 0;
  const store = createDemoStore(storage, () => { schedules++; });
  assert.equal(store.getSnapshot().artifacts.code.state, 'unknown');
  assert.equal(store.getSnapshot().tasks.at(-1).state, 'unknown');
  assert.equal(store.getSnapshot().models.state, 'unknown');
  assert.equal(store.getSnapshot().environment.course, 'paused');
  store.task('code', 'must not replay', { state: 'completed' });
  assert.equal(schedules, 0);
});

test('cancelled demo work keeps history and a late callback cannot fabricate completion', () => {
  const callbacks = [];
  const store = createDemoStore(null, (callback) => callbacks.push(callback));
  const before = store.getSnapshot().tasks.length;
  const id = store.task('code', 'sample run', { state: 'completed' });
  store.cancelTask(id);
  callbacks[0]();
  assert.equal(store.getSnapshot().tasks.length, before + 1);
  assert.equal(store.getSnapshot().tasks.at(-1).state, 'cancelled');
  assert.equal(store.getSnapshot().artifacts.code.state, 'cancelled');
  assert.equal(store.getSnapshot().artifacts.code.attempts, undefined);
  assert.ok(store.getSnapshot().tasks.some((task) => task.state === 'unknown'));
  assert.ok(store.getSnapshot().tasks.some((task) => task.state === 'failed'));
});

test('simulated model failures and unknown outcomes are retained as such in task history', () => {
  const callbacks = [];
  const store = createDemoStore(null, (callback) => callbacks.push(callback));
  store.task('models', 'unknown test example', { state: 'unknown' });
  callbacks[0]();
  store.task('models', 'failed test example', { state: 'failed' });
  callbacks[1]();
  assert.deepEqual(store.getSnapshot().tasks.slice(-2).map((task) => task.state), ['unknown', 'failed']);
});

test('duplicate run clicks do not schedule parallel work and later explicit practice keeps earlier results', () => {
  const callbacks = [];
  const store = createDemoStore(null, (callback) => callbacks.push(callback));
  store.task('code', 'first sample', { state: 'active', result: codeExampleResult(brokenCode) });
  store.task('code', 'duplicate sample', { state: 'completed' });
  assert.equal(callbacks.length, 1);
  callbacks[0]();
  store.task('code', 'corrected sample', { state: 'completed', result: codeExampleResult(fixedCode) });
  callbacks[1]();
  assert.equal(store.getSnapshot().artifacts.code.attempts.length, 2);
  assert.equal(store.getSnapshot().artifacts.code.attempts[0].result.passed, false);
  assert.equal(store.getSnapshot().artifacts.code.attempts[1].result.passed, true);
});

test('submitted knowledge checks do not replace the original response on repeated submission', () => {
  const store = createDemoStore(null);
  store.answerCheck('choice', '0');
  store.answerCheck('choice', 'None');
  assert.equal(store.getSnapshot().artifacts.choice.response, '0');
  assert.equal(store.getSnapshot().artifacts.choice.result.kind, 'incorrect');
});

test('exam requires active state and a complete group and locks its single submission', () => {
  const store = createDemoStore(null);
  store.submitExam();
  assert.equal(store.getSnapshot().exam.history.length, 0);
  store.patch('exam', { state: 'active', choice: 'None' });
  store.submitExam();
  assert.equal(store.getSnapshot().exam.history.length, 0);
  store.patch('exam', { code: fixedCode });
  store.submitExam();
  store.submitExam();
  assert.equal(store.getSnapshot().exam.history.length, 1);
  assert.equal(store.getSnapshot().exam.state, 'completed');
});

test('cancelled course preparation cannot become ready through its late timer', () => {
  const callbacks = [];
  const store = createDemoStore(null, (callback) => callbacks.push(callback));
  store.patch('environment', { engine: 'ready', consent: true, course: 'preparing' });
  const id = store.task('course', 'course sample', {}, () => store.patch('environment', { course: 'ready' }));
  store.cancelTask(id);
  store.patch('environment', { consent: false, course: 'declined' });
  callbacks[0]();
  assert.equal(store.getSnapshot().environment.course, 'declined');
  assert.equal(store.getSnapshot().environment.consent, false);
});

test('storage from another demo version or malformed data does not become a configuration or execution', () => {
  const storage = memoryStorage();
  storage.setItem(demoStorageKey, '{"version":999,"models":{"credential":true}}');
  assert.deepEqual(restoreDemoState(storage), initialDemoState());
  storage.setItem(demoStorageKey, 'not valid json');
  assert.deepEqual(restoreDemoState(storage), initialDemoState());
});
