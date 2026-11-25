import { useId, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, FileCode2, FileText, LockKeyhole, Play, RefreshCw, RotateCcw, Send, X } from 'lucide-react';
import { AnimatedText, Disclosure, Notice, useDemo } from './DemoUI';
import type { ActionPhase } from './DemoUI';
import { TabBar, TabPanels } from './PracticeWorkbench';
import {
  ActionGroup, AnswerFeedback, ArtifactAction, ChoiceAnswer, CodeBlock, CodeEditor, DataTable,
  Explanation, IsolatedPreview, KeyValueList, LineRangeAnswer, OrderingAnswer, ResultFeedback,
  ReviewFinding, SourceReference, StepPlayer, TextAnswer,
  CodeDiff, TreeView, RelationGraph, SequenceDiagram, ParameterControl,
} from './LearningComponents';
import { componentCatalog, componentProps, componentSource } from './component-catalog.mjs';
import { artifactGalleryPath } from './artifact-catalog.mjs';
import { brokenCode, checks, fixedCode, projectFiles, sampleCss, sampleHtml } from './learning-demo-data.mjs';
import { checkResponse, codeExampleResult, demoStore, rangeAnswerReady } from './demo-state.mjs';
import AlgorithmExample from './AlgorithmExamples';

function SourceExample() {
  const permitted = useDemo().material.permitted;
  return <>
    <SourceReference title="Python 函数与边界条件" version={1} section="§2" block={3} disabled={!permitted}
      onOpen={() => demoStore.update({ reader: { id: 'demo-python-functions', block: 2 } })} />
    {!permitted && <Notice>材料使用权限已撤销。</Notice>}
  </>;
}

function FileExample() {
  const id = useId();
  const [file, setFile] = useState('app.py');
  const [code, setCode] = useState(projectFiles['app.py']);
  const tabs = Object.entries(projectFiles).map(([name, value]) => ({
    id: name, label: name, icon: name === 'app.py' ? FileCode2 : LockKeyhole,
    content: <CodeEditor label={name === 'app.py' ? name : `${name}（只读）`}
      value={name === 'app.py' ? code : value} readOnly={name !== 'app.py'} onChange={setCode} />,
  }));
  return <>
    <TabBar id={id} label="组件示例文件" tabs={tabs} selected={file} onSelect={setFile} />
    <TabPanels autoHeight id={id} tabs={tabs} selected={file} />
  </>;
}

function PreviewExample() {
  const id = useId();
  const [tab, setTab] = useState('html');
  const [html, setHtml] = useState(sampleHtml);
  const [css, setCss] = useState(sampleCss);
  const [applied, setApplied] = useState({ html: sampleHtml, css: sampleCss });
  const tabs = [
    { id: 'html', label: 'HTML', icon: FileCode2, content: <CodeEditor embedded label="组件预览 HTML" value={html} onChange={setHtml} /> },
    { id: 'css', label: 'CSS', icon: FileText, content: <CodeEditor embedded label="组件预览 CSS" value={css} onChange={setCss} /> },
  ];
  return <div className="demo-component-preview">
    <div>
      <TabBar id={id} label="组件预览代码" tabs={tabs} selected={tab} onSelect={setTab} />
      <TabPanels autoHeight id={id} tabs={tabs} selected={tab} />
      <ActionGroup><ArtifactAction icon={RefreshCw} label="应用到组件预览" primary onClick={() => setApplied({ html, css })}>
        更新预览
      </ArtifactAction></ActionGroup>
    </div>
    <IsolatedPreview {...applied} title="组件隔离预览（无脚本、无网络）" />
  </div>;
}

