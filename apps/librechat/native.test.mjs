import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { after, before, test } from 'node:test';
import { access, mkdtemp, rmdir, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createNativeServer, nativeConversation, nativeMessages } from './native-server.mjs';
import { createNativeStore, isNativeEmptyConversation, readArtifactDraft, NATIVE_CODE_REVIEW_CAPABILITY } from './native-client.mjs';
import { initialCompositionDraftV2 } from './composition-v2-runtime.mjs';
import { nativeFiles, overlayNativeSource } from './native-overlay.mjs';

const id = '10000000-0000-4000-8000-000000000001';
const snapshot = {
  actor: { id: 'actor', display_name: 'Learner' }, cursor: 1, goals: [{ id: 'goal', title: 'Actual goal' }],
  conversations: [{ id, goal_id: 'goal', created_at: '2026-11-05T00:00:00Z' }],
  turns: [{ conversation_id: id, turns: [{ id: 'turn', user_text: 'Request', assistant_text: 'Accepted text', created_at: '2026-11-05T00:00:00Z', completed_at: '2026-11-05T00:01:00Z' }] }],
};
let server, origin, directory;
let readiness = 200;
const calls = [];
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'leornian-native-host-'));
  await writeFile(join(directory, 'index.html'), '<html><body>pinned client</body></html>');
  server = await createNativeServer({
    directory, backend: 'http://127.0.0.1:8091',
    fetchBackend: async (url, init) => {
      const body = init.body && typeof init.body !== 'string' ? await new Response(init.body).text() : init.body;
      calls.push({ path: url.pathname, method: init.method ?? 'GET', authorization: init.headers?.Authorization ?? init.headers?.authorization, body });
      if (url.pathname === '/v1/snapshot') return Response.json(snapshot);
      if (url.pathname === `/v1/conversations/${id}/history`) {
        return Response.json([...snapshot.turns[0].turns].reverse());
      }
      if (url.pathname === '/health/ready') return Response.json(
        { status: readiness === 200 ? 'ready' : 'unavailable' }, { status: readiness },
      );
      if (url.pathname === '/v1/local-sessions') return Response.json({
        token: 'owned-test-local-token', actor: snapshot.actor,
        expires_at: new Date(Date.now() + 604800000).toISOString(),
      });
      if (url.pathname === '/v1/local-sessions/refresh') return Response.json({
        token: init.headers.Authorization.slice(7), actor: snapshot.actor,
        expires_at: new Date(Date.now() + 604800000).toISOString(),
      });
      if (url.pathname === '/v1/local-sessions/current') return new Response(null, { status: 204 });
      return new Response('event: fact\ndata: {"sequence":2}\n\n', { headers: { 'Content-Type': 'text/event-stream' } });
    },
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
});
after(async () => {
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
  await unlink(join(directory, 'index.html'));
  await rmdir(directory); // Only the two explicitly created test paths; never recursive cleanup.
});

test('the full client bridge maps real owner identities and accepted text, not demo transcripts', () => {
  const conversation = nativeConversation(snapshot, snapshot.conversations[0]);
  assert.equal(conversation.title, 'Actual goal');
  const messages = nativeMessages(snapshot, id);
  assert.deepEqual(messages.map((message) => message.messageId), ['turn:user', 'turn:assistant']);
  assert.equal(messages[1].text, 'Accepted text');
  assert.equal(messages[1].parentMessageId, 'turn:user');
  assert.ok(!JSON.stringify(messages).includes('token'));
});

test('reviewed stage replies persist before the final answer without duplicate user messages', () => {
  const original = snapshot.turns[0].turns[0];
  const pending = { ...original, assistant_text: null, completed_at: null,
    stage_replies: [{ id: 'checked-call', text: '本批资料准备中。', created_at: original.created_at }] };
  const messages = nativeMessages(snapshot, id, [pending]);
  assert.deepEqual(messages.map((message) => message.messageId), [
    'turn:user', 'turn:stage:checked-call',
  ]);
  assert.equal(messages[1].text, '本批资料准备中。');
  const final = nativeMessages(snapshot, id, [{ ...pending, assistant_text: '完整路线。' }]);
  assert.deepEqual(final.map((message) => message.messageId), [
    'turn:user', 'turn:stage:checked-call', 'turn:assistant',
  ]);
  assert.equal(final[2].parentMessageId, 'turn:stage:checked-call');
});

