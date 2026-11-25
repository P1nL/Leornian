import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createNativeStore, NativeApiError } from './native-client.mjs';
import { overlayNativeSource } from './native-overlay.mjs';

const snapshot = (actor = 'owner', cursor = 1) => ({ actor: { id: actor }, cursor, turns: [] });
const session = { conversation_id: 'conversation', revision: 2, active_branch_id: 'branch' };
const intent = {
  id: 'intent', conversation_id: 'conversation', generation: 1, artifact_id: 'artifact',
  trigger_kind: 'expected_result', trigger_ref: 'original-result', priority: 1,
  state: 'pending', wait_reason: 'paused', run_id: null, run_status: null,
};

test('explicit teaching reads all scoped branches and the latest twenty intents without commands', async () => {
  const calls = [];
  const store = createNativeStore({ storage: null, request: async (path, init) => {
    calls.push({ path, method: init?.method ?? 'GET' });
    if (path === '/v1/snapshot') return snapshot();
    if (path.endsWith('/teaching-session')) return session;
    if (path === '/v1/conversations/conversation/teaching-intents?limit=20') return [intent];
    if (!path.includes('&before=')) return Array.from({ length: 100 }, (_, index) => ({ id: `branch-${index}` }));
    assert.ok(path.endsWith('&before=branch-99'));
    return [{ id: 'old-branch' }];
  } });
  await store.refresh();
  await store.openTeaching('conversation');
  assert.equal(store.getSnapshot().teaching.branches.length, 101);
  assert.deepEqual(store.getSnapshot().teaching.session, session);
  assert.deepEqual(store.getSnapshot().teaching.intents, [intent]);
  assert.ok(calls.every((call) => call.method === 'GET'));
  assert.ok(calls.slice(1).every((call) => /^\/v[12]\/conversations\/conversation\//.test(call.path)));
  const count = calls.length;
  await store.openTeaching('conversation');
  assert.equal(calls.length, count);
});

test('legacy reply deltas never reveal unchecked body and keep filtered thinking after synchronization', async () => {
  const previousFetch = globalThis.fetch;
  const delivered = [], states = [];
  const store = createNativeStore({ storage: null, request: async () => snapshot('owner', delivered.length ? 3 : 1) });
  const frames = [
    { sequence: 2, event_type: 'tutor.thinking', payload: {
      conversation_id: 'conversation', turn_id: 'turn', thinking_summary: '正在整理讲解思路。',
    } },
    { sequence: 2, event_type: 'tutor.thinking', payload: {
      conversation_id: 'conversation', turn_id: 'turn', thinking_text: '先理解循环。',
    } },
    { sequence: 2, event_type: 'tutor.thinking', payload: {
      conversation_id: 'conversation', turn_id: 'turn', thinking_text: '先理解循环。\n再安排查找练习。',
    } },
    ...[{ offset: 0, reply_text: 'A😀' }, { offset: 0, reply_text: 'A😀' }, { offset: 2, reply_text: 'B' }]
      .map((payload) => ({ sequence: 3, event_type: 'tutor.reply_delta',
        payload: { conversation_id: 'conversation', turn_id: 'turn', ...payload } })),
    { sequence: 3, event_type: 'tutor.succeeded', payload: { conversation_id: 'conversation', turn_id: 'turn' } },
  ];
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      delivered.push(true);
      controller.enqueue(new TextEncoder().encode(frames.map((event) =>
        `event: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`).join('')));
    },
  }));
  const unsubscribe = store.subscribe(() => states.push(store.getSnapshot().live.conversation));
  const stop = store.start();
  try {
    for (let index = 0; index < 100 && !store.getSnapshot().live.conversation?.complete; index++) {
      await new Promise((resolve) => setTimeout(resolve, 1));
    }
    assert(!states.some((state) => state?.text));
    assert.deepEqual(store.getSnapshot().live.conversation.summaries, ['正在整理讲解思路。']);
    assert(states.some((state) => state?.streaming && state.thinking === '先理解循环。'));
    assert.equal(store.getSnapshot().live.conversation.thinking, '先理解循环。\n再安排查找练习。');
    assert.equal(store.getSnapshot().live.conversation.text, '');
  } finally { stop(); unsubscribe(); globalThis.fetch = previousFetch; }
});

test('a later snapshot refresh reads session control state again; read failure is not legacy permission', async () => {
  let revision = 2, fail = false;
  const store = createNativeStore({ storage: null, request: async (path) => {
    if (path === '/v1/snapshot') return snapshot('owner', revision);
    if (fail) throw new NativeApiError(503, 'unavailable', 'Teaching read unavailable');
    return path.endsWith('/teaching-session') ? { ...session, revision } : [];
  } });
  await store.refresh(); await store.openTeaching('conversation');
  revision++;
  await store.refresh();
  assert.equal(store.getSnapshot().teaching.session.revision, 3);
  fail = true;
  await store.refreshTeaching();
  assert.match(store.getSnapshot().teaching.error, /unavailable/);
  assert.equal(store.getSnapshot().teaching.session.revision, 3);
  assert.equal(store.getSnapshot().teaching.loading, false);
});

