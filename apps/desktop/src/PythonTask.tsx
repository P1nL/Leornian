import type { PythonQuestion } from "./api";

export function PythonTask({ question, code, onChange, locked, scope }: {
  question: PythonQuestion; code: string; onChange: (value: string) => void;
  locked: boolean; scope: string;
}) {
  const id = `python-code-${scope}-${question.slot}`;
  return <div className="python-task">
    <h4>{question.title}</h4><p className="choice-prompt">{question.prompt}</p>
    <p>stdin：一份 JSON 整数数组。stdout：只输出一个 JSON 整数。</p>
    <pre><code>{`输入 ${JSON.stringify(question.sample.input)}\n输出 ${question.sample.expected}`}</code></pre>
    <label htmlFor={id}>你的 Python 程序</label>
    <textarea id={id} className="code-input" rows={8} value={code}
      disabled={locked} maxLength={12000} spellCheck={false}
      onChange={(event) => onChange(event.target.value)} />
    {new TextEncoder().encode(code).length > 12000 &&
      <p className="error">程序超过 12,000 字节，请精简后再提交。</p>}
  </div>;
}