function AnswerExample({ subtype }: { subtype: string }) {
  const check = checks.find((item) => item.subtype === subtype)!;
  const [value, setValue] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [order, setOrder] = useState<string[]>(check.options ?? []);
  const [lines, setLines] = useState<number[]>([]);
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [submitted, setSubmitted] = useState(false);
  return <>
    <Explanation><p>{check.prompt}</p></Explanation>
    {check.code && <CodeBlock>{check.code}</CodeBlock>}
    {subtype === 'single' && <ChoiceAnswer label={check.prompt} options={check.options!} value={value} onChange={setValue} />}
    {subtype === 'multiple' && <ChoiceAnswer multiple label={check.prompt} options={check.options!} value={selected} onChange={setSelected} />}
    {['prediction', 'short'].includes(subtype) && <TextAnswer label={subtype === 'prediction' ? '预测输出，每行一项' : '你的解释'}
      accessibleLabel={`${check.title}组件回答`} value={value} onChange={setValue} />}
    {subtype === 'ordering' && <OrderingAnswer label="组件查询阶段顺序" value={order} onChange={setOrder} />}
    {subtype === 'range' && <><LineRangeAnswer lines={check.lines!} value={lines} reasons={reasons} drafts={drafts}
      disabled={submitted}
      feedback={submitted ? { 4: <p>{check.explanation}</p> } : {}}
      onDraftChange={(line, draft) => setDrafts((current) => {
        const next = { ...current };
        if (draft === null) delete next[line]; else next[line] = draft;
        return next;
      })}
      onSave={(line) => {
        setReasons((current) => ({ ...current, [line]: drafts[line].trim() }));
        setLines((current) => current.includes(line) ? current : [...current, line]);
        setDrafts((current) => { const next = { ...current }; delete next[line]; return next; });
      }}
      onRemove={(line) => {
        setLines((current) => current.filter((number) => number !== line));
        setReasons((current) => { const next = { ...current }; delete next[line]; return next; });
      }} />
      <ActionGroup><ArtifactAction icon={Send} label="提交组件审查" primary completed={submitted}
        disabled={submitted || !rangeAnswerReady(check, lines, reasons, drafts)} onClick={() => setSubmitted(true)}>
        {submitted ? '已提交' : '提交审查'}
      </ArtifactAction></ActionGroup>
      {submitted && <AnswerFeedback kind="reference">{checkResponse(check, lines).text}</AnswerFeedback>}
    </>}
  </>;
}

function ProcessExample() {
  const [step, setStep] = useState(0);
  const values = [1, 2, 3];
  return <StepPlayer label="组件循环步骤" items={values} step={step} onStep={setStep}
    feedback={<KeyValueList label="当前观察值" entries={[
      { name: '已观察', value: `${step} / 3 步` },
      { name: 'result', value: <code>{values.slice(0, step).reduce((sum, value) => sum + value, 0)}</code> },
    ]} />}
    actions={<ArtifactAction icon={RotateCcw} label="重新观察" disabled={step === 0} onClick={() => setStep(0)} />} />;
}

function FeedbackExample() {
  const id = useId();
  const [kind, setKind] = useState('incorrect');
  const tabs = [
    { id: 'incorrect', label: '需调整', content: <AnswerFeedback kind="incorrect">{checks[0].explanation}</AnswerFeedback> },
    { id: 'correct', label: '正确', content: <AnswerFeedback kind="correct">{checks[0].explanation}</AnswerFeedback> },
    { id: 'reference', label: '参考讲评', content: <AnswerFeedback kind="reference">{checks[5].explanation}</AnswerFeedback> },
  ];
  return <>
    <TabBar id={id} label="反馈样式" tabs={tabs} selected={kind} onSelect={setKind} />
    <TabPanels autoHeight id={id} tabs={tabs} selected={kind} />
  </>;
}

function ReviewExample() {
  return <ReviewFinding lines={brokenCode.split('\n')} findings={[{ line: 4, content:
    <p><code>result = value</code> 覆盖了已有结果，应改为 <code>result += value</code>。</p>,
  }]} />;
}

function DiffExample() {
  const [code, setCode] = useState(fixedCode);
  return <>
    <p>以错误版为基准。底部开关在原编辑区插入只读旧行，当前代码仍可编辑。</p>
    <CodeDiff before={brokenCode} after={code} label="差异样例代码" onChange={setCode} />
  </>;
}

const treeNodes = [{ id: 'project', label: '求和练习', children: [
  { id: 'src', label: 'src', children: [{ id: 'total', label: 'total.py' }] },
  { id: 'tests', label: 'tests', children: [{ id: 'test', label: 'test_total.py' }] },
] }];
const treeFiles: Record<string, { label: string; code: string }> = {
  total: { label: 'total.py', code: fixedCode },
  test: { label: 'test_total.py', code: 'from src.total import total\n\nassert total([1, 2, 3]) == 6\nassert total([]) == 0' },
};

