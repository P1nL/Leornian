import { useEffect, useState } from 'react';
import { Copy, RotateCcw, Square } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import * as UI from './LearningComponents';
import { nativeRequest } from './native-client.mjs';
import { practiceChanged, programAnswer } from './native-practice';
import type { PracticeBinding, PracticeCommand } from './native-practice';
import type { CompositionDraftV2 } from './LearningCompositionV2';

type Task = components['schemas']['ProgramCandidatePresentation']['task'];
type History = components['schemas']['ProgramPracticeHistory'];
type Attempt = components['schemas']['ProgramPracticeAttempt'];
const statuses = { queued: '等待评测', passed: '本次通过', not_passed: '本次未通过', error: '本次未完成' };
const cells = (table: components['schemas']['SqlTableResult']) => table.rows.map((row, index) =>
  row.map((cell, column) => cell === null ? 'NULL' : table.types[index][column] === 'text' ? JSON.stringify(cell) : cell));
const environmentLabel = (environment: Task['environment']) =>
  environment.profile === 'sql-query.v1' ? `${environment.dialect} ${environment.runtime_version}`
    : environment.profile === 'python-project-io.v1' ? `Python 多文件 ${environment.runtime_version}`
      : `${environment.language} ${environment.runtime_version} · 环境发布 ${environment.environment_release_id}`;

export function NativeProgramLanguage({ task }: { task: Task }) {
  const environment = task.environment;
  const language = environment.profile === 'sql-query.v1' ? environment.dialect
    : environment.profile === 'python-project-io.v1' ? 'Python' : environment.language;
  return <span title={environmentLabel(environment)}>{language} {environment.runtime_version}</span>;
}

export function NativeProgramSample({ task }: { task: Task }) {
  return task.language === 'sql_query'
    ? <Disclosure title="公开样例的参考结果（不是本次查询输出）">
      <UI.DataTable label="公开参考" columns={task.sample.expected.columns} rows={cells(task.sample.expected)} />
    </Disclosure>
    : task.language === 'web_project'
      ? <UI.DataTable label="公开浏览器检查，不代替完整评测" columns={['检查', '参考观察']}
        rows={[[JSON.stringify(task.sample.check), String(task.sample.expected)]]} />
      : task.language === 'http_project'
        ? <UI.DataTable label="公开 HTTP 场景" columns={['请求', '参考响应']}
          rows={task.sample.scenario.requests.map((request, index) => [
            `${request.method ?? 'GET'} ${request.path}${request.body ? `\n${request.body}` : ''}`,
            `${task.sample.expected[index].status}\n${task.sample.expected[index].body}`,
          ])} />
      : <UI.DataTable label="公开样例，不代替完整评测" columns={['输入', '参考输出']}
        rows={[[typeof task.sample.input === 'string' ? task.sample.input : JSON.stringify(task.sample.input), String(task.sample.expected)]]} />;
}

export function NativeProgramPrompt({ task, purpose = 'practice', showSample = true }: {
  task: Task; purpose?: 'practice' | 'assessment' | 'transfer'; showSample?: boolean;
}) {
  const [copyError, setCopyError] = useState('');
  return <>
    <UI.Explanation title={task.title}><p>{task.prompt}</p></UI.Explanation>
    <p className="demo-muted">固定环境：{environmentLabel(task.environment)}；{purpose === 'practice'
      ? '显式运行才创建尝试，普通练习不更新正式进度。' : purpose === 'assessment'
        ? '明确提交整组答案后，进入正式独立评测。' : '提交后检查本次新情境应用，原补救记录保留。'}</p>
    {task.language === 'sql_query' ? <>
      <p className="demo-muted">{task.comparison === 'ordered' ? '结果按行序比较' : '结果忽略行序，保留重复次数'}；列名、列序、类型和 NULL 都参与对照。</p>
      <Disclosure title="表结构与公开样例数据">
        {task.schema_definition.tables.map((table) => <div key={table.name}>
          <UI.DataTable label={table.name} columns={['列名', '类型', '约束']} rows={table.columns.map((column) => [
            column.name, column.type, [column.primary_key ? '主键' : '', (column.nullable ?? true) ? '允许 NULL' : '非空'].filter(Boolean).join(' · '),
          ])} />
          <UI.ActionGroup><Action icon={Copy} onClick={() => {
            setCopyError('');
            if (!navigator.clipboard) { setCopyError('复制未完成；可以手动选择表名。'); return; }
            void navigator.clipboard.writeText(table.name).catch(() => setCopyError('复制未完成；可以手动选择表名。'));
          }}>复制表名 {table.name}</Action></UI.ActionGroup>
          {!!table.foreign_keys?.length && <p>{table.foreign_keys.map((key) =>
            `${key.column} → ${key.references_table}.${key.references_column}`).join('；')}</p>}
          <UI.DataTable label={`${table.name} 的公开样例数据`} columns={table.columns.map((column) => column.name)}
            rows={task.sample.dataset.rows[table.name].map((row) => row.map((value) => JSON.stringify(value)))} />
        </div>)}
        {copyError && <Notice>{copyError}</Notice>}
      </Disclosure>
    </> : task.language === 'project_stdio'
      ? <p className="demo-muted">标准输出按文本比较，仅统一换行符并忽略末尾换行，空格与正文保留。</p>
      : task.language === 'http_project' &&
        <p className="demo-muted">每个场景使用独立服务{task.database ? `和 ${task.database.dialect} 测试数据库` : ''}，请求按顺序执行；按状态码和响应正文检查，JSON 正文按结构比较。</p>}
    {showSample && <NativeProgramSample task={task} />}
  </>;
}

