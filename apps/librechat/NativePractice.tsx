import { useEffect, useState } from 'react';
import { RotateCcw, Square } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import * as UI from './LearningComponents';
import { nativeRequest } from './native-client.mjs';
import { executableCode } from './composition-v2-runtime.mjs';
import type { PracticeBinding, PracticeCommand } from './native-practice';
import { NativeProgramHistory, NativeProgramProgress, NativeProgramPrompt, NativeProgramSample } from './NativeProgramPractice';
import type { CompositionDraftV2 } from './LearningCompositionV2';
import { NativeAssistance } from './NativeAssistance';

type History = components['schemas']['PythonPracticeHistory'];
const attemptStatus = {
  queued: '等待评测', passed: '本次通过', not_passed: '本次未通过', error: '本次未完成',
};

export function NativePracticeSample({ binding }: { binding: PracticeBinding }) {
  const presentation = binding.source.presentation;
  if (presentation.type === 'program_practice') return <NativeProgramSample task={presentation.task} />;
  return presentation.type === 'code_workspace' ? <UI.DataTable label="公开样例，不代替完整评测"
    columns={['输入', '样例输出']}
    rows={[[JSON.stringify(presentation.task.sample.input), String(presentation.task.sample.expected)]]} /> : null;
}

export function NativePracticeAttempts({ binding }: { binding: PracticeBinding }) {
  const history = binding.attempts;
  if (!history || !('attempts' in history ? history.attempts : history.items).length && !history.next_before) {
    return <p className="demo-muted">尚无运行记录；明确运行后保留每次提交和原始结果。</p>;
  }
  return 'attempts' in history
    ? <NativeProgramHistory binding={binding} initial={history} />
    : <NativePracticeHistory binding={binding} initial={history} />;
}

export function NativePracticePrompt({ binding, showSample = true, practiceOnly = false }: {
  binding: PracticeBinding; showSample?: boolean; practiceOnly?: boolean;
}) {
  const presentation = binding.source.presentation;
  if (presentation.type === 'program_practice') return <NativeProgramPrompt task={presentation.task} showSample={showSample} />;
  return <>
    <UI.Explanation title={presentation.type === 'code_workspace' ? binding.source.title : undefined}><p>{presentation.type === 'code_workspace'
      ? presentation.task.prompt : presentation.question.prompt}</p></UI.Explanation>
    {presentation.type === 'knowledge_response' && <>
      {presentation.question.response_type === 'prediction' && <>
        <UI.CodeBlock label="预测这段代码的输出；此处不执行">{presentation.question.code}</UI.CodeBlock>
        <p className="demo-muted">按行对照；统一换行，忽略行尾空白和末尾空行，不忽略行内空白。</p>
      </>}
      {!practiceOnly && presentation.question.response_type === 'short' &&
        <p className="demo-muted">提交后锁定本次回答并显示参考，不自动判分。</p>}
      {!practiceOnly && presentation.question.response_type === 'line_review' &&
        <p className="demo-muted">保存批注后提交整份审查；仅对照代码行位置，理由不自动评分。</p>}
    </>}
    {showSample && <NativePracticeSample binding={binding} />}
  </>;
}

