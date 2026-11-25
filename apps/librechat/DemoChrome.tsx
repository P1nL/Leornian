import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion, useIsPresent, useReducedMotion } from 'framer-motion';
import * as Ariakit from '@ariakit/react';
import { useNavigate } from 'react-router-dom';
import { Button, DropdownPopup, OGDialog, OGDialogContent, OGDialogHeader, OGDialogTitle } from '@librechat/client';
import { ListTodo, Ellipsis, X, Paperclip, ArrowUp, BookOpen, PackageCheck, ShieldCheck } from 'lucide-react';
import useScaledMaxWidth from '~/hooks/useScaledMaxWidth';
import { ARTIFACTS_SHEET_MAX_WIDTH } from '~/utils/breakpoints';
import { Action, AnimatedText, Collapse, DemoDialog, Disclosure, Notice, useDemo } from './DemoUI';
import { demoStore } from './demo-state.mjs';
import { readingDocuments } from './learning-demo-data.mjs';
import { artifactGalleryPath } from './artifact-catalog.mjs';
import { RouteWidget, ReviewActivity, MaterialUpdate, InstallationDialog } from './LearningArtifacts';
import { LearningComposerFrame, LearningStartFrame, LearningTaskPopover } from './LearningChrome';

type ReaderSelection = { id: string; block: number };

function ReaderContent({ selection }: { selection: ReaderSelection }) {
  const state = useDemo();
  const document = selection ? readingDocuments[selection.id] : null;
  const target = useRef<HTMLElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const pane = viewport.current;
    const block = target.current;
    if (!pane || !block) return;
    // Source navigation must never scroll the conversation's ancestors.
    const top = pane.scrollTop + block.getBoundingClientRect().top - pane.getBoundingClientRect().top
      - (pane.clientHeight - block.offsetHeight) / 2;
    pane.scrollTo({ top: Math.max(0, top) });
  }, [selection?.id, selection?.block]);
  if (!document) return null;
  return <div ref={viewport} className="demo-reader-content">
    {!state.material.permitted ? <Notice>当前演示已撤销使用权限，不再展示正文。</Notice> : <>
      <p className="demo-muted">文档 {selection.id} · 固定版本 {document.version} · {document.section}</p>
      <p className="demo-muted">这是精确引用的旧版本；接受教材新版也不改写这个引用。</p>
      {document.blocks.map((text: string, index: number) => index === selection.block
        ? <mark ref={target} tabIndex={-1} key={index}>原文块 {index + 1}：{text}</mark>
        : <p key={index}>{text}</p>)}
    </>}
  </div>;
}

function ReaderPane({ selection }: { selection: ReaderSelection }) {
  const present = useIsPresent();
  const reduced = useReducedMotion();
  return <motion.aside className="learning-demo demo-reader" data-learning-demo data-open={present}
    aria-label="教材阅读面板" {...(!present ? { inert: '' } : {})}
    initial={{ opacity: 0, x: reduced ? 0 : 28 }} animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: reduced ? 0 : 28 }} transition={{ duration: reduced ? 0 : .28, ease: [.22, 1, .36, 1] }}>
    <div className="demo-reader-header"><h3>{readingDocuments[selection.id]?.title}</h3>
      <button type="button" className="demo-icon-button" aria-label="关闭教材阅读"
        onClick={() => demoStore.update({ reader: null })}><X size={18} /></button></div>
    <ReaderContent selection={selection} />
  </motion.aside>;
}

export function DemoReader() {
  const state = useDemo();
  const isSmall = useScaledMaxWidth(ARTIFACTS_SHEET_MAX_WIDTH);
  const title = state.reader ? readingDocuments[state.reader.id]?.title : '';
  const close = () => demoStore.update({ reader: null });
  if (isSmall) return title ? <OGDialog open onOpenChange={(value) => { if (!value) close(); }}>
    <OGDialogContent title={title} className="text-text-primary w-11/12">
      <OGDialogHeader><OGDialogTitle>{title}</OGDialogTitle></OGDialogHeader>
      <div className="learning-demo" data-learning-demo><ReaderContent selection={state.reader} /></div>
    </OGDialogContent>
  </OGDialog> : null;
  return <AnimatePresence>{title && <ReaderPane key="reader" selection={state.reader} />}</AnimatePresence>;
}

