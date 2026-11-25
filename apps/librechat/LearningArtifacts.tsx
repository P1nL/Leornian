import { useId, useState } from 'react';
import {
  Archive, Brain, Bug, Check, ChevronDown, ChevronUp,
  Clock3, Copy, CornerUpLeft, Eye, FileCheck2, FileCode2, FileInput, FileText, Frown,
  GitCompare, GraduationCap, Hash, History, Lightbulb, LockKeyhole,
  Meh, MessageCircle, PackageCheck, Palette, RefreshCw, RotateCcw,
  Save, Send, ShieldCheck, Smile, X,
} from 'lucide-react';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@librechat/client';
import { AnimatedText, ArtifactFrame, Collapse, ContentTransition, DemoDialog, Disclosure, Notice, useDemo } from './DemoUI';
import {
  ActionGroup, AnswerFeedback, ArtifactAction, ChoiceAnswer, CodeBlock, CodeDiff, CodeEditor, Explanation,
  IsolatedPreview, KeyValueList, LineRangeAnswer, OrderingAnswer, ResultFeedback, ReviewFinding,
  SourceReference, StepPlayer, TextAnswer,
} from './LearningComponents';
import PracticeWorkbench, { TabBar, TabPanels } from './PracticeWorkbench';
import { PhosphorDiff } from './PhosphorIcons';
import { demoStore, codeExampleResult, sqlExampleResult, workspaceActionState, rangeAnswerReady } from './demo-state.mjs';
import {
  artifactById, brokenCode, fixedCode, messageWidgets, messageReferences, projectFiles,
  sampleSql, sampleHtml, sampleCss, readingDocuments,
} from './learning-demo-data.mjs';

function KnowledgeCheck({ definition }: { definition: any }) {
  const state = useDemo();
  const { id, check } = definition;
  const entry = state.artifacts[id] ?? {};
  const response = entry.response ?? (check.subtype === 'ordering' ? check.options : ['multiple', 'range'].includes(check.subtype) ? [] : '');
  const setResponse = (value: unknown) => demoStore.artifact(id, { response: value });
  const locked = entry.submitted === true;
  const reasons = entry.lineReasons ?? {};
  const drafts = entry.lineDrafts ?? {};
  const ready = check.subtype === 'range' ? rangeAnswerReady(check, response, reasons, drafts) : response.length > 0;
  return <ArtifactFrame id={id} title={definition.title} kind="knowledge_check" state={entry.state}>
    <Explanation><p>{check.prompt}</p></Explanation>
    {check.code && <CodeBlock>{check.code}</CodeBlock>}
    {check.subtype === 'single' && <ChoiceAnswer label={check.prompt} options={check.options}
      value={response} onChange={setResponse} disabled={locked} />}
    {check.subtype === 'multiple' && <ChoiceAnswer multiple label={check.prompt} options={check.options}
      value={response} onChange={setResponse} disabled={locked} />}
    {['prediction', 'short'].includes(check.subtype) && <TextAnswer
      label={check.subtype === 'prediction' ? '预测输出，每行一项' : '你的解释'}
      accessibleLabel={`${definition.title}回答`} value={response} readOnly={locked} onChange={setResponse} />}
    {check.subtype === 'ordering' && <OrderingAnswer label="查询阶段顺序" value={response}
      onChange={setResponse} disabled={locked} />}
    {check.subtype === 'range' && <LineRangeAnswer lines={check.lines} value={response}
      reasons={reasons} drafts={drafts}
      onDraftChange={(line, draft) => {
        const next = { ...drafts };
        if (draft === null) delete next[line]; else next[line] = draft;
        demoStore.artifact(id, { lineDrafts: next });
      }}
      onSave={(line) => demoStore.saveLineAnnotation(id, line)}
      onRemove={(line) => {
        const next = { ...reasons };
        delete next[line];
        demoStore.artifact(id, { response: response.filter((number: number) => number !== line), lineReasons: next });
      }}
      feedback={locked ? Object.fromEntries(check.answer.map((line: number) => [line, <p key={line}>{check.explanation}</p>])) : {}}
      disabled={locked} />}
    <ActionGroup><ArtifactAction icon={Send} label={check.subtype === 'range' ? '提交审查' : '提交演示回答'} primary
      completed={locked && entry.result?.kind !== 'incorrect'} phase={locked && entry.result?.kind === 'incorrect' ? 'attention' : undefined}
      disabled={locked || !ready}
      onClick={() => demoStore.answerCheck(id, response)}>{locked ? '已提交' : check.subtype === 'range' ? '提交审查' : '提交回答'}</ArtifactAction></ActionGroup>
    {entry.result && <AnswerFeedback kind={entry.result.kind}>{entry.result.text}</AnswerFeedback>}
  </ArtifactFrame>;
}

