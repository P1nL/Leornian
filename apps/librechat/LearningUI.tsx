import { Children, forwardRef, isValidElement, useId, useState } from 'react';
import { AnimatePresence, motion, useIsPresent, useReducedMotion } from 'framer-motion';
import { OGDialog, OGDialogContent, OGDialogHeader, OGDialogTitle, TooltipAnchor } from '@librechat/client';
import { ChevronRight, CircleAlert, LoaderCircle, Maximize2 } from 'lucide-react';
import type { ReactNode, ButtonHTMLAttributes } from 'react';
import { importantIcon, PhosphorCheck, PhosphorPlay, PhosphorSpinner, PhosphorWarning } from './PhosphorIcons';
import type { ActionIcon } from './PhosphorIcons';
import './learning-demo.css';
import './learning-motion.css';

export const actionSpring = { type: 'spring' as const, stiffness: 420, damping: 27, mass: .7 };
export type ActionPhase = 'idle' | 'busy' | 'completed' | 'attention' | 'unknown';
type ActionProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onDrag' | 'onDragStart' | 'onDragEnd' | 'onAnimationStart'> & {
  primary?: boolean; important?: boolean; completed?: boolean; busy?: boolean; phase?: ActionPhase;
  icon?: ActionIcon;
  resetHoverOnClick?: boolean;
};

function FoldingLabel({ children, phase }: { children: ReactNode; phase: ActionPhase }) {
  const reduced = useReducedMotion();
  const text = typeof children === 'string' || typeof children === 'number' ? String(children) : null;
  return <span className="demo-command-label" aria-hidden={text !== null}>
    <AnimatePresence initial={false} mode="popLayout">
      <motion.span key={`${phase}:${text}`} className="demo-label-words" initial="enter" animate="settle" exit="fold"
        variants={{
          enter: {},
          settle: { transition: { staggerChildren: reduced ? 0 : .022, delayChildren: reduced ? 0 : .11 } },
          fold: { transition: { staggerChildren: reduced ? 0 : .016, staggerDirection: -1 } },
        }}>
        {(text ? [...text] : [children]).map((character, index) => <motion.span key={index}
          className="demo-label-letter" variants={{
            enter: { opacity: 0, y: reduced ? 0 : 7, rotateX: reduced ? 0 : -80, scaleX: reduced ? 1 : .6 },
            settle: { opacity: 1, y: 0, rotateX: 0, scaleX: 1, transition: reduced ? { duration: .1 } : actionSpring },
            fold: { opacity: 0, y: reduced ? 0 : -5, rotateX: reduced ? 0 : 90, scaleX: reduced ? 1 : .2, transition: { duration: reduced ? .08 : .17 } },
          }}>{character === ' ' ? '\u00a0' : character}</motion.span>)}
      </motion.span>
    </AnimatePresence>
  </span>;
}