export function DemoSourcePanel({ children, panel, NativeGroup }: any) {
  const selection = useDemo().reader;
  return <ReaderLayout>
    <div className="demo-source-chat-canvas">
      <NativeGroup panel={selection ? null : panel}>{children}</NativeGroup>
    </div>
  </ReaderLayout>;
}

export function ReaderLayout({ children, className = '' }: { children: ReactNode; className?: string }) {
  const isSmall = useScaledMaxWidth(ARTIFACTS_SHEET_MAX_WIDTH);
  return <div className={`demo-source-layout ${className}`} data-reader-docked={!isSmall}>
    <div className="demo-source-main">{children}</div>
    <DemoReader />
  </div>;
}

const taskLabels: Record<string, string> = {
  running: '进行中', completed: '交互模拟已完成', waiting_config: '等待本人模型配置',
  unknown: '结果未知，不自动重发', cancelled: '已取消，历史保留', failed: '失败历史保留',
  superseded: '已被新版本替代，历史保留',
};
export function DemoTasks({ conversationId }: { conversationId: string; [key: string]: any }) {
  const state = useDemo();
  const tasks = state.tasks.filter((task: any) => !task.conversationId || task.conversationId === conversationId);
  return <LearningTaskPopover label="后台任务（演示）"
    description="全部为前端状态演示；不设置“全部重试”，也不自动清除失败或未知历史。">
      {tasks.map((task: any) => <div key={task.id} className="demo-task-row">
        <div>{task.title}</div><p className="demo-muted"><AnimatedText block>{taskLabels[task.state] ?? task.state}</AnimatedText></p>
        {task.state === 'running' && <><div className="demo-progress" /><Action onClick={() => demoStore.cancelTask(task.id)}>取消本次演示过程</Action></>}
        {task.state === 'unknown' && <Disclosure title="查看未知状态说明"><p>没有完整回执。保留旧事实，不把它当作零调用或可自动重发。</p></Disclosure>}
        {task.state === 'waiting_config' && <p className="demo-muted">配置入口：头像 → 设置 → 模型配置。查看此任务不触发调用。</p>}
      </div>)}
  </LearningTaskPopover>;
}

export function LearningRecords() {
  const state = useDemo();
  const artifacts = Object.entries(state.artifacts) as [string, any][];
  const responses = artifacts.filter(([, entry]) => entry.submitted).length;
  const attempts = artifacts.reduce((count, [, entry]) => count + (entry.attempts?.length ?? 0), 0);
  const assisted = artifacts.filter(([, entry]) => entry.hints || entry.answerVisible);
  return <section aria-label="学习记录">
    <p>这里汇总你在本标签页的演示操作，不写入真实学习记录，也不显示虚构的掌握百分比。</p>
    <div className="demo-table-wrap"><table><thead><tr><th>维度</th><th>演示操作</th><th>正式证据</th></tr></thead>
      <tbody><tr><td>概念理解</td><td><AnimatedText>{responses} 次作答交互</AnimatedText></td><td>未创建</td></tr>
        <tr><td>实际执行</td><td><AnimatedText>{attempts} 次固定结果展示</AnimatedText></td><td>未执行、未创建</td></tr>
        <tr><td>新情境应用</td><td>等待独立的新题检验</td><td>未创建</td></tr></tbody></table></div>
    <h4>辅助使用</h4>
    {assisted.length === 0 ? <p>尚未查看提示或答案。</p> : assisted.map(([id, entry]) =>
      <p key={id}><AnimatedText block>{id}：已看 {entry.hints ?? 0} 层提示{entry.answerVisible ? '，已看直接答案' : ''}。记录不因修改代码消失。</AnimatedText></p>)}
    <h4>考试与复习</h4><p><AnimatedText block>整组考试提交：{state.exam.history.length} 次；复习自评：{state.review.rating ?? '尚未进行'}。</AnimatedText></p>
    <h4>历史状态</h4><p>演示任务中的失败、取消、结果未知和旧版本都保留，可从顶部任务按钮查看。</p>
  </section>;
}

