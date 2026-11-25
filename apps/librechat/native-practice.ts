import type { components } from '@leornian/api-contracts';
import type {
  CompositionDraftV2, CompositionIntentV2, CompositionReceiptV2,
} from './LearningCompositionV2';

export type PracticeBinding = components['schemas']['CompositionComponentView'];
type PracticeView = components['schemas']['CompositionArtifactView'];
type PracticeAction = components['schemas']['CompositionRunAction'] |
  components['schemas']['CompositionRespondAction'] | components['schemas']['CompositionCancelRunAction'] |
  components['schemas']['CompositionAnswerAction'] | components['schemas']['CompositionProgramRunAction'] |
  components['schemas']['CompositionDirectAnswerAction'] |
  components['schemas']['CompositionHintAction'];
export type PracticeCommand = PracticeAction extends infer T ? T extends PracticeAction
  ? Omit<T, 'client_action_id' | 'expected_artifact_revision'> : never : never;
type ProgramAnswer = components['schemas']['CompositionProgramPayload']['answer'];
type DraftValue = CompositionDraftV2['values'][string];
type ProgramTask = components['schemas']['ProgramCandidatePresentation']['task'];

export function programAnswer(binding: PracticeBinding, value: DraftValue): ProgramAnswer | null {
  const presentation = binding.source.presentation;
  if (presentation.type !== 'program_practice') return null;
  return programTaskAnswer(presentation.task, value);
}

export function programTaskAnswer(task: ProgramTask, value: DraftValue): ProgramAnswer | null {
  if (task.language === 'sql_query') return typeof value === 'string' && value.trim() &&
    !value.includes('\0') && new TextEncoder().encode(value).length <= 12000
    ? { type: 'sql', query: value } : null;
  if (!Array.isArray(value) || value.length !== task.files.length ||
    value.some((file) => typeof file !== 'object' || file === null || !('path' in file))) return null;
  const edits = value as components['schemas']['ProgramFile'][];
  if (new Set(edits.map((file) => file.path)).size !== edits.length) return null;
  const files = task.files.map((original) => edits.find((file) => file.path === original.path));
  if (files.some((file, index) => !file || typeof file.content !== 'string' ||
    Boolean(file.read_only) !== Boolean(task.files[index].read_only) ||
    file.read_only && file.content !== task.files[index].content)) return null;
  const normalized = files as components['schemas']['ProgramFile'][];
  const maxBytes = task.language === 'python_project' ? 100000 : 256000;
  if (normalized.some((file) => file.content.length > 100000) ||
    normalized.reduce((bytes, file) => bytes + new TextEncoder().encode(file.content).length, 0) > maxBytes) return null;
  const type = task.language === 'project_stdio' ? 'stdio' : task.language === 'web_project' ? 'web'
    : task.language === 'http_project' ? 'http' : 'project';
  return { type, files: normalized.map((file) => ({ ...file, read_only: Boolean(file.read_only) })) };
}

export function practiceChanged(binding: PracticeBinding, value: DraftValue) {
  if (binding.source.presentation.type === 'program_practice') {
    const answer = programAnswer(binding, value);
    return !!answer && (!binding.result || 'answer' in binding.result &&
      JSON.stringify(answer) !== JSON.stringify(binding.result.answer));
  }
  if (!binding.result) return true;
  return 'code' in binding.result ? value !== binding.result.code : true;
}

export function restorePracticeDraft(
  definition: { components: { id: string; props: object }[] }, bindings: PracticeBinding[],
  draft: CompositionDraftV2, restored: boolean,
) {
  for (const binding of bindings) {
    const node = definition.components.find((item) => item.id === binding.component_id);
    if (!node || !('state' in node.props) || typeof node.props.state !== 'string' || !binding.result) continue;
    if ('selected_key' in binding.result) draft.values[node.props.state] = [binding.result.selected_key];
    else if ('response' in binding.result) {
      const response = binding.result.response;
      if (response.type === 'multiple') draft.values[node.props.state] = response.selected_ids;
      if (response.type === 'ordering') draft.values[node.props.state] = response.ordered_ids;
      if (response.type === 'short' || response.type === 'prediction') draft.values[node.props.state] = response.text;
      if (response.type === 'line_review') draft.annotations[node.props.state] = {
        saved: Object.fromEntries(response.annotations.map((a) => [a.line, a.reason])), pending: {},
      };
    }
    else if (!restored && 'answer' in binding.result) {
      const answer = binding.result.answer;
      draft.values[node.props.state] = answer.type === 'sql' ? answer.query : answer.files;
    }
    else if (!restored && 'code' in binding.result) draft.values[node.props.state] = binding.result.code;
  }
}

