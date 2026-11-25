import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { NativeArtifacts } from './NativeLearning';
import { practiceChanged, practiceCommand, practiceReceipts, programAnswer } from './native-practice';

const native = vi.hoisted(() => ({
  state: { snapshot: { actor: { id: 'program-owner' }, turns: [] }, epoch: 0, pending: [], reader: null },
  request: vi.fn(), write: vi.fn(),
}));
vi.mock('./native-client.mjs', async (original) => ({
  ...await original<typeof import('./native-client.mjs')>(),
  nativeRequest: native.request,
  nativeStore: { subscribe: () => () => {}, getSnapshot: () => native.state, write: native.write, refresh: vi.fn() },
}));
vi.mock('react-router-dom', () => ({ useParams: () => ({ conversationId: 'program-conversation' }), useNavigate: () => vi.fn() }));
beforeEach(() => { sessionStorage.clear(); native.write.mockReset().mockResolvedValue({}); native.state.epoch = 0; });
afterEach(cleanup);

const files = [
  { path: 'src/main.py', content: 'from helpers import calculate\nprint(calculate([]))', read_only: true },
  { path: 'src/helpers.py', content: 'def calculate(xs):\n    return 0', read_only: false },
];
const table = (value: string) => ({ profile: 'sql-table.v1', columns: ['answer'], rows: [[value]], types: [['integer']] });

function programView(project = false, result: any = null) {
  const environment = project ? { profile: 'python-project-io.v1', runtime_version: '3.12.14' }
    : { profile: 'sql-query.v1', dialect: 'sqlite', runtime_version: '3.46.1' };
  const task = {
    title: project ? '原多文件任务' : '原 SQL 任务', prompt: '执行明确提交；不自动运行。',
    environment, ...(project ? {
      language: 'python_project', files, entrypoint: 'src/main.py', sample: { input: [1, 2], expected: 3 },
    } : {
      language: 'sql_query', starter_query: 'SELECT 0 AS answer', comparison: 'ordered',
      schema_definition: { tables: [{ name: 'records', columns: [{ name: 'n', type: 'integer', nullable: false }] }] },
      sample: { dataset: { rows: { records: [[1], [2]] } }, expected: table('3') },
    }),
  };
  return {
    schema_version: 'learning_artifact.v2', id: 'program-artifact', conversation_id: 'program-conversation',
    source_turn_id: 'program-turn', kind: 'learning_composition', title: '原所有者练习',
    revision: 7, state: result ? result.status === 'queued' ? 'running' : 'completed' : 'ready',
    allowed_actions: ['cancel'], content_ref: { owner: 'tutor', id: 'program-presentation', revision: 1, public_identity: 'exact' },
    presentation: { type: 'learning_composition', definition: {
      schema_version: 'learning_composition.v2', title: '原所有者练习',
      states: { editor: project ? { type: 'files', files } : { type: 'code', value: 'SELECT 0 AS answer' } },
      components: [
        { id: 'editor', component: 'CodeEditor', props: { label: project ? '文件' : '查询', state: 'editor' } },
        { id: 'run', component: 'ArtifactAction', props: { label: '运行查询或项目', event: 'check_code', for_component: 'editor' } },
        { id: 'result', component: 'ResultFeedback', props: { label: '原评测结果', for_component: 'editor' } },
      ],
    } },
    component_bindings: [{
      component_id: 'editor', state: result?.status === 'queued' ? 'running' : result ? 'completed' : 'ready',
      result, action_id: null, source: {
        id: 'program-source', kind: project ? 'project_workspace' : 'sql_workspace', title: task.title,
        content_ref: { owner: 'item_bank', id: 'program-pack', slot: 'practice_1', revision: 1, public_identity: 'task-identity' },
        presentation: { type: 'program_practice', task },
      },
      allowed_actions: result?.status === 'queued' ? ['cancel_run'] : result?.status === 'error' ? ['run', 'retry'] : ['run'],
      attempts: { latest_attempt_id: result?.id ?? null, attempts: result ? [result] : [], next_before: null },
    }],
  };
}
function show(view: ReturnType<typeof programView>) {
  native.request.mockReset().mockImplementation(async (path: string) =>
    path.split('?')[0].endsWith('/program-artifact') ? view : [view]);
  return render(<NativeArtifacts messageId="program-turn:assistant" />);
}
function attempt(project = false, status = 'not_passed') {
  return {
    id: 'program-attempt', status, attempt_number: 2, previous_attempt_id: 'previous-program-attempt',
    retry_requested: false, environment: programView(project).component_bindings[0].source.presentation.task.environment,
    answer: project ? { type: 'project', files } : { type: 'sql', query: 'SELECT SUM(n)+40 AS answer FROM records' },
    feedback: '实际回执，不是模型结果。', passed_cases: 0, created_at: '2026-11-06T01:00:00Z',
    sample_result: { profile: 'program-public-sample.v1', outcome: 'completed', exit_code: 0, output: project ? 43 : table('43') },
  };
}

