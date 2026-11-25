import { useEffect, useState } from 'react';
import { nativeRequest } from './native-client.mjs';
import { Notice } from './LearningUI';

type Projection = {
  dimensions: { dimension: string; status: string; evidence_count: number; passed_count: number;
    failed_count: number; assisted_count: number; independent_pass_count: number }[];
  evidence: { source_receipt: string; evidence_kind: string; dimension: string; outcome: string;
    policy_version: string; item_version: string; occurred_at: string; independence: string;
    plan_revision: number | null; node_key: string | null; material_versions: object[] }[];
};
const dimensions: Record<string, string> = { concept: '概念理解', execution: '执行能力', transfer: '新情境应用' };
const status: Record<string, string> = { unobserved: '待观察', practicing: '练习积累中', demonstrated: '已有独立考核证据' };
const outcomes: Record<string, string> = { passed: '通过', not_passed: '未通过', error: '执行未完成', observed: '已记录观察' };
const independence: Record<string, string> = { independent_gate: '独立考核', assisted: '有辅助', practice: '普通练习', unknown: '独立性待核对' };

export default function NativeLearningEvidence({ planId, epoch = 0 }: { planId?: string; epoch?: number }) {
  const [value, setValue] = useState<Projection | null>(null), [error, setError] = useState('');
  useEffect(() => {
    setValue(null); setError('');
    void nativeRequest(`/v1/learning-evidence${planId ? `?plan_id=${planId}` : ''}`).then((result) => {
      setValue(result); setError('');
    }).catch((problem: Error) => setError(problem.message));
  }, [planId, epoch]);
  return <section aria-label="分维度能力证据" className="space-y-3">
    {error && <Notice>{error}</Notice>}
    <div className="grid gap-3 sm:grid-cols-3">
      {value?.dimensions.map((dimension) => <article key={dimension.dimension} className="border-border-light rounded-lg border p-3">
        <h3 className="text-text-primary text-sm font-medium">{dimensions[dimension.dimension]}</h3>
        <p className="text-text-secondary mt-1 text-xs">{status[dimension.status]}</p>
        <p className="mt-3 text-sm">{dimension.evidence_count} 条事实 · 独立通过 {dimension.independent_pass_count}</p>
        <p className="text-text-secondary text-xs">练习/考核通过 {dimension.passed_count} · 未通过 {dimension.failed_count} · 有辅助 {dimension.assisted_count}</p>
      </article>)}
    </div>
    <details><summary className="cursor-pointer text-sm">查看来源与历史结果</summary>
      <ol className="mt-3 space-y-3">
        {value?.evidence.map((fact) => <li key={`${fact.evidence_kind}:${fact.source_receipt}`} className="border-border-light border-l-2 pl-3 text-xs">
          <strong>{dimensions[fact.dimension]} · {outcomes[fact.outcome] ?? fact.outcome}</strong>
          <p>{fact.evidence_kind} · {new Date(fact.occurred_at).toLocaleString()} · {independence[fact.independence] ?? fact.independence}</p>
          <p className="text-text-secondary">题目 {fact.item_version} · 策略 {fact.policy_version} · 来源回执 {fact.source_receipt}</p>
          {fact.node_key && <p>节点 {fact.node_key} · 计划修订 {fact.plan_revision}</p>}
        </li>)}
      </ol>
    </details>
  </section>;
}