export function practiceCommand(
  intent: CompositionIntentV2, bindings: PracticeBinding[],
): PracticeCommand | null {
  const binding = bindings.find((item) => item.component_id === intent.component_id);
  if (!binding) return null;
  if (binding.source.presentation.type === 'program_practice') {
    if (intent.type !== 'check_code' || !binding.allowed_actions.includes('run')) return null;
    const answer = programAnswer(binding, intent.submission.type === 'code'
      ? intent.submission.code : intent.submission.files);
    return answer ? {
      action: 'run_program_component', component_id: intent.component_id,
      payload: { answer, previous_attempt_id: binding.result?.id ?? null, retry: false },
    } : null;
  }
  if (binding.source.presentation.type === 'knowledge_response' && binding.allowed_actions.includes('respond')) {
    const type = binding.source.presentation.question.response_type;
    const identity = { action: 'answer_component' as const, component_id: intent.component_id };
    if (intent.type === 'submit_answer') {
      const response = intent.response;
      if (response.type === 'text' && (type === 'short' || type === 'prediction') &&
        response.value.trim() && response.value.length <= 4000) {
        return { ...identity, payload: { type, text: response.value } };
      }
      if (response.type === 'choice' && type === 'multiple' && response.value.length) {
        return { ...identity, payload: { type, selected_ids: response.value } };
      }
      if (response.type === 'order' && type === 'ordering') {
        return { ...identity, payload: { type, ordered_ids: response.value } };
      }
    }
    if (intent.type === 'submit_review' && type === 'line_review' &&
      intent.annotations.length > 0 && intent.annotations.length <= 40 &&
      intent.annotations.every((a) => a.reason.trim() && a.reason.length <= 1000)) {
      return { ...identity, payload: { type, annotations: intent.annotations } };
    }
    return null;
  }
  if (intent.type === 'submit_answer' && intent.response.type === 'choice' &&
    intent.response.value.length === 1 && binding.allowed_actions.includes('respond')) {
    const selected = intent.response.value[0];
    if (!['A', 'B', 'C', 'D'].includes(selected)) return null;
    return {
      action: 'respond_component', component_id: intent.component_id,
      payload: { selected_key: selected as 'A' | 'B' | 'C' | 'D' },
    };
  }
  if (intent.type === 'check_code' && intent.submission.type === 'code' &&
    binding.allowed_actions.includes('run')) {
    return {
      action: 'run_component', component_id: intent.component_id, payload: {
        code: intent.submission.code, previous_attempt_id: binding.result?.id ?? null, retry: false,
      },
    };
  }
  return null;
}

export function practiceReceipts(view: PracticeView): CompositionReceiptV2[] {
  return (view.component_bindings ?? []).flatMap((binding): CompositionReceiptV2[] => {
    const result = binding.result;
    if (!result) return [];
    const identity = {
      artifact_id: view.id, content_ref: view.content_ref, component_id: binding.component_id,
      client_action_id: binding.action_id ?? null, result_id: result.id,
    };
    if ('response' in result) {
      const mode = result.response.type;
      if (mode === 'line_review') return [{
        ...identity, type: 'review', findings: result.findings,
        message: `${result.correct ? '定位与参考一致' : '定位与参考不同'}；批注理由未自动评判。${result.explanation}`,
      }];
      return [{
        ...identity, type: 'answer', correct: result.correct,
        message: `${mode === 'short' ? '已保存回答，未自动判分。' : ''}${result.explanation}`,
      }];
    }
    if ('correct' in result) return [{
      ...identity, type: 'answer', correct: result.correct, message: result.explanation,
    }];
    if (result.status === 'queued') return [];
    if ('answer' in result) {
      const sample = result.sample_result?.output;
      const integer = result.sample_result?.integer_text;
      const text = result.sample_result?.text_output;
      const table = typeof sample === 'object' && sample !== null && 'columns' in sample ? sample : null;
      const web = typeof sample === 'object' && sample !== null && 'results' in sample ? sample : null;
      const http = typeof sample === 'object' && sample !== null && 'responses' in sample ? sample : null;
      return [{
        ...identity, type: 'code', attempt_id: result.id,
        submission: result.answer.type === 'sql' ? { type: 'code', code: result.answer.query }
          : { type: 'files', files: result.answer.files },
        message: `${result.feedback ?? result.status}${result.status === 'error' ? '' : ` 通过用例 ${result.passed_cases}/3。`}`,
        columns: table ? table.columns : web ? ['公开检查', '实际观察'] : http ? ['状态码', '实际响应']
          : text != null || integer != null || typeof sample === 'number' ? ['公开样例的实际输出'] : [],
        rows: table ? table.rows.map((row, index) => row.map((cell, column) =>
          cell === null ? 'NULL' : table.types[index][column] === 'text' ? JSON.stringify(cell) : cell))
          : web ? web.results.map((item) => [item.key, item.actual === null ? '未返回' : String(item.actual)])
            : http ? http.responses.map((item) => [String(item.status), item.body])
              : text != null ? [[text]] : integer != null ? [[integer]]
              : typeof sample === 'number' ? [[String(sample)]] : [],
      }];
    }
    return [{
      ...identity, type: 'code', attempt_id: result.id,
      submission: { type: 'code', code: result.code },
      message: result.feedback ?? result.status,
      columns: result.status === 'error' ? [] : ['通过用例', '总用例'],
      rows: result.status === 'error' ? [] : [[String(result.passed_cases), String(result.total_cases)]],
    }];
  });
}

export function submittedReviewReceipts(view: PracticeView): CompositionReceiptV2[] {
  return (view.review_bindings ?? []).map((binding) => ({
    artifact_id: view.id, content_ref: view.content_ref, component_id: binding.component_id,
    client_action_id: null, result_id: view.content_ref.id,
    type: 'review', findings: binding.findings,
    message: '已检查的教学批注，不是新的评测结果。',
  }));
}
