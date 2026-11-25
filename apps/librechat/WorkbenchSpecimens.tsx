import { useId, useState } from 'react';
import { Check, Play, Plus, X } from 'lucide-react';
import { ToastViewport, useToastContext } from '@librechat/client';
import { NotificationSeverity } from '~/common';
import type { components } from '@leornian/api-contracts';
import AccountSettings from '~/components/Nav/AccountSettings';
import SearchBar from '~/components/Nav/SearchBar';
import { Action, AnimatedText, ContentTransition, DemoDialog, Disclosure, Notice } from './LearningUI';
import { LearningComposerFrame, LearningLoginForm, LearningTaskPopover } from './LearningChrome';
import { LearningAttachmentList } from './LearningAttachments';
import { LearningRouteFolder, LearningRouteNode } from './LearningNavigation';
import { LearningSourceReader } from './LearningSourceReader';
import { BaselinePanelContent } from './BaselinePanels';
import { BaselineRoutes } from './BaselineRoutes';
import { BaselineLearningMenu } from './BaselineLearning';
import { NativeTaskList } from './NativeLearning';
import { NativeTeachingControls } from './NativeTeaching';
import NativeAssessment from './NativeAssessment';
import NativeRecovery from './NativeRecovery';
import { NativeAssistance } from './NativeAssistance';
import type { PracticeBinding } from './native-practice';
import NativeThinking from './NativeThinking';
import NativeRouteConfirmation from './NativeRouteConfirmation';
import NativeModels from './NativeModels';
import NativeMaterialSources from './NativeMaterialSources';
import NativeMaterialUpdates from './NativeMaterialUpdates';
import BaselineRagProgress from './BaselineRagProgress';
import ApiKeyInput from './CCSApiKeyInput';
import { TabBar, TabPanels } from './PracticeWorkbench';
import ComponentGallery from './ComponentGallery';
import ArtifactGallery from './ArtifactGallery';
import { ReaderLayout } from './DemoChrome';
import { sampleIds, sampleReasoning, sampleSource, sampleThinking, sampleTime } from './workbench-data.mjs';

function AssistanceExample({ state }: { state: string }) {
  const [level, setLevel] = useState(state === 'completed' ? 3 : 0), [answer, setAnswer] = useState(state === 'completed');
  const binding: PracticeBinding = {
    component_id: 'sample-editor', state: 'ready', allowed_actions: ['request_direct_answer', 'request_hint'],
    assistance_profile: 'practice-direct-answer.v1', hint_profile: 'practice-hints.v1',
    next_hint_level: level < 3 ? (level + 1) as 1 | 2 | 3 : null,
    hint_receipts: Array.from({ length: level }, (_, index) => ({
      id: `sample-hint-${index}`, profile_version: 'practice-hints.v1', pack_id: 'sample-pack', pack_revision: 1,
      slot: 'practice_1', public_identity: 'sample-question', hint_identity: `hint-${index}`, assistance_kind: 'hint',
      level: (index + 1) as 1 | 2 | 3, created_at: sampleTime,
      content: { level: (index + 1) as 1 | 2 | 3, purpose: (['concept', 'strategy', 'next_step'] as const)[index],
        text: ['先考虑空列表应该返回什么。', '把累计结果与当前元素分开记录。', '先初始化为 0，再逐项相加。'][index] },
    })),
    assistance_receipt: answer ? {
      id: 'sample-answer', profile_version: 'practice-direct-answer.v1', assistance_kind: 'direct_answer',
      pack_id: 'sample-pack', pack_revision: 1, slot: 'practice_1', public_identity: 'sample-question', created_at: sampleTime,
      content: { type: 'python', code: 'def total(numbers):\n    return sum(numbers)',
        explanation: '参考程序把列表交给求和函数；空列表返回 0。' },
    } : null,
    source: {
      id: 'sample-question', conversation_id: sampleIds.conversation, focus: { kind: 'goal' },
      kind: 'code_workspace', title: '计算列表中的数字之和',
      content_ref: { owner: 'item_bank', id: 'sample-pack', revision: 1, slot: 'practice_1', public_identity: 'sample-question' },
      presentation: { type: 'code_workspace', task: { slot: 'practice_1', difficulty: 1, source_refs: [],
        language: 'python_io', title: '计算列表中的数字之和',
        prompt: '编写函数，计算输入列表的元素之和。', starter_code: 'def total(numbers):\n    pass', sample: { input: [2, 3, 5], expected: 10 } } },
    },
  };
  return <NativeAssistance binding={binding} blocked={state === 'disabled'} onCommand={(command) => {
    if (command.action === 'request_hint') setLevel(command.level);
    if (command.action === 'request_direct_answer') setAnswer(true);
  }} />;
}