export function Assistance({ anchor = 'project' }: { anchor?: string }) {
  const state = useDemo();
  const entry = state.artifacts[anchor] ?? {};
  const [answerDialog, setAnswerDialog] = useState(false);
  const hints = [
    'H1：先明确输入、输出和边界条件，再考虑实现。',
    'H2：累加时保留已有结果；接口返回值则要符合题目给定的数据结构。',
    'H3：逐行检查状态变化，用公开样例对照每一步。',
  ];
  const branch = entry.branch ?? [];
  const patch = (values: any) => demoStore.artifact(anchor, values);
  return <section className="learning-demo" data-learning-demo aria-label="提示与答疑">
    <div className="demo-actions">
      <ArtifactAction icon={Lightbulb} label={(entry.hints ?? 0) < 3 ? `查看 H${(entry.hints ?? 0) + 1} 提示` : '已展开 H1—H3'}
        disabled={(entry.hints ?? 0) >= 3} onClick={() => patch({ hints: (entry.hints ?? 0) + 1 })}>
        {(entry.hints ?? 0) < 3 ? `H${(entry.hints ?? 0) + 1}` : 'H1—H3'}
      </ArtifactAction>
      <ArtifactAction icon={Eye} label="查看直接答案" onClick={() => setAnswerDialog(true)} disabled={entry.answerVisible} />
    </div>
    <Collapse open={(entry.hints ?? 0) > 0}><Disclosure defaultOpen title={`已查看的提示 · ${entry.hints ?? 0}`}>
      {hints.map((hint, index) => <Collapse key={hint} open={index < (entry.hints ?? 0)}><p>{hint}</p></Collapse>)}</Disclosure></Collapse>
    {entry.answerVisible && <Notice>直接答案示例：累加使用 result += value；健康检查接口返回 {'{"status": "ok"}'}。
      本次演示已标记答案暴露，后续成功也不展示为无辅助独立通过。</Notice>}
    <Disclosure title={`答疑 · ${branch.length} 轮`} open={!entry.folded}
      onOpenChange={(open) => patch({ folded: !open })}>
      {branch.map((round: any, index: number) => <div key={index} className="demo-qa">
        <p className="demo-qa-user"><AnimatedText block><strong>你：</strong>{round.question}</AnimatedText></p>
        <p><AnimatedText block><strong>Tutor · 演示：</strong>{round.answer}</AnimatedText></p>
      </div>)}
      <label>围绕这份练习提问
        <input aria-label="练习答疑问题" value={entry.question ?? ''} maxLength={500}
          onChange={(event) => patch({ question: event.target.value })} />
      </label>
      <div className="demo-actions">
        <ArtifactAction icon={MessageCircle} label="查看答疑样例" disabled={!entry.question?.trim()} onClick={() => patch({
          question: '', branch: [...branch, {
            question: entry.question.trim(),
            answer: '这是预先编写的答疑样例，不是模型回复。先对照题目输入与输出，再定位当前状态在哪一行发生变化。',
          }],
        })} />
        <ArtifactAction icon={CornerUpLeft} label="回到练习并折叠答疑" onClick={() => patch({ folded: true })} />
      </div>
    </Disclosure>
    <DemoDialog open={answerDialog} onClose={() => setAnswerDialog(false)} title="查看直接答案">
      <p>这会在当前演示中保留“已看答案”的标记，不会重置已有提示或结果。</p>
      <div className="demo-actions"><ArtifactAction icon={Eye} label="确认查看演示答案" primary onClick={() => {
        patch({ answerVisible: true }); setAnswerDialog(false);
      }}>查看答案</ArtifactAction><ArtifactAction icon={X} label="暂不查看" onClick={() => setAnswerDialog(false)}>暂不查看</ArtifactAction></div>
    </DemoDialog>
  </section>;
}

function RunHistory({ attempts = [] }: { attempts?: any[] }) {
  if (!attempts.length) return <p className="demo-workbench-empty">暂无运行记录。</p>;
  return <ol className="demo-workbench-history">{attempts.map((attempt, index) => <li key={index}>
    <h4>第 {index + 1} 次检查</h4>
    <ResultFeedback {...(attempt.result ?? attempt)} />
    {attempt.result?.input && <Disclosure title="当时的输入"><CodeBlock>{attempt.result.input}</CodeBlock></Disclosure>}
  </li>)}</ol>;
}