test('late teaching reads cannot repopulate a different actor or conversation', async () => {
  let actor = 'owner', release;
  const delayed = new Promise((resolve) => { release = resolve; });
  const store = createNativeStore({ storage: null, request: async (path) => {
    if (path === '/v1/snapshot') return snapshot(actor);
    if (path === '/v2/conversations/conversation/teaching-session') return delayed;
    if (path.endsWith('/teaching-session')) return null;
    return [];
  } });
  await store.refresh();
  const original = store.openTeaching('conversation');
  await store.openTeaching('other-conversation');
  release(session);
  await original;
  assert.equal(store.getSnapshot().teaching.conversationId, 'other-conversation');
  assert.equal(store.getSnapshot().teaching.session, null);
  actor = 'other-owner';
  await store.refresh();
  assert.equal(store.getSnapshot().teaching, null);
});

test('an old owner intent read cannot repopulate the cache after identity changes', async () => {
  let actor = 'owner', release;
  const delayed = new Promise((resolve) => { release = resolve; });
  const store = createNativeStore({ storage: null, request: async (path) => {
    if (path === '/v1/snapshot') return snapshot(actor);
    if (path.endsWith('/teaching-session')) return session;
    if (path.endsWith('/teaching-intents?limit=20')) return delayed;
    return [];
  } });
  await store.refresh();
  const original = store.openTeaching('conversation');
  await new Promise((resolve) => setImmediate(resolve));
  actor = 'other-owner';
  await store.refresh();
  release([intent]);
  await original;
  assert.equal(store.getSnapshot().snapshot.actor.id, 'other-owner');
  assert.equal(store.getSnapshot().teaching, null);
});

test('an unknown intent cancellation reconciles only its stored original receipt and never resends', async () => {
  const path = '/v1/conversations/conversation/teaching-intents/intent/cancel';
  const lookup = `${path}/original-cancel`, calls = [];
  const receipt = { ...intent, state: 'cancelled', run_id: 'original-run', run_status: 'blocked_unknown' };
  let committed = false;
  const store = createNativeStore({ storage: null, request: async (target, init = {}) => {
    calls.push({ path: target, method: init.method ?? 'GET' });
    if (target === '/v1/snapshot') return snapshot();
    if (target === lookup) {
      if (!committed) throw new NativeApiError(404, 'not_found', 'No stored cancellation receipt');
      return receipt;
    }
    if (init.method === 'POST') throw new Error('connection lost after possible cancellation');
    if (target.endsWith('/teaching-session')) return session;
    return target.endsWith('/teaching-intents?limit=20') ? [intent] : [];
  } });
  await store.refresh(); await store.openTeaching('conversation');
  await assert.rejects(store.write(path, { client_action_id: 'original-cancel' }, {
    key: 'original-cancel', lookup,
  }), /possible cancellation/);
  await store.refreshTeaching();
  assert.equal(store.getSnapshot().teaching.intents[0].state, 'pending');
  assert.equal(store.getSnapshot().pending[0].status, 'unknown');
  await assert.rejects(store.reconcile('original-cancel'), /No stored cancellation receipt/);
  assert.equal(store.getSnapshot().pending.length, 1);
  committed = true;
  assert.deepEqual(await store.reconcile('original-cancel'), receipt);
  assert.equal(store.getSnapshot().pending.length, 0);
  assert.equal(calls.filter((call) => call.method === 'POST').length, 1);
});

test('a refresh during the initial teaching read cannot leave a pre-event session revision', async () => {
  let release, reads = 0, cursor = 1;
  const first = new Promise((resolve) => { release = resolve; });
  const store = createNativeStore({ storage: null, request: async (path) => {
    if (path === '/v1/snapshot') return snapshot('owner', cursor);
    if (path.endsWith('/teaching-session')) return ++reads === 1 ? first : { ...session, revision: 3 };
    return [];
  } });
  await store.refresh();
  const opening = store.openTeaching('conversation');
  cursor = 2;
  const updated = store.refresh();
  await new Promise((resolve) => setImmediate(resolve));
  release(session);
  await Promise.all([opening, updated]);
  assert.equal(reads, 2);
  assert.equal(store.getSnapshot().teaching.session.revision, 3);
});

test('the native flat thread groups original rows and does not depend on a legacy debug switch', () => {
  const view = "import { FLAT_THREAD, ThreadList } from './Thread';\nuseThreadRows(FLAT_THREAD ? messages : null, conversationId, fileMap);\nif (FLAT_THREAD && threadRows) {}\nrenderThread={(props) => <Thread {...props} />}";
  const result = overlayNativeSource('src/components/Chat/Messages/MessagesView.tsx', view);
  assert.match(result, /useThreadRows\(messages,/);
  assert.ok(!result.includes('FLAT_THREAD'));
  assert.ok(result.includes('<Thread {...props} /><NativeThreadTail conversationId={props.conversationId} />'));
  const list = 'return (\n    <>\n      {rows.map((row) => render(row))}\n    </>\n);';
  const grouped = overlayNativeSource('src/components/Chat/Messages/Thread/List.tsx', list);
  assert.match(grouped, /NativeTeachingRows rows=\{rows\}/);
  assert.match(grouped, /items\.map/);
  assert.match(grouped, /render\(row\)/);
});