export function DemoLearningMenu({ className = '' }: any) {
  const [isOpen, setIsOpen] = useState(false);
  const [dialog, setDialog] = useState('');
  const navigate = useNavigate();
  const id = useId();
  const items = [
    ['route', '查看当前路线'], ['records', '学习记录'], ['review', '到期复习'],
    ['materials', '教材与更新'], ['modes', '学习方式与提醒'],
  ].map(([value, label]) => ({ id: `demo-menu-${value}`, label, onClick: () => { setIsOpen(false); setDialog(value); } }));
  items.push({ id: 'demo-menu-artifacts', label: '学习工件一览', onClick: () => {
    setIsOpen(false); navigate(artifactGalleryPath);
  } });
  const titles: Record<string, string> = { route: '当前学习路线', records: '学习记录', review: '到期复习', materials: '教材与更新', modes: '学习方式与提醒' };
  return <>
    <DropdownPopup portal menuId={id} focusLoop unmountOnHide isOpen={isOpen} setIsOpen={setIsOpen} items={items}
      trigger={<Ariakit.MenuButton aria-label="当前学习菜单" render={<Button size="icon" variant="header-action" className={`relative size-9 shrink-0 ${className}`} />}>
        <Ellipsis size={20} />
      </Ariakit.MenuButton>} />
    <DemoDialog open={Boolean(dialog)} onClose={() => setDialog('')} title={titles[dialog] ?? '当前学习'}>
      {dialog === 'route' && <RouteWidget />}
      {dialog === 'records' && <LearningRecords />}
      {dialog === 'review' && <ReviewActivity />}
      {dialog === 'materials' && <MaterialUpdate />}
      {dialog === 'modes' && <DemoPreferences />}
    </DemoDialog>
  </>;
}

export function DemoPreferences() {
  const preferences = useDemo().preferences;
  return <section className="learning-demo" data-learning-demo aria-label="学习方式与提醒设置">
    <label>学习方式<select aria-label="学习方式" value={preferences.mode} onChange={(event) => demoStore.patch('preferences', { mode: event.target.value })}>
      <option value="guided">引导学习</option><option value="free_reading">自由阅读与问答</option>
    </select></label>
    <p className="demo-muted">自由阅读不默认连续推进。切换模式不会确认路线、开考或作答。</p>
    <label className="demo-choice"><input type="checkbox" checked={preferences.paused}
      onChange={(event) => demoStore.patch('preferences', { paused: event.target.checked })} /><span>暂停主动教学与提醒</span></label>
    <div className="demo-columns"><label>允许提醒的开始时间<input type="time" aria-label="提醒开始时间" value={preferences.from}
      onChange={(event) => demoStore.patch('preferences', { from: event.target.value })} /></label>
      <label>结束时间<input type="time" aria-label="提醒结束时间" value={preferences.to}
        onChange={(event) => demoStore.patch('preferences', { to: event.target.value })} /></label></div>
    <Notice>{preferences.paused ? '演示已暂停，不再显示主动续行提示。' : preferences.mode === 'free_reading' ? '自由阅读中，不自动推进。' : `演示提醒时段 ${preferences.from}—${preferences.to}。`}
      这些是本标签页的界面偏好，不创建后台定时任务。</Notice>
  </section>;
}

export function DemoEnvironmentSettings() {
  const state = useDemo();
  const [guide, setGuide] = useState(false);
  const [install, setInstall] = useState(false);
  const environment = state.environment;
  const labels: Record<string, string> = { missing: '未就绪', preparing: '正在模拟准备', ready: '界面样例已就绪', paused: '准备已暂停', waiting_authorization: '等待安装授权', deferred: '稍后准备', declined: '用户已拒绝', cancelled: '已取消' };
  return <section className="learning-demo" data-learning-demo aria-label="本机执行设置">
    <Notice>这里演示本机环境流程，不检测或安装系统组件，不修改全局 SDK，不提供远程 Runner。</Notice>
    <h4>本机隔离引擎</h4><p><AnimatedText block>{labels[environment.engine]}</AnimatedText></p>
    {environment.engine === 'preparing' && <div className="demo-progress" />}
    <Action disabled={['preparing', 'ready'].includes(environment.engine)} onClick={() => setGuide(true)}>查看首次准备引导</Action>
    <h4>课程专用环境</h4><p><AnimatedText block>Python / Flask 样例：{labels[environment.course]}</AnimatedText></p>
    <p className="demo-muted">基础语言支持和可信配方内置，实际环境按需准备，不一次安装全部 SDK。</p>
    <Action onClick={() => setInstall(true)}>查看课程环境与授权范围</Action>
    <InstallationDialog open={install} onClose={() => setInstall(false)} />
    <DemoDialog open={guide} onClose={() => setGuide(false)} title="首次准备本机隔离引擎">
      <p>正式流程会先检测兼容引擎，说明下载来源、系统权限及是否需要重启。当前不运行这些操作。</p>
      <p>引擎与课程依赖分别授权；已有可用引擎时应直接复用。</p>
      <Action primary icon={PackageCheck} onClick={() => {
        demoStore.patch('environment', { engine: 'preparing' });
        demoStore.task('engine', '本机引擎准备引导（演示）', {}, () => demoStore.patch('environment', { engine: 'ready' }));
        setGuide(false);
      }}>体验准备过程（不实际安装）</Action>
    </DemoDialog>
  </section>;
}