test('accepted thinking survives history reads as LibreChat reasoning and text parts', () => {
  const turn = { ...snapshot.turns[0].turns[0], thinking_text: '先理解目录结构，再学习路径操作。' };
  const messages = nativeMessages(snapshot, id, [turn]);
  assert.deepEqual(messages[1].content, [
    { type: 'think', think: turn.thinking_text, leornian_steps: [],
      leornian_key: `${snapshot.actor.id}:${turn.id}` },
    { type: 'text', text: turn.assistant_text },
  ]);
  assert.equal(messages[1].text, turn.assistant_text);
  assert.equal(messages[0].content, undefined);
});

test('structured steps survive history projection even when no model thinking text was returned', () => {
  const steps = [{
    id: 'actual-call', kind: 'review', title: '检查回复', summary: '检查内容与引用。',
    detail: '通过检查后才交付正文。', status: 'completed', duration_ms: 400,
  }];
  const messages = nativeMessages(snapshot, id, [{ ...snapshot.turns[0].turns[0], thinking_steps: steps }]);
  assert.deepEqual(messages[1].content[0].leornian_steps, steps);
  assert.equal(messages[1].content[0].leornian_key, 'actor:turn');
  assert.equal(messages[1].content[0].think, '');
  assert.equal(messages[1].text, 'Accepted text');
  const failed = nativeMessages(snapshot, id, [{
    ...snapshot.turns[0].turns[0], assistant_text: null, thinking_steps: steps,
  }]);
  assert.equal(failed[1].text, '');
  assert.equal(failed[1].leornianOutcome.status, 'empty');
  assert.deepEqual(failed[1].content[0].leornian_steps, steps);
  const active = { ...snapshot, runs: [{ turn_id: 'turn', status: 'running' }] };
  assert.equal(nativeMessages(active, id, [{
    ...snapshot.turns[0].turns[0], assistant_text: null, thinking_steps: steps,
  }]).length, 1);
});

test('empty terminal replies expose public task outcomes separately from accepted model text', () => {
  const turn = { ...snapshot.turns[0].turns[0], assistant_text: null, thinking_steps: [] };
  const data = {
    ...snapshot, runs: [{ id: 'run', turn_id: turn.id, status: 'failed', error_code: 'delivery_needs_input' }],
    delivery_tasks: [{
      run_id: 'run', status: 'waiting_input', required_input: ['请补充这道题的输入范围。'],
    }],
  };
  const original = structuredClone(data);
  const messages = nativeMessages(data, id, [turn]);
  assert.equal(messages[1].text, '');
  assert.equal(messages[1].leornianOutcome.status, 'waiting_input');
  assert.deepEqual(messages[1].leornianOutcome.requiredInput, ['请补充这道题的输入范围。']);
  assert.equal(messages[1].leornianOutcome.errorCode, 'delivery_needs_input');
  assert.deepEqual(data, original);
  assert.equal(nativeMessages(data, id, [{ ...turn, assistant_text: '已检查的正文。' }])[1].leornianOutcome, undefined);
});

test('failed and cancelled replies remain visible without thinking, while active replies stay live-only', () => {
  const turn = { ...snapshot.turns[0].turns[0], assistant_text: null, completed_at: null };
  for (const status of ['failed', 'cancelled', 'succeeded']) {
    const messages = nativeMessages({ ...snapshot, runs: [{ id: 'run', turn_id: turn.id, status }] }, id, [turn]);
    assert.equal(messages.length, 2, status);
    assert.equal(messages[1].leornianOutcome.status, status === 'succeeded' ? 'empty' : status);
    assert.equal(messages[1].text, '');
  }
  for (const status of ['queued', 'running', 'blocked_unknown']) {
    assert.equal(nativeMessages({ ...snapshot, runs: [{ turn_id: turn.id, status }] }, id, [turn]).length, 1);
  }
});

test('background author and review stages stay in owner task history rather than learner chat', () => {
  const data = structuredClone(snapshot);
  const first = data.turns[0].turns[0];
  data.turns[0].turns.push(
    { ...first, id: 'author', purpose: 'item_supply', user_text: 'Internal author stage' },
    { ...first, id: 'review', purpose: 'item_supply', user_text: 'Internal review stage' },
    { ...first, id: 'followup', purpose: 'teaching', user_text: 'Actual learner followup' },
  );
  const messages = nativeMessages(data, id);
  assert.deepEqual(messages.map((m) => m.messageId), [
    'turn:user', 'turn:assistant', 'followup:user', 'followup:assistant',
  ]);
  assert.equal(messages[2].parentMessageId, 'turn:assistant');
  assert.equal(data.turns[0].turns.length, 4);
});

