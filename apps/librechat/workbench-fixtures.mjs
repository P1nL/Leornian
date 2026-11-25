import { sampleIds, sampleModelConfiguration, sampleSnapshot, sampleSource, sampleTime } from './workbench-data.mjs';

const json = (value, status = 200) => new Response(JSON.stringify(value),
  { status, headers: { 'Content-Type': 'application/json' } });
async function requestBody(init) {
  if (!init.body) return {};
  if (typeof init.body === 'string') return JSON.parse(init.body);
  const text = await new Response(init.body).text();
  try { return JSON.parse(text); } catch { return {}; }
}

/** A local, per-frame API. There is deliberately no network transport here. */
export function createWorkbenchFixtures({ instance = 'default', story = 'page', state = 'default' } = {}) {
  const snapshot = sampleSnapshot({ instance, state });
  const models = sampleModelConfiguration(state === 'empty');
  const listeners = new Set(), history = [], receipts = new Map(), timers = new Set();
  const empty = state === 'empty';
  const requirement = { recipe_id: 'python-standard.v1', recipe_revision: 1, profile: 'python-io.v1',
    language: 'python', dialect: null, title: 'Python 基础环境', toolchains: ['Python 3.12'],
    dependency_lock: [], sources: [], version_policy: '固定配方', services: [],
    estimated_download_bytes: null, estimated_disk_bytes: null };
  const engine = { status: state === 'waiting' ? 'unavailable' : 'ready',
    detail: state === 'waiting' ? '等待本机引擎授权' : '本机引擎已就绪（样例）', version: 'sample', operating_system: 'linux' };
  const demands = empty ? [] : [{ id: 'sample-environment', local_scope: 'this-device.v1',
    plan_id: sampleIds.plan, plan_revision: 1, requirement_revision: 1, decision_revision: 1,
    decision: state === 'waiting' ? null : 'allow', status: state === 'waiting' ? 'waiting_authorization' : 'ready',
    requirement, release: state === 'waiting' ? null : { id: 'sample-release', version: 'sample',
      recipe_revision: 1, runtime_version: 'Python 3.12（样例）', toolchains: { python: '3.12' } }, error_code: null }];
  let sources = empty ? [] : [{ id: 'sample-source', revision: 1, goal_id: sampleIds.goal, title: 'Python 循环教程（样例）',
    entry_url: 'https://example.invalid/tutorial/', allowed_prefixes: ['https://example.invalid/tutorial/'],
    admission: state === 'revoked' ? 'revoked' : 'allowed', purposes: ['reference', 'indexing', 'planning'],
    use_until: null, retain_until: null }];
  const reviews = empty ? [] : [{ kind: 'memory_review', id: 'sample-review', goal_id: sampleIds.goal,
    card_id: 'sample-card', card_revision: 1, state: state === 'presented' ? 'presented' : 'due',
    conversation_id: state === 'presented' ? sampleIds.conversation : null, source_receipt: null,
    presented_at: state === 'presented' ? sampleTime : null, created_at: sampleTime,
    card: { id: 'sample-card', revision: 1, status: 'scheduled', due: true,
      prompt: '为什么累计变量通常从 0 开始？请用空列表的情况解释。',
      next_due_at: sampleTime, algorithm_version: 'FSRS（样例）', parameter_version: 'sample' } }];
  const notifications = empty ? [] : [{ id: 'sample-notification', offer_id: 'sample-offer', state: 'unread',
    kind: 'material_update', payload: { goal_id: sampleIds.goal, baseline_revision: 1, candidate_revision: 2, node_key: 'loops' } }];
  let preference = { revision: 1, enabled: false, timezone: 'Asia/Shanghai', start_minute: 540, end_minute: 1260 };
  const gate = { id: 'sample-gate', pack_id: 'sample-pack', plan_id: sampleIds.plan, plan_revision: 1, node_key: 'loops',
    policy_version: 'concept-gate.v1', relation_run_id: 'sample-relation',
    status: state === 'completed' ? 'passed' : state === 'presented' ? 'in_progress' : 'ready', created_at: sampleTime };
  const transfer = { id: 'sample-transfer', source_pack_id: 'sample-pack', plan_id: sampleIds.plan, plan_revision: 1,
    node_key: 'loops', kind: 'choice', remediation_id: 'sample-remediation',
    status: state === 'completed' ? 'passed' : state === 'presented' ? 'opened' : 'ready', created_at: sampleTime };
  const choice = (slot) => ({ slot, title: '循环与边界条件', prompt: '空列表的累计结果应当是什么？',
    options: ['0', '1', '未定义', '列表长度加一'].map((text, index) => ({ key: ['A', 'B', 'C', 'D'][index], text })) });
  const gateView = () => ({ gate, questions: gate.status === 'in_progress' ? ['assessment_1', 'assessment_2'].map(choice) : [],
    results: [], allowed_actions: gate.status === 'ready' ? ['start', 'cancel'] : gate.status === 'in_progress' ? ['submit', 'cancel'] : [] });
  const transferView = () => ({ transfer, question: transfer.status === 'opened' ? choice('practice_1') : null,
    allowed_actions: transfer.status === 'ready' ? ['open', 'cancel'] : transfer.status === 'opened' ? ['submit', 'cancel'] : [] });
  if (story === 'assessment' || story === 'recovery') {
    snapshot.packs = [{ id: 'sample-pack', plan_id: sampleIds.plan, plan_revision: 1, node_key: 'loops',
      status: 'published', kind: 'choice', revision: 1 }];
    snapshot.gates = story === 'assessment' ? [gate] : [];
    snapshot.remediations = story === 'recovery' ? [{ id: 'sample-remediation', pack_id: 'sample-pack',
      status: 'not_passed', transfer_required: true, created_at: sampleTime }] : [];
    snapshot.transfers = story === 'recovery' ? [transfer] : [];
  }
  const publish = () => {
    snapshot.cursor++;
    const frame = new TextEncoder().encode(`data: ${JSON.stringify({
      sequence: snapshot.cursor, event_type: 'workbench.changed', payload: {},
    })}\n\n`);
    for (const listener of listeners) listener.enqueue(frame);
  };
  const failRead = (path) => state === 'error' && (
    ['models', 'model-roles'].includes(story) && path === '/v1/model-configuration' ||
    story === 'environment' && path === '/v1/execution-environments' ||
    story === 'records' && path === '/v1/learning-evidence' ||
    story === 'reviews' && path === '/v1/review-activities' ||
    ['materials', 'material-sources'].includes(story) && /^\/v1\/material-(sources|demands)$/.test(path) ||
    story === 'material-updates' && path === '/v1/notifications'
  );
  const fetchBackend = async (input, init = {}) => {
    const url = new URL(input), path = url.pathname, method = init.method ?? 'GET';
    history.push({ path, method });
    if (failRead(path)) return json({ code: 'sample_read_failed', message: '样例读取失败，可切换状态或重置预览。' }, 503);
    if (path === '/health/ready') return json({ status: 'ready', mode: 'component-preview' });
    if (path === '/v1/events') {
      let own;
      return new Response(new ReadableStream({
        start(controller) {
          own = controller; listeners.add(controller); controller.enqueue(new TextEncoder().encode(': component preview\n\n'));
          if (state === 'streaming') {
            const send = (event_type, payload) => {
              snapshot.cursor++;
              controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ sequence: snapshot.cursor, event_type, payload })}\n\n`));
            };
            const timer = setTimeout(() => {
              timers.delete(timer); if (!listeners.has(controller)) return;
              send('tutor.thinking', { conversation_id: sampleIds.conversation, turn_id: sampleIds.turn,
                thinking_text: '先用一个小例子观察变量的变化。' });
              const completion = setTimeout(() => {
                timers.delete(completion); if (!listeners.has(controller)) return;
                const text = '循环每次读取一个元素，再把它加到累计结果中。先用 `[2, 3, 5]` 跟踪三次更新，结果依次是 **2 → 5 → 10**。这是本地样例的流式展示。';
                snapshot.turns[0].turns[0].assistant_text = text;
                snapshot.turns[0].turns[0].completed_at = sampleTime;
                snapshot.runs.forEach((run) => { run.status = 'succeeded'; });
                send('tutor.succeeded', { conversation_id: sampleIds.conversation, turn_id: sampleIds.turn, reply_text: text });
              }, 1800); timers.add(completion);
            }, 100); timers.add(timer);
          }
        },
        cancel() { listeners.delete(own); },
      }), { headers: { 'Content-Type': 'text/event-stream' } });
    }
    if (path === '/v1/local-sessions' || path === '/v1/local-sessions/refresh') return json({
      actor: snapshot.actor, token: 'component-preview-session', expires_at: '2099-01-01T00:00:00Z',
    });
    if (path === '/v1/snapshot') return json(snapshot);
    if (method === 'GET' && path.endsWith('/learning-artifacts')) return json([]);
    if (path === '/v1/gates/sample-gate' && method === 'GET') return json(gateView());
    if (path === '/v1/transfers/sample-transfer' && method === 'GET') return json(transferView());
    if (path === '/v1/jobs/sample-goal-job') return json({ id: 'sample-goal-job', status: 'succeeded', result_ref: sampleIds.goal });
    if (path.endsWith('/history')) return json([...snapshot.turns[0].turns].reverse());
    if (path.endsWith('/teaching-session')) return json(snapshot.teaching_sessions[0]);
    if (path.endsWith('/teaching-branches') || path.endsWith('/teaching-intents')) return json([]);
    if (path === '/v1/tutor/availability') return json({ ready: true });
    if (path.endsWith('/material-progress')) return json({
      demand_id: 'sample-demand', status: story === 'rag-progress'
        ? state === 'ready' ? 'ready' : state === 'unknown' ? 'blocked_unknown' : state === 'error' ? 'failed' : 'processing' : 'idle',
      reason_code: state === 'unknown' ? 'external_result_unknown' : null,
      current_documents: 2, ready_documents: state === 'ready' ? 2 : 1, background_documents: 3, background_ready_documents: 2,
      steps: [{ key: 'sources', status: 'completed' }, { key: 'parsing', status: state === 'ready' ? 'completed' : 'running' },
        { key: 'indexing', status: state === 'ready' ? 'completed' : 'pending' },
        { key: 'retrieval', status: state === 'unknown' ? 'unknown' : state === 'ready' ? 'completed' : 'pending' }],
      documents: [],
    });
    if (path.endsWith('/source') || path === '/v1/workbench/source') return state === 'revoked'
      ? json({ code: 'permission_revoked', message: '样例来源权限已撤销' }, 403) : json(sampleSource(state));
    if (path === '/v1/execution-environments') return json({ application_status: 'ready', engine, recipes: [requirement], demands });
    if (path.includes('/environment-requirements/')) return json({
      plan_id: sampleIds.plan, plan_revision: 1, requirement_revision: 1, engine, requirements: [requirement],
      demands, gaps: [], automatic_recipe_ids: ['python-standard.v1'], consent_required: [],
    });
    if (path === '/v1/model-configuration') return json(models);
    if (path === '/v1/model-connection-tests' && method === 'GET') return json([]);
    if (path === '/v1/material-search-configuration' && method === 'GET') return json({
      credential_present: false, enabled: false, revision: 0, provider: 'tavily',
    });
    if (path === '/v1/material-demands' && method === 'GET' || path.endsWith('/jobs') && method === 'GET') return json([]);
    if (path === '/v1/material-sources' && method === 'GET') return json(sources);
    if (path === '/v1/learning-evidence') return json({ dimensions: empty ? [] : ['concept', 'execution', 'transfer'].map((dimension, index) => ({
      dimension, status: index ? 'practicing' : 'demonstrated', evidence_count: index ? 2 : 4,
      passed_count: 2, failed_count: 0, assisted_count: 0, independent_pass_count: index ? 0 : 1,
    })), evidence: [] });
    if (path === '/v1/review-activities' && method === 'GET') return json(reviews);
    if (/\/reviews\/[^/]+\/logs$/.test(path)) return json([]);
    if (path.endsWith('/proactive-preference') && method === 'GET') return json(preference);
    if (path === '/v1/notifications' && method === 'GET') return json(notifications);
    if (/\/notifications\/[^/]+\/read$/.test(path)) return json({ ...notifications[0], state: 'read' });
    if (path === '/v1/material-update-offers/sample-offer') return json({ id: 'sample-offer', revision: 1,
      binding_id: 'sample-binding', binding_revision: 1, baseline_revision: 1, candidate_revision: 2,
      summary: '补充了空列表与边界条件的说明（样例）', migration_cost: 'dependent_content_requires_reprepare',
      impact: { dependencies: [{ kind: 'plan', id: sampleIds.plan, revision: 1 }] } });
    if (path.endsWith('/repreparations')) return json([]);
    if (method === 'GET' && /\/(assessments|gates|transfers|packs|artifacts|compositions)(\/|$)/.test(path)) return json([]);
    if (method === 'GET' && receipts.has(path)) return json(receipts.get(path));
    if (method === 'GET') return json({ code: 'sample_not_found', message: `尚未定义样例：${path}` }, 404);
    const body = await requestBody(init);
    let result = { id: `sample-${snapshot.cursor}`, revision: 1 };
    if (path === '/v1/goals') {
      snapshot.goals = [{ id: sampleIds.goal, title: body.text ?? '新的样例学习计划', created_at: sampleTime, material_scope: null }];
      result = { job_id: 'sample-goal-job' };
    } else if (path === '/v1/conversations') {
      snapshot.conversations[0].hidden_from_recents = false; result = snapshot.conversations[0];
    } else if (/\/gates\/sample-gate\/start$/.test(path)) {
      gate.status = 'in_progress'; result = gateView();
    } else if (/\/(concept-gates|gates)\/sample-gate\/.*submissions$/.test(path)) {
      gate.status = 'passed'; result = gateView();
    } else if (/\/transfers\/sample-transfer\/open$/.test(path)) {
      transfer.status = 'opened'; result = transferView();
    } else if (/\/transfers\/sample-transfer\/.*submissions$/.test(path)) {
      transfer.status = 'passed'; result = transferView();
    } else if (path.endsWith('/gate-requests')) {
      snapshot.gates = [gate]; result = gate;
    } else if (path.endsWith('/transfer-requests')) {
      snapshot.transfers = [transfer]; result = transfer;
    } else if (path.endsWith('/actions')) {
      const session = snapshot.teaching_sessions[0];
      session.revision++;
      if (body.action === 'pause') session.paused = true;
      if (body.action === 'resume') session.paused = false;
      if (body.mode) session.mode = body.mode;
      if (body.focus) session.focus = body.focus;
      if (body.policy) session.continuation_policy = body.policy;
      result = session;
    } else if (path.endsWith('/confirm')) {
      const plan = snapshot.plans[0];
      if (plan) plan.active = structuredClone(plan.latest);
      result = { ...plan, plan_id: sampleIds.plan, revision: 1 };
    } else if (path.endsWith('/cancel')) {
      snapshot.runs.forEach((run) => { run.status = 'cancelled'; });
      if (path.includes('/gates/')) gate.status = 'cancelled';
      if (path.includes('/transfers/')) transfer.status = 'cancelled';
      result = { status: 'cancelled' };
    } else if (path.endsWith('/turns') || path.endsWith('/plan-requests')) {
      if (path.endsWith('/plan-requests') && !snapshot.plans.length) snapshot.plans = sampleSnapshot({ instance, state: 'draft' }).plans;
      const id = `sample-turn-${snapshot.cursor}`;
      snapshot.turns[0].turns.push({ ...snapshot.turns[0].turns[0], id, user_text: body.text ?? '样例输入',
        assistant_text: '这是本地预览响应。你可以继续调整输入框与消息样式。', created_at: new Date().toISOString(), completed_at: new Date().toISOString() });
      result = { turn_id: id, run_id: 'sample-run', status: 'succeeded' };
    } else if (path.endsWith('/proactive-preference')) {
      preference = { ...preference, ...body, revision: preference.revision + 1 }; result = preference;
    } else if (/\/review-activities\/[^/]+\//.test(path)) {
      const item = reviews[0];
      if (item) {
        item.state = path.endsWith('/present') ? 'presented' : path.endsWith('/cancel') ? 'cancelled' : 'completed';
        item.conversation_id = sampleIds.conversation;
        if (item.state === 'completed') item.card.due = false;
        result = item;
      }
    } else if (path === '/v1/material-sources') {
      result = { ...body, id: `sample-source-${snapshot.cursor}`, revision: 1, admission: 'allowed' };
      sources.push(result);
    } else if (path.endsWith('/revoke')) {
      sources = sources.map((source) => ({ ...source, admission: 'revoked', revision: source.revision + 1 }));
      result = sources[0] ?? result;
    } else if (path.endsWith('/checks')) {
      result = { id: 'sample-observation', source_id: 'sample-source', status: 'unchanged',
        job_id: null, document_id: null, document_revision: null };
    } else if (path === '/v1/material-demands') {
      result = { ...body, id: 'sample-demand', revision: 1 };
    } else if (path.endsWith('/uploads') || path.includes('/material-uploads/')) {
      result = { id: 'sample-upload', state: path.endsWith('/content') ? 'stored' : 'pending' };
    } else if (path.endsWith('/files')) {
      result = { id: 'sample-material-job', state: 'queued' };
    } else if (path.includes('/model-role-mappings/')) {
      const role = path.split('/').at(-1); result = { role, profile_id: body.profile_id, revision: (body.expected_mapping_revision ?? 0) + 1 };
      models.mappings = models.mappings.filter((mapping) => mapping.role !== role).concat(result);
    } else if (path.includes('/model-connections/') && path.endsWith('/tests')) {
      result = { id: 'sample-probe', status: 'succeeded', connection_id: 'sample-connection',
        profile_id: body.profile_id, created_at: sampleTime, error_code: null,
        result: { latency_ms: 120, context_tokens: 65536, max_output_tokens: 8192, reachable: true } };
    } else if (path.includes('/model-connections') || path.includes('/model-presets/')) {
      result = { ...models.connections[0], ...body, id: models.connections[0]?.id ?? 'sample-connection',
        revision: 2, credential_present: true, credential_version: 1, created_at: sampleTime };
      models.connections = [result];
    } else if (path.includes('/model-profiles')) {
      result = { ...models.profiles[0], ...body, id: models.profiles[0]?.id ?? 'sample-profile', revision: 2 };
      models.profiles = [result];
    } else if (path.includes('/material-update-offers/') && path.endsWith('/decisions')) {
      result = { id: 'sample-decision', offer_id: 'sample-offer', decision: body.decision,
        binding_id: 'sample-binding', binding_revision: 1,
        successor_binding_id: body.decision === 'accept_update' ? 'sample-binding' : null,
        successor_binding_revision: body.decision === 'accept_update' ? 2 : null, requires_reprepare: [] };
    } else if (path === '/v1/environment-demands') {
      result = { ...demands[0], id: 'sample-environment', requirement, requirement_revision: 1,
        decision_revision: 0, decision: null, status: 'waiting_authorization' }; demands.push(result);
    } else if (path.includes('/environment-demands/')) {
      const demand = demands.at(-1);
      if (demand) { Object.assign(demand, { decision: body.decision, decision_revision: demand.decision_revision + 1,
        status: body.decision === 'allow' ? 'ready' : 'waiting_authorization' }); result = demand; }
    } else if (path === `/v1/goals/${sampleIds.goal}`) {
      if (method === 'PATCH' && snapshot.goals[0]) snapshot.goals[0].title = body.title;
      if (method === 'DELETE') snapshot.goals = [];
    } else if (path.endsWith('/recent-entry')) {
      snapshot.conversations[0].hidden_from_recents = true;
    } else {
      return json({ code: 'sample_action_unavailable', message: '此操作尚无本地样例响应。' }, 404);
    }
    const key = new Headers(init.headers).get('idempotency-key');
    if (key) {
      receipts.set(`${path}/${key}`, result);
      receipts.set(`${path}/commands/${key}`, result);
    }
    publish();
    return json(result);
  };
  return { fetchBackend, history, snapshot,
    close() { for (const timer of timers) clearTimeout(timer); timers.clear();
      for (const listener of listeners) { try { listener.close(); } catch {} } listeners.clear(); } };
}
