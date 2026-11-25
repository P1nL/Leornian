import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setImmediate } from 'node:timers/promises';
import { createNativeStore } from './native-client.mjs';

const body = '🐍 **Python**\n\n先认识变量，再写一个小程序。\n\n```python\nprint("hello")\n```\n'.repeat(10);
function snapshot(text = null, actor = 'owner') {
  return {
    actor: { id: actor }, cursor: text ? 3 : 1,
    conversations: [{ id: 'conversation', goal_id: 'goal' }],
    turns: [{ conversation_id: 'conversation', turns: [
      { id: 'turn', purpose: 'teaching', assistant_text: text, thinking_text: '先确认学习基础。' },
    ] }],
    runs: [{ conversation_id: 'conversation', turn_id: 'turn', status: text ? 'succeeded' : 'running' }],
  };
}
async function playback(t, initial = snapshot()) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let data = initial, stream;
  const reads = [];
  t.mock.method(globalThis, 'fetch', async (_url, { signal }) => {
    let closed = false;
    return new Response(new ReadableStream({
      start(controller) {
        stream = controller;
        signal.addEventListener('abort', () => {
          if (!closed) { closed = true; controller.close(); }
        }, { once: true });
      },
      cancel() { closed = true; },
    }));
  });
  const store = createNativeStore({ storage: null, request: async (path) => {
    reads.push(path);
    assert.equal(path, '/v1/snapshot');
    return structuredClone(data);
  } });
  const stop = store.start();
  t.after(stop);
  await setImmediate();
  return {
    store, reads,
    change(next) { data = next; },
    async send(type, extra = {}, sequence = data.cursor) {
      stream.enqueue(new TextEncoder().encode(`event: ${type}\ndata: ${JSON.stringify({
        sequence, event_type: type, payload: {
          conversation_id: 'conversation', turn_id: 'turn', ...extra,
        },
      })}\n\n`));
      await setImmediate();
    },
    finish() { for (let frame = 0; frame < 320; frame++) t.mock.timers.tick(25); },
  };
}

test('accepted text plays locally after success and survives the terminal snapshot refresh', async (t) => {
  const fixture = await playback(t), { store } = fixture;
  await fixture.send('tutor.thinking', { thinking_text: '先确认学习基础。' });
  await fixture.send('tutor.reply_delta', { offset: 0, reply_text: body.slice(0, 64) });
  assert.equal(store.getSnapshot().live.conversation.text, '');

  fixture.change(snapshot(body));
  await fixture.send('tutor.succeeded', { reply_text: body });
  let reply = store.getSnapshot().live.conversation;
  assert.equal(reply.text, '');
  assert.equal(reply.fullText, body);
  assert.equal(reply.complete, true);
  assert.equal(reply.streaming, true);
  store.finishReply('conversation', 'turn');
  assert.ok(store.getSnapshot().live.conversation);

  t.mock.timers.tick(25);
  reply = store.getSnapshot().live.conversation;
  assert.ok(reply.text.length > 0 && reply.text.length < body.length);
  assert.ok(body.startsWith(reply.text));
  assert.ok(reply.text.startsWith('🐍'));
  await store.refresh();
  assert.equal(store.getSnapshot().live.conversation.text, reply.text);
  fixture.finish();
  assert.equal(store.getSnapshot().live.conversation.text, body);
  assert.equal(store.getSnapshot().live.conversation.streaming, false);

  store.finishReply('conversation', 'turn');
  assert.equal(store.getSnapshot().live.conversation, undefined);
  await fixture.send('tutor.succeeded', { reply_text: body });
  await store.refresh();
  assert.equal(store.getSnapshot().live.conversation, undefined);
  assert.ok(fixture.reads.every((path) => path === '/v1/snapshot'));
});

test('a reviewed stage reply and final route play once with separate stable identities', async (t) => {
  const fixture = await playback(t), { store } = fixture;
  const pending = snapshot();
  pending.turns[0].turns[0].stage_replies = [{ id: 'checked-author', text: '正在准备本批资料。' }];
  pending.cursor = 2;
  fixture.change(pending);
  await fixture.send('tutor.stage_reply', { reply_id: 'checked-author', reply_text: '正在准备本批资料。' });
  fixture.finish();
  assert.equal(store.getSnapshot().live.conversation.messageId, 'turn:stage:checked-author');
  assert.equal(store.getSnapshot().live.conversation.text, '正在准备本批资料。');
  store.finishReply('conversation', 'turn');
  await store.refresh();
  assert.equal(store.getSnapshot().live.conversation, undefined);
  await fixture.send('tutor.thinking', { thinking_text: '正在整理完整路线。' }, 3);
  assert.equal(store.getSnapshot().live.conversation.thinking, '正在整理完整路线。');
  const final = snapshot('完整路线正文');
  final.turns[0].turns[0].stage_replies = pending.turns[0].turns[0].stage_replies;
  fixture.change(final);
  await fixture.send('tutor.succeeded', { reply_text: '完整路线正文' });
  fixture.finish();
  assert.equal(store.getSnapshot().live.conversation.messageId, 'turn:assistant');
  assert.equal(store.getSnapshot().live.conversation.text, '完整路线正文');
});