export function DemoFiles({ onRead = () => {} }: { onRead?: () => void }) {
  const state = useDemo();
  const [selected, setSelected] = useState('');
  const [attach, setAttach] = useState(false);
  const material = state.material;
  return <section className="learning-demo" data-learning-demo aria-label="演示材料详情">
    <div className="demo-actions"><Action onClick={() => setAttach(true)}>添加演示材料</Action>
      {Object.entries(readingDocuments).map(([id, document]: any) => <Action key={id} onClick={() => setSelected(id)}>{document.title} · 详情</Action>)}</div>
    <Collapse open={Boolean(selected)}>{selected && <>
      <h4>{readingDocuments[selected].title}</h4>
      <p><AnimatedText block>关联学习：{selected.includes('python') ? 'Python 入门' : 'SQL 复习'}；原文固定版本 1，当前路线采用版本 {material.version}。</AnimatedText></p>
      <p><AnimatedText block>处理状态样例：{({ sample: '内置样例', preparing: '处理中', parsed: '已提取，等待后续处理', ready: '演示准备完成', waiting_config: '已提取，等待本人模型配置', cancelled: '已取消，已有历史保留' } as Record<string, string>)[material.state]}</AnimatedText></p>
      <p>用途与保留期限分别管理，不默认七天到期；此演示只含公开编写的样例。</p>
      <div className="demo-actions"><Action disabled={!material.permitted} onClick={() => {
        demoStore.update({ reader: { id: selected, block: 1 } }); onRead();
      }}>阅读固定版本原文</Action>
        <Action onClick={() => demoStore.patch('material', { permitted: !material.permitted })}>
          {material.permitted ? '演示撤销使用权限' : '恢复样例使用权限'}
        </Action></div>
      {!material.permitted && <Notice>已撤销演示权限。阅读入口和已打开的阅读面板都停止展示正文，历史不删除。</Notice>}
      <MaterialUpdate />
    </>}</Collapse>
    <DemoAttachment open={attach} onClose={() => setAttach(false)} />
  </section>;
}

export function DemoAttachment({ open, onClose }: { open: boolean; onClose: () => void }) {
  const state = useDemo();
  const material = state.material;
  const [file, setFile] = useState('demo-python-functions');
  const begin = () => {
    demoStore.patch('material', { state: 'preparing' });
    demoStore.task('material', '材料提取与准备（演示）', {}, () => demoStore.patch('material', {
      state: state.models.saved && state.models.credential ? 'ready' : 'waiting_config',
    }));
    onClose();
  };
  return <DemoDialog open={open} onClose={onClose} title="添加学习材料">
    <p>选用内置公开样例体验上传后的流程。不读取真实文件、不进行 OCR 或材料外发。</p>
    <label>材料样例<select aria-label="材料样例" value={file} onChange={(event) => setFile(event.target.value)}>
      {Object.entries(readingDocuments).map(([id, document]: any) => <option key={id} value={id}>{document.title}.md</option>)}
    </select></label>
    <label className="demo-choice"><input type="checkbox" checked={material.purpose}
      onChange={(event) => demoStore.patch('material', { purpose: event.target.checked })} />
      <span>将这份演示材料用于当前学习；实际外发用途应另行明确。</span></label>
    <p className="demo-muted">使用截止与保留期限留空表示未声明真实期限，不自动填七天。</p>
    <Action primary icon={ShieldCheck} disabled={!material.purpose || material.state === 'preparing'} onClick={begin}>确认用途并体验准备过程</Action>
  </DemoDialog>;
}

