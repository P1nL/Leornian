import { artifactById, brokenCode, fixedCode, projectFiles, sampleSql } from './learning-demo-data.mjs';

export const demoStorageKey = 'leornian:librechat:interaction-demo:v1';
export function initialDemoState() {
  return {
    version: 1, artifacts: {}, sequence: 0, reader: null, composers: {},
    tasks: [
      { id: 'sample-waiting', title: '扫描教材 OCR（状态样例）', state: 'waiting_config', conversationId: null },
      { id: 'sample-unknown', title: '连接测试回执（状态样例）', state: 'unknown', conversationId: null },
      { id: 'sample-failed', title: '旧教材提取失败（历史样例）', state: 'failed', conversationId: null },
      { id: 'sample-cancelled', title: '上一次环境准备（历史样例）', state: 'cancelled', conversationId: null },
      { id: 'sample-superseded', title: '教材版本 1 的旧准备任务（历史样例）', state: 'superseded', conversationId: null },
    ],
    route: { revision: 1, confirmed: false, changes: '', history: [] },
    material: { permitted: true, purpose: false, state: 'sample', decision: null, version: 1 },
    environment: { engine: 'missing', course: 'waiting_authorization', consent: false },
    preferences: { mode: 'guided', paused: false, from: '19:00', to: '21:00' },
    exam: { state: 'ready', agreed: false, choice: '', code: '', history: [] },
    review: { state: 'due', answer: '', rating: null },
    assistance: { hints: 0, answer: false, branch: [], question: '', folded: false },
    intake: { goal: '', foundation: '', minutes: '30', step: 0 },
    models: { saved: false, credential: false, state: 'unconfigured', history: [] },
  };
}

export function restoreDemoState(storage) {
  const fresh = initialDemoState();
  try {
    const parsed = JSON.parse(storage?.getItem(demoStorageKey) ?? 'null');
    if (parsed?.version !== fresh.version) return fresh;
    const state = { ...fresh, ...parsed, reader: null };
    state.artifacts = Object.fromEntries(Object.entries(state.artifacts).map(([id, value]) =>
      [id, value.state === 'running' ? { ...value, state: 'unknown' } : value]));
    state.tasks = state.tasks.map((task) => task.state === 'running' ? { ...task, state: 'unknown' } : task);
    if (state.environment.course === 'preparing') state.environment.course = 'paused';
    if (state.environment.engine === 'preparing') state.environment.engine = 'paused';
    if (state.models.state === 'testing') state.models.state = 'unknown';
    return state;
  } catch {
    return fresh;
  }
}

export function rangeAnswerReady(check, response, reasons = {}, drafts = {}) {
  return Object.keys(drafts).length === 0 && Array.isArray(response) && response.length > 0 && response.every((line) =>
    Number.isInteger(line) && line >= 1 && line <= check.lines.length
    && typeof reasons[line] === 'string' && reasons[line].trim().length > 0);
}

export function checkResponse(check, response) {
  if (check.subtype === 'short') return { kind: 'reference', text: check.explanation };
  const normalize = (value) => String(value ?? '').trim().replaceAll('\r', '');
  const correct = Array.isArray(check.answer)
    ? Array.isArray(response) && (check.subtype === 'ordering'
      ? JSON.stringify(response) === JSON.stringify(check.answer)
      : JSON.stringify([...response].sort()) === JSON.stringify([...check.answer].sort()))
    : normalize(response) === normalize(check.answer);
  if (check.subtype === 'range') return {
    kind: 'reference',
    text: `${correct ? '所选代码行与参考一致。' : '所选代码行与参考不一致。'}理由已保留，本演示不自动评判理由。`,
  };
  return { kind: correct ? 'correct' : 'incorrect', text: check.explanation };
}

export function codeExampleResult(code) {
  const normalize = (value) => value.trim().replaceAll('\r', '');
  if (normalize(code) === normalize(fixedCode)) return {
    state: 'completed', label: '修正版的公开样例展示', passed: true,
    rows: [['[1, 2, 3]', '6', '6'], ['[]', '0', '0'], ['[-2, 5]', '3', '3']],
  };
  if (normalize(code) === normalize(brokenCode)) return {
    state: 'active', label: '错误版的公开样例展示', passed: false,
    rows: [['[1, 2, 3]', '6', '3'], ['[]', '0', '0'], ['[-2, 5]', '3', '5']],
  };
  return { state: 'active', label: '自定义代码已保留，但本演示不会执行或判定它。请载入内置样例查看结果。', rows: [] };
}

export function workspaceActionState(entry, draft, dialect) {
  if (entry.state === 'running') return 'busy';
  if (entry.state === 'unknown') return 'unknown';
  const result = entry.result;
  if (!result || result.input !== draft || (dialect && result.dialect !== dialect)) return 'idle';
  if (entry.state === 'completed' && result.state === 'completed') return 'completed';
  if (entry.state === 'active' && result.passed === false) return 'attention';
  return 'idle';
}