export const Action = forwardRef<HTMLButtonElement, ActionProps>(function Action({ primary = false, important = primary, completed = false, busy = false,
  phase: requestedPhase, icon: Icon, children, className = '', disabled, onClick,
  resetHoverOnClick = false, onPointerMove, ...props }, ref) {
  const reduced = useReducedMotion();
  const [suppressHover, setSuppressHover] = useState(false);
  const phase = busy ? 'busy' : requestedPhase ?? (completed ? 'completed' : 'idle');
  const blocked = disabled || phase === 'busy';
  const idleIcon = importantIcon(Icon);
  const completedIcon = idleIcon === PhosphorPlay ? PhosphorPlay : PhosphorCheck;
  const DisplayIcon = important
    ? phase === 'busy' ? PhosphorSpinner : phase === 'completed' ? completedIcon
      : ['attention', 'unknown'].includes(phase) ? PhosphorWarning : idleIcon
    : phase === 'busy' ? LoaderCircle : ['attention', 'unknown'].includes(phase) ? CircleAlert : Icon;
  const name = props['aria-label'] ?? (typeof children === 'string' ? children : undefined);
  const stateName = phase === 'busy' ? '处理中' : phase === 'completed' ? '已完成' : phase === 'attention' ? '需修改' : phase === 'unknown' ? '结果未知' : '';
  const button = <motion.button ref={ref} type="button" {...props} aria-label={name} aria-busy={phase === 'busy' || undefined}
    disabled={blocked} data-action-state={phase} data-completed={phase === 'completed' || undefined}
    data-important={important || undefined}
    data-suppress-hover={suppressHover || undefined}
    className={`demo-action demo-motion-button${primary ? ' demo-primary' : ''}${important ? ' demo-command-icon' : ''} ${className}`}
    layout={false}
    transition={reduced ? { duration: .1 } : actionSpring}
    onPointerMove={(event) => { if (suppressHover) setSuppressHover(false); onPointerMove?.(event); }}
    onClick={(event) => { if (resetHoverOnClick) setSuppressHover(true); onClick?.(event); }}>
    {(Icon || important || phase !== 'idle') && <span className="demo-command-symbol" aria-hidden="true">
      <AnimatePresence initial={false}>
        <motion.span key={`${phase}:${DisplayIcon?.displayName ?? ''}`} className="demo-command-glyph"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: reduced ? .08 : .18 }}>
          {phase === 'completed' && !important ? <motion.svg className="demo-completion-disc" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="11" />
            <motion.path d="m6.5 12 3.5 3.5 7.5-8" fill="none" stroke="white" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" initial={{ pathLength: reduced ? 1 : 0 }}
              animate={{ pathLength: 1 }} transition={{ duration: reduced ? 0 : .25, delay: reduced ? 0 : .12 }} />
          </motion.svg> : DisplayIcon ? <DisplayIcon size={17} className={phase === 'busy' ? 'demo-command-spinner' : undefined} /> : null}
        </motion.span>
      </AnimatePresence>
    </span>}
    {!important && children && <FoldingLabel phase={phase}>{children}</FoldingLabel>}
  </motion.button>;
  return important ? <TooltipAnchor description={`${name}${stateName ? ` · ${stateName}` : ''}`} render={button} /> : button;
});

export function ArtifactAction({ label, children, className = '', ...props }: ActionProps & {
  icon: ActionIcon; label: string;
}) {
  const important = props.important ?? props.primary ?? false;
  const button = <Action {...props} aria-label={label} data-artifact-command
    className={`demo-artifact-command${!children || important ? ' demo-command-icon' : ''} ${className}`}>{children}</Action>;
  return important ? button : <TooltipAnchor description={label} render={button} />;
}

function TransitionBody({ children }: { children: ReactNode }) {
  const present = useIsPresent();
  const reduced = useReducedMotion();
  return <motion.div className="demo-motion-stage" data-leaving={!present || undefined}
    {...(!present ? { inert: '' } : {})}
    initial={{ opacity: 0, y: reduced ? 0 : 6 }} animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: reduced ? 0 : -6 }} transition={{ duration: reduced ? .08 : .18 }}>
    {children}
  </motion.div>;
}

export function ContentTransition({ stage, children }: { stage: string; children: ReactNode }) {
  return <AnimatePresence initial={false} mode="wait"><TransitionBody key={stage}>{children}</TransitionBody></AnimatePresence>;
}

export function Collapse({ open, children, id }: { open: boolean; children: ReactNode; id?: string }) {
  return <div id={id} className="demo-collapse" data-open={open} aria-hidden={!open}
    {...(!open ? { inert: '' } : {})}>
    <div className="demo-collapse-clip"><div className="demo-collapse-content">{children}</div></div>
  </div>;
}

export function Disclosure({ title, children, defaultOpen = false, open: controlledOpen, onOpenChange, className = '' }: {
  title: ReactNode; children: ReactNode; defaultOpen?: boolean; open?: boolean;
  onOpenChange?: (open: boolean) => void; className?: string;
}) {
  const id = useId();
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const open = controlledOpen ?? localOpen;
  return <div className={`demo-disclosure ${className}`}>
    <button type="button" className="demo-disclosure-toggle" aria-expanded={open} aria-controls={id}
      onClick={() => { setLocalOpen(!open); onOpenChange?.(!open); }}>
      <ChevronRight size={16} aria-hidden="true" /><AnimatedText>{title}</AnimatedText>
    </button>
    <Collapse id={id} open={open}>{children}</Collapse>
  </div>;
}

