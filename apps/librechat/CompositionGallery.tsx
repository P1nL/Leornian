import { useId, useState } from 'react';
import { Check } from 'lucide-react';
import { ArtifactAction, CodeEditor, Disclosure, Notice } from './LearningUI';
import LearningComposition from './LearningComposition';
import type { Composition, CompositionDraft, CompositionIntent, CompositionReceipt } from './LearningComposition';
import { initialCompositionDraft, parseComposition } from './composition-runtime.mjs';
import examples from './composition-examples.json';
import { brokenCode } from './learning-demo-data.mjs';
import { codeExampleResult } from './demo-state.mjs';

function PreviewSession({ definition, active }: { definition: Composition; active: boolean }) {
  const [draft, setDraft] = useState<CompositionDraft>(() => initialCompositionDraft(definition));
  const [submitted, setSubmitted] = useState(false);
  const [receipt, setReceipt] = useState<CompositionReceipt>();
  const handleAction = (intent: CompositionIntent) => {
    if (intent.type === 'submit_review') {
      setSubmitted(true);
      setReceipt({
        type: 'review', message: '已提交本页批注；以下仅为公开样例讲评，不评判理由或写入学习记录。',
        feedback: definition.scene.type === 'code_review' && definition.scene.code === brokenCode
          ? { 4: '这里覆盖了之前的结果，应使用 result += value 累加。' } : {},
      });
    } else {
      const isFixture = JSON.stringify(definition) === JSON.stringify(examples[3]);
      const result = isFixture ? codeExampleResult(intent.code) : null;
      setReceipt({
        type: 'code', code: intent.code, message: result
          ? `离线样例回执，未执行代码：${result.label}`
          : '自定义配置已展示；未接执行服务，不生成检查结果。',
        rows: result?.rows ?? [],
      });
    }
  };
  return <LearningComposition definition={definition} draft={draft} onDraftChange={setDraft}
    onAction={handleAction} status={submitted ? 'submitted' : 'ready'} receipt={receipt} active={active} />;
}

export default function CompositionGallery({ active }: { active: boolean }) {
  const id = useId();
  const [sample, setSample] = useState('0');
  const [definition, setDefinition] = useState(() => parseComposition(examples[0]));
  const [config, setConfig] = useState(() => JSON.stringify(examples[0], null, 2));
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const apply = (value: unknown) => {
    const parsed = parseComposition(value);
    setDefinition(parsed);
    setRevision((current) => current + 1);
    setError('');
  };
  return <>
    <div className="demo-gallery-toolbar">
      <label htmlFor={id}>组合场景</label>
      <select id={id} value={sample} onChange={(event) => {
        const index = event.target.value;
        setSample(index);
        setConfig(JSON.stringify(examples[Number(index)], null, 2));
        apply(examples[Number(index)]);
      }}>
        {sample === 'custom' && <option value="custom" disabled>自定义配置</option>}
        {examples.map((example, index) => <option key={index} value={index}>{example.title}</option>)}
      </select>
    </div>
    <div className="demo-component-stage">
      <PreviewSession key={revision} definition={definition} active={active} />
    </div>
    <Disclosure title="编辑组合配置">
      <p>改变数据或视图后明确应用；应用成功会重置本页草稿，格式错误则保留当前场景。</p>
      <CodeEditor label="组合 JSON 配置" value={config} onChange={setConfig} />
      <div className="demo-actions"><ArtifactAction icon={Check} label="应用组合配置" primary onClick={() => {
        try { apply(JSON.parse(config)); setSample('custom'); }
        catch (cause) { setError(cause instanceof Error ? cause.message : '配置无效'); }
      }} /></div>
      {error && <Notice>配置未应用：{error}</Notice>}
    </Disclosure>
  </>;
}