function PublicCases({ rows }: { rows: string[][] }) {
  const [selected, setSelected] = useState(0);
  const id = useId();
  const tabs = rows.map((row, index) => ({ id: String(index), label: `用例 ${index + 1}`, icon: Hash,
    content: <KeyValueList label={`用例 ${index + 1}`} entries={[
      { name: '输入', value: <code>{row[0]}</code> }, { name: '预期输出', value: <code>{row[1]}</code> },
    ]} /> }));
  return <>
    <TabBar id={id} label="公开用例" tabs={tabs} selected={String(selected)} onSelect={(value) => setSelected(Number(value))} />
    <TabPanels id={id} tabs={tabs} selected={String(selected)} className="demo-case-panels" />
  </>;
}

function WorkspaceResult({ entry, draft, dialect }: { entry: any; draft: string; dialect?: string }) {
  return <>
    {entry.state === 'unknown' && <Notice>刷新打断了演示过程，保留未知状态，不自动再运行。请在任务中查看这一条记录。</Notice>}
    {entry.state === 'running' && <><div className="demo-progress" /><Notice>正在检查…</Notice></>}
    {entry.result ? <>
      {(entry.result.input !== draft || (dialect && dialect !== entry.result.dialect))
        && <Notice>草稿或方言已修改；下方仍是上次运行的结果。</Notice>}
      <ResultFeedback {...entry.result} />
    </> : !['running', 'unknown'].includes(entry.state)
      && <p className="demo-workbench-empty">先运行代码，结果会显示在这里。</p>}
  </>;
}

function CodeWorkspace({ definition }: { definition: any }) {
  const state = useDemo();
  const id = definition.id;
  const project = definition.project;
  const entry = state.artifacts[id] ?? {};
  const [file, setFile] = useState('app.py');
  const [showDiff, setShowDiff] = useState(false);
  const draft = entry.draft ?? (project ? projectFiles['app.py'] : brokenCode);
  const busy = entry.state === 'running' || entry.state === 'unknown';
  const allowed = !project || state.environment.course === 'ready';
  const [consentOpen, setConsentOpen] = useState(false);
  const cases = project ? [['GET /health', '{"status":"ok"}']] : codeExampleResult(fixedCode).rows;
  const run = () => {
    const result = project
      ? draft.trim() === projectFiles['app.py'].trim()
        ? { state: 'completed', label: '固定项目样例的测试展示', rows: [['GET /health', 'status=ok', 'status=ok']] }
        : { state: 'active', label: '自定义项目草稿已保留；本演示不执行它。', rows: [] }
      : codeExampleResult(draft);
    demoStore.task(id, project ? '受控项目样例检查' : 'Python 公开样例检查', { ...result, result: { ...result, input: draft } });
  };
  return <ArtifactFrame id={id} title={definition.title} kind="code_workspace" state={entry.state}>
    <PracticeWorkbench title={definition.title} tabs={[
      { id: 'description', label: '题目描述', icon: FileText, content: <>
        <Explanation title={project ? '实现健康检查接口' : '实现列表求和'}>
        <p>{project ? '完成 Flask 项目的 GET /health 接口，返回表示服务正常的 JSON 对象。'
          : '实现 total(values)，返回整数列表中所有元素的和。空列表返回 0，不要只保留最后一个值。'}</p></Explanation>
        <h4>公开示例</h4>
        {cases.slice(0, 2).map((row: string[], index: number) => <CodeBlock key={index}>
          输入：{row[0]}{'\n'}输出：{row[1]}
        </CodeBlock>)}
        <h4>练习约束</h4>
        <p>{project ? '仅 app.py 可编辑；test_app.py 与 requirements.lock 保持只读。使用任务内测试客户端，不公开宿主端口。'
          : '输入为整数列表，输出为整数；需要覆盖空列表和负数。先运行错误样例，再载入修正版观察反馈变化。'}</p>
      </> },
      { id: 'assistance', label: '提示答疑', icon: Lightbulb, content: <Assistance anchor={project ? 'project' : 'code'} /> },
      project ? { id: 'environment', label: '环境配置', icon: PackageCheck, content: <>
        <h4>课程隔离环境</h4><p>Python + Flask 3.1.2（演示版本），不修改全局 SDK。</p>
        <Notice>环境状态：{allowed ? '课程环境已模拟就绪' : state.environment.course === 'preparing'
          ? '正在模拟准备' : '等待本机环境准备或安装授权'}。{!allowed && '可以继续阅读，暂不能运行。'}</Notice>
        <ArtifactAction icon={PackageCheck} label="查看环境与安装范围" onClick={() => setConsentOpen(true)}>安装范围</ArtifactAction>
      </> } : { id: 'review', label: '代码评审', icon: GitCompare, content: <CodeReview definition={artifactById.get('review')} embedded /> },
      { id: 'history', label: '运行记录', icon: History, content: <RunHistory attempts={entry.attempts} /> },
    ]} language={<span>Python{project ? ' · Flask' : ''}</span>}
      files={project ? { selected: file, onSelect: setFile, tabs: Object.keys(projectFiles).map((name) => ({
        id: name, label: name, icon: name === 'app.py' ? FileCode2 : LockKeyhole,
        content: <CodeEditor embedded label={name === 'app.py' ? name : `${name}（只读）`}
          value={name === 'app.py' ? draft : projectFiles[name]} readOnly={busy || name !== 'app.py'}
          onChange={(value) => demoStore.artifact(id, { draft: value })} />,
      })) } : undefined}
      editor={<CodeDiff embedded before={brokenCode} after={draft} label="Python 代码"
        open={showDiff} hideToggle readOnly={busy} onChange={(value) => demoStore.artifact(id, { draft: value })} />}
      tools={project ? <span className="demo-muted"><AnimatedText>{allowed ? '环境已就绪' : '等待环境授权'}</AnimatedText></span> : <>
        <ArtifactAction icon={FileCheck2} label="载入修正版" disabled={busy} onClick={() => demoStore.artifact(id, { draft: fixedCode })} />
        <ArtifactAction icon={Bug} label="载入错误版" disabled={busy} onClick={() => demoStore.artifact(id, { draft: brokenCode })} />
        <ArtifactAction icon={PhosphorDiff} label="切换Python 代码修改" aria-pressed={showDiff}
          onClick={() => setShowDiff(!showDiff)} />
      </>}
      tests={<PublicCases rows={cases} />} result={<WorkspaceResult entry={entry} draft={draft} />}
      hasResult={Boolean(entry.result) || entry.state === 'unknown'} busy={entry.state === 'running'}
      runPhase={workspaceActionState(entry, draft)}
      runDisabled={busy || !allowed} runLabel="运行并检查（演示）" onRun={run} />
    {project && <InstallationDialog open={consentOpen} onClose={() => setConsentOpen(false)} />}
  </ArtifactFrame>;
}