export function DemoStart() {
  const state = useDemo();
  const navigate = useNavigate();
  const intake = state.intake;
  return <LearningStartFrame description="用下面的输入框体验目标补问。回复来自固定前端样例，不会发送给模型。">
    <Action onClick={() => navigate(artifactGalleryPath)}>查看学习工件一览</Action>
    {intake.step === 0 && <div className="demo-actions">{['我想用 Python 自动整理文件', '我想复习 SQL 分组查询', '我想做一个简单网页'].map((goal) =>
      <Action key={goal} onClick={() => demoStore.patch('intake', { goal, step: 1 })}>{goal}</Action>)}</div>}
    {intake.step >= 1 && <><p className="demo-qa-user"><AnimatedText block>你：{intake.goal}</AnimatedText></p><p><AnimatedText block>Tutor · 演示：你已有怎样的基础？</AnimatedText></p></>}
    {intake.step >= 2 && <><p className="demo-qa-user"><AnimatedText block>你：{intake.foundation}</AnimatedText></p><p><AnimatedText block>Tutor · 演示：每天打算学习多久？</AnimatedText></p>
      <label>每天可用分钟数<input type="number" min={5} max={480} aria-label="每天学习分钟数" value={intake.minutes}
        onChange={(event) => demoStore.patch('intake', { minutes: event.target.value })} /></label>
      <p>已保留目标与回答。下面打开现成的示范路线，不假装已经按任意目标生成课程。</p>
      <div className="demo-actions"><Action primary icon={BookOpen} onClick={() => navigate('/c/demo-python-learning')}>打开 Python 示范路线</Action>
        <Action onClick={() => navigate('/c/demo-sql-review')}>打开 SQL 示范学习</Action></div>
    </>}
  </LearningStartFrame>;
}

export function DemoComposer({ conversationId }: { conversationId?: string }) {
  const state = useDemo();
  const [attachment, setAttachment] = useState(false);
  const id = conversationId ?? 'new';
  const entry = state.composers[id] ?? { draft: '', rounds: [] };
  const navigate = useNavigate();
  const submit = () => {
    const text = entry.draft.trim();
    if (!text) return;
    if (id === 'new') {
      demoStore.patch('intake', state.intake.step === 0 ? { goal: text, step: 1 } : { foundation: text, step: 2 });
    }
    demoStore.update({ composers: { ...state.composers, [id]: {
      draft: '', rounds: id === 'new' ? [] : [...entry.rounds, {
        question: text, answer: '这是固定的前端答疑样例，不是模型生成。可以继续操作上方工件，或从学习菜单查看路线、复习和记录。',
      }],
    } } });
  };
  return <LearningComposerFrame value={entry.draft}
    label="学习目标或问题（演示）" sendLabel="发送演示输入" status="前端交互演示" attachmentLabel="添加材料（演示）"
    placeholder={id === 'new' ? state.intake.step === 0 ? '我想学习……' : '说说你已有的基础……' : '围绕当前学习提问……（固定样例回复）'}
    onChange={(draft) => demoStore.update({ composers: { ...state.composers, [id]: { ...entry, draft } } })}
    onSubmit={submit} onAttachment={() => setAttachment(true)}
    leading={entry.rounds.length > 0 && <Disclosure title={`当前学习的答疑 · ${entry.rounds.length} 轮`}>
      {entry.rounds.map((round: any, index: number) => <div key={index}><p className="demo-qa-user"><AnimatedText block>你：{round.question}</AnimatedText></p><p><AnimatedText block>Tutor · 演示：{round.answer}</AnimatedText></p></div>)}
    </Disclosure>}>
    {id === 'new' && <div className="demo-actions"><Action onClick={() => navigate('/c/demo-knowledge-checks')}>先体验六种知识检查</Action></div>}
    <DemoAttachment open={attachment} onClose={() => setAttachment(false)} />
  </LearningComposerFrame>;
}
