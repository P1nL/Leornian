import { useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { AnimatePresence, motion, useIsPresent, useReducedMotion } from 'framer-motion';
import { StepBack, StepForward } from 'lucide-react';
import { AnimatedText, ArtifactAction } from './LearningUI';
import { PhosphorPause, PhosphorPlay, PhosphorRefresh } from './PhosphorIcons';
import './algorithm-visuals.css';

type Tone = 'idle' | 'active' | 'done' | 'queued' | 'muted' | 'rejected';
type Item = { id: string; value: string | number; tone?: Tone };
type Node = { id: string; label: string; x: number; y: number; tone?: Tone };
type Edge = { from: string; to: string; tone?: Tone };
const toneNames = { idle: '', active: '当前', done: '已确认', queued: '待处理', muted: '已排除', rejected: '跳过或不匹配' };
const itemName = (item: Item) => `${item.value}${item.tone && toneNames[item.tone] ? `，${toneNames[item.tone]}` : ''}`;
function useSceneMotion() {
  return useReducedMotion() ? { duration: 0 } : { type: 'spring' as const, stiffness: 280, damping: 26, mass: .7 };
}

export function AlgorithmSequence({ items, pointers = [], label = '序列与指针' }: {
  items: readonly Item[]; pointers?: readonly { label: string; index: number }[]; label?: string;
}) {
  const transition = useSceneMotion();
  return <div className="algo-sequence" role="group" aria-label={label} data-learning-component="algorithm-sequence">
    <div className="algo-sequence-cells">
      {items.map((item, index) => <motion.div layout="position" transition={transition} key={item.id} className="algo-sequence-item">
        <span className="algo-index" aria-hidden="true">{index}</span>
        <div className="algo-cell" data-tone={item.tone} aria-label={itemName(item)}>{item.value}</div>
      </motion.div>)}
    </div>
    {pointers.length > 0 && <div className="algo-pointers" style={{ height: pointers.length * 27 }}>
      <AnimatePresence initial={false}>{pointers.map((pointer, row) => <motion.span key={pointer.label} className="algo-pointer"
        initial={{ opacity: 0, left: `${(pointer.index + .5) / Math.max(1, items.length) * 100}%` }}
        animate={{ opacity: 1, left: `${(pointer.index + .5) / Math.max(1, items.length) * 100}%` }}
        exit={{ opacity: 0 }}
        transition={transition} style={{ top: row * 27 }} aria-label={`${pointer.label} 指向下标 ${pointer.index}`}>
        {pointer.label}
      </motion.span>)}</AnimatePresence>
    </div>}
  </div>;
}

export function AlgorithmContainer({ items, mode = 'stack', label = mode === 'stack' ? '栈' : '队列' }: {
  items: readonly Item[]; mode?: 'stack' | 'queue'; label?: string;
}) {
  const transition = useSceneMotion();
  return <div className="algo-container" data-mode={mode} role="group" aria-label={label} data-learning-component="algorithm-container">
    <div className="algo-container-label">{label}{items.length > 0 && <span>{mode === 'stack' ? '栈顶在上' : '队首先出'}</span>}</div>
    <div className="algo-container-items">
      <AnimatePresence initial={false} mode="popLayout">
        {items.map((item) => <motion.div key={item.id} layout="position" className="algo-cell" data-tone={item.tone}
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
          transition={transition} aria-label={itemName(item)}>{item.value}</motion.div>)}
      </AnimatePresence>
      {items.length === 0 && <span className="algo-empty">空</span>}
    </div>
  </div>;
}

export function AlgorithmGraph({ nodes, edges, directed = true, label = '节点与连线' }: {
  nodes: readonly Node[]; edges: readonly Edge[]; directed?: boolean; label?: string;
}) {
  const transition = useSceneMotion();
  const id = useId();
  return <svg className="algo-graph" viewBox="0 0 480 280" role="img" aria-label={label} data-learning-component="algorithm-graph">
    <title>{nodes.map((node) => `${node.label}：${toneNames[node.tone ?? 'idle'] || '未访问'}`).join('；')}</title>
    <defs><marker id={`${id}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="rgb(var(--text-secondary))" />
    </marker></defs>
    {edges.map((edge) => {
      const from = nodes.find((node) => node.id === edge.from)!;
      const to = nodes.find((node) => node.id === edge.to)!;
      if (edge.from === edge.to) return <motion.path key={`${edge.from}-${edge.to}`}
        className="algo-edge" data-tone={edge.tone} fill="none"
        d={`M ${from.x + 12} ${from.y - 20} C ${from.x + 70} ${from.y - 70}, ${from.x - 70} ${from.y - 70}, ${from.x - 12} ${from.y - 20}`}
        markerEnd={directed ? `url(#${id}-arrow)` : undefined} />;
      const length = Math.hypot(to.x - from.x, to.y - from.y) || 1;
      const dx = (to.x - from.x) / length * 25, dy = (to.y - from.y) / length * 25;
      return <motion.line key={`${edge.from}-${edge.to}`} className="algo-edge" data-tone={edge.tone} initial={false}
        animate={{ x1: from.x + dx, y1: from.y + dy, x2: to.x - dx, y2: to.y - dy }} transition={transition}
        markerEnd={directed ? `url(#${id}-arrow)` : undefined} />;
    })}
    {nodes.map((node) => <g key={node.id} className="algo-node" data-tone={node.tone}>
      <motion.circle initial={false} animate={{ cx: node.x, cy: node.y }} r="23" transition={transition} />
      <motion.text initial={false} animate={{ x: node.x, y: node.y + 1 }} transition={transition}
        textAnchor="middle" dominantBaseline="middle">{node.label}</motion.text>
    </g>)}
  </svg>;
}