test('public history overrides only message projection and preserves legacy snapshot calls', () => {
  const original = structuredClone(snapshot);
  const branch = '30000000-0000-4000-8000-000000000001';
  const older = { ...snapshot.turns[0].turns[0], id: 'older', teaching_branch_id: branch };
  const latest = snapshot.turns[0].turns[0];
  const messages = nativeMessages(snapshot, id, [older, latest]);
  assert.deepEqual(messages.map((message) => message.messageId), [
    'older:user', 'older:assistant', 'turn:user', 'turn:assistant',
  ]);
  assert.deepEqual(messages.slice(0, 2).map((message) => message.leornianBranchId), [branch, branch]);
  assert.ok(messages.slice(2).every((message) => !('leornianBranchId' in message)));
  assert.equal(messages[2].parentMessageId, 'older:assistant');
  assert.deepEqual(nativeMessages(snapshot, id).map((message) => message.messageId), [
    'turn:user', 'turn:assistant',
  ]);
  assert.deepEqual(nativeMessages(snapshot, id, []), []);
  assert.deepEqual(snapshot, original);
});

test('pending server teaching intents never impersonate users or interrupt the visible chain', () => {
  const data = structuredClone(snapshot);
  const first = data.turns[0].turns[0];
  const pending = {
    ...first, id: 'pending', teaching_intent_id: '40000000-0000-4000-8000-000000000001',
    user_text: 'Internal continuation instruction', assistant_text: null, completed_at: null,
  };
  const followup = {
    ...first, id: 'followup', teaching_intent_id: null, user_text: 'Actual learner question',
  };
  data.turns[0].turns = [
    pending, first, { ...pending, id: 'pending-middle' }, followup,
    { ...pending, id: 'pending-last' },
  ];
  const original = structuredClone(data);
  const messages = nativeMessages(data, id);
  assert.deepEqual(messages, nativeMessages(snapshot, id, [first, followup]));
  assert.deepEqual(messages.map((message) => message.messageId), [
    'turn:user', 'turn:assistant', 'followup:user', 'followup:assistant',
  ]);
  assert.equal(messages[2].parentMessageId, 'turn:assistant');
  assert.equal(messages[2].text, 'Actual learner question');
  assert.ok(!JSON.stringify(messages).includes(pending.user_text));
  assert.deepEqual(nativeMessages(snapshot, id, [pending]), []);
  assert.deepEqual(data, original);
});

test('accepted server teaching keeps only its assistant identity, branch and actual parent', () => {
  const first = snapshot.turns[0].turns[0];
  const branch = '30000000-0000-4000-8000-000000000001';
  const continuation = {
    ...first, id: 'continuation', teaching_intent_id: '40000000-0000-4000-8000-000000000001',
    teaching_branch_id: branch, user_text: 'Internal result-driven teaching instruction',
    assistant_text: 'Continue with the next loop concept.',
  };
  const followup = {
    ...first, id: 'followup', teaching_branch_id: branch,
    user_text: 'Why does an empty input skip the loop?', assistant_text: 'There are no elements.',
  };
  const turns = [
    first, { ...continuation, id: 'background', purpose: 'item_supply' },
    continuation, followup,
  ];
  const original = structuredClone(turns);
  const messages = nativeMessages(snapshot, id, turns);
  assert.deepEqual(messages.map((message) => message.messageId), [
    'turn:user', 'turn:assistant', 'continuation:assistant', 'followup:user', 'followup:assistant',
  ]);
  assert.deepEqual(messages.map((message) => message.parentMessageId), [
    '00000000-0000-0000-0000-000000000000', 'turn:user', 'turn:assistant',
    'continuation:assistant', 'followup:user',
  ]);
  assert.deepEqual(messages.map((message) => message.isCreatedByUser), [
    true, false, false, true, false,
  ]);
  assert.deepEqual(messages.map((message) => message.text), [
    first.user_text, first.assistant_text, continuation.assistant_text,
    followup.user_text, followup.assistant_text,
  ]);
  assert.equal(messages[2].sender, 'Tutor');
  assert.ok(messages.slice(2).every((message) => message.leornianBranchId === branch));
  assert.ok(!JSON.stringify(messages).includes(continuation.user_text));
  assert.equal(nativeMessages(snapshot, id, [continuation])[0].parentMessageId,
    '00000000-0000-0000-0000-000000000000');
  assert.deepEqual(turns, original);
});