function ComposerExample({ state, attachments = false }: { state: string; attachments?: boolean }) {
  const [value, setValue] = useState(state === 'empty' ? '' : state === 'long'
    ? '我希望通过一个完整的小程序理解循环、函数与列表的协作，并观察不同边界条件下的结果。'.repeat(5)
    : '我想进一步理解循环与边界条件。');
  const [sent, setSent] = useState(false);
  const [files, setFiles] = useState(attachments ? [
    { id: 'sample-file', name: '循环与边界条件.pdf', ready: state !== 'uploading' && state !== 'error',
      failed: state === 'error', status: state === 'uploading' ? '正在上传资料…' : state === 'error' ? '上传待恢复' : '已准备' },
  ] : []);
  return <LearningComposerFrame value={value} onChange={(text) => { setValue(text); setSent(false); }}
    onSubmit={() => { setSent(true); setValue(''); }}
    onAttachment={() => setFiles([...files, { id: `sample-${files.length}`, name: '新增教材.md', ready: true, failed: false, status: '已准备' }])}
    placeholder="围绕当前节点提问……" label="学习目标或问题" sendLabel="发送给 Tutor"
    status={state === 'busy' ? '正在提交…' : state === 'uploading' ? '正在上传资料…' : ''}
    disabled={state === 'disabled' || state === 'busy'} sendDisabled={state === 'uploading'}
    attachments={<LearningAttachmentList attachments={files} error={state === 'error' && attachments ? '样例上传失败，原附件保留。' : ''} />}>
    {state === 'error' && !attachments && <Notice>样例提交未完成，草稿保留。</Notice>}
    {sent && <Notice>已在本地预览中接收。</Notice>}
  </LearningComposerFrame>;
}

function LoginExample({ state }: { state: string }) {
  const [name, setName] = useState('预览学习者'), [token, setToken] = useState('');
  const [entered, setEntered] = useState(false);
  return <><LearningLoginForm name={name} token={token} onName={setName} onToken={setToken}
    busy={state === 'busy'} error={state === 'error' ? '样例会话未能连接，请核对后重试。' : ''}
    onEnter={() => setEntered(true)} />{entered && <Notice>已进入本地预览身份。</Notice>}</>;
}

function RouteExample({ state }: { state: string }) {
  const [current, setCurrent] = useState(0);
  return <section className="baseline-routes" aria-label="学习路线">
    <h2>学习</h2>
    <LearningRouteFolder title="Python 基础学习" current={state !== 'collapsed'}>
      <ol>{['循环如何推进', '把规则写成函数', '独立完成小程序'].map((title, index) => <li key={title}>
        <LearningRouteNode title={title} index={index} unlocked={state !== 'disabled' && index < 2}
          studied={index === 0} current={index === current} busy={false} onOpen={() => setCurrent(index)} />
      </li>)}</ol>
    </LearningRouteFolder>
  </section>;
}

function DialogExample({ state }: { state: string }) {
  const [open, setOpen] = useState(true), [saved, setSaved] = useState(false);
  return <><Action onClick={() => setOpen(true)}>打开确认弹窗</Action>
    <DemoDialog title="确认当前修改" open={open} onClose={() => setOpen(false)}>
      <p>将当前选择应用到本地预览。</p>
      {state === 'error' && <Notice>样例保存失败，内容保留。</Notice>}
      <div className="demo-actions"><Action onClick={() => setOpen(false)}>取消</Action>
        <Action important busy={state === 'busy'} aria-label="确认修改" icon={Check}
          onClick={() => { setSaved(true); setOpen(false); }}>确认修改</Action></div>
    </DemoDialog>{saved && <Notice>已应用到本地预览。</Notice>}</>;
}