function TreeExample() {
  const [expanded, setExpanded] = useState(['project', 'src', 'tests']);
  const [selected, setSelected] = useState('total');
  return <>
    <p>示例项目：展开目录，选择文件查看内容。</p>
    <TreeView label="求和练习文件结构" nodes={treeNodes} expanded={expanded} selected={selected}
      onToggle={(id) => setExpanded((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])}
      onSelect={setSelected} />
    <div className="demo-visual-detail"><CodeBlock label={treeFiles[selected].label}>{treeFiles[selected].code}</CodeBlock></div>
  </>;
}

const relationNodes = [
  { id: 'test', label: '测试文件', x: 110, y: 85 },
  { id: 'app', label: '应用代码', x: 380, y: 85 },
  { id: 'framework', label: 'Flask', x: 650, y: 85 },
  { id: 'lock', label: '依赖锁文件', x: 380, y: 260 },
];
const relationEdges = [
  { from: 'test', to: 'app', label: '调用并检查' },
  { from: 'app', to: 'framework', label: '使用框架' },
  { from: 'lock', to: 'framework', label: '固定版本' },
];
const relationDetails: Record<string, string> = {
  test: '测试调用应用接口，对比响应是否符合预期。',
  app: '应用代码依赖框架提供路由和响应能力，同时接受测试检查。',
  framework: '应用使用 Flask；依赖锁文件记录所用版本。',
  lock: '锁文件约束依赖版本，不负责运行应用或测试。',
};

function RelationExample() {
  const [selected, setSelected] = useState<string | null>(null);
  return <>
    <p>点击节点，突出与它直接相连的依赖关系；再次点击取消。</p>
    <RelationGraph label="示例项目依赖关系" nodes={relationNodes} edges={relationEdges} selected={selected} onSelect={setSelected} />
    <p className="demo-visual-detail" aria-live="polite"><AnimatedText block>{selected ? relationDetails[selected] : '箭头从使用者指向被使用的对象。'}</AnimatedText></p>
  </>;
}

const sequenceParticipants = [
  { id: 'browser', label: '浏览器' }, { id: 'app', label: '应用' }, { id: 'db', label: '数据库' },
];
const sequenceSteps = [
  { id: 'request', from: 'browser', to: 'app', label: 'GET /orders' },
  { id: 'query', from: 'app', to: 'db', label: 'SELECT 订单' },
  { id: 'rows', from: 'db', to: 'app', label: '返回订单行' },
  { id: 'response', from: 'app', to: 'browser', label: '返回 JSON' },
];
const sequenceDetails = [
  '浏览器发起读取订单的请求。',
  '应用查询数据库，此时浏览器还没有收到结果。',
  '数据库把查询结果交还应用。',
  '应用组织响应并返回浏览器，一次请求完成。',
];

function SequenceExample() {
  const [step, setStep] = useState(0);
  return <>
    <p>一次查询的协作示意，可点击箭头或逐步播放；不发送真实请求。</p>
    <SequenceDiagram label="查询订单调用时序" participants={sequenceParticipants} steps={sequenceSteps} activeStep={step} onStep={setStep} />
    <StepPlayer label="请求过程" items={['请求', '查询', '返回数据', '响应']} step={step + 1}
      onStep={(next) => setStep(next - 1)} feedback={<p className="demo-visual-detail" aria-live="polite"><AnimatedText block>{sequenceDetails[step]}</AnimatedText></p>}
      actions={<ArtifactAction icon={RotateCcw} label="重新观察调用时序" onClick={() => setStep(0)} />} />
  </>;
}

function ParameterExample() {
  const [count, setCount] = useState(3);
  const [increment, setIncrement] = useState(2);
  return <>
    <p>调整循环次数和每次增量，观察累加器的变化。</p>
    <ParameterControl label="循环次数" min={0} max={8} value={count} onChange={setCount} />
    <ParameterControl label="每次增量" min={-3} max={5} value={increment} onChange={setIncrement} />
    <CodeBlock>{`result = 0\nfor _ in range(${count}):\n    result += ${increment}`}</CodeBlock>
    <div className="demo-parameter-trace" aria-label="每一步的累加结果">
      {Array.from({ length: count + 1 }, (_, index) => <span key={index}><AnimatedText>{index * increment}</AnimatedText></span>)}
    </div>
    <output className="demo-parameter-result" aria-live="polite"><AnimatedText>result = {count * increment}</AnimatedText></output>
  </>;
}