test('message history reads every public keyset page with the current owner and one intact chain', async () => {
  const branch = '30000000-0000-4000-8000-000000000001';
  const turns = Array.from({ length: 205 }, (_, index) => ({
    id: `20000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
    purpose: index === 100 ? 'item_supply' : 'teaching',
    user_text: `Question ${index}`, assistant_text: index === 204 ? null : `Reply ${index}`,
    created_at: new Date(Date.parse('2026-11-05T00:00:00Z') + index * 1000).toISOString(),
    completed_at: index === 204 ? null
      : new Date(Date.parse('2026-11-05T00:00:00Z') + index * 1000 + 500).toISOString(),
    teaching_branch_id: index >= 50 && index < 200 ? branch : null,
  }));
  const data = { ...snapshot, turns: [{ conversation_id: id, turns: turns.slice(-3) }] };
  const original = structuredClone(data);
  const descending = [...turns].reverse(), requests = [];
  const host = await createNativeServer({
    directory,
    fetchBackend: async (url, init) => {
      requests.push({
        path: url.pathname, search: url.search, method: init.method ?? 'GET',
        authorization: init.headers?.Authorization,
      });
      if (url.pathname === '/v1/snapshot') {
        if (init.headers.Authorization === 'Bearer other-owner') {
          return Response.json({ ...data, actor: { id: 'other', display_name: 'Other' }, conversations: [] });
        }
        return Response.json(data);
      }
      assert.equal(url.pathname, `/v1/conversations/${id}/history`);
      assert.equal(url.searchParams.get('limit'), '100');
      const before = url.searchParams.get('before');
      const start = before ? descending.findIndex((turn) => turn.id === before) + 1 : 0;
      return Response.json(descending.slice(start, start + 100));
    },
  });
  await new Promise((resolve) => host.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${host.address().port}`;
  const headers = { Cookie: 'leornian_local_session=history-owner', Authorization: 'Bearer forged' };
  try {
    const response = await fetch(base + `/api/messages/${id}`, { headers });
    assert.equal(response.status, 200);
    const messages = await response.json();
    const visible = turns.filter((turn) => turn.purpose !== 'item_supply');
    assert.deepEqual(messages.map((message) => message.messageId), visible.flatMap((turn) => [
      `${turn.id}:user`, ...(turn.assistant_text === null ? [] : [`${turn.id}:assistant`]),
    ]));
    for (const [index, message] of messages.entries()) {
      const turn = turns.find((turn) => message.messageId.startsWith(`${turn.id}:`));
      assert.equal(message.parentMessageId,
        index ? messages[index - 1].messageId : '00000000-0000-0000-0000-000000000000');
      assert.equal(message.conversationId, id);
      assert.equal(message.isCreatedByUser, message.messageId.endsWith(':user'));
      assert.equal(message.text, message.isCreatedByUser ? turn.user_text : turn.assistant_text);
      assert.equal(message.leornianBranchId, turn.teaching_branch_id ?? undefined);
    }
    assert.deepEqual(requests.map((request) => request.path + request.search), [
      '/v1/snapshot',
      `/v1/conversations/${id}/history?limit=100`,
      `/v1/conversations/${id}/history?limit=100&before=${descending[99].id}`,
      `/v1/conversations/${id}/history?limit=100&before=${descending[199].id}`,
    ]);
    assert.ok(requests.every((request) =>
      request.method === 'GET' && request.authorization === 'Bearer history-owner'));
    assert.deepEqual(data, original);
    let count = requests.length;
    assert.equal((await fetch(base + `/api/messages/${id}`)).status, 401);
    assert.equal(requests.length, count);
    assert.equal((await fetch(base + '/api/messages/10000000-0000-4000-8000-000000000002',
      { headers })).status, 404);
    assert.deepEqual(requests.slice(count).map((request) => request.path), ['/v1/snapshot']);
    count = requests.length;
    assert.equal((await fetch(base + `/api/messages/${id}`, {
      headers: { Cookie: 'leornian_local_session=other-owner' },
    })).status, 404);
    assert.deepEqual(requests.slice(count), [{
      path: '/v1/snapshot', search: '', method: 'GET', authorization: 'Bearer other-owner',
    }]);
  } finally {
    host.closeAllConnections();
    await new Promise((resolve) => host.close(resolve));
  }
});

test('a failed later history page never falls back to snapshot or returns a partial transcript', async () => {
  for (const status of [503, 401]) {
    const requests = [];
    const host = await createNativeServer({
      directory,
      fetchBackend: async (url, init) => {
        requests.push({ path: url.pathname, search: url.search, method: init.method ?? 'GET' });
        assert.equal(init.headers.Authorization, 'Bearer history-owner');
        if (url.pathname === '/v1/snapshot') return Response.json(snapshot);
        assert.equal(url.pathname, `/v1/conversations/${id}/history`);
        if (url.searchParams.has('before')) {
          return Response.json({ code: 'history_unavailable' }, { status });
        }
        return Response.json(Array.from({ length: 100 }, (_, index) => ({
          ...snapshot.turns[0].turns[0],
          id: `20000000-0000-4000-8000-${String(100 - index).padStart(12, '0')}`,
        })));
      },
    });
    await new Promise((resolve) => host.listen(0, '127.0.0.1', resolve));
    try {
      const response = await fetch(`http://127.0.0.1:${host.address().port}/api/messages/${id}`, {
        headers: { Cookie: 'leornian_local_session=history-owner' },
      });
      assert.equal(response.status, status);
      assert.equal((await response.json()).code,
        status === 401 ? 'unauthorized' : 'native_host_unavailable');
      assert.equal(requests.length, 3);
      assert.ok(requests.every((request) => request.method === 'GET'));
      assert.match(requests[2].search, /before=20000000-0000-4000-8000-000000000001/);
    } finally {
      host.closeAllConnections();
      await new Promise((resolve) => host.close(resolve));
    }
  }
});

test('local login is explicit, owner-backed and cookie-scoped; display auth is not fabricated', async () => {
  assert.equal((await fetch(origin + '/api/auth/refresh', { method: 'POST' })).status, 401);
  const session = await fetch(origin + '/api/auth/local', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin }, body: JSON.stringify({ display_name: 'Learner' }),
  });
  assert.equal(session.status, 200);
  const cookie = session.headers.get('set-cookie');
  assert.match(cookie, /HttpOnly; SameSite=Strict/);
  const auth = await fetch(origin + '/api/auth/refresh', { method: 'POST', headers: { Cookie: cookie.split(';')[0] } });
  assert.equal((await auth.json()).user.id, snapshot.actor.id);
  assert.match(auth.headers.get('set-cookie'), /HttpOnly; SameSite=Strict/);
  assert.equal(calls.at(-1).path, '/v1/local-sessions/refresh');
  const logout = await fetch(origin + '/api/auth/logout', {
    method: 'POST', headers: { Cookie: cookie.split(';')[0] },
  });
  assert.equal(logout.status, 200);
  assert.equal(calls.at(-1).path, '/v1/local-sessions/current');
  assert.equal(calls.at(-1).method, 'DELETE');
});

test('the original client health check reflects actual local API readiness, including failure', async () => {
  const response = await fetch(origin + '/health');
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: 'ready' });
  try {
    readiness = 503;
    assert.equal((await fetch(origin + '/health')).status, 503);
  } finally { readiness = 200; }
  assert.equal(calls.at(-1).path, '/health/ready');
});

