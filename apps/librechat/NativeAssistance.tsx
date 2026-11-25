import { BookOpen, Lightbulb } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure } from './LearningUI';
import * as UI from './LearningComponents';
import type { PracticeBinding, PracticeCommand } from './native-practice';

type Response = components['schemas']['ResponseDirectAnswer']['response'];

function ResponseReference({ value }: { value: Response }) {
  if (value.type === 'prediction') return <UI.CodeBlock label="参考输出">
    {value.text === '' ? '（没有输出）' : value.text}
  </UI.CodeBlock>;
  if (value.type === 'short') return <p>{value.text}</p>;
  if (value.type === 'multiple') return <p>参考选项：{value.selected_ids.join('、')}</p>;
  if (value.type === 'ordering') return <p>参考顺序：{value.ordered_ids.join(' → ')}</p>;
  return <ul>{value.annotations.map((item) => <li key={item.line}>
    第 {item.line} 行：{item.reason}
  </li>)}</ul>;
}

type AssistanceProps = {
  binding: PracticeBinding; blocked: boolean; onCommand: (command: PracticeCommand) => void;
};

function DirectAssistance({ binding, blocked, onCommand }: AssistanceProps) {
  if (binding.assistance_profile !== 'practice-direct-answer.v1') return null;
  const receipt = binding.assistance_receipt;
  if (!receipt) return binding.allowed_actions.includes('request_direct_answer') ? <div
    role="group" aria-label={`${binding.source.title} 的辅助`}>
    <p className="demo-muted">请求后会记录辅助；不会填入草稿、自动提交或运行。</p>
    <UI.ActionGroup><Action icon={BookOpen} disabled={blocked} onClick={() => onCommand({
      action: 'request_direct_answer', component_id: binding.component_id,
    })}>请求直接答案</Action></UI.ActionGroup>
  </div> : null;
  const content = receipt.content;
  return <Disclosure title="参考答案（已记辅助）">
    <p className="demo-muted">来自这道已发布练习；后续成功不作为无辅助独立证据。</p>
    {content.type === 'choice' && <p>参考选项：{content.correct_key}</p>}
    {content.type === 'python' && <UI.CodeBlock label="参考程序（不会自动运行）">{content.code}</UI.CodeBlock>}
    {content.type === 'response' && <ResponseReference value={content.response} />}
    {content.type === 'response' && !!content.findings?.length && <ul>
      {content.findings.map((item, index) => <li key={index}>第 {item.line} 行：{item.content}</li>)}
    </ul>}
    {content.type === 'program' && (content.answer.type === 'sql'
      ? <UI.CodeBlock label="参考查询（不会自动运行）">{content.answer.query}</UI.CodeBlock>
      : <>{content.answer.files.map((file) => <Disclosure key={file.path}
        title={`${file.path}${file.read_only ? ' · 受保护' : ''}`}>
        <UI.CodeBlock label={file.path}>{file.content}</UI.CodeBlock>
      </Disclosure>)}</>)}
    <p>{content.explanation}</p>
  </Disclosure>;
}

const hintLabels = { 1: '概念线索', 2: '解题策略', 3: '下一步' } as const;

export function NativeAssistance(props: AssistanceProps) {
  const { binding, blocked, onCommand } = props;
  if (binding.hint_profile !== 'practice-hints.v1') return <DirectAssistance {...props} />;
  const receipts = binding.hint_receipts ?? [];
  const next = binding.next_hint_level;
  return <>
    <section aria-label={`${binding.source.title} 的分级提示`}>
      <p className="demo-muted">提示按 H1—H3 逐级请求并记录辅助；不会修改草稿或替你提交、运行。</p>
      {receipts.map((receipt) => <Disclosure key={receipt.id}
        defaultOpen={receipt.level === receipts.length}
        title={`H${receipt.level} · ${hintLabels[receipt.level]}（已记辅助）`}>
        <p>{receipt.content.text}</p>
      </Disclosure>)}
      {next && binding.allowed_actions.includes('request_hint') && <UI.ActionGroup>
        <Action icon={Lightbulb} disabled={blocked} onClick={() => onCommand({
          action: 'request_hint', component_id: binding.component_id, level: next,
        })}>请求 H{next} · {hintLabels[next]}</Action>
      </UI.ActionGroup>}
    </section>
    <DirectAssistance {...props} />
  </>;
}