test('a delivered stage keeps its own thinking when later work updates the same turn', async (t) => {
  const fixture = await playback(t), { store } = fixture;
  const completed = { id: 'first-author', kind: 'thinking', status: 'completed',
    detail: '已完成的回复摘要' };
  const pending = snapshot();
  pending.cursor = 2;
  pending.turns[0].turns[0].thinking_steps = [];
  pending.turns[0].turns[0].stage_replies = [{
    id: 'first-author', text: '已交付正文', thinking_text: '已完成的回复摘要',
    thinking_steps: [completed],
  }];
  fixture.change(pending);
  await store.refresh();
  assert.deepEqual(store.getSnapshot().live.conversation.steps, [completed]);
  await store.refresh();
  assert.deepEqual(store.getSnapshot().live.conversation.steps, [completed]);
  await fixture.send('tutor.thinking', { thinking_step: {
    id: 'next-author', kind: 'thinking', status: 'running', detail: '后续步骤',
  } }, 3);
  assert.deepEqual(store.getSnapshot().live.conversation.steps.map((step) => step.id),
    ['next-author']);
  assert.equal(pending.turns[0].turns[0].stage_replies[0].thinking_text, '已完成的回复摘要');
});

test('step updates replace stable identities and a reconnect restores earlier steps without regression', async (t) => {
  const earlier = { id: 'earlier', kind: 'thinking', status: 'completed', detail: 'Earlier summary' };
  const current = { id: 'current', kind: 'thinking', status: 'running', detail: '' };
  const initial = snapshot();
  initial.turns[0].turns[0].thinking_steps = [earlier];
  const fixture = await playback(t, initial), { store } = fixture;
  await fixture.send('tutor.thinking', { thinking_step: current }, 2);
  await fixture.send('tutor.thinking', {
    thinking_step: { ...current, detail: 'Complete visible summary', status: 'completed' },
  }, 3);
  await fixture.send('tutor.thinking', { thinking_step: current }, 2);
  let steps = store.getSnapshot().live.conversation.steps;
  assert.deepEqual(steps.map((step) => step.id), ['earlier', 'current']);
  assert.equal(steps[1].detail, 'Complete visible summary');

  fixture.change({ ...initial, cursor: 2 });
  await store.refresh();
  steps = store.getSnapshot().live.conversation.steps;
  assert.equal(steps[1].detail, 'Complete visible summary');
  fixture.change(snapshot(null, 'other'));
  await store.refresh();
  await fixture.send('tutor.thinking', {
    thinking_step: { ...current, detail: 'Old identity private summary' },
  }, 4);
  assert.deepEqual(store.getSnapshot().live, {});
});

test('snapshot-first delivery starts playback once, before history can reveal the full reply', async (t) => {
  const fixture = await playback(t), { store } = fixture;
  fixture.change(snapshot(body));
  await store.refresh();
  assert.equal(store.getSnapshot().live.conversation.text, '');
  t.mock.timers.tick(100);
  const prefix = store.getSnapshot().live.conversation.text;
  assert.ok(prefix.length > 0 && prefix.length < body.length);
  await fixture.send('tutor.succeeded', { reply_text: body });
  assert.equal(store.getSnapshot().live.conversation.text, prefix);
  fixture.finish();
  assert.equal(store.getSnapshot().live.conversation.text, body);
});

test('existing history never replays and switching identities clears pending playback', async (t) => {
  const fixture = await playback(t, snapshot('Previously accepted reply')), { store } = fixture;
  assert.deepEqual(store.getSnapshot().live, {});
  await fixture.send('tutor.succeeded', { reply_text: 'Previously accepted reply' });
  assert.deepEqual(store.getSnapshot().live, {});

  const next = snapshot();
  next.turns[0].turns[0].id = 'new-turn';
  fixture.change(next);
  await store.refresh();
  next.turns[0].turns[0].assistant_text = body;
  fixture.change({ ...next, cursor: 4 });
  await store.refresh();
  t.mock.timers.tick(25);
  assert.ok(store.getSnapshot().live.conversation.text);

  fixture.change(snapshot('Other identity history', 'other'));
  await store.refresh();
  fixture.finish();
  assert.deepEqual(store.getSnapshot().live, {});
  assert.equal(store.getSnapshot().snapshot.actor.id, 'other');
});

test('failed or unknown generation never queues body playback', async (t) => {
  const fixture = await playback(t), { store } = fixture;
  await fixture.send('tutor.thinking', { thinking_text: '先确认学习基础。' });
  const failed = snapshot();
  failed.cursor = 3;
  failed.runs[0].status = 'blocked_unknown';
  fixture.change(failed);
  await fixture.send('tutor.blocked_unknown');
  fixture.finish();
  assert.equal(store.getSnapshot().live.conversation, undefined);
  assert.equal(store.getSnapshot().snapshot.runs[0].status, 'blocked_unknown');
});

test('terminal snapshots release stale thinking without waiting for a lost failure frame', async (t) => {
  const fixture = await playback(t), { store } = fixture;
  await fixture.send('tutor.thinking', { thinking_text: '原生成中的摘要。' });
  assert.equal(store.getSnapshot().live.conversation.streaming, true);
  const failed = snapshot();
  failed.cursor = 3;
  failed.runs[0].status = 'failed';
  fixture.change(failed);
  await store.refresh();
  assert.equal(store.getSnapshot().live.conversation, undefined);
  await fixture.send('tutor.thinking', { thinking_text: '重放的旧摘要。' }, 2);
  assert.equal(store.getSnapshot().live.conversation, undefined);
  assert.equal(store.getSnapshot().snapshot.turns[0].turns[0].assistant_text, null);
});

test('a failed continuation keeps its already checked stage reply playback', async (t) => {
  const fixture = await playback(t), { store } = fixture;
  const failed = snapshot();
  failed.cursor = 3;
  failed.runs[0].status = 'failed';
  failed.turns[0].turns[0].stage_replies = [{ id: 'stage', text: '已经独立检查的阶段正文。' }];
  fixture.change(failed);
  await store.refresh();
  fixture.finish();
  assert.equal(store.getSnapshot().live.conversation.text, '已经独立检查的阶段正文。');
  assert.equal(store.getSnapshot().live.conversation.messageId, 'turn:stage:stage');
});
