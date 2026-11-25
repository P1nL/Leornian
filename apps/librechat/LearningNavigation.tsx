import type { ReactNode } from 'react';
import { Check, ChevronRight, Circle, Folder, LockKeyhole } from 'lucide-react';

export function LearningRouteFolder({ title, current, actions, children }: {
  title: string; current: boolean; actions?: ReactNode; children: ReactNode;
}) {
  return <details className="baseline-route" open={current || undefined}>
    <summary><Folder size={17} /><span>{title}</span>{actions}
      <ChevronRight className="baseline-route-chevron" size={15} /></summary>
    {children}
  </details>;
}

export function LearningRouteNode({ title, index, unlocked, studied, current, busy, onOpen }: {
  title: string; index: number; unlocked: boolean; studied: boolean; current: boolean;
  busy: boolean; onOpen: () => void;
}) {
  return <button className="baseline-node" disabled={!unlocked || busy}
    aria-current={current ? 'step' : undefined}
    title={!unlocked ? index === 0 ? '路线确认后开始学习' : '先学习前面的节点，或在收尾时选择结束本节' : undefined}
    onClick={onOpen}>
    {!unlocked ? <LockKeyhole size={14} /> : studied ? <Check size={14} /> : <Circle size={13} />}
    <span>{index + 1}. {title}</span>
  </button>;
}