export function NativePracticeProgress({ binding, code, value, blocked, onCommand, showHistory = true }: {
  binding: PracticeBinding; code: string; blocked: boolean; onCommand: (command: PracticeCommand) => void;
  value?: CompositionDraftV2['values'][string]; showHistory?: boolean;
}) {
  const result = binding.result;
  if (binding.source.presentation.type === 'program_practice') return <NativeProgramProgress
    binding={binding} value={value ?? code} blocked={blocked} onCommand={onCommand} showHistory={showHistory} />;
  if (binding.source.kind === 'knowledge_response') {
    if (binding.source.presentation.question.response_type === 'prediction' &&
      binding.allowed_actions.includes('respond') && code === '') return <UI.ActionGroup>
      <Action disabled={blocked} onClick={() => onCommand({
        action: 'answer_component', component_id: binding.component_id,
        payload: { type: 'prediction', text: '' },
      })}>确认没有输出</Action>
    </UI.ActionGroup>;
    if (code.length > 4000 && binding.source.presentation.question.response_type !== 'line_review') {
      return <Notice>回答超过 4000 字符；草稿保留，请缩短后提交。</Notice>;
    }
    if (!result || !('response' in result)) return null;
    const reference = result.reference;
    return <>
      {result.response.type === 'line_review' && <Notice>
        {result.correct ? '定位与参考一致' : '定位与参考不同'}；批注理由未自动评判。{result.explanation}
      </Notice>}
      {(reference.type === 'short' || reference.type === 'prediction') &&
        <Disclosure title={reference.type === 'short' ? '查看参考回答（未自动判分）' : '查看参考输出'}>
          {reference.type === 'prediction' ? <UI.CodeBlock label="参考输出">{reference.text}</UI.CodeBlock>
            : <p>{reference.text}</p>}
        </Disclosure>}
    </>;
  }
  if (binding.source.kind !== 'code_workspace' || !result || !('code' in result)) return null;
  const unchanged = code === result.code;
  return <>
    {result.status === 'queued' && <Notice>第 {result.attempt_number} 次尝试已接收，等待本机 Runner 的结果。</Notice>}
    {binding.allowed_actions.includes('cancel_run') && <UI.ActionGroup>
      <Action icon={Square} disabled={blocked} onClick={() => onCommand({
        action: 'cancel_component_run', component_id: binding.component_id, expected_attempt_id: result.id,
      })}>取消本次运行</Action>
    </UI.ActionGroup>}
    {unchanged && binding.allowed_actions.includes('retry') && <UI.ActionGroup>
      <Action icon={RotateCcw} disabled={blocked || !executableCode(code)} onClick={() => onCommand({
        action: 'run_component', component_id: binding.component_id,
        payload: { code, previous_attempt_id: result.id, retry: true },
      })}>重试同一份代码</Action>
    </UI.ActionGroup>}
    {unchanged && result.status !== 'queued' && binding.allowed_actions.includes('run') &&
      <p className="demo-muted">{result.status === 'error' ? '可修改代码提交；原代码重试需使用明确的重试按钮。'
        : '修改代码后可提交新尝试；之前的代码和评分保留，不代表通过正式考核。'}</p>}
    {showHistory && binding.attempts && 'items' in binding.attempts &&
      <NativePracticeHistory binding={binding} initial={binding.attempts} />}
  </>;
}

export function NativePracticeRecord({ binding }: { binding: PracticeBinding }) {
  const result = binding.result;
  return <>
    {!!result && 'correct' in result && <Disclosure title="原作答与反馈">
      {'selected_key' in result ? <p>原选择：{result.selected_key}</p> : <p>
        {result.response.type === 'line_review' ? result.response.annotations.map((note) =>
          `第 ${note.line} 行：${note.reason}`).join('；') : 'text' in result.response ? result.response.text :
          'selected_ids' in result.response ? result.response.selected_ids.join('、') : result.response.ordered_ids.join(' → ')}
      </p>}
      <UI.AnswerFeedback kind={result.correct === null ? 'reference' : result.correct ? 'correct' : 'incorrect'}>
        {result.explanation}
      </UI.AnswerFeedback>
      {'response' in result && <NativePracticeProgress binding={binding} code="" blocked onCommand={() => {}} />}
      {'findings' in result && result.findings.length > 0 && <ul>{result.findings.map((finding) =>
        <li key={finding.line}>第 {finding.line} 行：{finding.content}</li>)}</ul>}
    </Disclosure>}
    {(binding.assistance_receipt || !!binding.hint_receipts?.length) &&
      <NativeAssistance binding={binding} blocked onCommand={() => {}} />}
  </>;
}

function NativePracticeHistory({ binding, initial }: { binding: PracticeBinding; initial: History }) {
  const [older, setOlder] = useState<History['items']>([]);
  const [next, setNext] = useState(initial.next_before);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    setOlder([]); setNext(initial.next_before); setError('');
  }, [initial.latest_attempt_id]);
  const items = [...initial.items, ...older].filter((item, index, all) =>
    all.findIndex((other) => other.id === item.id) === index);
  return <Disclosure title="练习历史">
    {items.map((attempt) => <Disclosure key={attempt.id}
      title={`第 ${attempt.attempt_number} 次 · ${attemptStatus[attempt.status]}`}>
      <p><time dateTime={attempt.created_at}>{new Date(attempt.created_at).toLocaleString('zh-CN')}</time>
        {attempt.retry_requested ? ' · 明确重试' : ''}</p>
      {attempt.feedback && <p>{attempt.feedback}</p>}
      {['passed', 'not_passed'].includes(attempt.status) && <p>通过用例 {attempt.passed_cases}/{attempt.total_cases}</p>}
      <UI.CodeBlock label="这次提交的代码">{attempt.code}</UI.CodeBlock>
    </Disclosure>)}
    {next && <Action busy={busy} onClick={() => {
      setBusy(true); setError('');
      const ref = binding.source.content_ref;
      void nativeRequest(`/v2/packs/${ref.id}/execution-practice-attempts?slot=${ref.slot}&before=${next}&limit=20`)
        .then((page: History) => { setOlder((rows) => [...rows, ...page.items]); setNext(page.next_before); })
        .catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
    }}>读取更早尝试</Action>}
    {error && <Notice>{error}</Notice>}
  </Disclosure>;
}