function CommonExample({ id, state }: { id: string; state: string }) {
  const [count, setCount] = useState(0), [tab, setTab] = useState('prompt'), [key, setKey] = useState('preview-value');
  const tabsId = useId();
  const { showToast } = useToastContext();
  if (id === 'toast') return <><Action onClick={() => showToast({
    message: state === 'error' ? '样例操作未完成，内容保留。' : '当前修改已应用到本地预览。',
    severity: state === 'error' ? NotificationSeverity.ERROR : NotificationSeverity.SUCCESS,
    duration: Infinity,
  })}>显示通知</Action><ToastViewport className="wb-toast-viewport" /></>;
  if (id === 'model-key') return <div className="ccs-models"><ApiKeyInput value={key} onChange={setKey}
    hint="这里使用可见的样例值观察显示、隐藏和编辑效果。" /></div>;
  if (id === 'buttons') return <div className="demo-stack">
    <div className="demo-actions"><Action icon={Plus} onClick={() => setCount(count + 1)}
      disabled={state === 'disabled'} busy={state === 'busy'} completed={state === 'completed'}
      phase={state === 'unknown' ? 'unknown' : undefined}>添加内容</Action>
      <Action important icon={Play} aria-label="运行样例" onClick={() => setCount(count + 1)}
        disabled={state === 'disabled'} busy={state === 'busy'} completed={state === 'completed'} />
      <Action icon={X} onClick={() => setCount(0)}>清空</Action></div>
    <p className="demo-muted">已操作 {count} 次。可用鼠标悬停或 Tab 聚焦观察状态。</p>
  </div>;
  if (id === 'disclosure') return <Disclosure title="查看当前节点的学习说明" defaultOpen={state === 'expanded'}>
    <p>观察输入、每一步的状态变化与最终结果。</p><Action onClick={() => setCount(count + 1)}>记录一次观察</Action>
    <p>已观察 {count} 次。</p>
  </Disclosure>;
  if (id === 'notice') return <Notice>{state === 'error' ? '当前读取失败，内容保留；可重置后重试。'
    : state === 'unknown' ? '原提交结果尚待核对。' : state === 'loading' ? '正在读取当前内容…' : '当前内容已保存。'}</Notice>;
  if (id === 'tabs') {
    const tabs = [
      { id: 'prompt', label: '题目', content: <p>用函数计算列表中所有数字的和。</p> },
      { id: 'result', label: '运行结果', content: <pre className="demo-pre">10</pre> },
      { id: 'history', label: '历史记录', content: <Notice>当前暂无运行记录。</Notice> },
    ];
    return <><TabBar id={tabsId} label="工作台内容" tabs={tabs} selected={tab} onSelect={setTab} />
      <TabPanels id={tabsId} tabs={tabs} selected={tab} autoHeight /></>;
  }
  if (id === 'motion') return <div className="demo-stack">
    <Action onClick={() => setCount(count + 1)}>切换内容，观察过渡</Action>
    <ContentTransition stage={String(count)}><AnimatedText block>
      {count % 2 ? '完成这一轮观察，继续检查边界条件。' : '从一个简单的输入开始，跟踪每一次更新。'}
    </AnimatedText></ContentTransition>
    <Disclosure title="展开说明"><p>折叠与展开沿用产品中的动效。</p></Disclosure>
  </div>;
  if (id === 'tokens') {
    const variables = ['--surface-primary', '--surface-secondary', '--surface-hover', '--text-primary', '--text-secondary', '--border-light', '--border-medium'];
    return <div className="wb-token-sheet">
      <h2>产品主题变量</h2><div className="wb-token-list">{variables.map((name) => <div key={name}>
        <span className="wb-swatch" style={{ background: `rgb(var(${name}))` }} /><code>{name}</code>
        <span>{getComputedStyle(document.documentElement).getPropertyValue(name).trim()}</span>
      </div>)}</div>
      <h2>文字与间距</h2><h3>学习节点标题</h3><p>先观察一次执行，再解释变量如何变化。</p>
      <p className="demo-muted">说明文字与状态提示</p><pre className="demo-pre">result += number</pre>
      <div className="demo-actions"><Action onClick={() => setCount(count + 1)}>操作按钮</Action><span>已操作 {count} 次</span></div>
    </div>;
  }
  return null;
}

export default function WorkbenchSpecimens({ surface, state, panel }: { surface: string; state: string; panel: string }) {
  if (panel) return <BaselinePanelContent panel={panel} />;
  switch (surface) {
    case 'login': return <LoginExample state={state} />;
    case 'routes': return <BaselineRoutes />;
    case 'route-node': return <RouteExample state={state} />;
    case 'composer': return <ComposerExample state={state} />;
    case 'attachments': return <ComposerExample state={state} attachments />;
    case 'tasks': return <><NativeTaskList /><LearningTaskPopover><NativeTaskList /></LearningTaskPopover></>;
    case 'learning-menu': return <BaselineLearningMenu />;
    case 'thinking': return <NativeThinking scopeKey={`workbench-${state}`} generating={state === 'busy'}
      steps={sampleThinking(state) as components['schemas']['ThinkingStep'][]} reasoning={sampleReasoning} />;
    case 'teaching': return <NativeTeachingControls conversationId={sampleIds.conversation} focus={{ kind: 'goal' }} />;
    case 'route-confirmation': return <NativeRouteConfirmation conversationId={sampleIds.conversation} />;
    case 'assessment': return <NativeAssessment planId={sampleIds.plan} planRevision={1} nodeKey="loops" />;
    case 'recovery': return <NativeRecovery planId={sampleIds.plan} planRevision={1} nodeKey="loops" />;
    case 'assistance': return <AssistanceExample state={state} />;
    case 'material-sources': return <NativeMaterialSources goalId={sampleIds.goal} />;
    case 'material-updates': return <NativeMaterialUpdates />;
    case 'models': return <NativeModels />;
    case 'model-roles': return <NativeModels view="roles" />;
    case 'rag-progress': return <div className="wb-rag-example"><BaselineRagProgress conversationId={sampleIds.conversation} /></div>;
    case 'source-reader': return <LearningSourceReader
      content={state === 'loading' ? null : sampleSource(state) as components['schemas']['CompositionSourceView']}
      error={state === 'revoked' ? '来源权限已撤销' : ''} />;
    case 'search': return <SearchBar />;
    case 'account': return <AccountSettings />;
    case 'dialog': return <DialogExample state={state} />;
    case 'component-gallery': return <ReaderLayout><ComponentGallery onViewArtifact={() => {}} /></ReaderLayout>;
    case 'artifact-gallery': return <ArtifactGallery />;
    default: return <CommonExample id={surface} state={state} />;
  }
}
