import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { ArrowDown, ArrowUp, BookOpen, MessageSquare, Pause, Pencil, Play, Save, StepForward, Trash2, X } from 'lucide-react';
import { AnimatedText, ArtifactAction, Collapse, Notice, actionSpring } from './LearningUI';

export { CodeEditor, ArtifactAction } from './LearningUI';
export { CodeDiff, TreeView, RelationGraph, SequenceDiagram, ParameterControl } from './LearningVisuals';
export {
  AlgorithmPlayer, AlgorithmSequence, AlgorithmContainer, AlgorithmGraph, AlgorithmGrid,
  AlgorithmRecursion, AlgorithmIntervals, AlgorithmBits, AlgorithmGeometry,
} from './AlgorithmVisuals';

// Brief task requirements only; long-form teaching stays in the message stream.
export function Explanation({ title, children }: { title?: string; children: ReactNode }) {
  return <div className="demo-explanation" data-learning-component="explanation">
    {title && <h4>{title}</h4>}{children}
  </div>;
}

export function SourceReference({ title, version, section, block, disabled = false, onOpen }: {
  title: string; version: number; section: string; block: number | string; disabled?: boolean; onOpen: () => void;
}) {
  return <span data-learning-component="source-reference">
    <ArtifactAction icon={BookOpen} label="阅读并定位引用" disabled={disabled} onClick={onOpen}
      title={`${title} · 文档版本 ${version} · ${section} · 原文块 ${block}`}>
      {`${title} · ${section}`}
    </ArtifactAction>
  </span>;
}

export function CodeBlock({ children, label }: { children: ReactNode; label?: string }) {
  return <pre className="demo-pre" aria-label={label} data-learning-component="code-block"><code>{children}</code></pre>;
}

export function DataTable({ columns, rows, label }: {
  columns: readonly string[]; rows: readonly (readonly ReactNode[])[]; label: string;
}) {
  return <div className="demo-table-wrap" data-learning-component="data-table"><table aria-label={label}>
    <thead><tr>{columns.map((name) => <th key={name} scope="col">{name}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column}><AnimatedText>{cell}</AnimatedText></td>)}</tr>)}</tbody>
  </table></div>;
}

export function KeyValueList({ entries, label }: { entries: { name: string; value: ReactNode }[]; label: string }) {
  return <dl className="demo-case-values" aria-label={label} data-learning-component="key-values">
    {entries.map(({ name, value }) => <div key={name}><dt>{name}</dt><dd><AnimatedText block>{value}</AnimatedText></dd></div>)}
  </dl>;
}

function previewDocument(html: string, css: string) {
  const template = document.createElement('template');
  template.innerHTML = html;
  const allowed = new Set(['MAIN', 'SECTION', 'ARTICLE', 'HEADER', 'FOOTER', 'NAV', 'ASIDE', 'DIV', 'SPAN', 'H1', 'H2', 'H3', 'H4', 'P', 'UL', 'OL', 'LI', 'BUTTON', 'STRONG', 'EM', 'PRE', 'CODE', 'BR', 'HR']);
  for (const element of [...template.content.querySelectorAll('*')]) {
    if (!allowed.has(element.tagName)) { element.remove(); continue; }
    for (const attribute of [...element.attributes]) {
      if (!['class', 'id', 'type', 'aria-label'].includes(attribute.name)) element.removeAttribute(attribute.name);
    }
  }
  const safeCss = css.replaceAll('<', '\\3c ');
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; form-action 'none'; base-uri 'none'"><style>${safeCss}</style>${template.innerHTML}`;
}

export function IsolatedPreview({ html, css, title = 'HTML CSS 隔离预览' }: { html: string; css: string; title?: string }) {
  return <iframe title={title} className="demo-preview" sandbox="" referrerPolicy="no-referrer"
    data-learning-component="isolated-preview" srcDoc={previewDocument(html, css)} />;
}

type ChoiceProps = { label: string; options: readonly (string | { id: string; text: string })[]; disabled?: boolean } & (
  { multiple?: false; value: string; onChange: (value: string) => void }
  | { multiple: true; value: string[]; onChange: (value: string[]) => void }
);

export function ChoiceAnswer(props: ChoiceProps) {
  const name = useId();
  return <fieldset disabled={props.disabled} aria-label={props.label} data-learning-component="choice-answer">
    {props.options.map((item) => {
      const option = typeof item === 'string' ? item : item.id;
      return <label className="demo-choice" key={option}>
      <input type={props.multiple ? 'checkbox' : 'radio'} name={name} value={option}
        checked={props.multiple ? props.value.includes(option) : props.value === option}
        onChange={() => {
          if (props.multiple) props.onChange(props.value.includes(option)
            ? props.value.filter((value) => value !== option) : [...props.value, option]);
          else props.onChange(option);
        }} /><span>{typeof item === 'string' ? item : item.text}</span>
    </label>; })}
  </fieldset>;
}

