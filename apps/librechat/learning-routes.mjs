import { intakeKey, readIntake, sendPlanningTurn } from './native-intake.mjs';

export async function beginPlanning(conversation, text, { store, request, storage }) {
  const actorId = store.getSnapshot().snapshot.actor.id;
  const saved = readIntake(storage, actorId);
  if (!saved || saved.conversation_id !== conversation.id) throw new Error('请继续原学习计划的创建。');
  saved.discussion_key ??= crypto.randomUUID();
  const save = () => storage.setItem(intakeKey(actorId), JSON.stringify(saved));
  if (saved.discussion_dispatched) {
    return request(`/v1/conversations/${conversation.id}/turn-requests/${saved.discussion_key}`);
  }
  saved.discussion_dispatched = true; save();
  try { return await sendPlanningTurn(store, conversation.id, text, saved.discussion_key); }
  catch (error) {
    if (error.status >= 400 && error.status < 500) { saved.discussion_dispatched = false; save(); }
    throw error;
  }
}

/** @param {import('../../packages/api-contracts/src/generated').components['schemas']['Snapshot']} snapshot
 * @param {import('../../packages/api-contracts/src/generated').components['schemas']['LearningPlan']} plan
 * @param {string} conversationId */
export function routeNodes(snapshot, plan, conversationId) {
  const revision = plan.active?.revision;
  const nodes = (plan.active ?? plan.latest).document.nodes;
  const conversation = snapshot.conversations.find((item) => item.id === conversationId);
  const studied = new Set((conversation?.studied_nodes ?? []).filter((item) =>
    item.plan_id === plan.id && item.plan_revision === revision).map((item) => item.node_key));
  const ended = new Set((conversation?.ended_nodes ?? []).filter((item) =>
    item.plan_id === plan.id && item.plan_revision === revision).map((item) => item.node_key));
  for (const page of snapshot.turns ?? []) {
    if (page.conversation_id !== conversationId) continue;
    for (const turn of page.turns) {
      const focus = turn.context_focus;
      if (turn.purpose === 'teaching' && turn.completed_at && turn.assistant_text != null &&
        !turn.teaching_intent_id && focus?.kind === 'node' && focus.plan_id === plan.id &&
        focus.expected_plan_revision === revision) studied.add(focus.node_key);
    }
  }
  let unlocked = Boolean(plan.active);
  return nodes.map((node) => {
    const result = { ...node, unlocked, studied: studied.has(node.key), ended: ended.has(node.key) };
    unlocked = unlocked && (result.studied || result.ended);
    return result;
  });
}

export async function enterTeachingNode(conversationId, focus, { store, request, actionKey = () => crypto.randomUUID() }) {
  const root = `/v2/conversations/${conversationId}/teaching-session`;
  const current = await request(root);
  if (current?.focus.kind === 'node' && current.focus.plan_id === focus.plan_id &&
    current.focus.expected_plan_revision === focus.expected_plan_revision && current.focus.node_key === focus.node_key) return current;
  const key = actionKey();
  return store.write(`${root}/actions`, {
    action: current ? 'set_topic' : 'open', ...(current ? {} : { mode: 'guided' }),
    focus, client_action_id: key, expected_session_revision: current?.revision ?? 0,
  }, { key, lookup: `${root}/actions/${key}` });
}

/** Called only by the learner's explicit route-confirmation control.
 * @param {any} conversation
 * @param {any} plan
 * @param {{store: any, request: any, storage: Storage, onConfirmed?: () => void,
 * environmentRequirements?: import('../../packages/api-contracts/src/generated').components['schemas']['EnvironmentRequirement'][]}} options */
export async function confirmFirstNode(conversation, plan, {
  store, request, storage, onConfirmed = () => {}, environmentRequirements = undefined,
}) {
  const actorId = store.getSnapshot().snapshot.actor.id;
  const revision = plan.latest.revision;
  const key = `leornian.native.route-start:${actorId}:${conversation.id}:${plan.id}:${revision}`;
  const saved = JSON.parse(storage.getItem(key) ?? 'null') ?? {};
  const save = () => storage.setItem(key, JSON.stringify(saved));
  for (const original of [saved.confirm_key, saved.focus_key, saved.first_turn_key]) {
    if (original && store.getSnapshot().pending?.some((pending) => pending.key === original)) {
      await store.reconcile(original);
    }
  }
  const root = `/v1/conversations/${conversation.id}`;
  const currentPlan = store.getSnapshot().snapshot?.plans?.find((item) => item.id === plan.id);
  const alreadyConfirmed = plan.active?.revision === revision || currentPlan?.active?.revision === revision;
  if (saved.entered || saved.first_turn_dispatched || (alreadyConfirmed && !saved.confirm_key)) {
    onConfirmed?.();
    if (saved.first_turn_dispatched) {
      await request(`${root}/turn-requests/${saved.first_turn_key}`);
    }
    return null;
  }
  if (!saved.confirmed && !alreadyConfirmed) {
    // Keep the exact consent body when recovering an unresolved confirmation.
    saved.confirm_body ??= {
      expected_revision: revision,
      ...(environmentRequirements === undefined ? {} : { environment_requirements: environmentRequirements }),
    };
    save();
    try {
      await store.write(`/v1/plans/${plan.id}/confirm`, saved.confirm_body, {
        key: saved.confirm_key ?? (saved.confirm_key = crypto.randomUUID(), save(), saved.confirm_key),
        lookup: `/v1/plans/${plan.id}/confirmations/${revision}`,
      });
    } catch (error) {
      if (error.status >= 400 && error.status < 500) {
        delete saved.confirm_body; delete saved.confirm_key; save();
      }
      throw error;
    }
    saved.confirmed = true; save();
    onConfirmed?.();
    await store.refresh();
  }
  if (store.getSnapshot().snapshot?.actor.id !== actorId) throw new Error('学习身份已切换。');
  const first = plan.latest.document.nodes[0];
  if (!first) throw new Error('当前路线尚无可学习的第一个节点。');
  const focus = { kind: 'node', plan_id: plan.id, expected_plan_revision: revision, node_key: first.key };
  await enterTeachingNode(conversation.id, focus, { store, request, actionKey: () => {
    saved.focus_key = crypto.randomUUID(); save(); return saved.focus_key;
  } });
  saved.entered = true; save();
  return { plan, first, focus };
}
