import { Check } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { Action, Notice } from './LearningUI';

type Report = components['schemas']['ReviewReportView'];
export type ReviewReportCommand = Omit<components['schemas']['CompleteReviewAction'],
  'client_action_id' | 'expected_artifact_revision'>;

export function NativeReviewReport({ report, blocked, pending = false, onCommand }: {
  report: Report; blocked: boolean; pending?: boolean; onCommand: (command: ReviewReportCommand) => void;
}) {
  return <section aria-label="评审阅读确认" className="space-y-2">
    {report.completion ? <div role="status">
      <p>已确认阅读本次评审</p>
      <p className="demo-muted">已保存：<time dateTime={report.completion.completed_at}>
        {new Date(report.completion.completed_at).toLocaleString('zh-CN', { hour12: false })}
      </time></p>
    </div> : report.state === 'ready' && report.allowed_actions.includes('complete_review')
      ? <Action icon={Check} disabled={blocked} onClick={() => onCommand({
        action: 'complete_review', component_id: report.component_id,
      })}>我已阅读本次评审</Action> : null}
    {report.state === 'cancelled' && <Notice>本次评审已取消。</Notice>}
    {pending && <Notice>阅读确认尚待核对，请在“任务与原提交回执”中读取原回执。</Notice>}
  </section>;
}
