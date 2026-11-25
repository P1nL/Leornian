import { workbenchConversationId } from './workbench-catalog.mjs';

export const sampleIds = {
  conversation: workbenchConversationId, goal: '00000000-0000-4000-8000-000000000002',
  plan: '00000000-0000-4000-8000-000000000003', document: '00000000-0000-4000-8000-000000000004',
  turn: '00000000-0000-4000-8000-000000000005',
};
export const sampleTime = '2026-11-17T09:00:00Z';
export const sampleReasoning = '先确定输入与输出，再用一个小例子观察循环如何推进。最后检查空列表和边界值。';
export function sampleThinking(state = 'default') {
  return [
    { id: 'understand', kind: 'thinking', title: '理解学习目标', summary: '先掌握循环与列表的协作',
      detail: sampleReasoning, status: 'completed', tool_name: null, started_at: sampleTime,
      completed_at: sampleTime, duration_ms: 1240 },
    { id: 'check', kind: 'review', title: '核对示例', summary: '检查空列表与停止条件',
      detail: '空列表应返回 0。每处理一个元素，累计值更新一次。',
      status: state === 'busy' ? 'running' : state === 'error' ? 'failed' : 'completed',
      tool_name: 'learning_get_context', started_at: sampleTime,
      completed_at: state === 'busy' ? null : sampleTime, duration_ms: state === 'busy' ? null : 680 },
  ];
}
/** @returns {import('../../packages/api-contracts/src/generated').components['schemas']['CompositionSourceView']} */
export function sampleSource(state = 'default') {
  return {
    component_id: 'sample-source-reference', citation: { source_id: sampleIds.document, revision: 1 },
    title: '循环与列表 · 预览教材', excerpt: '循环让同一条规则依次作用于列表中的元素。',
    valid_until: null, location: { location_basis: 'document_page', number: 3,
      method: 'embedded_text', requires_ocr: false, reason_code: null },
    block: {
      id: '00000000-0000-4000-8000-000000000006', ordinal: 0, kind: 'paragraph', span_basis: 'source_text',
      ref: { document_id: sampleIds.document, document_revision: 1,
        block_id: '00000000-0000-4000-8000-000000000006', span: { start: 0, end: 1 }, content_digest: 'sample-content' },
      section_path: ['基础语法', '循环与列表'], source_page: 3,
      text: (state === 'long'
        ? '每一步先读取当前元素，再更新累计值。观察变量的变化，可以把程序的执行过程与结果联系起来。\n\n'.repeat(24)
        : '循环让同一条规则依次作用于列表中的元素。先把 total 设为 0，再依次加上每个数。空列表没有可处理的元素，因此结果仍然是 0。'),
    },
  };
}