export function InstallationDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const state = useDemo();
  const environment = state.environment;
  const stopPreparation = () => state.tasks.filter((task: any) => task.artifactId === 'course' && task.state === 'running')
    .forEach((task: any) => demoStore.cancelTask(task.id));
  const prepare = () => {
    demoStore.patch('environment', { consent: true, course: 'preparing' });
    demoStore.task('course', '准备课程隔离环境（演示）', {}, () => demoStore.patch('environment', { course: 'ready' }));
    onClose();
  };
  return <DemoDialog open={open} onClose={onClose} title="本机课程环境与安装授权">
    <p>以下仅演示授权流程，不下载、安装或修改系统。</p>
    <dl>
      <dt>依赖与来源</dt><dd>Python 课程环境 + Flask==3.1.2；可信配方和锁定依赖，来源 PyPI（均为样例）。</dd>
      <dt>隔离位置</dt><dd>Leornian 专用课程环境，不修改全局 SDK。</dd>
      <dt>网络与服务</dt><dd>准备阶段仅访问获准依赖源；练习使用任务内测试客户端，不公开宿主端口。</dd>
      <dt>资源与费用</dt><dd>下载量和磁盘用量尚未估算；实际安装前需展示真实信息。本演示不产生费用。</dd>
    </dl>
    <Notice>路线确认不等于安装授权；系统引擎准备与本次课程依赖是两个决定。</Notice>
    <div className="demo-actions">
      <ArtifactAction icon={ShieldCheck} label={environment.consent ? '在已授权范围内模拟恢复' : '同意范围并模拟准备'}
        primary disabled={environment.engine !== 'ready' || environment.course === 'preparing'} onClick={prepare}>
        {environment.consent ? '恢复准备' : '同意并准备'}
      </ArtifactAction>
      <ArtifactAction icon={Clock3} label="稍后准备" onClick={() => { stopPreparation(); demoStore.patch('environment', { course: 'deferred' }); onClose(); }}>稍后准备</ArtifactAction>
      <ArtifactAction icon={X} label="拒绝本次安装" onClick={() => { stopPreparation(); demoStore.patch('environment', { consent: false, course: 'declined' }); onClose(); }}>拒绝安装</ArtifactAction>
    </div>
    {environment.engine !== 'ready' && <p>请先在“设置 → 本机执行”体验引擎准备。这里不会代为获取管理员权限。</p>}
  </DemoDialog>;
}