test.each([false, true])('original %s program owner uses the existing tabbed workbench without an implicit run', async (project) => {
  show(programView(project));
  const editor = await screen.findByRole('textbox', { name: project ? 'src/main.py' : '查询' });
  const workbench = editor.closest('.demo-workbench') as HTMLElement;
  expect(workbench).toBeTruthy();
  expect(within(workbench).getByRole('region', { name: '题目与学习工具' })).toBeTruthy();
  expect(within(workbench).getByRole('region', { name: '测试用例与运行结果' })).toBeTruthy();
  expect(within(workbench).getByRole('tab', { name: '测试用例' }).getAttribute('aria-selected')).toBe('true');
  expect(within(workbench).getAllByRole('button', { name: '运行查询或项目' })).toHaveLength(1);
  expect(within(workbench).getByRole('button', { name: '运行查询或项目' }).closest('.demo-workbench-runbar')).toBeTruthy();
  expect(within(workbench).getByRole('button', { name: '放大代码工作台' })).toBeTruthy();
  expect(within(workbench).getAllByRole('textbox', { hidden: true })).toHaveLength(project ? 2 : 1);
  fireEvent.click(within(workbench).getByRole('tab', { name: '运行记录' }));
  expect(within(workbench).getByRole('tabpanel', { name: '运行记录' }).textContent).toContain('尚无运行记录');
  expect(native.write).not.toHaveBeenCalled();
});

test('SQL uses negotiated reading and explicit typed query submission, while copying never runs', async () => {
  show(programView());
  const editor = await screen.findByRole('textbox', { name: '查询' });
  expect(native.request.mock.calls.some(([path]) => path.includes('program_capability=learning_programs.v2'))).toBe(true);
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('表结构与公开样例数据'));
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
  fireEvent.click(screen.getByRole('button', { name: '复制表名 records' }));
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith('records');
  expect((editor as HTMLTextAreaElement).value).toBe('SELECT 0 AS answer');
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.change(editor, { target: { value: 'SELECT SUM(n) AS answer FROM records' } });
  fireEvent.click(screen.getByRole('button', { name: '运行查询或项目' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'run_program_component', component_id: 'editor', expected_artifact_revision: 7,
    payload: { answer: { type: 'sql', query: 'SELECT SUM(n) AS answer FROM records' }, previous_attempt_id: null, retry: false },
  });
  expect(native.write.mock.calls[0][1].payload).not.toHaveProperty('code');
  const binding = programView().component_bindings[0] as any;
  expect(programAnswer(binding, '中'.repeat(4001))).toBeNull();
  expect(practiceChanged(binding, '中'.repeat(4001))).toBe(false);
});

test('actual SQL sample is separate from reference and refresh preserves a changed draft without resubmission', async () => {
  const view = programView(false, attempt());
  const shown = show(view);
  const editor = await screen.findByRole('textbox', { name: '查询' });
  expect(screen.getByText('43')).toBeTruthy();
  expect(screen.getByText(/仅含公开样例的实际输出/)).toBeTruthy();
  fireEvent.click(screen.getByText('公开样例的参考结果（不是本次查询输出）'));
  expect(screen.getByText('3')).toBeTruthy();
  fireEvent.change(editor, { target: { value: 'SELECT 17 AS answer' } });
  shown.unmount();
  show(view);
  expect((await screen.findByRole('textbox', { name: '查询' }) as HTMLTextAreaElement).value).toBe('SELECT 17 AS answer');
  expect(native.write).not.toHaveBeenCalled();
  expect(practiceReceipts(view as any)[0]).toMatchObject({
    submission: { type: 'code', code: attempt().answer.query }, rows: [['43']],
  });
});

