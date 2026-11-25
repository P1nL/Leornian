import { lazy, Suspense } from 'react';
import type { components } from '@leornian/api-contracts';

const QuestionBankRelay = lazy(() => import('./QuestionBankRelay'));
type Report = components['schemas']['GenerationReport'];
type Stage = components['schemas']['GenerationStage'];
const roles: [Stage['role'], string][] = [
  ['author', '拟题'], ['blind', '独立盲解'], ['curriculum', '课程范围'], ['difficulty', '难度梯度'],
  ['technical', '技术正确性'], ['ambiguity', '题意与歧义'], ['security', '安全与泄题'], ['adversarial', '边界与独立性'],
];
const statuses = { queued: '已排队', running: '进行中', failed: '未完成', cancelled: '已取消',
  blocked_unknown: '等待核对原回执', succeeded: '已完成' };
const slots: Record<string, string> = { practice_1: '练习一', practice_2: '练习二', assessment_1: '考核一',
  assessment_2: '考核二', remediation_1: '补救题' };
const decisions = { pass: '通过', revise: '需修订', reject: '不通过' };
const independence = { supported: '支持独立作答', revise: '需修订', reject: '不支持独立作答' };
export const packStatuses = { authoring: '拟题中', blind_solving: '盲解中', qualifying: '验证执行中',
  reviewing: '六审中', changes_required: '需修订', ready: '待发布', published: '已发布', failed: '未完成', cancelled: '已取消' };
const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN', { month: 'numeric',
  day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

function outcome(stage: Stage) {
  if (stage.status !== 'succeeded') return statuses[stage.status];
  if (stage.independence === 'reject' || Object.values(stage.decisions ?? {}).includes('reject')) return '不通过';
  if (stage.independence === 'revise' || Object.values(stage.decisions ?? {}).includes('revise')) return '需修订';
  if (stage.independence) return '通过';
  if (stage.role === 'blind' && stage.blind_passed != null) return stage.blind_passed ? '比对通过' : '比对未通过';
  return statuses[stage.status];
}

function StageEntry({ title, stage }: { title: string; stage?: Stage }) {
  if (!stage) return <li className="bank-stage-pending"><span>{title}</span><small>未开始</small></li>;
  return <li><details>
    <summary><span>{title}</span><strong>{outcome(stage)}</strong></summary>
    <div className="bank-stage-body">
      <p className="demo-muted">派发 {formatTime(stage.started_at)}
        {stage.completed_at && ` · 结束 ${formatTime(stage.completed_at)}`}</p>
      {stage.public_notes.length > 0 && <div><h4>模型公开说明</h4>
        {stage.public_notes.map((note) => <p key={note}>{note}</p>)}</div>}
      {stage.role === 'author' && stage.item_count != null && <p>作者提交了 {stage.item_count} 道题的草案。</p>}
      {stage.role === 'blind' && stage.item_count != null && <p>已独立提交 {stage.item_count} 份作答。
        {stage.blind_passed == null ? '尚无整组自动比对结论。' : stage.blind_passed ? '整组答案比对通过。' : '整组未通过比对。'}</p>}
      {stage.independence && <div><h4>逐题结论</h4>
        <dl>{Object.entries(slots).map(([slot, label]) => {
          const verdict = stage.decisions?.[slot];
          return verdict ? <div key={slot}><dt>{label}</dt><dd>{decisions[verdict]}</dd></div> : null;
        })}</dl><p>练习与考核的关系：{independence[stage.independence]}。</p></div>}
    </div>
  </details></li>;
}

export function QuestionBankGeneration({ report, executable }: { report: Report; executable: boolean }) {
  const byRole = new Map(report.stages.map((stage) => [stage.role, stage]));
  const totals = report.qualifications;
  const qualified = (totals.passed ?? 0) + (totals.not_passed ?? 0) + (totals.error ?? 0);
  return <section aria-label="题目生成过程" className="bank-process">
    <Suspense fallback={null}><QuestionBankRelay key={report.pack_id} report={report} executable={executable} /></Suspense>
    <h3>出题与盲解</h3>
    <ol>{roles.slice(0, 2).map(([role, title]) => <StageEntry key={role} title={title} stage={byRole.get(role)} />)}
      {executable && <li className="bank-stage-pending"><span>沙盘执行验证</span>
        <small>{Object.keys(totals).length ? `已返回 ${qualified}/5 · 通过 ${totals.passed ?? 0}` : '未开始'}</small></li>}
    </ol>
    <h3>六项独立审核 <small>{roles.slice(2).filter(([role]) => byRole.get(role)?.independence).length}/6 已返回</small></h3>
    <ol>{roles.slice(2).map(([role, title]) => <StageEntry key={role} title={title} stage={byRole.get(role)} />)}</ol>
    <p className="bank-publication">{report.published_at
      ? `已发布 · ${formatTime(report.published_at)}` : `本版题包：${packStatuses[report.status]}`}</p>
  </section>;
}