function ExecutionResult({ definition }: { definition: any }) {
  const state = useDemo();
  const code = state.artifacts.code ?? {};
  const [expanded, setExpanded] = useState(false);
  return <ArtifactFrame id={definition.id} title={definition.title} kind="execution_result" state={code.state ?? 'pending'}>
    {code.result ? <ResultFeedback {...code.result} /> : <Notice>运行代码样例后，在这里查看结果。</Notice>}
    <div className="demo-actions"><ArtifactAction icon={expanded ? ChevronUp : ChevronDown} label="公开详情"
      onClick={() => setExpanded(!expanded)} aria-expanded={expanded} /></div>
    <Collapse open={expanded}><CodeBlock>样例执行协议：Python JSON 整数列表 → 整数{'\n'}只展示公开样例，不包含隐藏测试或私有答案。{'\n'}评分和讲评分开：即使讲评未完成，已有结果仍可阅读。</CodeBlock></Collapse>
  </ArtifactFrame>;
}

function CodeReview({ definition, embedded = false }: { definition: any; embedded?: boolean }) {
  const entry = useDemo().artifacts.review ?? {};
  const content = <>
    <p>错误样例 v1：对照逐行反馈修订。</p>
    <ReviewFinding lines={brokenCode.split('\n')} findings={[{ line: 4, content:
      <p><code>result = value</code> 每次都会丢掉之前的和，应保留原值再累加。</p>,
    }]} />
    <div className="demo-actions"><ArtifactAction icon={FileInput} label="将修订示例放入编辑器" onClick={() => {
      demoStore.artifact('code', { draft: fixedCode });
      demoStore.artifact('review', { state: 'active', applied: true });
    }} />
      <ArtifactAction icon={Check} label="完成评审交互" important completed={entry.state === 'completed'}
        disabled={!entry.applied || entry.state === 'completed'} onClick={() => demoStore.artifact('review', { state: 'completed' })}>
        {entry.state === 'completed' ? '已评审' : '完成评审'}</ArtifactAction>
    </div>
    {entry.applied && <Notice>修订已放入编辑器，仍需运行检查。</Notice>}
  </>;
  return embedded ? content : <ArtifactFrame id="review" title={definition.title} kind="code_review" state={entry.state}>
    {content}
  </ArtifactFrame>;
}

function SqlWorkspace({ definition }: { definition: any }) {
  const state = useDemo();
  const entry = state.artifacts.sql ?? {};
  const [copied, setCopied] = useState(false);
  const draft = entry.draft ?? sampleSql;
  const busy = ['running', 'unknown'].includes(entry.state);
  const dialect = entry.dialect ?? 'SQLite';
  return <ArtifactFrame id="sql" title={definition.title} kind="sql_workspace" state={entry.state}>
    <PracticeWorkbench title={definition.title} tabs={[
      { id: 'description', label: '题目描述', icon: FileText, content: <>
        <h4>按类别汇总订单</h4><p>对 orders 按 category 分组，计算 amount 的总和，只保留总和大于 100 的类别。</p>
        <h4>预期结果</h4><CodeBlock>category | total{'\n'}books    | 150{'\n'}tools    | 240</CodeBlock>
        <p>分组后使用 HAVING 筛选。结果不要求特定顺序。</p>
      </> },
      { id: 'schema', label: '表结构', icon: FileText, content: <aside aria-label="SQL 表结构"><h4>Schema · orders</h4>
        <CodeBlock>id INTEGER{'\n'}category TEXT{'\n'}amount INTEGER</CodeBlock>
        <ArtifactAction icon={Copy} label={copied ? '已复制 orders' : '复制表名'} completed={copied} onClick={async () => {
          try { await navigator.clipboard.writeText('orders'); setCopied(true); }
          catch { setCopied(false); }
        }} />
      </aside> },
      { id: 'assistance', label: '提示答疑', icon: Lightbulb, content: <Assistance anchor="sql" /> },
      { id: 'history', label: '运行记录', icon: History, content: <RunHistory attempts={entry.attempts} /> },
    ]} language={<select aria-label="SQL 方言" value={dialect} disabled={busy}
      onChange={(event) => demoStore.artifact('sql', { dialect: event.target.value })}>
      {['SQLite', 'PostgreSQL', 'MySQL'].map((name) => <option key={name}>{name}</option>)}
    </select>} editor={<CodeEditor embedded label="SQL 查询" value={draft} readOnly={busy}
      onChange={(value) => demoStore.artifact('sql', { draft: value })} />}
      tools={<ArtifactAction icon={RotateCcw} label="载入内置 SQL 样例" disabled={busy} onClick={() => demoStore.artifact('sql', { draft: sampleSql })} />}
      tests={<><h4>orders · 公开样例数据</h4><CodeBlock>id | category | amount{'\n'}1  | books    | 100{'\n'}2  | books    | 50{'\n'}3  | tools    | 240{'\n'}4  | food     | 30</CodeBlock></>}
      result={<WorkspaceResult entry={entry} draft={draft} dialect={dialect} />}
      hasResult={Boolean(entry.result) || entry.state === 'unknown'} busy={entry.state === 'running'}
      runPhase={workspaceActionState(entry, draft, dialect)}
      runDisabled={busy} runLabel="运行查询（演示）" onRun={() => {
      const result = sqlExampleResult(draft);
      demoStore.task('sql', `${dialect} 结果展示`, { ...result, result: { ...result, input: draft, dialect } });
    }} />
  </ArtifactFrame>;
}

