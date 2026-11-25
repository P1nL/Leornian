import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import NativeExampleRun from './NativeExampleRun';
import { nativeStore } from './native-client.mjs';

afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); });
const props = { root: '/v2/conversations/c/learning-artifacts/a', actorId: 'learner',
  componentId: 'editor', revision: 1, disabled: false, title: '问候', editor: <span>编辑区</span> };

test('editing is local; Run uses the latest draft and displays the actual receipt', async () => {
  const write = vi.spyOn(nativeStore, 'write').mockResolvedValue({
    command_id: 'one', status: 'reported',
    compilation: { exit_code: 0, outcome: 'completed', stdout: 'Build succeeded.', stderr: '' },
    output: { exit_code: 0, outcome: 'completed', stdout: '晚上好\n', stderr: '' },
  });
  const view = render(<NativeExampleRun {...props} languages={['csharp']} code={'Console.WriteLine("你好");'} />);
  view.rerender(<NativeExampleRun {...props} languages={['csharp']} code={'Console.WriteLine("晚上好");'} />);
  expect(write).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '运行' }));
  await waitFor(() => expect(screen.getByRole('log').textContent).toContain('晚上好'));
  expect(screen.getByRole('status').textContent).toContain('退出码 0');
  expect(write).toHaveBeenCalledTimes(1);
  expect(write.mock.calls[0][0]).toBe(props.root + '/example-runs');
  expect(write.mock.calls[0][1]).toMatchObject({ code: 'Console.WriteLine("晚上好");', component_id: 'editor' });
  expect(write.mock.calls[0][1]).toHaveProperty('share_code_for_teaching', true);
  expect(screen.queryByRole('checkbox')).toBeNull();
  expect(screen.queryByText(/得分|评测通过/)).toBeNull();
  expect(screen.queryByText(/Build succeeded/)).toBeNull();
});

test('teaching runs share without a control; later free practice only updates the terminal', async () => {
  const write = vi.spyOn(nativeStore, 'write');
  const running = { status: 'running', terminal: { transcript: '请输入：', accepting_input: true, stopping: false } };
  const finished = { status: 'reported', terminal: { transcript: '请输入：65\n第一次结果', accepting_input: false, stopping: false },
    output: { exit_code: 0, outcome: 'completed', stdout: '请输入：第一次结果', stderr: '' } };
  let entered = false;
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    if (String(url).endsWith('/input')) {
      expect(JSON.parse(init!.body as string)).toMatchObject({ input_id: expect.any(String), text: '65' });
      expect(String(url)).toBe(`/leornian${props.root}/example-runs/${write.mock.calls[0][1].command_id}/input`);
      entered = true;
    }
    return Response.json(entered ? finished : running);
  });
  write.mockResolvedValueOnce(running).mockResolvedValueOnce({ ...finished, terminal: { ...finished.terminal, transcript: '第二次结果' } });
  const surface = { run_label: '运行这个示例', stdin_label: '终端', stdin_hint: '运行后按提示输入。',
    input_mode: 'line_during_run', output_mode: 'live_terminal' } as const;
  const view = render(<NativeExampleRun {...props} languages={['javascript']} surface={surface} code="console.log('demo')" />);
  expect(screen.getByText(surface.stdin_hint)).toBeTruthy();
  expect(screen.queryByRole('textbox', { name: '终端输入' })).toBeNull();
  expect(screen.queryByRole('checkbox')).toBeNull();
  expect(screen.queryByText(/分享给 Tutor/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: surface.run_label }));
  expect(await screen.findByText('请输入：')).toBeTruthy();
  expect(write.mock.calls[0][1]).toMatchObject({ interactive: true, share_code_for_teaching: true });
  expect(write.mock.calls[0][1]).not.toHaveProperty('stdin');
  fireEvent.change(screen.getByRole('textbox', { name: '终端输入' }), { target: { value: '65' } });
  fireEvent.click(screen.getByRole('button', { name: '发送输入' }));
  await waitFor(() => expect(screen.getByRole('log').textContent).toBe('请输入：65\n第一次结果'));
  expect(screen.queryByRole('textbox', { name: '终端输入' })).toBeNull();
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/input'))).toHaveLength(1);
  view.rerender(<NativeExampleRun {...props} practiceOnly languages={['javascript']} surface={surface} code="console.log('demo')" />);
  fireEvent.click(screen.getByRole('button', { name: surface.run_label }));
  await screen.findByText('第二次结果');
  expect(screen.getByRole('log').textContent).toBe('第二次结果');
  expect(write.mock.calls[1][1]).toMatchObject({ share_code_for_teaching: false });
  expect(screen.queryByRole('checkbox')).toBeNull();
});

test('reopening attaches to the same terminal; stopping does not start a new run', async () => {
  sessionStorage.setItem(`leornian.example:${props.actorId}:${props.root}:1:editor`, 'original');
  const write = vi.spyOn(nativeStore, 'write');
  let stopped = false;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    if (String(url).endsWith('/original/stop') && init?.method === 'POST') stopped = true;
    return Response.json({ status: stopped ? 'expired' : 'running', error_code: stopped ? 'learner_cancelled' : null,
      terminal: { transcript: '分钟：', accepting_input: !stopped, stopping: false } });
  });
  render(<NativeExampleRun {...props} languages={['python']} code="input()" />);
  expect(await screen.findByText('分钟：')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '停止运行' }));
  expect(await screen.findByText('已停止运行')).toBeTruthy();
  expect(screen.queryByRole('textbox', { name: '终端输入' })).toBeNull();
  expect(write).not.toHaveBeenCalled();
});

test('without a local runtime the draft stays available and Run does not submit', () => {
  const write = vi.spyOn(nativeStore, 'write');
  render(<NativeExampleRun {...props} languages={[]} code="print(1)" />);
  fireEvent.click(screen.getByRole('button', { name: '运行' }));
  expect(screen.getByText('本机语言环境尚未就绪')).toBeTruthy();
  expect(write).not.toHaveBeenCalled();
});
