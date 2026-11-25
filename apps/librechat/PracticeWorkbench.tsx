import { useEffect, useId, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import type { KeyboardEvent, ReactNode } from 'react';
import { Code2, ListChecks, Maximize2, Play, Square, Terminal } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import {
  OGDialog, OGDialogContent, OGDialogHeader, OGDialogTitle,
  ResizableHandle, ResizablePanel, ResizablePanelGroup,
} from '@librechat/client';
import useScaledMaxWidth from '~/hooks/useScaledMaxWidth';
import { actionSpring, ArtifactAction } from './LearningUI';
import type { ActionPhase } from './LearningUI';

export type WorkbenchTab = { id: string; label: string; icon?: LucideIcon; content: ReactNode };
type WorkbenchProps = {
  title: string;
  terminal?: ReactNode;
  onStop?: () => void;
  stopping?: boolean;
  tabs: WorkbenchTab[];
  language: ReactNode;
  editor: ReactNode;
  files?: { tabs: WorkbenchTab[]; selected: string; onSelect: (value: string) => void };
  tools?: ReactNode;
  tests?: ReactNode;
  result?: ReactNode;
  hasResult: boolean;
  busy: boolean;
  runDisabled: boolean;
  runLabel: string;
  runPhase?: ActionPhase;
  onRun: () => void;
};

export function TabBar({ id, label, tabs, selected, onSelect }: {
  id: string; label: string; tabs: { id: string; label: string; icon?: LucideIcon }[];
  selected: string; onSelect: (value: string) => void;
}) {
  const reduced = useReducedMotion();
  const indicatorId = useId();
  const navigate = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = tabs.findIndex((tab) => tab.id === selected);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : event.key === 'ArrowRight' ? (index + 1) % tabs.length
        : event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length : null;
    if (next === null) return;
    event.preventDefault();
    onSelect(tabs[next].id);
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  };
  return <motion.div layoutScroll className="demo-workbench-tabs" role="tablist" aria-label={label} onKeyDown={navigate}>
    {tabs.map((tab) => {
      const Icon = tab.icon;
      return <motion.button key={tab.id} type="button" role="tab" title={tab.label}
        id={`${id}-tab-${tab.id}`} aria-controls={`${id}-panel-${tab.id}`}
        aria-selected={selected === tab.id} tabIndex={selected === tab.id ? 0 : -1}
        whileTap={reduced ? undefined : { opacity: .7 }} transition={actionSpring}
        onClick={() => onSelect(tab.id)}>
        {selected === tab.id && <motion.span className="demo-tab-indicator" aria-hidden="true"
          layoutId={indicatorId} transition={reduced ? { duration: 0 } : { ...actionSpring, damping: 38 }} />}
        {Icon && <Icon size={16} aria-hidden="true" />}<span>{tab.label}</span></motion.button>;
    })}
  </motion.div>;
}

export function TabPanels({ id, tabs, selected, panelClassName = '', className = '', autoHeight = false }: {
  id: string; tabs: WorkbenchTab[]; selected: string; panelClassName?: string; className?: string; autoHeight?: boolean;
}) {
  const reduced = useReducedMotion();
  return <div className={`demo-tab-panels${autoHeight ? ' demo-tab-panels-auto' : ''} ${className}`}>
    {tabs.map((tab) => {
      const active = tab.id === selected;
      return <motion.div key={tab.id} role="tabpanel" tabIndex={active ? 0 : -1}
        id={`${id}-panel-${tab.id}`} aria-labelledby={`${id}-tab-${tab.id}`}
        aria-hidden={!active} {...(!active ? { inert: '' } : {})}
        className={`demo-tab-panel ${panelClassName}`} initial={false}
        animate={{ opacity: active ? 1 : 0, y: reduced || active ? 0 : 7 }}
        transition={{ duration: reduced ? .08 : .2, ease: 'easeOut' }}>
        {tab.content}
      </motion.div>;
    })}
  </div>;
}