export function sampleSnapshot({ instance = 'default', state = 'default' } = {}) {
  const draft = state === 'draft';
  const nodes = [
    { key: 'loops', title: '循环如何推进', objective: '跟踪一次循环中的变量变化', estimated_minutes: 25, prerequisite_keys: [], source_refs: [] },
    { key: 'functions', title: '把重复规则写成函数', objective: '明确输入、返回值和边界条件', estimated_minutes: 35, prerequisite_keys: ['loops'], source_refs: [] },
    { key: 'practice', title: '独立完成一个小程序', objective: '组合列表、循环与函数', estimated_minutes: 40, prerequisite_keys: ['functions'], source_refs: [] },
  ];
  const revision = { revision: 1, document: { title: 'Python 基础学习路线',
    summary: '从观察变量变化开始，逐步把规则写成函数，再通过一个小程序串联起来。',
    assumptions: ['已能运行简单的 Python 程序'], nodes }, created_at: sampleTime };
  const focus = { kind: 'node', plan_id: sampleIds.plan, expected_plan_revision: 1, node_key: 'loops', lesson_id: null };
  const turn = {
    id: sampleIds.turn, conversation_id: sampleIds.conversation, purpose: 'teaching',
    user_text: '循环为什么需要先把 total 设成 0？',
    assistant_text: '把 `total` 设为 **0**，相当于先准备一个空的累计结果。\n\n```python\ndef total(numbers):\n    result = 0\n    for number in numbers:\n        result += number\n    return result\n```\n\n| 输入 | 返回值 |\n| --- | --- |\n| `[2, 3, 5]` | `10` |\n| `[]` | `0` |\n\n你可以先跟踪第一个元素被处理后，`result` 变成了多少。',
    thinking_text: sampleReasoning, thinking_steps: sampleThinking(state),
    context_focus: focus, created_at: sampleTime, completed_at: sampleTime, stage_replies: [],
    teaching_intent_id: null, teaching_branch_id: null,
  };
  if (state === 'long') turn.assistant_text += '\n\n' + '观察当前元素、累计结果和下一次循环之间的关系。每一轮只完成一次明确的更新。\n\n'.repeat(32);
  if (state === 'error') { turn.assistant_text = ''; turn.completed_at = null; }
  if (state === 'streaming') { turn.assistant_text = ''; turn.completed_at = null; turn.thinking_steps = sampleThinking('busy'); }
  const session = { id: 'sample-session', conversation_id: sampleIds.conversation, revision: 1,
    mode: 'guided', paused: false, focus: draft ? { kind: 'goal' } : focus,
    continuation_policy: 'manual', active_branch_id: null, updated_at: sampleTime };
  return {
    cursor: 1, actor: { id: `component-preview-${instance}`, display_name: '预览学习者' },
    goals: state === 'empty' ? [] : [{ id: sampleIds.goal, title: state === 'long' ? '从基础语法到可执行项目的 Python 学习路线与复习安排' : 'Python 基础学习',
      created_at: sampleTime, material_scope: null }],
    conversations: [{ id: sampleIds.conversation, goal_id: sampleIds.goal, created_at: sampleTime,
      hidden_from_recents: state === 'empty', studied_nodes: [] }],
    plans: state === 'empty' ? [] : [{ id: sampleIds.plan, goal_id: sampleIds.goal, latest: revision,
      active: draft ? null : revision }],
    turns: [{ conversation_id: sampleIds.conversation, turns: state === 'empty' ? [] : [turn] }],
    teaching_sessions: [session], lessons: [], sources: state === 'empty' ? [] : [
      { id: sampleIds.document, goal_id: sampleIds.goal, title: '循环与列表 · 预览教材', revision: 1, usable: true },
    ],
    jobs: [], packs: [], evaluations: [], artifacts: [], compositions: [], composition_artifacts: [],
    gates: [], transfers: [], supply_demands: [], remediations: [], program_attempts: [], python_attempts: [],
    deliveries: [], deliveries_v2: [], delivery_tasks: [],
    runs: ['busy', 'unknown', 'error', 'streaming'].includes(state) ? [{
      id: 'sample-run', turn_id: turn.id, conversation_id: sampleIds.conversation,
      status: state === 'unknown' ? 'blocked_unknown' : state === 'error' ? 'failed' : 'running',
      cancel_requested: false, error_code: state === 'error' ? 'sample_connection_failed' : null,
      created_at: sampleTime,
    }] : [],
  };
}

export function sampleModelConfiguration(empty = false) {
  const connection = { id: 'sample-connection', revision: 1, label: '教学提供方（样例）', protocol: 'chat_completions',
    base_url: 'https://example.invalid/v1', region: 'custom', local_endpoint: false, enabled: true, deleted: false,
    credential_version: 1, credential_present: true, created_at: sampleTime };
  const profile = { id: 'sample-profile', connection_id: connection.id, revision: 1, label: '教学模型（样例）',
    model: 'sample-chat', operation: 'chat', enabled: true, allow_private_material: true,
    consent_revision: 1, context_tokens: 65536, max_output_tokens: 8192, embedding_dimensions: 1024,
    thinking: 'enabled', timeout_seconds: 300, roles: ['tutor.v1', 'planner.v1'],
    created_at: sampleTime };
  return { capabilities: ['explicit-role-assignment.v1', 'provider-presets.v1', 'provider-presets.v2', 'provider-presets.v3'],
    credential_storage: 'available', configuration_scope: 'user',
    connections: empty ? [] : [connection], profiles: empty ? [] : [profile],
    mappings: empty ? [] : [{ role: 'tutor.v1', profile_id: profile.id, revision: 1 }, { role: 'planner.v1', profile_id: profile.id, revision: 1 }],
    presets: [
      { id: 'deepseek', label: 'DeepSeek', base_url: 'https://example.invalid/v1', region: 'global', models: ['sample-chat'],
        api_key_url: '', model_details: [{ model: 'sample-chat', operation: 'chat', context_tokens: 65536 }] },
      { id: 'qwen', label: '千问', base_url: 'https://example.invalid/compatible-mode/v1', region: 'cn-beijing',
        models: ['sample-chat', 'sample-ocr', 'sample-embedding', 'sample-rerank'],
        model_details: ['chat', 'ocr', 'embedding', 'rerank'].map((operation) => ({
          model: `sample-${operation}`, operation, context_tokens: operation === 'chat' ? 65536 : 0,
        })) },
    ] };
}
