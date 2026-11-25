import { compositionContentKey } from './composition-v2-runtime.mjs';

export const NATIVE_CODE_REVIEW_CAPABILITY = 'learning_code_review.v2';

export class NativeApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
export async function nativeRequest(path, init = {}) {
  const response = await fetch(`/leornian${path}`, {
    ...init, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new NativeApiError(response.status, body.code ?? 'request_failed', body.message ?? '请求未完成');
  }
  return response.json();
}

export function createNativeStore({ request = nativeRequest, storage = globalThis.sessionStorage } = {}) {
  /** @type {{snapshot: import('../../packages/api-contracts/src/generated').components['schemas']['Snapshot'] | null,
   * epoch: number, connection: string, error: string,
   * composerNotice: {conversationId: string, text: string, error: string, draftKey?: string} | null,
   * live: Record<string, {turnId: string, summaries: string[], thinking: string, text: string, fullText?: string,
   * steps?: import('../../packages/api-contracts/src/generated').components['schemas']['ThinkingStep'][],
   * stepsSequence?: number, messageId?: string, streaming: boolean, complete?: boolean}>,
   * pending: {key: string, path: string, body: object, lookup?: string, status: string}[],
   * teaching: {actorId: string, conversationId: string,
   * session: import('../../packages/api-contracts/src/generated').components['schemas']['TeachingSession'] | null,
   * branches: import('../../packages/api-contracts/src/generated').components['schemas']['TeachingBranch'][],
   * intents: import('../../packages/api-contracts/src/generated').components['schemas']['TeachingIntent'][],
   * loading: boolean, error: string} | null,
   * reader: {path: string, content: import('../../packages/api-contracts/src/generated').components['schemas']['CompositionSourceView'] | null, error: string} | null}} */
  let state = { snapshot: null, epoch: 0, connection: '正在同步', error: '', pending: [], reader: null, teaching: null,
    live: {}, composerNotice: null };
  const listeners = new Set();
  let controller, refreshing, refreshingReader = 0;
  let teachingGeneration = 0, refreshingTeaching;
  const emit = (patch) => { state = { ...state, ...patch }; listeners.forEach((fn) => fn()); };
  const replyTimers = new Map(), acceptedReplies = new Set();
  const liveFor = (id, turnId) => {
    if (state.live[id]?.turnId === turnId) return state.live[id];
    const turn = state.snapshot?.turns?.find((page) => page.conversation_id === id)
      ?.turns.find((item) => item.id === turnId);
    return { turnId, summaries: [], thinking: turn?.thinking_text ?? '', text: '',
      steps: turn?.thinking_steps ?? [], stepsSequence: state.snapshot?.cursor ?? 0, streaming: false };
  };
  const cancelReply = (id) => {
    clearTimeout(replyTimers.get(id));
    replyTimers.delete(id);
  };
  const playReply = (id) => {
    if (replyTimers.has(id)) return;
    const turnId = state.live[id]?.turnId;
    const tick = () => {
      replyTimers.delete(id);
      const prior = state.live[id];
      if (!prior?.complete || prior.turnId !== turnId) return;
      const target = [...(prior.fullText ?? '')], shown = [...prior.text].length;
      // Small batches stay readable; long replies finish within roughly eight seconds.
      const next = Math.min(target.length, shown + Math.max(2, Math.ceil(target.length / 320)));
      emit({ live: { ...state.live, [id]: {
        ...prior, text: target.slice(0, next).join(''), streaming: next < target.length,
      } } });
      if (next < target.length) replyTimers.set(id, setTimeout(tick, 25));
    };
    replyTimers.set(id, setTimeout(tick, 25));
  };
  const acceptReply = (id, turnId, text, thinking, steps, replyId) => {
    const identity = replyId ? `${turnId}:stage:${replyId}` : turnId;
    if (!text || acceptedReplies.has(identity)) return;
    acceptedReplies.add(identity);
    cancelReply(id);
    const prior = liveFor(id, turnId);
    emit({ live: { ...state.live, [id]: {
      ...prior, messageId: replyId ? identity : `${turnId}:assistant`, text: '',
      fullText: text, thinking: thinking ?? prior.thinking,
      steps: steps ?? prior.steps,
      complete: true, streaming: true,
    } } });
    playReply(id);
  };
  const key = () => `leornian.native.writes.v1:${state.snapshot?.actor.id}`;
  const savePending = (pending) => { storage?.setItem(key(), JSON.stringify(pending)); emit({ pending }); };
  const refreshTeaching = async () => {
    const selected = state.teaching, generation = teachingGeneration;
    if (!selected) return;
    if (refreshingTeaching?.generation === generation) {
      const previous = refreshingTeaching;
      await previous.promise;
      if (generation === teachingGeneration && state.epoch > previous.epoch) return refreshTeaching();
      return;
    }
    const promise = (async () => {
      emit({ teaching: { ...selected, loading: true, error: '' } });
      try {
        const root = `/v2/conversations/${selected.conversationId}`;
        const session = await request(`${root}/teaching-session`);
        const branches = [];
        if (session) {
          let before = '';
          do {
            const page = await request(`${root}/teaching-branches?limit=100${before ? `&before=${before}` : ''}`);
            branches.push(...page);
            before = page.length === 100 ? page.at(-1).id : '';
          } while (before);
        }
        const intents = session
          ? await request(`/v1/conversations/${selected.conversationId}/teaching-intents?limit=20`) : [];
        if (generation === teachingGeneration) emit({
          teaching: { ...selected, session, branches, intents, loading: false, error: '' },
        });
      } catch (error) {
        if (generation === teachingGeneration) emit({
          teaching: { ...selected, loading: false, error: error.message },
        });
      }
    })().finally(() => { if (refreshingTeaching?.generation === generation) refreshingTeaching = null; });
    refreshingTeaching = { generation, epoch: state.epoch, promise };
    return promise;
  };
  const refreshReader = async () => {
    if (!state.reader) return;
    const selected = state.reader, generation = ++refreshingReader;
    emit({ reader: { ...selected, error: '' } });
    try {
      const content = await request(selected.path);
      if (generation === refreshingReader && state.reader) emit({ reader: { ...selected, content, error: '' } });
    } catch (error) {
      if (generation === refreshingReader && state.reader) emit({ reader: { ...selected, content: null, error: error.message } });
    }
  };
  const refresh = async () => {
    if (refreshing) return refreshing;
    refreshing = (async () => {
      const snapshot = await request('/v1/snapshot');
      if (state.snapshot && snapshot.actor.id === state.snapshot.actor.id && snapshot.cursor < state.snapshot.cursor) return;
      if (state.snapshot?.actor.id !== snapshot.actor.id) {
        for (const id of replyTimers.keys()) cancelReply(id);
        acceptedReplies.clear();
        for (const page of snapshot.turns ?? []) for (const turn of page.turns) {
          if (turn.assistant_text) acceptedReplies.add(turn.id);
          for (const reply of turn.stage_replies ?? []) acceptedReplies.add(`${turn.id}:stage:${reply.id}`);
        }
        let pending = [];
        try { pending = JSON.parse(storage?.getItem(`leornian.native.writes.v1:${snapshot.actor.id}`) ?? '[]'); } catch {}
        // An interrupted request is not evidence that no server transaction committed.
        pending = pending.map((p) => ({ ...p, status: 'unknown' }));
        teachingGeneration++;
        emit({ snapshot, pending, reader: null, teaching: null, live: {}, composerNotice: null, epoch: state.epoch + 1, error: '' });
      } else {
        const previous = new Map(state.snapshot.turns.flatMap((page) =>
          page.turns.map((turn) => [turn.id, turn.assistant_text])));
        // A snapshot may observe acceptance before the corresponding SSE frame.
        for (const page of snapshot.turns) for (const turn of page.turns) {
          for (const reply of turn.stage_replies ?? []) {
            acceptReply(page.conversation_id, turn.id, reply.text,
              reply.thinking_text ?? '', reply.thinking_steps ?? [], reply.id);
          }
          if (turn.purpose !== 'item_supply' && turn.assistant_text &&
            previous.get(turn.id) !== turn.assistant_text) {
            acceptReply(page.conversation_id, turn.id, turn.assistant_text,
              turn.thinking_text, turn.thinking_steps);
          }
        }
        const live = { ...state.live };
        for (const page of snapshot.turns) for (const turn of page.turns) {
          const prior = live[page.conversation_id];
          const stage = turn.stage_replies?.find((reply) =>
            prior?.messageId === `${turn.id}:stage:${reply.id}`);
          if (prior?.turnId === turn.id && turn.thinking_steps &&
            snapshot.cursor >= (prior.stepsSequence ?? 0)) {
            live[page.conversation_id] = {
              ...prior, steps: stage?.thinking_steps ?? turn.thinking_steps,
              ...(stage ? { thinking: stage.thinking_text ?? '' } : {}),
              stepsSequence: snapshot.cursor,
            };
          }
        }
        for (const run of snapshot.runs ?? []) {
          const prior = live[run.conversation_id];
          if (prior?.turnId === run.turn_id && !prior.fullText &&
            ['failed', 'cancelled', 'blocked_unknown'].includes(run.status)) {
            cancelReply(run.conversation_id);
            delete live[run.conversation_id];
          }
        }
        emit({ snapshot, live, epoch: state.epoch + 1, error: '' });
      }
      await refreshReader();
      await refreshTeaching();
    })().finally(() => { refreshing = null; });
    return refreshing;
  };
  const synchronize = async (signal) => {
    while (!signal.aborted) {
      try {
        await refresh();
        if (signal.aborted) return;
        const streamActor = state.snapshot.actor.id;
        const response = await fetch(`/leornian/v1/events?after=${state.snapshot.cursor}`, {
          signal, credentials: 'same-origin', headers: { Accept: 'text/event-stream' },
        });
        if (!response.ok || !response.body) throw new Error('事件连接未就绪');
        emit({ connection: '已连接' });
        const reader = response.body.getReader(), decoder = new TextDecoder();
        let buffer = '';
        try {
          while (!signal.aborted) {
            const chunk = await reader.read();
            if (chunk.done) break;
            if (state.snapshot?.actor.id !== streamActor) throw new Error('身份已变化，重新同步会话');
            buffer += decoder.decode(chunk.value, { stream: true });
            let boundary;
            while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
              const frame = buffer.slice(0, boundary.index);
              buffer = buffer.slice(boundary.index + boundary[0].length);
              const data = frame.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
              if (!data) continue;
              if (frame.includes('event: stream.reset')) throw new Error('需要重新同步会话');
              const event = JSON.parse(data);
              const payload = event.payload;
              // Older APIs split an accepted reply into transport chunks; playback is local.
              if (event.event_type === 'tutor.reply_delta') continue;
              if (event.event_type === 'tutor.thinking') {
                const id = payload.conversation_id;
                if (acceptedReplies.has(payload.turn_id)) continue;
                if (state.snapshot.runs?.some((run) => run.turn_id === payload.turn_id &&
                  run.conversation_id === id && ['failed', 'cancelled', 'blocked_unknown'].includes(run.status))) continue;
                if (state.live[id]?.turnId !== payload.turn_id) cancelReply(id);
                let prior = liveFor(id, payload.turn_id);
                const turn = state.snapshot.turns.find((page) => page.conversation_id === id)
                  ?.turns.find((item) => item.id === payload.turn_id);
                if (payload.thinking_step && turn?.stage_replies?.some((reply) =>
                  reply.thinking_steps?.some((step) => step.id === payload.thinking_step.id))) continue;
                if (prior.messageId?.includes(':stage:')) {
                  cancelReply(id);
                  prior = { ...prior, messageId: `${payload.turn_id}:assistant`,
                    text: '', fullText: undefined, complete: false,
                    thinking: turn?.thinking_text ?? '', steps: turn?.thinking_steps ?? [] };
                }
                if (payload.thinking_step && event.sequence <= (prior.stepsSequence ?? 0)) continue;
                const summaries = payload.thinking_summary && !prior.summaries.includes(payload.thinking_summary)
                  ? [...prior.summaries, payload.thinking_summary] : prior.summaries;
                const thinking = payload.thinking_text ?? prior.thinking;
                const steps = [...(prior.steps ?? [])];
                if (payload.thinking_step) {
                  const index = steps.findIndex((step) => step.id === payload.thinking_step.id);
                  if (index < 0) steps.push(payload.thinking_step);
                  else steps[index] = payload.thinking_step;
                }
                emit({ live: { ...state.live, [id]: {
                  ...prior, summaries, thinking, steps,
                  stepsSequence: payload.thinking_step ? event.sequence : prior.stepsSequence,
                  streaming: true, complete: false,
                } } });
                continue;
              }
              if (event.event_type === 'tutor.succeeded') {
                acceptReply(payload.conversation_id, payload.turn_id, payload.reply_text);
              }
              if (event.event_type === 'tutor.stage_reply') {
                acceptReply(payload.conversation_id, payload.turn_id, payload.reply_text,
                  undefined, undefined, payload.reply_id);
              }
              if (/^knowledge\./.test(event.event_type ?? '') ||
                event.event_type === 'learning.dynamic_plan_confirmed') {
                if (state.reader) emit({ reader: { ...state.reader, content: null, error: '' } });
              }
              if (event.sequence > state.snapshot.cursor) await refresh();
              if (/^tutor\.(failed|cancelled|blocked_unknown)$/.test(event.event_type)) {
                const live = { ...state.live };
                const prior = live[payload.conversation_id];
                if (prior?.turnId === payload.turn_id && !prior.complete) {
                  cancelReply(payload.conversation_id);
                  live[payload.conversation_id] = { ...prior, text: '', streaming: false, complete: true };
                }
                emit({ live });
              }
            }
          }
        } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
        if (!signal.aborted) throw new Error('事件连接已断开');
      } catch (error) {
        if (signal.aborted) return;
        emit({ connection: '重连中', error: error.message });
        await new Promise((resolve) => {
          const timer = setTimeout(done, 1500);
          function done() { clearTimeout(timer); signal.removeEventListener('abort', done); resolve(); }
          signal.addEventListener('abort', done, { once: true });
        });
      }
    }
  };
  return {
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    getSnapshot: () => state,
    finishReply(conversationId, turnId) {
      const reply = state.live[conversationId];
      if (reply?.turnId !== turnId || !reply.complete || reply.streaming) return;
      const live = { ...state.live };
      delete live[conversationId];
      emit({ live });
    },
    /** @param {{conversationId: string, text: string, error: string, draftKey?: string} | null} composerNotice */
    setComposerNotice(composerNotice) { emit({ composerNotice }); },
    refresh,
    refreshTeaching,
    openTeaching(conversationId) {
      const actorId = state.snapshot?.actor.id;
      if (!actorId || !conversationId || conversationId === 'new') {
        if (state.teaching) { teachingGeneration++; emit({ teaching: null }); }
        return Promise.resolve();
      }
      if (state.teaching?.actorId === actorId && state.teaching.conversationId === conversationId) {
        return refreshingTeaching?.promise ?? Promise.resolve();
      }
      teachingGeneration++;
      emit({ teaching: { actorId, conversationId, session: null, branches: [], intents: [], loading: true, error: '' } });
      return refreshTeaching();
    },
    start() {
      if (controller) return () => {};
      controller = new AbortController();
      const own = controller;
      for (const [id, reply] of Object.entries(state.live)) {
        if (reply.complete && reply.streaming) playReply(id);
      }
      void synchronize(own.signal);
      return () => {
        own.abort();
        if (controller === own) {
          controller = null;
          for (const id of replyTimers.keys()) cancelReply(id);
        }
      };
    },
    /** @param {{key?: string, lookup?: string}} options */
    async write(path, body, options = {}) {
      const { key: requestKey = crypto.randomUUID(), lookup } = options;
      if (!state.snapshot) throw new Error('先同步当前身份');
      if (state.pending.some((p) => p.path === path && JSON.stringify(p.body) === JSON.stringify(body))) throw new Error('原提交尚未核对，不会重发');
      const pending = { key: requestKey, path, body, lookup, status: 'dispatching' };
      savePending([...state.pending, pending]);
      try {
        const receipt = await request(path, { method: 'POST', headers: { 'Idempotency-Key': requestKey }, body: JSON.stringify(body) });
        savePending(state.pending.filter((p) => p.key !== requestKey));
        await refresh().catch((error) => emit({ error: error.message }));
        return receipt;
      } catch (error) {
        if (error instanceof NativeApiError && error.status < 500) savePending(state.pending.filter((p) => p.key !== requestKey));
        else savePending(state.pending.map((p) => p.key === requestKey ? { ...p, status: 'unknown' } : p));
        throw error;
      }
    },
    async reconcile(requestKey) {
      const pending = state.pending.find((p) => p.key === requestKey);
      if (!pending?.lookup) throw new Error('没有只读核对入口；请检查服务端历史，不会自动重发');
      const receipt = await request(pending.lookup);
      savePending(state.pending.filter((p) => p.key !== requestKey));
      await refresh();
      return receipt;
    },
    openSource(path) { emit({ reader: { path, content: null, error: '' } }); return refreshReader(); },
    closeSource() { refreshingReader++; emit({ reader: null }); },
    expireSource() {
      refreshingReader++;
      if (state.reader) emit({ reader: { ...state.reader, content: null, error: '使用或保留期限已到，请重新核对来源' } });
    },
  };
}