function Surface({ expanded, onExpand, ...props }: WorkbenchProps & {
  expanded: boolean; onExpand: () => void;
}) {
  const id = useId();
  const narrow = useScaledMaxWidth(900);
  const [left, setLeft] = useState(props.tabs[0].id);
  const [bottom, setBottom] = useState(props.hasResult || props.busy ? 'result' : 'tests');
  useEffect(() => {
    if (props.busy || props.hasResult) setBottom('result');
  }, [props.busy, props.hasResult]);
  const example = props.terminal != null;
  const bottomTabs = [{ id: 'tests', label: '测试用例', icon: ListChecks },
    { id: 'result', label: '运行结果', icon: Terminal }];
  const description = <section className="demo-workbench-pane demo-workbench-description" aria-label={example ? '示例说明' : '题目与学习工具'}>
    <div className="demo-workbench-pane-heading">
      <TabBar id={`${id}-left`} label={example ? '示例工具' : '题目功能'} tabs={props.tabs} selected={left} onSelect={setLeft} />
    </div>
    <TabPanels id={`${id}-left`} tabs={props.tabs} selected={left} panelClassName="demo-workbench-content" />
  </section>;
  const editor = <section className="demo-workbench-pane demo-workbench-code" aria-label="代码编辑区">
    <div className="demo-workbench-pane-heading">
      <Code2 size={16} aria-hidden="true" /><strong>代码</strong>
      {!expanded && <ArtifactAction icon={Maximize2} label="放大代码工作台"
        className="demo-workbench-expand" onClick={onExpand} />}
    </div>
    <div className="demo-workbench-language">{props.language}</div>
    {props.files && <div className="demo-workbench-files"><TabBar id={`${id}-files`} label="项目文件" {...props.files} /></div>}
    <div className="demo-workbench-editor">{props.files
      ? <TabPanels id={`${id}-files`} tabs={props.files.tabs} selected={props.files.selected} />
      : props.editor}</div>
    <div className="demo-workbench-runbar">
      <div className="demo-workbench-tools">{props.tools}</div>
      {props.onStop ? <ArtifactAction icon={Square} label="停止运行" primary disabled={props.stopping}
        onClick={props.onStop}>停止</ArtifactAction> : <ArtifactAction icon={Play} label={props.runLabel} primary busy={props.busy} phase={props.runPhase}
        disabled={props.runDisabled} onClick={() => { setBottom('result'); props.onRun(); }}>
        {example ? (props.busy ? '运行中' : props.runLabel)
          : props.busy ? '检查中' : props.runPhase === 'completed' ? '已检查' : props.runPhase === 'attention' ? '需修改' : props.runPhase === 'unknown' ? '结果未知' : '运行检查'}
      </ArtifactAction>}
    </div>
  </section>;
  const results = example ? <section className="demo-workbench-pane demo-workbench-results" aria-label="终端">
    <div className="demo-workbench-pane-heading"><Terminal size={16} aria-hidden="true" /><strong>终端</strong></div>
    {props.terminal}
  </section> : <section className="demo-workbench-pane demo-workbench-results" aria-label="测试用例与运行结果">
    <div className="demo-workbench-pane-heading">
      <TabBar id={`${id}-bottom`} label="检查面板" tabs={bottomTabs} selected={bottom} onSelect={setBottom} />
    </div>
    <TabPanels id={`${id}-bottom`} selected={bottom} panelClassName="demo-workbench-content"
      tabs={bottomTabs.map((tab) => ({ ...tab, content: tab.id === 'tests' ? props.tests : props.result }))} />
  </section>;
  const right = <ResizablePanelGroup orientation="vertical" className="demo-workbench-right">
    <ResizablePanel defaultSize="64%" minSize="42%" className="demo-workbench-resizable">{editor}</ResizablePanel>
    <ResizableHandle className="demo-workbench-resizer" aria-label="调整编辑器与结果区高度" />
    <ResizablePanel defaultSize="36%" minSize="22%" className="demo-workbench-resizable">{results}</ResizablePanel>
  </ResizablePanelGroup>;
  return <div className={`learning-demo demo-workbench${narrow ? ' demo-workbench-stacked' : ''}`}
    data-learning-demo aria-label={`${props.title}代码工作台`}>
    {narrow ? <>{description}{right}</> : <ResizablePanelGroup orientation="horizontal">
      <ResizablePanel defaultSize="43%" minSize="28%" className="demo-workbench-resizable">{description}</ResizablePanel>
      <ResizableHandle className="demo-workbench-resizer" aria-label={example ? '调整说明与代码区宽度' : '调整题目与代码区宽度'} />
      <ResizablePanel defaultSize="57%" minSize="40%" className="demo-workbench-resizable">{right}</ResizablePanel>
    </ResizablePanelGroup>}
  </div>;
}

export default function PracticeWorkbench(props: WorkbenchProps) {
  const [expanded, setExpanded] = useState(false);
  return <>
    <Surface {...props} expanded={false} onExpand={() => setExpanded(true)} />
    <OGDialog open={expanded} onOpenChange={setExpanded}>
      <OGDialogContent title={props.title} className="demo-workbench-dialog text-text-primary">
        <OGDialogHeader><OGDialogTitle>{props.title}</OGDialogTitle></OGDialogHeader>
        <Surface {...props} expanded onExpand={() => {}} />
      </OGDialogContent>
    </OGDialog>
  </>;
}