function ActionExample() {
  const id = useId();
  const [phase, setPhase] = useState<ActionPhase>('idle');
  const [disabled, setDisabled] = useState(false);
  const [clicks, setClicks] = useState(0);
  const labels = { idle: '运行检查', busy: '检查中', completed: '已检查', attention: '需修改', unknown: '结果未知' };
  const phases = Object.entries(labels).map(([key, label]) => ({ id: key, label }));
  return <>
    <TabBar id={id} label="按钮状态样式" tabs={phases} selected={phase} onSelect={(value) => setPhase(value as ActionPhase)} />
    <TabPanels autoHeight id={id} tabs={phases.map((item) => ({ ...item, content: <p>{item.label}样式，仅用于预览。</p> }))} selected={phase} />
    <label className="demo-choice"><input type="checkbox" checked={disabled} onChange={(event) => setDisabled(event.target.checked)} /><span>禁用按钮</span></label>
    <ActionGroup><ArtifactAction icon={Play} label="触发组件样例回调" primary phase={phase}
      disabled={disabled || phase === 'unknown' || phase === 'completed'} onClick={() => setClicks(clicks + 1)}>{labels[phase]}</ArtifactAction></ActionGroup>
    {clicks > 0 && <Notice>已触发 {clicks} 次本页回调，没有执行代码。</Notice>}
  </>;
}

function ConfirmationExample() {
  const [confirmed, setConfirmed] = useState(false);
  return <>
    <Explanation><p>确认只记录此页选择，不安装环境或修改学习路线。</p></Explanation>
    <ActionGroup>
      <ArtifactAction icon={Check} label="确认组件样例" primary completed={confirmed} disabled={confirmed}
        onClick={() => setConfirmed(true)}>{confirmed ? '已确认' : '确认'}</ArtifactAction>
      <ArtifactAction icon={X} label="撤销组件样例选择" disabled={!confirmed} onClick={() => setConfirmed(false)}>撤销</ArtifactAction>
    </ActionGroup>
  </>;
}

const examples: Record<string, (props: { active: boolean }) => ReactNode> = {
  explanation: () => <Explanation title="实现列表求和"><p>实现 <code>total(values)</code>，返回所有整数的和。空列表返回 0。</p></Explanation>,
  'source-reference': () => <SourceExample />,
  'code-block': () => <CodeBlock>{checks[2].code}</CodeBlock>,
  'code-editor': () => <FileExample />,
  'code-diff': () => <DiffExample />,
  'data-table': () => <DataTable label="订单样例数据" columns={['id', 'category', 'amount']}
    rows={[[1, 'books', 100], [2, 'books', 50], [3, 'tools', 240], [4, 'food', 30]]} />,
  'key-values': () => <KeyValueList label="公开输入与预期输出" entries={[
    { name: '输入', value: <code>[1, 2, 3]</code> }, { name: '预期输出', value: <code>6</code> },
  ]} />,
  'isolated-preview': () => <PreviewExample />,
  'tree-view': () => <TreeExample />,
  'relation-graph': () => <RelationExample />,
  'sequence-diagram': () => <SequenceExample />,
  'algorithm-sequence': ({ active }) => <AlgorithmExample kind="sequence" active={active} />,
  'algorithm-container': ({ active }) => <AlgorithmExample kind="container" active={active} />,
  'algorithm-graph': ({ active }) => <AlgorithmExample kind="graph" active={active} />,
  'algorithm-grid': ({ active }) => <AlgorithmExample kind="grid" active={active} />,
  'algorithm-recursion': ({ active }) => <AlgorithmExample kind="recursion" active={active} />,
  'algorithm-intervals': ({ active }) => <AlgorithmExample kind="intervals" active={active} />,
  'algorithm-bits': ({ active }) => <AlgorithmExample kind="bits" active={active} />,
  'algorithm-geometry': ({ active }) => <AlgorithmExample kind="geometry" active={active} />,
  'single-answer': () => <AnswerExample subtype="single" />,
  'multiple-answer': () => <AnswerExample subtype="multiple" />,
  'prediction-answer': () => <AnswerExample subtype="prediction" />,
  'short-answer': () => <AnswerExample subtype="short" />,
  'ordering-answer': () => <AnswerExample subtype="ordering" />,
  'line-range-answer': () => <AnswerExample subtype="range" />,
  'parameter-control': () => <ParameterExample />,
  'step-player': () => <ProcessExample />,
  'answer-feedback': () => <FeedbackExample />,
  'result-feedback': () => <ResultFeedback {...codeExampleResult(brokenCode)} />,
  'review-finding': () => <ReviewExample />,
  'action-states': () => <ActionExample />,
  'action-group': () => <ConfirmationExample />,
};