export const nativeStore = createNativeStore();
export function isNativeEmptyConversation(snapshot, conversationId) {
  return Boolean(conversationId && conversationId !== 'new' && snapshot?.turns.some(
    (page) => page.conversation_id === conversationId && page.turns.length === 0,
  ));
}
export function readArtifactDraft(actorId, artifact, definition, initial) {
  const original = `leornian.native.draft.v2:${actorId}:${compositionContentKey(artifact)}`;
  const key = artifact.practice_only ? original + ':practice' : original;
  let value, saved;
  try {
    saved = sessionStorage.getItem(key);
    value = JSON.parse(saved ?? (artifact.practice_only ? sessionStorage.getItem(original) : null) ?? 'null');
  } catch {}
  const draft = initial(definition);
  if (value && typeof value === 'object') {
    // Source/file identity and immutable code always come from accepted content.
    for (const [id, state] of Object.entries(definition.states ?? {})) {
      const cached = value.values?.[id];
      if (state.type === 'code' && !state.read_only && typeof cached === 'string') draft.values[id] = cached;
      if (state.type === 'text' && typeof cached === 'string') draft.values[id] = cached;
      if (['choice', 'order'].includes(state.type) && Array.isArray(cached) && cached.every((x) => typeof x === 'string')) {
        const node = definition.components.find((n) => n.props.state === id && ['ChoiceAnswer', 'OrderingAnswer'].includes(n.component));
        const ids = new Set((node?.props.options ?? node?.props.items ?? []).map((item) => item.id));
        if (new Set(cached).size === cached.length && cached.every((item) => ids.has(item)) &&
          (state.type !== 'order' || cached.length === ids.size) && (state.type !== 'choice' || node?.props.multiple || cached.length <= 1)) draft.values[id] = cached;
      }
      if (state.type === 'number' && typeof cached === 'number' && Number.isFinite(cached)) {
        const controls = definition.components.filter((n) => n.component === 'ParameterControl' && n.props.state === id);
        if (controls.every((n) => cached >= n.props.minimum && cached <= n.props.maximum)) draft.values[id] = cached;
      }
      if (state.type === 'files' && Array.isArray(cached)) draft.values[id] = state.files.map((file) => {
        const edited = cached.find((f) => f.path === file.path);
        return !file.read_only && typeof edited?.content === 'string'
          ? { ...file, content: edited.content } : file;
      });
      if (state.type === 'annotations') {
        const node = definition.components.find((n) => n.component === 'LineRangeAnswer' && n.props.state === id);
        if (!node) continue;
        const count = definition.states[node.props.code_state].value.split('\n').length;
        const notes = value.annotations?.[id];
        if (notes) draft.annotations[id] = Object.fromEntries(['saved', 'pending'].map((kind) => [kind,
          Object.fromEntries(Object.entries(notes[kind] ?? {}).filter(([line, text]) =>
            Number.isInteger(Number(line)) && Number(line) >= 1 && Number(line) <= count && typeof text === 'string')),
        ]));
      }
      if (state.type === 'playback' && Number.isInteger(cached) && cached >= 0 && cached <= 10000) draft.values[id] = cached;
      if (state.type === 'selection' && (typeof cached === 'string' || cached === null)) draft.values[id] = cached;
    }
    for (const node of definition.components) {
      if (node.component === 'CodeEditor' && definition.states[node.props.state].type === 'files') {
        const selected = value.selectedFiles?.[node.id];
        if (definition.states[node.props.state].files.some((file) => file.path === selected)) draft.selectedFiles[node.id] = selected;
      }
      if (node.component === 'TreeView') {
        const branches = new Set();
        const walk = (nodes) => nodes.forEach((item) => {
          if (item.children?.length) { branches.add(item.id); walk(item.children); }
        });
        walk(node.props.nodes);
        if (Array.isArray(value.expanded?.[node.id])) draft.expanded[node.id] =
          [...new Set(value.expanded[node.id].filter((key) => branches.has(key)))];
      }
    }
  }
  return { key, draft, restored: Boolean(saved && value?.values && typeof value.values === 'object') };
}