export function NativeCompilation({ result }: { result: components['schemas']['CaseOutput'] | null | undefined }) {
  if (!result) return null;
  const passed = result.outcome === 'completed' && result.exit_code === 0;
  const status = passed ? '编译通过' : result.outcome === 'completed' ? '编译未通过' : '编译未完成';
  return <section className="space-y-2" aria-label="独立编译回执">
    <p role="status">{status} · {result.outcome} · 退出码 {result.exit_code ?? '无'}</p>
    {!passed && <Notice>本次未执行样例和评测用例。</Notice>}
    {result.stdout !== '' && <UI.CodeBlock label="编译标准输出">{result.stdout}</UI.CodeBlock>}
    {result.stderr !== '' && <UI.CodeBlock label="编译标准错误">{result.stderr}</UI.CodeBlock>}
  </section>;
}

function ProgramSubmission({ attempt }: { attempt: Attempt }) {
  return attempt.answer.type === 'sql'
    ? <UI.CodeBlock label="这次提交的查询">{attempt.answer.query}</UI.CodeBlock>
    : <>{attempt.answer.files.map((file) => <Disclosure key={file.path}
      title={`${file.path}${file.read_only ? ' · 受保护' : ''}`}>
      <UI.CodeBlock label={file.path}>{file.content}</UI.CodeBlock>
    </Disclosure>)}</>;
}

export function NativeProgramProgress({ binding, value, blocked, onCommand, showHistory = true }: {
  binding: PracticeBinding; value: CompositionDraftV2['values'][string]; blocked: boolean;
  onCommand: (command: PracticeCommand) => void; showHistory?: boolean;
}) {
  const result = binding.result;
  const answer = programAnswer(binding, value);
  if (!result || !('answer' in result)) return answer ? null : <Notice>
    查询须在 12000 UTF-8 字节内；项目须保留完整文件清单与受保护内容，Python旧项目限100KB，语言项目与网页项目限256KB。
  </Notice>;
  const unchanged = !practiceChanged(binding, value);
  return <>
    {result.status === 'queued' && <Notice>第 {result.attempt_number} 次尝试已接收，等待固定环境的实际执行回执。</Notice>}
    {binding.allowed_actions.includes('cancel_run') && <UI.ActionGroup>
      <Action icon={Square} disabled={blocked} onClick={() => onCommand({
        action: 'cancel_component_run', component_id: binding.component_id, expected_attempt_id: result.id,
      })}>取消本次运行</Action>
    </UI.ActionGroup>}
    {unchanged && answer && binding.allowed_actions.includes('retry') && <UI.ActionGroup>
      <Action icon={RotateCcw} disabled={blocked} onClick={() => onCommand({
        action: 'run_program_component', component_id: binding.component_id,
        payload: { answer, previous_attempt_id: result.id, retry: true },
      })}>明确重试同一份提交</Action>
    </UI.ActionGroup>}
    {!answer && <Notice>草稿超出查询/文件限制，或固定清单、受保护内容已变化；修正后才能提交。</Notice>}
    {unchanged && result.status !== 'queued' && <p className="demo-muted">
      {result.status === 'error' ? '本次未生成能力结论；可修改后提交，或明确重试。' : '修改后可创建新尝试；原提交和成绩保留，不代表通过正式考核。'}
    </p>}
    <NativeCompilation result={result.compilation} />
    {result.sample_result && <p className="demo-muted">
      结果表仅含公开样例的实际输出；其余测试数据和输出不公开。
      {result.sample_result.output === null && result.sample_result.integer_text == null &&
        result.sample_result.text_output == null &&
        ` 样例未产生有效结果（${result.sample_result.outcome}）。`}
      {typeof result.sample_result.output === 'object' && result.sample_result.output !== null &&
        'rows' in result.sample_result.output && result.sample_result.output.rows.length === 0 &&
        ' 本次查询返回 0 行。'}
    </p>}
    {showHistory && binding.attempts && 'attempts' in binding.attempts &&
      <NativeProgramHistory binding={binding} initial={binding.attempts} />}
  </>;
}

export function NativeProgramHistory({ binding, initial }: { binding: PracticeBinding; initial: History }) {
  const [older, setOlder] = useState<Attempt[]>([]), [next, setNext] = useState(initial.next_before);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { setOlder([]); setNext(initial.next_before); setError(''); }, [initial.latest_attempt_id]);
  const attempts = [...initial.attempts, ...older].filter((item, index, all) =>
    all.findIndex((other) => other.id === item.id) === index);
  return <Disclosure title="练习历史">
    {attempts.map((attempt) => <Disclosure key={attempt.id}
      title={`第 ${attempt.attempt_number} 次 · ${statuses[attempt.status]}`}>
      <p><time dateTime={attempt.created_at}>{new Date(attempt.created_at).toLocaleString('zh-CN')}</time>
        {attempt.retry_requested ? ' · 明确重试' : ''}</p>
      <p>{environmentLabel(attempt.environment)}</p>
      {attempt.feedback && <p>{attempt.feedback}</p>}
      <NativeCompilation result={attempt.compilation} />
      {['passed', 'not_passed'].includes(attempt.status) && <p>通过用例 {attempt.passed_cases}/3</p>}
      <ProgramSubmission attempt={attempt} />
    </Disclosure>)}
    {next && <Action busy={busy} onClick={() => {
      setBusy(true); setError('');
      const ref = binding.source.content_ref;
      void nativeRequest(`/v2/packs/${ref.id}/program-practice-attempts?slot=${ref.slot}&before=${next}&limit=20`)
        .then((page: History) => { setOlder((rows) => [...rows, ...page.attempts]); setNext(page.next_before); })
        .catch((problem: Error) => setError(problem.message)).finally(() => setBusy(false));
    }}>读取更早尝试</Action>}
    {error && <Notice>{error}</Notice>}
  </Disclosure>;
}
