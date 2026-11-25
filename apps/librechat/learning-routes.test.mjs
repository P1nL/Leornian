import assert from 'node:assert/strict';
import { test } from 'node:test';
import { confirmFirstNode, routeNodes } from './learning-routes.mjs';

const plan = { id: 'plan', active: { revision: 2, document: {
  nodes: ['one', 'two', 'three'].map((key) => ({ key, title: key })),
} } };

test('route folders unlock the first node and only advance after an accepted learner dialogue', () => {
  const snapshot = { conversations: [{ id: 'conversation', studied_nodes: [] }], turns: [
    { conversation_id: 'conversation', turns: [{ purpose: 'teaching', completed_at: null,
      assistant_text: null, context_focus: { kind: 'node', plan_id: 'plan', expected_plan_revision: 2, node_key: 'one' } }] },
  ] };
  assert.deepEqual(routeNodes(snapshot, plan, 'conversation').map((node) => node.unlocked), [true, false, false]);
  snapshot.turns[0].turns[0].completed_at = 'now';
  snapshot.turns[0].turns[0].assistant_text = 'Accepted explanation';
  assert.deepEqual(routeNodes(snapshot, plan, 'conversation').map((node) => node.unlocked), [true, true, false]);
  snapshot.turns[0].turns[0].teaching_intent_id = 'automatic';
  assert.deepEqual(routeNodes(snapshot, plan, 'conversation').map((node) => node.unlocked), [true, false, false]);
  snapshot.conversations[0].ended_nodes = [{ plan_id: 'plan', plan_revision: 2, node_key: 'one' }];
  const nodes = routeNodes(snapshot, plan, 'conversation');
  assert.equal(nodes[0].studied, false);
  assert.deepEqual(nodes.map((node) => node.unlocked), [true, true, false]);
});

test('owner-projected studied nodes survive history pagination and cannot unlock another revision', () => {
  const snapshot = { conversations: [{ id: 'conversation', studied_nodes: [
    { plan_id: 'plan', plan_revision: 2, node_key: 'one' },
    { plan_id: 'plan', plan_revision: 1, node_key: 'two' },
  ] }], turns: [] };
  assert.deepEqual(routeNodes(snapshot, plan, 'conversation').map((node) => node.unlocked), [true, true, false]);
});

test('a legacy unknown first learning turn retains its original key and is only read on continuation', async () => {
  const memory = new Map(), storage = { getItem: (key) => memory.get(key), setItem: (key, value) => memory.set(key, value) };
  const draft = { id: 'plan', latest: { revision: 1, document: { nodes: [{ key: 'one', title: 'First' }] } }, active: null };
  const state = { snapshot: { actor: { id: 'actor' }, plans: [draft] }, pending: [] };
  const writes = [], reads = [];
  let session = null;
  const store = {
    getSnapshot: () => state, refresh: async () => {},
    write: async (path, data, options) => {
      writes.push({ path, data, options });
      if (path.endsWith('/confirm')) { draft.active = draft.latest; return draft; }
      if (path.endsWith('/actions')) { session = { revision: 1, focus: data.focus }; return session; }
      throw new Error('Original learning request outcome unknown');
    },
  };
  const request = async (path) => {
    reads.push(path);
    return path.endsWith('/teaching-session') ? session : { turn_id: 'original' };
  };
  const conversation = { id: 'conversation' }, dependencies = { store, request, storage };
  storage.setItem('leornian.native.route-start:actor:conversation:plan:1', JSON.stringify({
    confirmed: true, first_turn_key: 'legacy-first', first_turn_dispatched: true,
  }));
  await confirmFirstNode(conversation, draft, dependencies);
  const turns = writes.filter((call) => call.path.endsWith('/turns'));
  assert.equal(turns.length, 0);
  assert(reads.includes('/v1/conversations/conversation/turn-requests/legacy-first'));
});

test('reconfirming does not return to the first node or repeat teaching even with stale local state', async () => {
  const memory = new Map(), storage = {
    getItem: (key) => memory.get(key), setItem: (key, value) => memory.set(key, value),
  };
  const draft = { id: 'plan', latest: { revision: 1, document: {
    nodes: [{ key: 'one', title: 'First' }, { key: 'two', title: 'Second' }],
  } }, active: null };
  const state = { snapshot: { actor: { id: 'actor' } }, pending: [] };
  const writes = [], commands = new Map();
  let session = null;
  const store = {
    getSnapshot: () => state, refresh: async () => {},
    write: async (path, body, options) => {
      writes.push({ path, body, options });
      if (path.endsWith('/confirm')) { draft.active = draft.latest; return draft; }
      if (path.endsWith('/actions')) {
        const original = commands.get(body.client_action_id);
        if (original) assert.deepEqual(body, original, 'An idempotency key cannot change commands');
        commands.set(body.client_action_id, body);
        assert.equal(body.expected_session_revision, session?.revision ?? 0);
        session = { revision: (session?.revision ?? 0) + 1, focus: body.focus };
        return session;
      }
      return { turn_id: 'first-turn' };
    },
  };
  const request = async (path) => path.endsWith('/teaching-session') ? session : { turn_id: 'first-turn' };
  const dependencies = { store, request, storage };
  await confirmFirstNode({ id: 'conversation' }, draft, dependencies);
  session = { revision: 2, focus: { ...session.focus, node_key: 'two' } };
  assert.equal(await confirmFirstNode({ id: 'conversation' }, draft, dependencies), null);
  draft.active = null;
  assert.equal(await confirmFirstNode({ id: 'conversation' }, draft, dependencies), null);
  const actions = writes.filter((item) => item.path.endsWith('/actions'));
  assert.equal(actions.length, 1);
  assert.equal(actions[0].body.action, 'open');
  assert.equal(session.focus.node_key, 'two');
  assert.equal(writes.filter((item) => item.path.endsWith('/turns')).length, 0);
});

test('an unresolved confirmation freezes its shown installation scope and original key', async () => {
  const memory = new Map(), storage = {
    getItem: (key) => memory.get(key), setItem: (key, value) => memory.set(key, value),
  };
  const draft = { id: 'consent-plan', active: null, latest: {
    revision: 1, document: { nodes: [{ key: 'one', title: 'First' }] },
  } };
  const state = { snapshot: { actor: { id: 'actor' } }, pending: [] };
  const writes = [];
  const store = {
    getSnapshot: () => state, refresh: async () => {},
    write: async (path, body, options) => {
      writes.push({ path, body, options });
      throw new Error('confirmation result unknown');
    },
  };
  const requirement = { recipe_id: 'python-flask.v1', dependency_lock: ['Flask==3.1.2'] };
  const dependencies = { store, request: async () => null, storage };
  await assert.rejects(confirmFirstNode({ id: 'conversation' }, draft, {
    ...dependencies, environmentRequirements: [requirement],
  }), /unknown/);
  await assert.rejects(confirmFirstNode({ id: 'conversation' }, draft, dependencies), /unknown/);
  assert.equal(writes.length, 2);
  assert.equal(writes[0].options.key, writes[1].options.key);
  assert.deepEqual(writes[0].body, writes[1].body);
  assert.deepEqual(writes[1].body.environment_requirements, [requirement]);
});
