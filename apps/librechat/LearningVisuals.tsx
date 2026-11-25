import { useEffect, useId, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ChevronRight, FileCode2, Folder, FolderOpen } from 'lucide-react';
import { ArtifactAction, Collapse } from './LearningUI';
import { normalizeParameter } from './component-utils.mjs';
import { PhosphorDiff, PhosphorMinus, PhosphorPlus } from './PhosphorIcons';
import InlineCodeEditor from './InlineCodeEditor';
import './learning-visuals.css';

export function CodeDiff({ before, after, label = '代码修改对照', onChange, readOnly = false, embedded = false,
  open: controlledOpen, onOpenChange, hideToggle = false }: {
  before: string; after: string; label?: string; onChange?: (value: string) => void; readOnly?: boolean; embedded?: boolean;
  open?: boolean; onOpenChange?: (open: boolean) => void; hideToggle?: boolean;
}) {
  const id = useId();
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  return <div className={`demo-code-diff${embedded ? ' demo-code-diff-embedded' : ''}`} data-learning-component="code-diff">
    <div id={id} className="demo-diff-editor">
      <InlineCodeEditor label={label} value={after} before={before} showDiff={open} readOnly={readOnly || !onChange} onChange={onChange} />
    </div>
    {!hideToggle && <div className="demo-diff-toolbar">
      <ArtifactAction icon={PhosphorDiff} label={`切换${label}修改对照`} aria-pressed={open} aria-controls={id}
        onClick={() => { setLocalOpen(!open); onOpenChange?.(!open); }} />
    </div>}
  </div>;
}

export type LearningTreeNode = { id: string; label: string; children?: readonly LearningTreeNode[] };

export function TreeView({ label, nodes, expanded, onToggle, selected, onSelect }: {
  label: string; nodes: readonly LearningTreeNode[]; expanded: readonly string[]; onToggle: (id: string) => void;
  selected?: string; onSelect: (id: string) => void;
}) {
  const id = useId();
  const render = (items: readonly LearningTreeNode[]) => <ul className="demo-tree-branches">
    {items.map((node) => {
      const branch = Boolean(node.children?.length);
      const open = expanded.includes(node.id);
      const Icon = branch ? open ? FolderOpen : Folder : FileCode2;
      return <li key={node.id}>
        <button type="button" className="demo-tree-node" aria-expanded={branch ? open : undefined}
          aria-controls={branch ? `${id}-${node.id}` : undefined} aria-pressed={!branch ? selected === node.id : undefined}
          onClick={() => branch ? onToggle(node.id) : onSelect(node.id)}>
          <ChevronRight size={16} className="demo-tree-chevron" data-open={open} data-leaf={!branch} aria-hidden="true" />
          <Icon size={18} aria-hidden="true" /><span>{node.label}</span>
        </button>
        {branch && <Collapse id={`${id}-${node.id}`} open={open}>{render(node.children!)}</Collapse>}
      </li>;
    })}
  </ul>;
  return <div className="demo-tree" role="group" aria-label={label} data-learning-component="tree-view">{render(nodes)}</div>;
}

type RelationNode = { id: string; label: string; x: number; y: number };
type RelationEdge = { from: string; to: string; label: string };