function InteractiveDemo({ definition }: { definition: any }) {
  const entry = useDemo().artifacts.animation ?? {};
  const step = entry.step ?? 0;
  const values = [1, 2, 3];
  return <ArtifactFrame id="animation" title={definition.title} kind="demo" state={entry.state}>
    <p>每一步读取一个元素并更新 result。</p>
    <StepPlayer label="循环步骤" items={values} step={step}
      onStep={(next) => demoStore.artifact('animation', { step: next, state: 'active' })}
      feedback={<Notice>已观察 {step} / 3 步，当前 result = {values.slice(0, step).reduce((sum, value) => sum + value, 0)}</Notice>}
      actions={<ArtifactAction icon={Check} label="确认看完演示" primary completed={entry.state === 'completed'}
        disabled={step < 3 || entry.state === 'completed'} onClick={() => demoStore.artifact('animation', { state: 'completed' })}>
        {entry.state === 'completed' ? '已看完' : '看完了'}</ArtifactAction>} />
  </ArtifactFrame>;
}

function RestrictedPreview({ definition }: { definition: any }) {
  const entry = useDemo().artifacts.preview ?? {};
  const html = entry.html ?? sampleHtml;
  const css = entry.css ?? sampleCss;
  const id = useId();
  const [tab, setTab] = useState('html');
  const [preview, setPreview] = useState({ html: sampleHtml, css: sampleCss });
  const [applied, setApplied] = useState('');
  const source = JSON.stringify([html, css]);
  return <ArtifactFrame id="preview" title={definition.title} kind="restricted_preview" state={entry.state}>
    <div className="demo-html-workbench"><ResizablePanelGroup orientation="horizontal">
      <ResizablePanel defaultSize="50%" minSize="30%" className="demo-workbench-resizable">
        <section className="demo-workbench-pane" aria-label="HTML CSS 编辑区">
          <div className="demo-workbench-pane-heading">
            <TabBar id={id} label="网页代码" tabs={[{ id: 'html', label: 'HTML', icon: FileCode2 }, { id: 'css', label: 'CSS', icon: Palette }]}
              selected={tab} onSelect={setTab} />
          </div>
          <TabPanels id={id} selected={tab} panelClassName="demo-html-editor-panel" tabs={[
            { id: 'html', label: 'HTML', content: <CodeEditor label="HTML 内容" value={html} onChange={(value) => demoStore.artifact('preview', { html: value })} /> },
            { id: 'css', label: 'CSS', content: <CodeEditor label="CSS 样式" value={css} onChange={(value) => demoStore.artifact('preview', { css: value })} /> },
          ]} />
          <div className="demo-workbench-runbar"><ArtifactAction icon={RefreshCw} label="更新受限预览" primary completed={applied === source} onClick={() => {
            setPreview({ html, css }); setApplied(source); demoStore.artifact('preview', { state: 'active' });
          }}>{applied === source ? '已更新' : '更新预览'}</ArtifactAction></div>
        </section>
      </ResizablePanel>
      <ResizableHandle className="demo-workbench-resizer" aria-label="调整网页编辑与预览区宽度" />
      <ResizablePanel defaultSize="50%" minSize="30%" className="demo-workbench-resizable">
        <section className="demo-workbench-pane demo-html-result" aria-label="HTML CSS 预览区">
          <div className="demo-workbench-pane-heading"><Eye size={16} aria-hidden="true" /><strong>效果预览</strong></div>
          <IsolatedPreview {...preview} />
        </section>
      </ResizablePanel>
    </ResizablePanelGroup></div>
    <p className="demo-muted">隔离预览：不运行脚本，不加载外部资源。</p>
  </ArtifactFrame>;
}