test('hidden recent entries stay absent after fresh reads while their route and messages remain accessible', async () => {
  const headers = { Cookie: 'leornian_local_session=owner-a' };
  const list = () => fetch(origin + '/api/convos', { headers }).then((response) => response.json());
  assert.equal((await list()).conversations.length, 1);
  const conversation = snapshot.conversations[0];
  try {
    conversation.hidden_from_recents = true;
    assert.deepEqual(await list(), { conversations: [], nextCursor: null });
    assert.deepEqual(await list(), { conversations: [], nextCursor: null });
    const route = await fetch(origin + `/api/convos/${id}`, { headers });
    assert.equal(route.status, 200);
    assert.equal((await route.json()).conversationId, id);
    const messages = await fetch(origin + `/api/messages/${id}`, { headers });
    assert.equal(messages.status, 200);
    assert.equal((await messages.json())[1].text, 'Accepted text');
    assert.equal(snapshot.goals.length, 1);
  } finally { delete conversation.hidden_from_recents; }
});

test('parallel local hosts use only their explicitly configured cookie without replacing the default', async () => {
  const forwarded = [];
  const isolated = await createNativeServer({
    directory, sessionCookieName: 'leornian_demo_acceptance',
    fetchBackend: async (_url, init) => {
      forwarded.push(init.headers?.Authorization ?? init.headers?.authorization);
      return Response.json({
        token: init.headers.Authorization.slice(7), actor: snapshot.actor,
        expires_at: new Date(Date.now() + 604800000).toISOString(),
      });
    },
  });
  await new Promise((resolve) => isolated.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${isolated.address().port}`;
  try {
    const oldCookie = 'leornian_local_session=old-owned-fixture';
    assert.equal((await fetch(base + '/api/auth/refresh', {
      method: 'POST', headers: { Cookie: oldCookie },
    })).status, 401);
    assert.equal(forwarded.length, 0);
    const response = await fetch(base + '/api/auth/refresh', {
      method: 'POST', headers: { Cookie: `${oldCookie}; leornian_demo_acceptance=new-owned-fixture` },
    });
    assert.equal(response.status, 200);
    assert.deepEqual(forwarded, ['Bearer new-owned-fixture']);
    const logout = await fetch(base + '/api/auth/logout', { method: 'POST' });
    assert.match(logout.headers.get('set-cookie'), /^leornian_demo_acceptance=;/);
    assert.doesNotMatch(logout.headers.get('set-cookie'), /leornian_local_session/);
    await assert.rejects(createNativeServer({
      directory, sessionCookieName: 'invalid; Path=/',
    }), /cookie name/);
  } finally {
    isolated.closeAllConnections();
    await new Promise((resolve) => isolated.close(resolve));
  }
});

async function recoveryHost(t, { expired = false, revoked = false, wrongActor = false } = {}) {
  const state = await mkdtemp(join(tmpdir(), 'leornian-session-recovery-'));
  const file = join(state, 'handoff.json');
  const grant = {
    token: 'replacement-session-fixture', actor_id: snapshot.actor.id,
    previous_digests: [createHash('sha256').update('expired-owner-fixture').digest('hex')],
    handoff_expires_at: new Date(Date.now() + (expired ? -1000 : 600000)).toISOString(),
  };
  await writeFile(file, JSON.stringify(grant), { mode: 0o600 });
  const requests = [];
  let replacementRevoked = revoked;
  const host = await createNativeServer({
    directory, sessionRecoveryFile: file,
    fetchBackend: async (url, init) => {
      const token = init.headers.Authorization?.slice(7);
      requests.push({ path: url.pathname, method: init.method, token });
      if (url.pathname === '/v1/local-sessions/current') {
        if (token === grant.token) replacementRevoked = true;
        return new Response(null, { status: 204 });
      }
      if (url.pathname === '/v1/local-sessions/refresh') {
        const other = token === 'other-owner-fixture';
        if (!other && (token !== grant.token || replacementRevoked)) {
          return Response.json({ code: 'unauthorized' }, { status: 401 });
        }
        return Response.json({
          token, actor: other || wrongActor ? { id: 'other', display_name: 'Other' } : snapshot.actor,
          expires_at: new Date(Date.now() + 604800000).toISOString(),
        });
      }
      return Response.json(snapshot);
    },
  });
  await new Promise((resolve) => host.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    host.closeAllConnections();
    await new Promise((resolve) => host.close(resolve));
    await unlink(file).catch((error) => { if (error.code !== 'ENOENT') throw error; });
    await rmdir(state);
  });
  const base = `http://127.0.0.1:${host.address().port}`;
  const refresh = (token, extra = {}) => fetch(base + '/api/auth/refresh', {
    method: 'POST', headers: { ...(token ? { Cookie: `leornian_local_session=${token}` } : {}), ...extra },
  });
  return { base, refresh, file, grant, requests };
}

test('authorized maintenance handoff survives an interrupted response and ends on cookie acknowledgement', async (t) => {
  const host = await recoveryHost(t);
  for (let attempt = 0; attempt < 2; attempt++) {
    const response = await host.refresh();
    assert.equal(response.status, 200);
    assert.equal((await response.json()).user.id, snapshot.actor.id);
    assert.match(response.headers.get('set-cookie'), /HttpOnly; SameSite=Strict/);
    await access(host.file);
  }
  const acknowledged = await host.refresh(host.grant.token);
  assert.equal(acknowledged.status, 200);
  await assert.rejects(access(host.file), { code: 'ENOENT' });
  assert.equal((await host.refresh()).status, 401);
  assert.ok(host.requests.every((request) => request.path === '/v1/local-sessions/refresh'));
});

test('handoff replaces only the original expired browser credential and never another identity', async (t) => {
  const host = await recoveryHost(t);
  const count = host.requests.length;
  assert.equal((await host.refresh(undefined, { Origin: 'https://untrusted.example' })).status, 403);
  assert.equal(host.requests.length, count);
  const other = await host.refresh('other-owner-fixture');
  assert.equal((await other.json()).user.id, 'other');
  assert.ok(!other.headers.get('set-cookie').includes(host.grant.token));
  assert.equal((await host.refresh('unrelated-expired-fixture')).status, 401);
  const original = await host.refresh('expired-owner-fixture');
  assert.equal(original.status, 200);
  assert.equal((await original.json()).user.id, snapshot.actor.id);
});

test('logout cancels an unused recovery handoff and revokes the browser token', async (t) => {
  const host = await recoveryHost(t);
  assert.equal((await host.refresh()).status, 200);
  const logout = await fetch(host.base + '/api/auth/logout', {
    method: 'POST', headers: { Cookie: `leornian_local_session=${host.grant.token}` },
  });
  assert.equal(logout.status, 200);
  assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
  await assert.rejects(access(host.file), { code: 'ENOENT' });
  assert.equal((await host.refresh(host.grant.token)).status, 401);
  assert.equal((await host.refresh()).status, 401);
});

test('expired, revoked or wrong-owner recovery grants cannot issue a login cookie', async (t) => {
  for (const options of [{ expired: true }, { revoked: true }, { wrongActor: true }]) {
    const host = await recoveryHost(t, options);
    const response = await host.refresh();
    assert.equal(response.status, options.wrongActor ? 503 : 401);
    assert.equal(response.headers.get('set-cookie'), null);
  }
});

test('only the local public native API is proxied; SSE and auth headers retain their real scope', async () => {
  const count = calls.length;
  const reply = await fetch(origin + '/leornian/v2/conversations/' + id + '/learning-artifacts', {
    method: 'POST', headers: { Cookie: 'leornian_local_session=owner-a', Authorization: 'Bearer forged', 'Content-Type': 'application/json', 'Idempotency-Key': 'same-action' },
    body: JSON.stringify({ action: 'cancel' }),
  });
  assert.equal(reply.status, 200);
  assert.equal(calls[count].authorization, 'Bearer owner-a');
  assert.equal(calls[count].body, '{"action":"cancel"}');
  assert.match(await reply.text(), /event: fact/);
  for (const path of ['/api/ask', '/api/files', '/api/agents', '/api/keys']) {
    assert.equal((await fetch(origin + path, { method: 'POST' })).status, 403);
  }
  assert.equal((await fetch(origin + '/leornian/v1/%252e%252e/private')).status, 404);
  assert.equal((await fetch(origin + '/api/auth/local', { method: 'POST', headers: { Origin: 'https://elsewhere.invalid' }, body: '{}' })).status, 403);
  assert.equal((await fetch(origin + '/sw.js')).status, 404);
  assert.match(await (await fetch(origin + '/registerSW.js')).text(), /No persistent service worker/);
  await assert.rejects(createNativeServer({ directory, backend: 'https://remote.invalid' }), /local HTTP/);
});

test('a course reload uses the rebuilt client entry without restarting the local server', async () => {
  const index = join(directory, 'index.html');
  try {
    await writeFile(index, '<html><head></head>new course client</html>');
    const response = await fetch(origin + '/c/' + id, { headers: { Accept: 'text/html' } });
    const html = await response.text();
    assert.match(html, /new course client/);
    assert.match(html, /__leornian\/bootstrap.js/);
  } finally { await writeFile(index, '<html><body>pinned client</body></html>'); }
});

test('native overlays reuse the incumbent full client while preview modules and store stay out', () => {
  assert.ok(nativeFiles.includes('LearningCompositionV2.tsx'));
  assert.ok(!nativeFiles.some((file) => /demo-state|DemoUI|DemoChrome/.test(file)));
  const original = "function Login() {}\nexport default Login;";
  assert.match(overlayNativeSource('src/components/Auth/Login.tsx', original), /NativeLogin/);
  assert.equal(original, "function Login() {}\nexport default Login;");
  assert.throws(() => overlayNativeSource('src/components/Auth/Login.tsx', 'changed'), /changed/);
});

test('only a confirmed empty native conversation replaces upstream perpetual loading', () => {
  const empty = { ...snapshot, turns: [{ conversation_id: id, turns: [] }] };
  assert.equal(isNativeEmptyConversation(empty, id), true);
  assert.equal(isNativeEmptyConversation(empty, 'new'), false);
  assert.equal(isNativeEmptyConversation(empty, 'unloaded-conversation'), false);
  assert.equal(isNativeEmptyConversation(null, id), false);
  assert.equal(isNativeEmptyConversation(snapshot, id), false);
});

function memoryStorage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test('new review capability does not rewrite an older unresolved Tutor request', async () => {
  assert.equal(NATIVE_CODE_REVIEW_CAPABILITY, 'learning_code_review.v2');
  const storage = memoryStorage();
  const old = {
    key: 'old-request', path: `/v1/conversations/${id}/turns`, lookup: '/old-turn-request',
    status: 'dispatching', body: {
      text: 'Review the exact submitted code.',
      presentation_capabilities: {
        versions: ['learning_composition.v2'], actions: ['learning_code_review.v1'],
      },
    },
  };
  storage.setItem(`leornian.native.writes.v1:${snapshot.actor.id}`, JSON.stringify([old]));
  const requests = [];
  const store = createNativeStore({ storage, request: async (path, init = {}) => {
    requests.push([path, init.method ?? 'GET']);
    return snapshot;
  } });
  await store.refresh();
  assert.deepEqual(store.getSnapshot().pending[0], { ...old, status: 'unknown' });
  assert.deepEqual(requests, [['/v1/snapshot', 'GET']]);
});

test('unknown review completion reloads and recovers only the original read-only action receipt', async () => {
  const storage = memoryStorage(), requests = [];
  const path = `/v2/conversations/${id}/learning-artifacts/artifact/actions`;
  const body = {
    action: 'complete_review', component_id: 'submitted', client_action_id: 'review-action',
    expected_artifact_revision: 7,
  };
  const receipt = {
    schema_version: 'learning_review_action.v1', client_action_id: 'review-action',
    artifact_id: 'artifact', artifact_revision: 8, state: 'completed',
    component_id: 'submitted', result_owner: 'tutor', result_id: 'review-completion',
  };
  const request = async (target, init = {}) => {
    requests.push([target, init.method ?? 'GET']);
    if (target === '/v1/snapshot') return snapshot;
    if (init.method === 'POST') throw new Error('review receipt connection lost');
    assert.equal(target, `${path}/review-action`);
    return receipt;
  };
  const store = createNativeStore({ storage, request });
  await store.refresh();
  await assert.rejects(store.write(path, body, {
    key: 'review-action', lookup: `${path}/review-action`,
  }), /connection lost/);
  const restored = createNativeStore({ storage, request });
  await restored.refresh();
  assert.equal(restored.getSnapshot().pending[0].status, 'unknown');
  assert.deepEqual(restored.getSnapshot().pending[0].body, body);
  await assert.rejects(restored.write(path, body), /不会重发/);
  assert.deepEqual(await restored.reconcile('review-action'), receipt);
  assert.equal(restored.getSnapshot().pending.length, 0);
  assert.equal(requests.filter(([, method]) => method === 'POST').length, 1);
});

test('uncertain writes survive reload and read-only reconciliation never dispatches a second action', async () => {
  const storage = memoryStorage(), requests = [];
  const request = async (path, init = {}) => {
    requests.push([path, init.method ?? 'GET']);
    if (path === '/v1/snapshot') return snapshot;
    if (init.method === 'POST') throw new Error('connection lost after possible commit');
    return { artifact_id: 'artifact', client_action_id: 'action', state: 'running' };
  };
  const store = createNativeStore({ request, storage });
  await store.refresh();
  const body = { action: 'run', client_action_id: 'action', expected_artifact_revision: 1, payload: { code: 'print(1)' } };
  await assert.rejects(store.write('/v2/artifact/actions', body, { key: 'action', lookup: '/v2/artifact/actions/action' }));
  assert.equal(store.getSnapshot().pending[0].status, 'unknown');
  const resumed = createNativeStore({ request, storage });
  await resumed.refresh();
  assert.equal(resumed.getSnapshot().pending.length, 1);
  await assert.rejects(resumed.write('/v2/artifact/actions', body, { key: 'another' }), /不会重发/);
  await resumed.reconcile('action');
  assert.equal(resumed.getSnapshot().pending.length, 0);
  assert.equal(requests.filter(([, method]) => method === 'POST').length, 1);
});

test('drafts restore only the exact server content and cannot alter readonly source/file identity', () => {
  const previous = globalThis.sessionStorage;
  globalThis.sessionStorage = memoryStorage();
  try {
    const artifact = { id: 'artifact', content_ref: { owner: 'tutor', id: 'content', revision: 1, public_identity: 'digest' } };
    const definition = {
      states: { code: { type: 'code', value: 'original' }, frozen: { type: 'code', value: 'immutable', read_only: true },
        files: { type: 'files', files: [{ path: 'main.py', content: 'start' }, { path: 'test.py', content: 'trusted', read_only: true }] } },
      components: [],
    };
    const saved = readArtifactDraft('actor', artifact, definition, initialCompositionDraftV2);
    sessionStorage.setItem(saved.key, JSON.stringify({ ...saved.draft, values: {
      code: 'edited', frozen: 'forged', files: [{ path: 'main.py', content: 'user edit' }, { path: 'test.py', content: 'forged' }, { path: '../escape', content: 'bad' }],
    } }));
    const restored = readArtifactDraft('actor', { ...artifact, revision: 9 }, definition, initialCompositionDraftV2);
    assert.equal(restored.draft.values.code, 'edited');
    assert.equal(restored.draft.values.frozen, 'immutable');
    assert.deepEqual(restored.draft.values.files.map((f) => f.content), ['user edit', 'trusted']);
    assert.equal(readArtifactDraft('another-actor', artifact, definition, initialCompositionDraftV2).draft.values.code, 'original');
    assert.equal(readArtifactDraft('actor', { ...artifact, content_ref: { ...artifact.content_ref, revision: 2 } }, definition, initialCompositionDraftV2).draft.values.code, 'original');
  } finally { if (previous === undefined) delete globalThis.sessionStorage; else globalThis.sessionStorage = previous; }
});
