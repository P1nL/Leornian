export const intakeKey = (actorId) => `leornian.native.intake.v1:${actorId}`;
/** @type {import('../../packages/api-contracts/src/generated').components['schemas']['GoalMaterialScope']} */
export const defaultMaterialScope = {
  contract: 'goal-material-scope.v1', language: null, language_version: null,
  framework: null, framework_version: null, authorized_official_sources: true,
  authorized_public_sources: true,
};

export function readIntake(storage, actorId) {
  try {
    const saved = JSON.parse(storage.getItem(intakeKey(actorId)) || 'null');
    return saved?.actor_id === actorId && typeof saved.text === 'string' ? saved : null;
  } catch { return null; }
}

export async function prepareLearning(text, { store, request, storage,
  materialScope = /** @type {import('../../packages/api-contracts/src/generated').components['schemas']['GoalMaterialScope'] | null} */ (null),
  attachmentDraft = false,
  pause = (ms) =>
  new Promise((resolve) => setTimeout(resolve, ms)) }) {
  const actorId = store.getSnapshot().snapshot?.actor.id;
  if (!actorId) throw new Error('请先恢复本机学习身份。');
  text = text.trim();
  if (text.length < 3 || text.length > 1200) throw new Error('请填写 3–1200 字的学习目标。');
  const key = intakeKey(actorId);
  let saved = readIntake(storage, actorId);
  if (saved?.text === text && materialScope === defaultMaterialScope) {
    // A new application default cannot expand an already submitted goal's permission.
    materialScope = saved.material_scope ?? null;
  }
  if (saved?.attachment_draft && !saved.conversation_id && !saved.discussion_dispatched && !attachmentDraft) {
    const prepared = await prepareLearning(saved.text, {
      store, request, storage, materialScope: saved.material_scope ?? null, attachmentDraft: true, pause,
    });
    if (!prepared.conversation) return prepared;
    saved = readIntake(storage, actorId);
  }
  if (saved?.attachment_draft && saved.conversation_id && !saved.discussion_dispatched && !attachmentDraft) {
    await request(`/v1/goals/${saved.goal_id}`, {
      method: 'PATCH',
      body: JSON.stringify({ title: text.replace(/\s+/g, ' ').slice(0, 120), motivation: text }),
    });
    materialScope = saved.material_scope ?? null;
    saved = { ...saved, text, attachment_draft: false,
      fingerprint: JSON.stringify({ text, material_scope: materialScope }) };
    storage.setItem(key, JSON.stringify(saved));
    await store.refresh();
  }
  const fingerprint = JSON.stringify({ text, material_scope: materialScope });
  if (saved?.conversation_id && !saved.discussion_dispatched && saved.text !== text) {
    const draftKey = `leornian.native.composer:${actorId}:${saved.conversation_id}`;
    if (storage.getItem(draftKey) === null) storage.setItem(draftKey, saved.text);
    storage.removeItem(key);
    saved = null;
  }
  if (saved && (saved.fingerprint ?? JSON.stringify({
    text: saved.text, material_scope: saved.material_scope ?? null,
  })) !== fingerprint) throw new Error('请先继续处理已提交的学习目标与科目授权，或从已有目标进入。');
  if (!saved) {
    saved = { actor_id: actorId, text, material_scope: materialScope, fingerprint, attachment_draft: attachmentDraft,
      request_key: crypto.randomUUID(), job_id: null, conversation_id: null };
    storage.setItem(key, JSON.stringify(saved));
    try {
      const title = text.replace(/\s+/g, ' ').slice(0, 120);
      const accepted = await store.write('/v1/goals', { title, motivation: text,
        ...(materialScope ? { material_scope: materialScope } : {}) }, {
        key: saved.request_key, lookup: `/v1/goal-requests/${saved.request_key}`,
      });
      saved.job_id = accepted.job_id;
      storage.setItem(key, JSON.stringify(saved));
    } catch (error) {
      if (!store.getSnapshot().pending.some((item) => item.path === '/v1/goals')) storage.removeItem(key);
      throw error;
    }
  }
  if (saved.conversation_id) return { status: 'ready', conversation: { id: saved.conversation_id, goal_id: saved.goal_id } };
  if (!saved.job_id && saved.request_key) {
    const receipt = await request(`/v1/goal-requests/${saved.request_key}`);
    saved.job_id = receipt.job_id;
    storage.setItem(key, JSON.stringify(saved));
  }
  if (!saved.job_id) throw new Error('目标请求尚无确定回执。请在任务中查看状态，或从已保存目标进入；不会重新提交。');
  for (let index = 0; index < 20; index++) {
    const job = await request(`/v1/jobs/${saved.job_id}`);
    if (job.status === 'failed') {
      storage.removeItem(key);
      throw new Error(`目标准备失败：${job.error_code || '请查看任务记录'}`);
    }
    if (job.status === 'succeeded' && job.result_ref) {
      const conversation = await request('/v1/conversations', {
        method: 'POST', body: JSON.stringify({ goal_id: job.result_ref }),
      });
      saved.goal_id = conversation.goal_id;
      saved.conversation_id = conversation.id;
      storage.setItem(key, JSON.stringify(saved));
      await store.refresh();
      return { status: 'ready', conversation };
    }
    if (index < 19) await pause(250);
  }
  return { status: 'waiting', job_id: saved.job_id };
}