export default function ComponentGallery({ onViewArtifact }: { onViewArtifact: (id: string) => void }) {
  const id = useId();
  const [category, setCategory] = useState('all');
  const groups = category === 'all' ? componentCatalog : componentCatalog.filter((group) => group.id === category);
  return <>
    <div className="demo-gallery-toolbar">
      <label htmlFor={`${id}-category`}>按组件类别查看</label>
      <select id={`${id}-category`} value={category} onChange={(event) => setCategory(event.target.value)}>
        <option value="all">全部八类组件</option>
        {componentCatalog.map((group) => <option key={group.id} value={group.id}>{group.title}（{group.examples.length}）</option>)}
      </select>
    </div>
    <nav className="demo-gallery-index" aria-label="可拼接组件目录">
      {groups.map((group) => <div key={group.id}><span>{group.title}</span>
        <ul>{group.examples.map((example) => <li key={example.id}>
          <a href={`${artifactGalleryPath}?view=components#component-${example.id}`}>{example.title}</a>
        </li>)}</ul>
      </div>)}
    </nav>
    <div className="demo-gallery-content">
      {componentCatalog.map((group) => <section key={group.id} className="demo-gallery-group" hidden={category !== 'all' && category !== group.id}
        aria-labelledby={`${id}-${group.id}`}>
        <h2 id={`${id}-${group.id}`}>{group.title}</h2>
        {group.examples.map((example) => {
          const Example = examples[example.id];
          return <section key={example.id} id={`component-${example.id}`} className="demo-gallery-example demo-component-example" aria-label={`${example.title}组件样例`}>
            <header className="demo-component-heading"><h3>{example.title}</h3>
              {example.artifacts.length > 0 && <button type="button" className="demo-gallery-text-action" onClick={() => onViewArtifact(example.artifacts[0])}>查看完整工件</button>}
            </header>
            <div className="demo-component-stage"><Example active={category === 'all' || category === group.id} /></div>
            <Disclosure className="demo-gallery-source" title="组件接口与样式定位">
              <dl>
                <dt>组件</dt><dd><code>{example.components.join(' + ')}</code></dd>
                <dt>参数</dt><dd>{example.components.map((name) => <p key={name}><code>{name}: {componentProps[name]}</code></p>)}</dd>
                <dt>实现</dt><dd><code>{example.id.startsWith('algorithm-') ? 'apps/librechat/AlgorithmVisuals.tsx（LearningComponents 统一导出）'
                  : ['code-diff', 'tree-view', 'relation-graph', 'sequence-diagram', 'parameter-control'].includes(example.id)
                  ? 'apps/librechat/LearningVisuals.tsx（LearningComponents 统一导出）'
                  : ['code-editor', 'action-states'].includes(example.id) ? 'apps/librechat/LearningUI.tsx（LearningComponents 统一导出）' : componentSource}</code></dd>
                {['code-diff', 'tree-view', 'relation-graph', 'sequence-diagram', 'parameter-control'].includes(example.id)
                  && <><dt>样式文件</dt><dd><code>apps/librechat/learning-visuals.css</code></dd></>}
                {example.id.startsWith('algorithm-') && <>
                  <dt>样式文件</dt><dd><code>apps/librechat/algorithm-visuals.css</code></dd>
                  <dt>演示步骤</dt><dd><code>apps/librechat/algorithm-demos.mjs</code>（固定教学轨迹，不执行用户代码）</dd>
                </>}
                <dt>样式选择器</dt><dd><code>{example.selectors}</code></dd>
                <dt>使用中的工件</dt><dd>{example.artifacts.length ? example.artifacts.join('、') : '独立组件样例，尚未接入完整工件'}</dd>
              </dl>
            </Disclosure>
          </section>;
        })}
      </section>)}
    </div>
  </>;
}