export function DemoDialog({ open, onClose, title, children }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode;
}) {
  return <OGDialog open={open} onOpenChange={(value) => { if (!value) onClose(); }}>
    <OGDialogContent title={title} className="demo-motion-dialog text-text-primary w-11/12 max-w-3xl">
      <OGDialogHeader><OGDialogTitle>{title}</OGDialogTitle></OGDialogHeader>
      <div className="learning-demo demo-dialog-body" data-learning-demo>{children}</div>
    </OGDialogContent>
  </OGDialog>;
}

export function ArtifactFrame({ id, title, kind, state = 'ready', children }: {
  id: string; title: string; kind: string; state?: string; children: ReactNode;
}) {
  return <section className="learning-demo demo-artifact" data-learning-demo data-artifact-id={id}
    data-presentation={kind} data-artifact-state={state} aria-label={title}>
    <header className="demo-section-heading"><h3>{title}</h3></header>
    <div className="demo-artifact-body">{children}</div>
  </section>;
}

export function CodeEditor({ label, value, onChange, readOnly = false, embedded = false }: {
  label: string; value: string; onChange?: (value: string) => void; readOnly?: boolean; embedded?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const editor = (large = false) => <div className={`demo-editor${large ? ' demo-editor-large' : ''}`}>
    <pre aria-hidden="true" className="demo-line-numbers">{value.split('\n').map((_, index) => index + 1).join('\n')}</pre>
    <textarea aria-label={large ? `${label}（放大）` : label} value={value} readOnly={readOnly}
      autoComplete="off" autoCapitalize="off" spellCheck={false}
      onChange={(event) => onChange?.(event.target.value)}
      onScroll={(event) => {
        const gutter = event.currentTarget.previousElementSibling;
        if (gutter) gutter.scrollTop = event.currentTarget.scrollTop;
      }}
      onKeyDown={(event) => {
        if (event.key !== 'Tab' || readOnly) return;
        event.preventDefault();
        const input = event.currentTarget;
        const start = input.selectionStart;
        onChange?.(`${value.slice(0, start)}  ${value.slice(input.selectionEnd)}`);
        requestAnimationFrame(() => { input.selectionStart = input.selectionEnd = start + 2; });
      }} />
  </div>;
  return <div className={`demo-code-field${embedded ? ' demo-code-field-embedded' : ''}`}>
    {!embedded && <div className="demo-editor-heading"><span>{label}{readOnly ? ' · 只读' : ''}</span>
      <ArtifactAction icon={Maximize2} label={`放大${label}`} onClick={() => setExpanded(true)} />
    </div>}
    {editor()}
    {!embedded && <DemoDialog open={expanded} onClose={() => setExpanded(false)} title={label}>{editor(true)}</DemoDialog>}
  </div>;
}

function copyText(children: ReactNode): string {
  return Children.toArray(children).map((child) => isValidElement<{ children?: ReactNode }>(child)
    ? copyText(child.props.children) : String(child)).join('');
}

function CopyLayer({ children }: { children: ReactNode }) {
  const present = useIsPresent();
  const reduced = useReducedMotion();
  return <motion.span className="demo-copy-layer" data-leaving={!present || undefined}
    aria-hidden={!present || undefined}
    initial={{ opacity: 0, y: reduced ? 0 : 4 }} animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: reduced ? 0 : -4 }} transition={{ duration: reduced ? 0 : .2 }}>
    {children}
  </motion.span>;
}

// Text-only content: do not wrap editors, inputs or interactive controls.
export function AnimatedText({ children, block = false }: { children: ReactNode; block?: boolean }) {
  return <span className="demo-animated-copy" data-block={block || undefined}>
    <AnimatePresence><CopyLayer key={copyText(children)}>{children}</CopyLayer></AnimatePresence>
  </span>;
}

export function Notice({ children }: { children: ReactNode }) {
  return <p className="demo-notice" role="status"><AnimatedText block>{children}</AnimatedText></p>;
}
