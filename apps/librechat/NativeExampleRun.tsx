import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { components } from '@leornian/api-contracts';
import { CornerDownLeft, FileText, History } from 'lucide-react';
import { Action } from './LearningUI';
import PracticeWorkbench from './PracticeWorkbench';
import { nativeRequest, nativeStore, NativeApiError } from './native-client.mjs';

type Result = components['schemas']['ExampleRunResult'];
type Language = components['schemas']['ExampleRunInput']['language'];
const names: Record<Language, string> = {
  python: 'Python', javascript: 'JavaScript', typescript: 'TypeScript', go: 'Go', java: 'Java', csharp: 'C#',
};

function ExampleTerminal({ transcript, status, draft, accepting, sending, error, retry, change, send }: {
  transcript: string; status: string; draft: string; accepting: boolean; sending: boolean;
  error: string; retry?: () => void; change: (text: string) => void; send: () => void;
}) {
  const output = useRef<HTMLDivElement>(null), follow = useRef(true);
  useEffect(() => {
    if (follow.current && output.current) output.current.scrollTop = output.current.scrollHeight;
  }, [transcript, status]);
  return <div className="example-terminal">
    <div className="example-terminal-output" ref={output} onScroll={(event) => {
      const box = event.currentTarget;
      follow.current = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
    }}>
      <pre role="log" aria-label="终端记录" aria-live="polite">{transcript}</pre>
      <div className="example-terminal-status" role="status">{status}</div>
      {error && <div role="alert">{error} {retry && <Action onClick={retry}>重新连接</Action>}</div>}
    </div>
    {accepting && <form className="example-terminal-line" onSubmit={(event) => { event.preventDefault(); send(); }}>
      <span aria-hidden="true">›</span><input aria-label="终端输入" value={draft}
        autoComplete="off" spellCheck={false} maxLength={2048} readOnly={sending}
        placeholder="输入后按回车" onChange={(event) => change(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229)) event.preventDefault();
        }} />
      <button type="submit" aria-label="发送输入" title="发送输入" disabled={sending}><CornerDownLeft size={16} /></button>
    </form>}
  </div>;
}