export function AlgorithmGrid({ cells, columnLabels, rowLabels, label = '网格与状态表' }: {
  cells: readonly (readonly Item[])[]; columnLabels: readonly string[]; rowLabels: readonly string[]; label?: string;
}) {
  return <div className="algo-grid-wrap" data-learning-component="algorithm-grid">
    <table className="algo-grid" aria-label={label}><thead><tr><td />
      {columnLabels.map((column) => <th key={column} scope="col">{column}</th>)}
    </tr></thead><tbody>
      {cells.map((row, index) => <tr key={rowLabels[index]}><th scope="row">{rowLabels[index]}</th>
        {row.map((cell) => <td key={cell.id}><div className="algo-cell" data-tone={cell.tone} aria-label={itemName(cell)}>{cell.value}</div></td>)}
      </tr>)}
    </tbody></table>
  </div>;
}

export function AlgorithmRecursion({ calls, stack, label = '递归与搜索过程' }: {
  calls: readonly { id: string; label: string; depth: number; tone?: Tone }[]; stack: readonly string[]; label?: string;
}) {
  const transition = useSceneMotion();
  return <div className="algo-recursion" role="group" aria-label={label} data-learning-component="algorithm-recursion">
    <ol className="algo-call-tree">
      <AnimatePresence initial={false}>
        {calls.map((call) => <motion.li key={call.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={transition}
          style={{ '--call-depth': call.depth } as CSSProperties} data-tone={call.tone}>
          <span className="algo-call-branch" aria-hidden="true" /><code>{call.label}</code>
          {call.tone === 'rejected' && <span className="algo-call-result">剪枝</span>}
          {call.tone === 'done' && <span className="algo-call-result">答案</span>}
        </motion.li>)}
      </AnimatePresence>
    </ol>
    <div className="algo-call-stack"><span>调用栈</span>
      {stack.length ? stack.map((call, index) => <code key={`${index}-${call}`}>{call}</code>) : <span className="algo-empty">空</span>}
    </div>
  </div>;
}

export function AlgorithmIntervals({ intervals, cursor, max, minimum = 0, label = '区间与事件扫描' }: {
  intervals: readonly { id: string; start: number; end: number; tone?: Tone }[]; cursor: number; max: number; minimum?: number; label?: string;
}) {
  const transition = useSceneMotion();
  const span = max - minimum || 1;
  const tickCount = Math.min(10, Math.ceil(span));
  return <div className="algo-intervals" role="group" aria-label={label} data-learning-component="algorithm-intervals">
    <div className="algo-time-axis">{Array.from({ length: tickCount + 1 }, (_, index) =>
      <span key={index} style={{ left: `${index / tickCount * 100}%` }}>{Number((minimum + span * index / tickCount).toPrecision(4))}</span>)}</div>
    <div className="algo-interval-tracks">
      <motion.div className="algo-scan-line" initial={false} animate={{ left: `${(cursor - minimum) / span * 100}%` }} transition={transition} aria-hidden="true" />
      {intervals.map((interval) => <div key={interval.id} className="algo-interval-row">
        <div className="algo-interval" data-tone={interval.tone}
          style={{ left: `${(interval.start - minimum) / span * 100}%`, width: `${(interval.end - interval.start) / span * 100}%` }}
          aria-label={`${interval.id}，${interval.start} 到 ${interval.end}，${toneNames[interval.tone ?? 'idle']}`}>
          {interval.id}<span>{interval.start}–{interval.end}</span>
        </div>
      </div>)}
    </div>
  </div>;
}

function BitOperandRow({ row, width }: { row: { label: string; value: number }; width: number }) {
  const present = useIsPresent();
  const reduced = useReducedMotion();
  const transition = { duration: reduced ? 0 : .26, ease: [.22, 1, .36, 1] as [number, number, number, number] };
  return <motion.div className="algo-bit-row-shell" data-operand={row.label} aria-hidden={!present || undefined}
    initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
    exit={{ height: 0, opacity: 0 }} transition={transition}>
    <div className="algo-bit-row" role="group" aria-label={`${row.label} 等于 ${row.value}`}>
      <code>{row.label}</code>
      {row.value.toString(2).padStart(width, '0').split('').map((bit, i) =>
        <span key={i} className="algo-cell" data-tone={bit === '1' ? 'active' : 'idle'} aria-label={`第 ${width - 1 - i} 位：${bit}`}>
          <span className="algo-bit-glyphs" aria-hidden="true">
            <AnimatePresence initial={false}>
              <motion.span key={bit} initial={{ y: reduced ? 0 : 10, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
                exit={{ y: reduced ? 0 : -10, opacity: 0 }} transition={transition}>{bit}</motion.span>
            </AnimatePresence>
          </span>
        </span>)}
    </div>
  </motion.div>;
}

export function AlgorithmBits({ rows, width = 8, label = '位与数值变化' }: {
  rows: readonly { label: string; value: number }[]; width?: number; label?: string;
}) {
  return <div className="algo-bits" role="group" aria-label={label} data-learning-component="algorithm-bits"
    style={{ '--algo-bit-count': width } as CSSProperties}>
    <div className="algo-bit-positions"><span>位</span>{Array.from({ length: width }, (_, i) => <span key={i}>{width - 1 - i}</span>)}</div>
    <AnimatePresence initial={false}>
      {rows.map((row) => <BitOperandRow key={row.label} row={row} width={width} />)}
    </AnimatePresence>
  </div>;
}

export function AlgorithmGeometry({ points, links, extent = 8, minimum = 0, label = '坐标与几何' }: {
  points: readonly { id: string; x: number; y: number }[]; links: readonly Edge[]; extent?: number; minimum?: number; label?: string;
}) {
  const id = useId();
  const span = extent - minimum || 1;
  const x = (value: number) => 120 + (value - minimum) / span * 240;
  const y = (value: number) => 275 - (value - minimum) / span * 240;
  const gridSize = 240 / Math.min(16, span);
  return <svg className="algo-geometry" viewBox="0 0 490 310" role="img" aria-label={label} data-learning-component="algorithm-geometry">
    <title>{points.map((point) => `${point.id} (${point.x}, ${point.y})`).join('；')}</title>
    <defs><pattern id={`${id}-grid`} width={gridSize} height={gridSize} x="120" y="35" patternUnits="userSpaceOnUse">
      <path d={`M ${gridSize} 0 H 0 V ${gridSize}`} className="algo-coordinate-grid" />
    </pattern></defs>
    <rect x="120" y="35" width="240" height="240" fill={`url(#${id}-grid)`} />
    <path d={`M ${x(0)} 28 V 275 M 120 ${y(0)} H 370`} className="algo-coordinate-axis" />
    {Array.from({ length: 5 }, (_, i) => Number((minimum + span * i / 4).toPrecision(4))).map((n) => <g key={n} className="algo-coordinate-label">
      <text x={x(n)} y="298" textAnchor="middle">{n}</text><text x="107" y={y(n) + 5} textAnchor="end">{n}</text>
    </g>)}
    {links.map((link, i) => {
      const a = points.find((point) => point.id === link.from)!;
      const b = points.find((point) => point.id === link.to)!;
      return <line key={`${link.from}-${link.to}-${i}`} className="algo-edge" data-tone={link.tone}
        x1={x(a.x)} y1={y(a.y)} x2={x(b.x)} y2={y(b.y)} />;
    })}
    {points.map((point) => <g key={point.id} className="algo-coordinate-point">
      <circle cx={x(point.x)} cy={y(point.y)} r="6" /><text x={x(point.x) + 12} y={y(point.y) - 12}>{point.id}</text>
    </g>)}
  </svg>;
}

export type AlgorithmStep<T> = { line: number; note: string; variables: Record<string, string | number>; scene: T };
export function AlgorithmPlayer<T>({ title, code, steps, renderScene, active = true, showCode = true, showVariables = true,
  step: controlledStep, onStep }: {
  title: string; code: readonly string[]; steps: readonly AlgorithmStep<T>[];
  renderScene: (scene: T) => ReactNode; active?: boolean; showCode?: boolean; showVariables?: boolean;
  step?: number; onStep?: (step: number) => void;
}) {
  const id = useId();
  const [localStep, setLocalStep] = useState(0);
  const step = controlledStep ?? localStep;
  const stepChanged = useRef(onStep);
  stepChanged.current = onStep;
  const setStep = (next: number) => { setLocalStep(next); stepChanged.current?.(next); };
  const [playing, setPlaying] = useState(false);
  const last = steps.length - 1;
  const index = Math.min(step, last);
  const frame = steps[index];
  useEffect(() => { setLocalStep(0); setPlaying(false); }, [steps]);
  useEffect(() => {
    if (!active || index >= last) { setPlaying(false); return; }
    if (!playing) return;
    const timer = window.setTimeout(() => setStep(Math.min(index + 1, last)), 1100);
    return () => window.clearTimeout(timer);
  }, [active, playing, index, last]);
  useEffect(() => {
    const pauseWhenHidden = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener('visibilitychange', pauseWhenHidden);
    return () => document.removeEventListener('visibilitychange', pauseWhenHidden);
  }, []);
  const seek = (next: number) => { setPlaying(false); setStep(Math.max(0, Math.min(last, next))); };
  if (!frame) return <p>暂无演示步骤。</p>;
  return <section className="algo-player" aria-label={title} data-learning-component="algorithm-player" data-step={index} data-playing={playing}>
    <h4>{title}</h4>
    <div className="algo-workbench" data-code-visible={showCode}>
      <div className="algo-stage" role="group" aria-label={`${title}画面`}>{renderScene(frame.scene)}</div>
      {showCode && <div className="algo-code" role="group" aria-label={`${title}示意代码`}>
        <ol>{code.map((line, i) => <li key={i} data-active={frame.line === i + 1} aria-current={frame.line === i + 1 ? 'step' : undefined}>
          <span className="algo-line-number" aria-hidden="true">{i + 1}</span><code>{line || ' '}</code>
        </li>)}</ol>
      </div>}
    </div>
    <div className="algo-observation" aria-live={playing ? 'off' : 'polite'} aria-atomic="true">
      <p><AnimatedText block>{frame.note}</AnimatedText></p>
      {showVariables && <dl className="algo-variables">{Object.entries(frame.variables).map(([name, value]) =>
        <div key={name}><dt>{name}</dt><dd><AnimatedText>{value}</AnimatedText></dd></div>)}</dl>}
    </div>
    <div className="algo-controls">
      <ArtifactAction icon={PhosphorRefresh} label={`${title}：重置`} disabled={index === 0 && !playing} onClick={() => seek(0)} />
      <ArtifactAction icon={StepBack} label={`${title}：上一步`} disabled={index === 0} onClick={() => seek(index - 1)} />
      <ArtifactAction primary icon={playing ? PhosphorPause : PhosphorPlay} completed={index === last}
        label={`${title}：${playing ? '暂停' : index === last ? '重新播放' : '播放'}`}
        onClick={() => { if (index === last) setStep(0); setPlaying((current) => !current); }} />
      <ArtifactAction icon={StepForward} label={`${title}：下一步`} disabled={index === last} onClick={() => seek(index + 1)} />
      <label className="sr-only" htmlFor={`${id}-progress`}>{title}步骤</label>
      <input id={`${id}-progress`} className="algo-progress" type="range" min={0} max={last} step={1} value={index}
        style={{ '--algo-progress': `${last > 0 ? index / last * 100 : 0}%` } as CSSProperties}
        aria-valuetext={`第 ${index + 1} 步，共 ${steps.length} 步`} onChange={(event) => seek(event.target.valueAsNumber)} />
      <output className="algo-position">
        <span className="algo-position-current" style={{ width: `${String(steps.length).length}ch` }}>
          <AnimatedText>{index + 1}</AnimatedText>
        </span><span className="algo-position-total"> / {steps.length}</span>
      </output>
    </div>
  </section>;
}