export function RouteWidget() {
  const state = useDemo();
  const [history, setHistory] = useState(false);
  const route = state.route;
  return <ArtifactFrame id="route" title="Python 文件整理路线" kind="route" state={route.confirmed ? 'completed' : 'ready'}>
    <ol>{['函数与返回值', '列表、循环与边界条件', '路径与文件分类', '综合练习与正式考核'].map((title, index) =>
      <li key={title} className="demo-step"><span>{index + 1}. {title}</span>{index === 0 && route.confirmed && <small>当前学习</small>}</li>)}</ol>
    {!route.confirmed && <label>希望调整什么？<textarea className="demo-textarea" aria-label="路线修改要求" rows={2} value={route.changes}
      onChange={(event) => demoStore.patch('route', { changes: event.target.value })} /></label>}
    <div className="demo-actions">
      <ArtifactAction icon={Check} label={route.confirmed ? '已确认这份演示路线' : '确认这份路线（演示）'}
        primary completed={route.confirmed} disabled={route.confirmed} onClick={() => demoStore.patch('route', {
        confirmed: true, history: [...route.history, { revision: route.revision, action: '明确确认' }],
      })}>{route.confirmed ? '已确认' : '确认路线'}</ArtifactAction>
      <ArtifactAction icon={Save} label="保存修改要求（演示）" disabled={!route.changes.trim() || route.confirmed} onClick={() => demoStore.patch('route', {
        revision: route.revision + 1, history: [...route.history, { revision: route.revision, action: `修改要求：${route.changes}` }], changes: '',
      })} />
      <ArtifactAction icon={History} label="查看路线版本" aria-expanded={history} onClick={() => setHistory(!history)} />
    </div>
    <Collapse open={history}><Notice>当前版本 {route.revision}。{route.history.length === 0 ? '尚无操作历史。' : route.history.map((record: any) => `v${record.revision} ${record.action}`).join('；')}
      修改要求仅展示留痕，不假装模型已按你的要求重新规划。</Notice></Collapse>
  </ArtifactFrame>;
}

export function MaterialUpdate() {
  const material = useDemo().material;
  const [open, setOpen] = useState(false);
  return <section className="learning-demo" data-learning-demo aria-label="教材更新提示">
    <Notice>教材更新样例：版本 2 增加了空列表的说明。未决定时仍使用版本 1，不因关闭提示停课。</Notice>
    <ArtifactAction icon={GitCompare} label="查看差异与更新选择" onClick={() => setOpen(true)} />
    {material.decision && <p><AnimatedText block>演示决定：{({ accept: '采用新版，旧记录仍保留', defer: '稍后决定，继续原版', keep: '本轮保留旧版' } as Record<string, string>)[material.decision]}</AnimatedText></p>}
    <DemoDialog open={open} onClose={() => setOpen(false)} title="教材更新与影响">
      <p><strong>旧版：</strong>函数把输入转换为输出。</p><p><strong>新版：</strong>补充空列表返回 0 的例子；当前学习目标和已完成记录不变。</p>
      <p>影响范围：当前课时的边界条件讲解。此为静态比较，不代表自动审核已经通过。</p>
      <div className="demo-actions">{[['accept', '更新到新版'], ['defer', '稍后决定'], ['keep', '本轮保留旧版']].map(([decision, label]) =>
        <ArtifactAction key={decision} icon={decision === 'accept' ? RefreshCw : decision === 'defer' ? Clock3 : Archive} label={label} onClick={() => {
          demoStore.patch('material', { decision, version: decision === 'accept' ? 2 : material.version }); setOpen(false);
        }}>{label}</ArtifactAction>)}</div>
    </DemoDialog>
  </section>;
}

export function ExamWidget() {
  const exam = useDemo().exam;
  return <ArtifactFrame id="exam" title="正式考试的交互样例" kind="exam" state={exam.state}>
    <ContentTransition stage={exam.state === 'ready' ? 'ready' : 'exam'}>
    {exam.state === 'ready' ? <>
      <p>两道演示题整组提交一次；开考后不提供单题试跑、提示或直接答案。</p>
      <label className="demo-choice"><input type="checkbox" checked={exam.agreed} onChange={(event) => demoStore.patch('exam', { agreed: event.target.checked })} />
        <span>我理解开考与普通练习不同，并准备开始这次演示。</span></label>
      <div className="demo-actions"><ArtifactAction icon={GraduationCap} label="明确开考（演示）" primary disabled={!exam.agreed}
        onClick={() => demoStore.patch('exam', { state: 'active' })}>开考</ArtifactAction></div>
    </> : <>
      <p>题一：没有 return 的函数返回什么？</p>
      <ChoiceAnswer label="题一：没有 return 的函数返回什么？" options={['0', 'None']} value={exam.choice}
        disabled={exam.state !== 'active'} onChange={(choice) => demoStore.patch('exam', { choice })} />
      <CodeEditor label="题二：编写 total(values)" value={exam.code} readOnly={exam.state !== 'active'}
        onChange={(value) => demoStore.patch('exam', { code: value })} />
      <div className="demo-actions"><ArtifactAction icon={Send} label="整组提交一次（演示）" primary completed={exam.state === 'completed'}
        disabled={exam.state !== 'active' || !exam.choice || !exam.code.trim()} onClick={() => demoStore.submitExam()}>
        {exam.state === 'completed' ? '已提交' : '整组提交'}</ArtifactAction></div>
      {exam.state === 'completed' && <Notice>回答已锁定，不可重交。本演示不生成真实分数。</Notice>}
    </>}
    </ContentTransition>
  </ArtifactFrame>;
}