export function teachingTurnInput(text, focus, session) {
  return {
    text, focus,
    ...(session ? { teaching_session_revision: session.revision } : {}),
    ...(session && focus?.kind === 'node' ? { node_pacing: true } : {}),
    presentation_capabilities: {
      versions: ['learning_composition.v2'],
      actions: ['learning_practice.v2', 'learning_responses.v1', 'learning_code_review.v2',
        'learning_programs.v2', 'learning_direct_answers.v1', 'learning_hints.v1', 'learning_demo_events.v1',
        'learning_example_runs.v2', 'learning_templates.v1'],
    },
  };
}

export function composerDraftKey(actorId, conversationId, focus) {
  const base = `leornian.native.composer:${actorId}:${conversationId}`;
  return focus?.kind === 'node'
    ? `${base}:${focus.plan_id}:${focus.expected_plan_revision}:${encodeURIComponent(focus.node_key)}` : base;
}

export function continueNode(store, conversationId, session) {
  const after = session.node_window.after_turn_id;
  const key = `node-window:${session.revision}:${after ?? 'opening'}`;
  return store.write(`/v2/conversations/${conversationId}/teaching-session/continue`, {
    expected_session_revision: session.revision, focus: session.focus, after_turn_id: after,
    presentation_capabilities: teachingTurnInput('', session.focus, session).presentation_capabilities,
  }, { key: `${conversationId}:${key}`, lookup: `/v1/conversations/${conversationId}/turn-requests/${key}` });
}

export function sendTeachingTurn(store, conversationId, text, focus, session) {
  const key = crypto.randomUUID();
  const path = `/v1/conversations/${conversationId}`;
  return store.write(`${path}/turns`, teachingTurnInput(text, focus, session), {
    key, lookup: `${path}/turn-requests/${key}`,
  });
}

/** @param {{ requirements_revision: number } | null} start */
export function sendPlanningTurn(store, conversationId, text, key = crypto.randomUUID(), start = null) {
  const snapshot = store.getSnapshot().snapshot;
  const conversation = snapshot?.conversations.find((item) => item.id === conversationId);
  const plan = snapshot?.plans.find((item) => item.goal_id === conversation?.goal_id);
  const root = `/v1/conversations/${conversationId}`;
  return store.write(`${root}/plan-requests`, {
    text, expected_revision: plan?.latest.revision ?? 0, discussion: true, focus: { kind: 'goal' },
    ...(start ? { start_plan: true, expected_requirements_revision: start.requirements_revision } : {}),
  }, { key, lookup: `${root}/turn-requests/${key}` });
}