export function TextAnswer({ label, accessibleLabel = label, value, onChange, readOnly = false, rows = 3 }: {
  label: string; accessibleLabel?: string; value: string; onChange: (value: string) => void; readOnly?: boolean; rows?: number;
}) {
  return <label data-learning-component="text-answer">{label}
    <textarea className="demo-textarea" aria-label={accessibleLabel} value={value} readOnly={readOnly}
      rows={rows} onChange={(event) => onChange(event.target.value)} />
  </label>;
}

export function OrderingAnswer({ label, value, onChange, disabled = false, labels = {} }: {
  label: string; value: string[]; onChange: (value: string[]) => void; disabled?: boolean; labels?: Record<string, string>;
}) {
  return <ol aria-label={label} data-learning-component="ordering-answer">
    {value.map((item, index) => <li key={item} className="demo-step">
      <span>{index + 1}. {labels[item] ?? item}</span>
      {[-1, 1].map((direction) => <ArtifactAction key={direction} resetHoverOnClick icon={direction < 0 ? ArrowUp : ArrowDown}
        label={`${labels[item] ?? item}${direction < 0 ? '上移' : '下移'}`} disabled={disabled || index + direction < 0 || index + direction >= value.length}
        onClick={() => {
          const next = [...value];
          [next[index], next[index + direction]] = [next[index + direction], next[index]];
          onChange(next);
        }} />)}
    </li>)}
  </ol>;
}

function LineBubble({ title, actions, children }: { title: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return <div className="demo-line-reason">
    <div className="demo-line-reason-heading"><span>{title}</span>
      {actions && <div className="demo-line-reason-actions">{actions}</div>}
    </div>
    {children}
  </div>;
}

export function LineRangeAnswer({ label = '选择代码行并说明理由', lines, value, reasons, drafts,
  onDraftChange, onSave, onRemove, disabled = false, feedback = {} }: {
  label?: string; lines: readonly string[]; value: number[]; reasons: Record<number, string>;
  drafts: Record<number, string>; onDraftChange: (line: number, draft: string | null) => void;
  onSave: (line: number) => void; onRemove: (line: number) => void; disabled?: boolean;
  feedback?: Record<number, ReactNode>;
}) {
  const id = useId();
  const [activeLine, setActiveLine] = useState<number | null>(null);
  const inputs = useRef(new Map<number, HTMLTextAreaElement>());
  const rows = useRef(new Map<number, HTMLButtonElement>());
  useEffect(() => {
    if (activeLine !== null && !disabled) inputs.current.get(activeLine)?.focus({ preventScroll: true });
  }, [activeLine, disabled]);
  const edit = (line: number) => {
    onDraftChange(line, reasons[line] ?? '');
    setActiveLine(line);
  };
  const finish = (line: number, action: () => void) => {
    action();
    setActiveLine(null);
    rows.current.get(line)?.focus({ preventScroll: true });
  };
  return <div role="group" aria-label={label} className="demo-line-answer" data-learning-component="line-range-answer">
    {lines.map((line, index) => {
      const number = index + 1;
      const saved = value.includes(number);
      const editing = Object.hasOwn(drafts, number) && !disabled;
      const selected = saved || editing;
      const reasonId = `${id}-reason-${number}`;
      return <div className="demo-annotated-line" key={number}>
        <button type="button" className="demo-selectable-line" aria-label={`第 ${number} 行：${line}`}
          ref={(element) => { if (element) rows.current.set(number, element); else rows.current.delete(number); }}
          aria-expanded={selected || Boolean(feedback[number])} aria-controls={reasonId} disabled={disabled}
          data-annotated={selected || Boolean(feedback[number])}
          onClick={() => {
            if (editing) finish(number, () => onDraftChange(number, null));
            else edit(number);
          }}>
          <span className="demo-selectable-line-number" aria-hidden="true">{number}</span>
          <code>{line || ' '}</code>
          <MessageSquare size={16} className="demo-line-check" aria-hidden="true" />
        </button>
        <Collapse id={reasonId} open={selected || Boolean(feedback[number])}>
          {(editing || saved) && <LineBubble title={editing
            ? <label htmlFor={`${reasonId}-input`}>第 {number} 行的理由</label> : '你的批注'}
            actions={!disabled && (editing ? <>
              <ArtifactAction icon={Save} label={`保存第 ${number} 行批注`} primary
                disabled={!drafts[number]?.trim()} onClick={() => finish(number, () => onSave(number))} />
              <ArtifactAction icon={X} label={`取消第 ${number} 行编辑`}
                onClick={() => finish(number, () => onDraftChange(number, null))} />
            </> : <>
              <ArtifactAction icon={Pencil} label={`编辑第 ${number} 行批注`} onClick={() => edit(number)} />
              <ArtifactAction icon={Trash2} label={`移除第 ${number} 行批注`} onClick={() => finish(number, () => onRemove(number))} />
            </>)}>
            {editing ? <textarea id={`${reasonId}-input`} className="demo-textarea" rows={2}
                ref={(element) => { if (element) inputs.current.set(number, element); else inputs.current.delete(number); }}
                value={drafts[number]} placeholder="为什么选择这一行？"
                onChange={(event) => onDraftChange(number, event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    event.preventDefault();
                    finish(number, () => onDraftChange(number, null));
                  }
                }} />
              : <p className="demo-saved-annotation"><AnimatedText block>{reasons[number]}</AnimatedText></p>}
          </LineBubble>}
          {feedback[number] && <LineBubble title="参考评审">{feedback[number]}</LineBubble>}
        </Collapse>
      </div>;
    })}
  </div>;
}