export function sqlExampleResult(sql) {
  return sql.trim().replaceAll('\r', '') === sampleSql
    ? { state: 'completed', columns: ['category', 'total'], rows: [['books', 150], ['tools', 240]] }
    : { state: 'active', columns: [], rows: [], label: '查询草稿已保留；未执行此输入。载入内置 SQL 样例可查看结果排版。' };
}

export function createDemoStore(storage, schedule = (callback) => setTimeout(callback, 900)) {
  let snapshot = restoreDemoState(storage);
  const listeners = new Set();
  const update = (change) => {
    snapshot = { ...snapshot, ...change };
    try {
      // Reader selection is transient. No API keys or uploaded originals enter this store.
      storage?.setItem(demoStorageKey, JSON.stringify({ ...snapshot, reader: null }));
    } catch { /* The UI remains usable when session storage is unavailable. */ }
    listeners.forEach((listener) => listener());
  };
  const patch = (key, values) => update({ [key]: { ...snapshot[key], ...values } });
  const artifact = (id, values) => {
    if (!artifactById.has(id)) throw new Error('Unknown demonstration artifact');
    update({ artifacts: { ...snapshot.artifacts, [id]: { ...snapshot.artifacts[id], ...values } } });
  };
  const task = (id, title, result, done) => {
    if (snapshot.artifacts[id]?.state === 'running' || snapshot.artifacts[id]?.state === 'unknown') return;
    const taskId = `demo-task-${snapshot.sequence + 1}`;
    const conversationId = artifactById.get(id)?.conversationId ?? null;
    artifactById.has(id) && artifact(id, { state: 'running' });
    update({
      sequence: snapshot.sequence + 1,
      tasks: [...snapshot.tasks, { id: taskId, artifactId: id, title, state: 'running', conversationId }],
    });
    schedule(() => {
      if (snapshot.tasks.find((entry) => entry.id === taskId)?.state !== 'running') return;
      const taskState = ['failed', 'unknown'].includes(result.state) ? result.state : 'completed';
      update({ tasks: snapshot.tasks.map((entry) => entry.id === taskId ? { ...entry, state: taskState } : entry) });
      if (artifactById.has(id)) artifact(id, { ...result, attempts: [...(snapshot.artifacts[id]?.attempts ?? []), result] });
      done?.();
    });
    return taskId;
  };
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    update, patch, artifact, task,
    cancelTask(taskId) {
      const entry = snapshot.tasks.find((candidate) => candidate.id === taskId);
      if (!entry || entry.state !== 'running') return;
      update({ tasks: snapshot.tasks.map((candidate) => candidate.id === taskId ? { ...candidate, state: 'cancelled' } : candidate) });
      if (artifactById.has(entry.artifactId)) artifact(entry.artifactId, { state: 'cancelled' });
      if (entry.artifactId === 'course') patch('environment', { course: 'cancelled' });
      if (entry.artifactId === 'engine') patch('environment', { engine: 'paused' });
      if (entry.artifactId === 'material') patch('material', { state: 'cancelled' });
      if (entry.artifactId === 'models') patch('models', { state: 'cancelled' });
    },
    saveLineAnnotation(id, line) {
      const definition = artifactById.get(id);
      const entry = snapshot.artifacts[id] ?? {};
      const draft = entry.lineDrafts?.[line];
      if (definition?.check?.subtype !== 'range' || entry.submitted
        || !Number.isInteger(line) || line < 1 || line > definition.check.lines.length
        || typeof draft !== 'string' || !draft.trim()) return;
      const lineDrafts = { ...entry.lineDrafts };
      delete lineDrafts[line];
      artifact(id, {
        response: [...new Set([...(entry.response ?? []), line])].sort((a, b) => a - b),
        lineReasons: { ...entry.lineReasons, [line]: draft.trim() }, lineDrafts,
      });
    },
    answerCheck(id, response) {
      const definition = artifactById.get(id);
      if (!definition?.check || snapshot.artifacts[id]?.submitted) return;
      if (definition.check.subtype === 'range'
        && !rangeAnswerReady(definition.check, response, snapshot.artifacts[id]?.lineReasons, snapshot.artifacts[id]?.lineDrafts)) return;
      const result = checkResponse(definition.check, response);
      artifact(id, { state: 'completed', response, result, submitted: true });
    },
    submitExam() {
      if (snapshot.exam.state !== 'active' || !snapshot.exam.choice || !snapshot.exam.code.trim()) return;
      const receipt = { choice: snapshot.exam.choice, code: snapshot.exam.code, kind: '示例整组提交' };
      patch('exam', { state: 'completed', history: [...snapshot.exam.history, receipt] });
    },
  };
}

export const demoStore = createDemoStore(typeof window === 'undefined' ? null : window.sessionStorage);
export const defaultDraft = (id) => id === 'code' ? brokenCode : id === 'sql' ? sampleSql : id === 'project' ? projectFiles['app.py'] : '';