export function RelationGraph({ label, nodes, edges, selected, onSelect, width = 760, height = 320 }: {
  label: string; nodes: readonly RelationNode[]; edges: readonly RelationEdge[];
  selected: string | null; onSelect: (id: string | null) => void; width?: number; height?: number;
}) {
  const id = useId();
  const descriptions = edges.map((edge) => `${nodes.find((node) => node.id === edge.from)?.label} → ${nodes.find((node) => node.id === edge.to)?.label}：${edge.label}`);
  return <div className="demo-diagram-scroll" data-learning-component="relation-graph" role="group" aria-label={label}>
    <div className="demo-relation-canvas" style={{ width, height }}>
      <svg width={width} height={height} aria-hidden="true">
        <defs><marker id={`${id}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
        </marker></defs>
        {edges.map((edge, index) => {
          const from = nodes.find((node) => node.id === edge.from)!;
          const to = nodes.find((node) => node.id === edge.to)!;
          if (edge.from === edge.to) return <g key={index} className="demo-relation-edge"
            data-active={selected === edge.from} data-muted={selected !== null && selected !== edge.from}>
            <path d={`M ${from.x + 55} ${from.y - 25} C ${from.x + 125} ${from.y - 75}, ${from.x - 125} ${from.y - 75}, ${from.x - 55} ${from.y - 25}`}
              fill="none" stroke="currentColor" markerEnd={`url(#${id}-arrow)`} />
            <text x={from.x} y={from.y - 65} textAnchor="middle">{edge.label}</text>
          </g>;
          const dx = to.x - from.x;
          const dy = to.y - from.y;
          const inset = Math.min(dx ? 75 / Math.abs(dx) : Infinity, dy ? 25 / Math.abs(dy) : Infinity);
          const active = selected === edge.from || selected === edge.to;
          return <g key={index} className="demo-relation-edge" data-active={active} data-muted={selected !== null && !active}>
            <line x1={from.x + dx * inset} y1={from.y + dy * inset}
              x2={to.x - dx * inset} y2={to.y - dy * inset} markerEnd={`url(#${id}-arrow)`} />
            <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 12} textAnchor="middle">{edge.label}</text>
          </g>;
        })}
      </svg>
      {nodes.map((node) => <button key={node.id} type="button" className="demo-relation-node"
        style={{ left: node.x - 75, top: node.y - 25 }} aria-pressed={selected === node.id}
        aria-describedby={`${id}-edges`} onClick={() => onSelect(selected === node.id ? null : node.id)}>
        {node.label}
      </button>)}
    </div>
    <ul id={`${id}-edges`} className="sr-only">{descriptions.map((text, index) => <li key={index}>{text}</li>)}</ul>
  </div>;
}

export type SequenceStep = { id: string; from: string; to: string; label: string };

export function SequenceDiagram({ label, participants, steps, activeStep, onStep }: {
  label: string; participants: readonly { id: string; label: string }[];
  steps: readonly SequenceStep[]; activeStep: number; onStep: (step: number) => void;
}) {
  const id = useId();
  const width = Math.max(620, participants.length * 220);
  const height = 90 + steps.length * 76;
  const position = (name: string) => 100 + participants.findIndex((participant) => participant.id === name) * (width - 200) / Math.max(1, participants.length - 1);
  return <div className="demo-diagram-scroll" data-learning-component="sequence-diagram">
    <svg className="demo-sequence" width={width} height={height} role="group" aria-label={label}>
      <defs><marker id={`${id}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
      </marker></defs>
      {participants.map((participant) => <g key={participant.id} className="demo-sequence-participant">
        <rect x={position(participant.id) - 70} y="8" width="140" height="40" rx="6" />
        <text x={position(participant.id)} y="34" textAnchor="middle">{participant.label}</text>
        <line x1={position(participant.id)} x2={position(participant.id)} y1="52" y2={height - 10} />
      </g>)}
      {steps.map((step, index) => {
        const from = position(step.from);
        const to = position(step.to);
        const y = 100 + index * 76;
        const same = step.from === step.to;
        return <g key={step.id} className="demo-sequence-step" role="button" tabIndex={0}
          aria-pressed={activeStep === index} aria-label={`第 ${index + 1} 步：${step.label}`}
          onClick={() => onStep(index)} onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onStep(index); }
          }}>
          <rect x="12" y={y - 37} width={width - 24} height="65" rx="6" className="demo-sequence-highlight" />
          <path d={same ? `M ${from} ${y} h 45 v 20 h -45` : `M ${from} ${y} H ${to}`}
            markerEnd={`url(#${id}-arrow)`} className="demo-sequence-arrow" />
          <text x={same ? from + 50 : (from + to) / 2} y={y - 12} textAnchor={same ? 'start' : 'middle'}>{step.label}</text>
        </g>;
      })}
    </svg>
  </div>;
}