export function ReviewActivity() {
  const review = useDemo().review;
  return <ArtifactFrame id="review-activity" title="到期复习样例" kind="review_activity" state={review.state === 'due' ? 'ready' : review.state}>
    <ContentTransition stage={review.state === 'due' ? 'due' : 'review'}>
    {review.state === 'due' ? <><p>复习主题：return 与 print。你可以现在开始，也可以保留到期提示。</p>
      <div className="demo-actions"><ArtifactAction icon={Brain} label="开始复习（演示）" primary
        onClick={() => demoStore.patch('review', { state: 'active' })}>开始复习</ArtifactAction></div></> : <>
      <TextAnswer label="不看材料，尝试回想两者的区别" accessibleLabel="复习回答" value={review.answer}
        readOnly={review.state === 'completed'} onChange={(answer) => demoStore.patch('review', { answer })} />
      <Disclosure title="查看参考说明"><p>return 把结果交给调用者；print 只负责显示。回看参考不等于独立作答通过。</p></Disclosure>
      <p>本次回想感觉如何？这是自评，不是客观编程评分。</p>
      <div className="demo-actions">{['困难', '一般', '轻松'].map((rating) => <ArtifactAction key={rating}
        icon={rating === '困难' ? Frown : rating === '一般' ? Meh : Smile} label={rating}
        important completed={review.rating === rating}
        aria-pressed={review.rating === rating} disabled={!review.answer.trim() || review.state === 'completed'}
        onClick={() => demoStore.patch('review', { state: 'completed', rating })}>{rating}</ArtifactAction>)}</div>
      {review.rating && <Notice>已保存自评“{review.rating}”。</Notice>}
    </>}
    </ContentTransition>
  </ArtifactFrame>;
}

function SourceLocator({ definition }: { definition: any }) {
  const permitted = useDemo().material.permitted;
  const { documentId, block } = definition.citation;
  const document = readingDocuments[documentId];
  return <>
    <SourceReference title={document.title} version={document.version} section={document.section} block={block + 1} disabled={!permitted}
      onOpen={() => demoStore.update({ reader: { id: documentId, block } })} />
    {!permitted && <Notice>演示使用权限已撤销，不再打开原文。可在“我的文件”的材料详情中查看。</Notice>}
  </>;
}

export function LearningArtifact({ id }: { id: string }) {
  if (id === 'route') return <RouteWidget />;
  if (id === 'update') return <MaterialUpdate />;
  if (id === 'exam') return <ExamWidget />;
  if (id === 'reviewActivity') return <ReviewActivity />;
  if (id === 'assistance') return <Assistance />;
  const definition = artifactById.get(id);
  if (!definition) return null;
  switch (definition.presentation.type) {
    case 'knowledge_check': return <KnowledgeCheck definition={definition} />;
    case 'code_workspace': return <CodeWorkspace definition={definition} />;
    case 'execution_result': return <ExecutionResult definition={definition} />;
    case 'code_review': return <CodeReview definition={definition} />;
    case 'sql_workspace': return <SqlWorkspace definition={definition} />;
    case 'demo': return <InteractiveDemo definition={definition} />;
    case 'restricted_preview': return <RestrictedPreview definition={definition} />;
    case 'source_locator': return <SourceLocator definition={definition} />;
    default: return null;
  }
}

export default function LearningArtifacts({ messageId }: { messageId?: string }) {
  const widgets = messageId ? messageWidgets[messageId] : null;
  const references = messageId ? messageReferences[messageId] : null;
  return <>
    {references && <div className="demo-actions" aria-label="消息来源引用">
      {references.map((id: string) => <LearningArtifact key={id} id={id} />)}
    </div>}
    {widgets?.map((id: string) => <LearningArtifact key={id} id={id} />)}
  </>;
}