test('multifile submits exact editable files and retains protected contents across reload', async () => {
  const view = programView(true);
  const shown = show(view);
  expect((await screen.findByRole('textbox', { name: 'src/main.py' }) as HTMLTextAreaElement).readOnly).toBe(true);
  fireEvent.click(screen.getByRole('tab', { name: 'src/helpers.py' }));
  const editor = screen.getByRole('textbox', { name: 'src/helpers.py' });
  fireEvent.change(editor, { target: { value: 'def calculate(xs):\n    return sum(xs)' } });
  shown.unmount();
  show(view);
  expect((await screen.findByRole('textbox', { name: 'src/helpers.py' }) as HTMLTextAreaElement).value).toContain('return sum(xs)');
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '运行查询或项目' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  const answer = native.write.mock.calls[0][1].payload.answer;
  expect(answer.type).toBe('project');
  expect(answer.files[0]).toEqual(files[0]);
  expect(answer.files[1].content).toContain('return sum(xs)');
  const binding = view.component_bindings[0] as any;
  expect(programAnswer(binding, [{ ...files[0], content: 'print(999)' }, files[1]])).toBeNull();
  expect(practiceCommand({ type: 'check_code', component_id: 'editor', submission: { type: 'code', code: 'print(0)' } }, [binding])).toBeNull();
});

test('queued program only cancels the exact attempt; errored same-query retry is explicit', async () => {
  const queued = programView(false, attempt(false, 'queued'));
  const shown = show(queued);
  await screen.findByRole('button', { name: '取消本次运行' });
  expect((screen.getByRole('textbox', { name: '查询' }) as HTMLTextAreaElement).readOnly).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '取消本次运行' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'cancel_component_run', expected_attempt_id: 'program-attempt',
  });
  shown.unmount(); native.write.mockClear();
  show(programView(false, { ...attempt(false, 'error'), sample_result: null }));
  await screen.findByRole('button', { name: '明确重试同一份提交' });
  expect(native.write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '明确重试同一份提交' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1]).toMatchObject({
    action: 'run_program_component', payload: { previous_attempt_id: 'program-attempt', retry: true },
  });
});

test('project actual output uses exact integer text rather than rounded JavaScript numbers', () => {
  const value = '1' + '0'.repeat(99) + '3';
  const result = { ...attempt(true), sample_result: {
    profile: 'program-public-sample.v1', outcome: 'completed', exit_code: 0,
    output: null, integer_text: value,
  } };
  const receipt = practiceReceipts(programView(true, result) as any)[0];
  expect(receipt).toMatchObject({ columns: ['公开样例的实际输出'], rows: [[value]] });
});

function extendedProjectView(language: string, web = false, result: any = null) {
  const view = programView(true, result) as any;
  const manifest = web ? [
    { path: 'index.html', content: '<button id="run">Start</button>', read_only: false },
    { path: 'base.css', content: 'button { display: block; }', read_only: true },
  ] : [
    { path: language === 'java' ? 'Main.java' : language === 'go' ? 'main.go'
      : language === 'csharp' ? 'Program.cs' : language === 'python' ? 'main.py'
        : language === 'typescript' ? 'main.ts' : 'main.js',
    content: 'editable starter', read_only: false },
  ];
  view.presentation.definition.states.editor = { type: 'files', files: manifest };
  const task = view.component_bindings[0].source.presentation.task;
  task.language = web ? 'web_project' : 'project_stdio';
  task.environment = {
    profile: web ? 'web-check.v1' : 'project-stdio.v1', language: web ? 'html-css' : language,
    runtime_version: '1.0.0', environment_release_id: 'fixed-local-release',
  };
  task.files = manifest; task.entrypoint = manifest[0].path;
  task.sample = web ? { check: { key: 'label', kind: 'text', selector: '#run' }, expected: 'Start' }
    : { input: '2 3\n', expected: '5\n' };
  return view;
}

test.each(['python', 'javascript', 'typescript', 'java', 'go', 'csharp'])(
  '%s project uses its exact local release and stdio owner answer instead of the legacy Python tag',
  async (language) => {
    const view = extendedProjectView(language);
    show(view);
    const path = view.component_bindings[0].source.presentation.task.files[0].path;
    const editor = await screen.findByRole('textbox', { name: path });
    expect(screen.getByText(/环境发布 fixed-local-release/)).toBeTruthy();
    expect(native.write).not.toHaveBeenCalled();
    fireEvent.change(editor, { target: { value: 'actual edited source' } });
    fireEvent.click(screen.getByRole('button', { name: '运行查询或项目' }));
    await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
    expect(native.write.mock.calls[0][1].payload.answer).toEqual({
      type: 'stdio', files: [{ path, content: 'actual edited source', read_only: false }],
    });
  },
);