export default function NativeExampleRun({ root, actorId, componentId, revision, code, languages, surface, disabled,
  title, editor, description, workspace, practiceOnly = false, sample }: {
  root: string; actorId: string; componentId: string; revision: number;
  code: string; languages: Language[]; disabled: boolean;
  surface?: components['schemas']['ExampleRunSurface'] | null;
  title: string; editor: ReactNode; description?: ReactNode;
  workspace?: components['schemas']['ExampleWorkspace'] | null;
  practiceOnly?: boolean;
  sample?: { answer: components['schemas']['PracticeSampleRunInput']['answer'] | null;
    language: ReactNode; tests: ReactNode; history?: ReactNode };
}) {
  const key = `leornian.example:${actorId}:${root}:${revision}:${componentId}`;
  const [command, setCommand] = useState(() => {
    try { return sessionStorage.getItem(key) ?? ''; } catch { return ''; }
  });
  const [result, setResult] = useState<Result | null>(null);
  const [selected, setSelected] = useState<Language | ''>('');
  const [draft, setDraft] = useState(''), [error, setError] = useState('');
  const [controlError, setControlError] = useState(''), [controlling, setControlling] = useState(false);
  const [sending, setSending] = useState(false), [reading, setReading] = useState(0);
  const dispatching = useRef(false), controlPending = useRef(false);
  const inputId = useRef('');
  const language = selected && languages.includes(selected) ? selected : languages[0];
  const runnable = sample ? Boolean(sample.answer) : Boolean(language && code);
  const waiting = !!command && result?.status !== 'reported' && result?.status !== 'expired';
  const remember = (id: string) => {
    setCommand(id);
    try { if (id) sessionStorage.setItem(key, id); else sessionStorage.removeItem(key); } catch {}
  };

  useEffect(() => {
    if (!command || !waiting || sending) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const read = async () => {
      try {
        const pending = nativeStore.getSnapshot().pending.some((entry) => entry.key === command);
        const next: Result = pending ? await nativeStore.reconcile(command)
          : await nativeRequest(`${root}/example-runs/${command}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setResult(next); setError('');
        if (next.status === 'queued' || next.status === 'running') timer = setTimeout(read, next.terminal ? 350 : 1000);
      } catch (problem) {
        if (!controller.signal.aborted) setError((problem as Error).message);
      }
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [command, waiting, root, sending, reading]);

  const run = async () => {
    if (!runnable || disabled || waiting || dispatching.current) return;
    const id = crypto.randomUUID();
    dispatching.current = true;
    setDraft(''); inputId.current = ''; setControlError('');
    setSending(true); setResult(null); setError(''); remember(id);
    try {
      const next = await nativeStore.write(`${root}/example-runs`, {
        command_id: id, expected_artifact_revision: revision, component_id: componentId,
        ...(sample ? { answer: sample.answer } : {
          language, code, interactive: true, share_code_for_teaching: !practiceOnly,
        }),
      }, { key: id, lookup: `${root}/example-runs/${id}` });
      setResult(next);
    } catch (problem) {
      if (problem instanceof NativeApiError && problem.status < 500) remember('');
      setError((problem as Error).message);
    } finally { dispatching.current = false; setSending(false); }
  };
  const control = async (action: 'input' | 'stop') => {
    if (!waiting || controlPending.current || !result?.terminal ||
        (action === 'input' && !result.terminal.accepting_input)) return;
    controlPending.current = true; setControlling(true); setControlError('');
    try {
      const next: Result = await nativeRequest(`${root}/example-runs/${command}/${action}`, {
        method: 'POST', ...(action === 'input' ? { body: JSON.stringify({
          input_id: inputId.current ||= crypto.randomUUID(), text: draft,
        }) } : {}),
      });
      if (action === 'input') { setDraft(''); inputId.current = ''; }
      setResult(next); setReading(value => value + 1);
    } catch (problem) { setControlError((problem as Error).message); }
    finally { controlPending.current = false; setControlling(false); }
  };
  const output = result?.output, compilation = result?.compilation;
  const compileFailed = compilation && (compilation.outcome !== 'completed' || compilation.exit_code !== 0);
  const displayed = compileFailed ? compilation : output;
  const accepting = Boolean(waiting && result?.terminal?.accepting_input);
  const status = result?.status === 'reported' ? (displayed?.outcome === 'timeout' ? '运行超时'
    : displayed?.outcome === 'output_limit' ? '输出已达上限' : displayed?.outcome === 'infrastructure_error'
      ? '运行环境出错' : `${compileFailed ? '编译失败' : '程序已结束'} · 退出码 ${displayed?.exit_code ?? '未知'}`)
    : result?.status === 'expired' ? (result.error_code === 'learner_cancelled' ? '已停止运行' : '本次运行已失效')
    : result?.terminal?.stopping ? '正在停止…' : accepting ? '运行中'
    : waiting && result?.terminal?.transcript ? '正在结束…' : waiting || sending ? '正在启动…'
    : sample ? '点击「运行公开样例」查看输出。'
    : surface?.input_mode === 'line_during_run' ? surface.stdin_hint : '点击「运行」，看到程序提示后输入，按回车发送。';
  const transcript = result?.terminal?.transcript || [displayed?.stdout, displayed?.stderr].filter(Boolean).join('\n');
  const terminal = <ExampleTerminal transcript={transcript} status={status} draft={draft}
    accepting={accepting} sending={controlling} error={controlError || error}
    retry={error && waiting ? () => setReading(value => value + 1) : undefined}
    change={(text) => { inputId.current = ''; setDraft(text); }} send={() => void control('input')} />;
  return <PracticeWorkbench title={title}
    tabs={[{ id: 'description', label: sample ? '题目描述' : '示例说明', icon: FileText,
      content: <>{description ?? <p>可以修改代码，然后运行试试。</p>}
        {workspace?.stdin && <details className="example-input-guide"><summary>可以尝试的输入</summary>
          <pre>{workspace.stdin.trimEnd()}</pre></details>}</> },
      ...(sample?.history ? [{ id: 'history', label: '原提交记录', icon: History, content: sample.history }] : [])]}
    language={sample ? sample.language : languages.length > 1 ? <select aria-label="运行语言" value={language}
      disabled={waiting || sending}
      onChange={(event) => setSelected(event.target.value as Language)}>
      {languages.map((item) => <option key={item} value={item}>{names[item]}</option>)}
    </select> : <span>{workspace ? names[workspace.language] : language ? names[language] : title}</span>}
    editor={editor} terminal={sample ? undefined : terminal} tests={sample?.tests} result={sample && terminal}
    tools={!sample && !language && !waiting && <span className="text-sm text-text-secondary">本机语言环境尚未就绪</span>}
    onStop={waiting && result?.terminal ? () => void control('stop') : undefined}
    stopping={controlling || result?.terminal?.stopping} runLabel={sample ? '运行公开样例' : surface?.run_label ?? '运行'}
    runDisabled={disabled || !runnable || waiting || sending || controlling}
    busy={sending || waiting && !error} hasResult={Boolean(result || error)} onRun={() => void run()} />;
}