export function ParameterControl({ label, value, min, max, step = 1, onChange, disabled = false }: {
  label: string; value: number; min: number; max: number; step?: number;
  onChange: (value: number) => void; disabled?: boolean;
}) {
  const id = useId();
  const [draft, setDraft] = useState(String(value));
  const [editing, setEditing] = useState(false);
  const previous = useRef(value);
  const cancelEdit = useRef(false);
  const reduced = useReducedMotion();
  const direction = value >= previous.current ? 1 : -1;
  const progress = max === min ? 0 : (value - min) / (max - min) * 100;
  const ticks = Math.min(40, Math.round((max - min) / step));
  const spring = reduced ? { duration: 0 } : { type: 'spring' as const, stiffness: 320, damping: 26, mass: .65 };
  useEffect(() => setDraft(String(value)), [value]);
  useEffect(() => { previous.current = value; }, [value]);
  const commit = () => {
    const number = draft.trim() === '' ? value : Number(draft);
    const next = Number.isFinite(number) ? normalizeParameter(number, min, max, step) : value;
    onChange(next); setDraft(String(next));
  };
  return <div className="demo-parameter" data-learning-component="parameter-control">
    <label className="demo-parameter-label" htmlFor={`${id}-number`}>{label}</label>
    <div className="demo-parameter-stepper">
      <ArtifactAction icon={PhosphorMinus} label={`减少${label}`} disabled={disabled || value <= min}
        onClick={() => onChange(normalizeParameter(value - step, min, max, step))} />
      <div className="demo-parameter-value" data-editing={editing}>
        <span className="demo-parameter-roll" aria-hidden="true">
          <AnimatePresence initial={false} custom={direction}>
            <motion.span key={value} custom={direction}
              variants={{
                enter: (dir: number) => ({ y: reduced ? 0 : dir * 42, opacity: 0 }),
                exit: (dir: number) => ({ y: reduced ? 0 : -dir * 42, opacity: 0 }),
              }} initial="enter" animate={{ y: 0, opacity: 1 }} exit="exit" transition={spring}>{value}</motion.span>
          </AnimatePresence>
        </span>
        <input id={`${id}-number`} type="number" min={min} max={max} step={step} value={draft} disabled={disabled}
        onFocus={() => setEditing(true)}
        onChange={(event) => {
          setDraft(event.target.value);
          if (event.target.value !== '' && event.target.validity.valid) onChange(event.target.valueAsNumber);
        }} onBlur={() => { if (!cancelEdit.current) commit(); cancelEdit.current = false; setEditing(false); }} onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
          if (event.key === 'Escape') { event.preventDefault(); cancelEdit.current = true; setDraft(String(value)); event.currentTarget.blur(); }
        }} />
      </div>
      <ArtifactAction icon={PhosphorPlus} label={`增加${label}`} disabled={disabled || value >= max}
        onClick={() => onChange(normalizeParameter(value + step, min, max, step))} />
    </div>
    <div className="demo-parameter-track">
      <div className="demo-parameter-rail" aria-hidden="true">
        <motion.span className="demo-parameter-fill" animate={{ width: `${progress}%` }} transition={spring} />
        {Array.from({ length: ticks + 1 }, (_, index) => <span key={index} className="demo-parameter-tick"
          data-active={index / Math.max(1, ticks) * 100 <= progress} style={{ left: `${index / Math.max(1, ticks) * 100}%` }} />)}
        <motion.span className="demo-parameter-end" animate={{ left: `${progress}%` }} transition={spring} />
      </div>
      <input type="range" aria-label={`${label}滑块`} min={min} max={max} step={step} value={value} disabled={disabled}
        onChange={(event) => { const next = event.target.valueAsNumber; onChange(next); setDraft(String(next)); }} />
    </div>
    <div className="demo-parameter-bounds" aria-hidden="true"><span>{min}</span><span>{max}</span></div>
  </div>;
}