test('web project submits exact files and displays only public browser observations', async () => {
  const view = extendedProjectView('html-css', true);
  show(view);
  await screen.findByRole('textbox', { name: 'index.html' });
  fireEvent.click(screen.getByRole('tab', { name: 'base.css' }));
  expect((screen.getByRole('textbox', { name: 'base.css' }) as HTMLTextAreaElement).readOnly).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '运行查询或项目' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1].payload.answer.type).toBe('web');
  const binding = view.component_bindings[0];
  const manifest = binding.source.presentation.task.files;
  expect(programAnswer(binding, [{ ...manifest[0] }, { ...manifest[1], content: 'tampered' }])).toBeNull();
  binding.result = {
    ...attempt(true), answer: { type: 'web', files: manifest },
    sample_result: { profile: 'program-public-sample.v1', outcome: 'completed', exit_code: 0,
      output: { protocol: 'web-check-result.v1', results: [{ key: 'label', actual: '' }, { key: 'exists', actual: false }] } },
  };
  const receipt = practiceReceipts(view)[0];
  expect(receipt).toMatchObject({ columns: ['公开检查', '实际观察'], rows: [['label', ''], ['exists', 'false']] });
});

test('stdio public sample keeps raw whitespace and empty output without SQL-table assumptions', () => {
  const view = extendedProjectView('javascript');
  const binding = view.component_bindings[0];
  binding.result = {
    ...attempt(true), answer: { type: 'stdio', files: binding.source.presentation.task.files },
    sample_result: { profile: 'program-public-sample.v1', outcome: 'completed', exit_code: 0,
      output: null, text_output: '  five \n' },
  };
  expect(practiceReceipts(view)[0]).toMatchObject({ rows: [['  five \n']] });
  binding.result.sample_result.text_output = '';
  expect(practiceReceipts(view)[0]).toMatchObject({ rows: [['']] });
});

test('HTTP project submits the declared files and displays public responses', async () => {
  const view = extendedProjectView('python');
  const binding = view.component_bindings[0];
  const task = binding.source.presentation.task;
  task.language = 'http_project';
  task.environment.profile = 'project-http.v1';
  task.database = { dialect: 'sqlite' };
  task.sample = {
    scenario: { requests: [{ method: 'POST', path: '/items', body: '{"value":"book"}' }] },
    expected: [{ status: 201, body: '{"id":1}' }],
  };
  show(view);
  await screen.findByRole('textbox', { name: 'main.py' });
  expect(screen.getByText(/每个场景使用独立服务和 sqlite 测试数据库/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '运行查询或项目' }));
  await waitFor(() => expect(native.write).toHaveBeenCalledTimes(1));
  expect(native.write.mock.calls[0][1].payload.answer.type).toBe('http');
  binding.result = {
    ...attempt(true), answer: { type: 'http', files: task.files },
    sample_result: { profile: 'program-public-sample.v1', outcome: 'completed', exit_code: 0,
      output: { protocol: 'http-scenario-result.v1', responses: [{ status: 201, body: '{"id":1}' }] } },
  };
  expect(practiceReceipts(view)[0]).toMatchObject({
    columns: ['状态码', '实际响应'], rows: [['201', '{"id":1}']],
  });
});

test('a failed compilation keeps its own diagnostic and does not invent a sample execution', async () => {
  const result = {
    ...attempt(true), sample_result: null,
    compilation: { outcome: 'completed', exit_code: 1, stdout: 'javac started',
      stderr: 'Main.java:3: error: missing return statement' },
  };
  show(extendedProjectView('java', false, result));
  const compilation = (await screen.findAllByRole('region', { name: '独立编译回执' }))[0];
  expect(compilation.textContent).toContain('编译未通过');
  expect(compilation.textContent).toContain('本次未执行样例和评测用例。');
  expect(compilation.textContent).toContain('javac started');
  expect(compilation.textContent).toContain('missing return statement');
  expect(screen.queryByText(/仅含公开样例的实际输出/)).toBeNull();
  expect(native.write).not.toHaveBeenCalled();
});