// Playback advances a supplied observation index, never a score or completion.
export function StepPlayer({ label, items, step, onStep, feedback, actions, active = true }: {
  label: string; items: readonly ReactNode[]; step: number; onStep: (step: number) => void;
  feedback?: ReactNode; actions?: ReactNode; active?: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const indicatorId = useId();
  const reduced = useReducedMotion();
  const finished = step >= items.length;
  useEffect(() => {
    const pause = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener('visibilitychange', pause);
    return () => document.removeEventListener('visibilitychange', pause);
  }, []);
  useEffect(() => {
    if (!playing || finished || !active) { setPlaying(false); return; }
    const timer = setTimeout(() => {
      if (document.visibilityState === 'visible' && !container.current?.closest('[inert], [hidden]')) onStep(step + 1);
      else setPlaying(false);
    }, 900);
    return () => clearTimeout(timer);
  }, [playing, finished, step, onStep, active]);
  return <div ref={container} data-learning-component="step-player">
    <div className="demo-steps" aria-label={label}>{items.map((item, index) =>
      <span key={index} className="demo-step-value" data-active={index === step - 1} aria-current={index === step - 1 ? 'step' : undefined}>
        {index === step - 1 && <motion.span className="demo-step-highlight" aria-hidden="true"
          layoutId={indicatorId} transition={reduced ? { duration: 0 } : actionSpring} />}
        {item}
      </span>)}</div>
    {feedback}
    <ActionGroup>
      <ArtifactAction icon={StepForward} label="观察下一步" disabled={finished} onClick={() => onStep(step + 1)} />
      <ArtifactAction icon={playing ? Pause : Play} label={playing ? '暂停播放' : '自动播放'}
        aria-pressed={playing} disabled={finished} onClick={() => setPlaying(!playing)} />
      {actions}
    </ActionGroup>
  </div>;
}

export function ResultFeedback({ label, columns = ['公开输入', '预期', '样例输出'], rows = [] }: {
  label?: string; columns?: readonly string[]; rows?: readonly (readonly ReactNode[])[];
}) {
  return <div data-learning-component="result-feedback">
    {label && <Notice>{label}</Notice>}
    {rows.length > 0 && <DataTable label="公开检查结果" columns={columns} rows={rows} />}
  </div>;
}

export function AnswerFeedback({ kind, children }: { kind: 'correct' | 'incorrect' | 'reference'; children: ReactNode }) {
  return <div data-learning-component="answer-feedback" data-feedback={kind}>
    <Notice>{kind === 'correct' ? '回答正确。' : kind === 'incorrect' ? '还需要调整。' : '参考讲评：'} {children}</Notice>
  </div>;
}

export function ReviewFinding({ lines, findings }: {
  lines: readonly string[]; findings: { line: number; content: ReactNode }[];
}) {
  return <div className="demo-line-answer" data-learning-component="review-finding" aria-label="逐行代码评审">
    {lines.map((line, index) => {
      const notes = findings.filter((finding) => finding.line === index + 1);
      return <div className="demo-annotated-line" key={index}>
        <div className="demo-selectable-line demo-reviewed-line" data-annotated={notes.length > 0}>
          <span className="demo-selectable-line-number">{index + 1}</span>
          <code>{line || ' '}</code>
          <MessageSquare size={16} className="demo-line-check" aria-hidden="true" />
        </div>
        {notes.map((finding, noteIndex) => <LineBubble key={noteIndex} title="参考评审">{finding.content}</LineBubble>)}
      </div>;
    })}
  </div>;
}

export function ActionGroup({ children }: { children: ReactNode }) {
  return <div className="demo-actions" data-learning-component="action-group">{children}</div>;
}
