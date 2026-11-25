import type { components } from '@leornian/api-contracts';

type Report = components['schemas']['GenerationReport'];
type Stage = components['schemas']['GenerationStage'];
const stages = {
  author: ['author', '拟题', '派发拟题'], blind: ['blind', '盲解', '派发盲解'], curriculum: ['scope', '课程审核', '送审考点'],
  difficulty: ['level', '难度审核', '送审难度'], technical: ['technical', '技术审核', '送审技术'], ambiguity: ['wording', '歧义审核', '送审措辞'],
  security: ['safety', '安全审核', '送审安全'], adversarial: ['stress', '对抗审核', '送审整包'],
} as const;
const statusText = { queued: '已排队', running: '进行中', failed: '未完成', cancelled: '已取消',
  blocked_unknown: '等待核对原回执', succeeded: '已完成' };

type Message = { key: string; from: string; to: string; action: string; text: string };

function resultText(stage: Stage) {
  if (stage.status !== 'succeeded') return statusText[stage.status];
  if (stage.role === 'author' && stage.item_count != null) return `提交了 ${stage.item_count} 道题的草案。`;
  if (stage.role === 'blind' && stage.blind_passed != null) return stage.blind_passed ? '盲解比对通过。' : '盲解比对未通过。';
  if (stage.role === 'blind' && stage.item_count != null) return `提交了 ${stage.item_count} 份独立作答。`;
  const verdicts = [stage.independence, ...Object.values(stage.decisions ?? {})];
  if (verdicts.includes('reject')) return '审核不通过。';
  if (verdicts.includes('revise')) return '需要修订。';
  if (stage.independence === 'supported') return '审核通过。';
  return stage.public_notes[0] ?? '阶段已完成。';
}

export function generationMessages(report: Report, executable: boolean): Message[] {
  const dated: { at: number; message: Message }[] = [];
  for (const stage of report.stages) {
    const [role, title, dispatch] = stages[stage.role], key = `${stage.role}:${stage.started_at}`;
    dated.push({ at: Date.parse(stage.started_at), message: {
      key: `${key}:dispatch`, from: 'author', to: role, action: dispatch,
      text: stage.completed_at ? `${title}已派发。` : `${title}：${statusText[stage.status]}。`,
    } });
    if (!stage.completed_at) continue;
    const returned = stage.status === 'succeeded';
    const destination = !returned || stage.role === 'author' || (stage.role === 'blind' && executable) ? role : 'release';
    const action = !returned ? stage.status === 'blocked_unknown' ? '等待核对' : statusText[stage.status]
      : stage.role === 'author' ? '提交题稿' : stage.role === 'blind' ? '提交盲解' : '返回审核';
    dated.push({ at: Date.parse(stage.completed_at), message: {
      key: `${key}:result`, from: role, to: destination, action, text: resultText(stage),
    } });
  }
  if (report.published_at) dated.push({ at: Date.parse(report.published_at), message: {
    key: 'published', from: 'release', to: 'release', action: '发布题包', text: '本版题包已发布。',
  } });
  const messages = dated.sort((first, second) => first.at - second.at).map(({ message }) => message);
  if (executable && Object.keys(report.qualifications).length) {
    const totals = report.qualifications;
    const returned = (totals.passed ?? 0) + (totals.not_passed ?? 0) + (totals.error ?? 0);
    const nextReview = messages.findIndex(message => message.key === 'published' ||
      (message.from === 'author' && message.to !== 'blind' && message.to !== 'author'));
    const qualification: Message[] = [{ key: 'qualification:input', from: 'blind', to: 'sandbox',
      action: '送交验证', text: '独立作答进入沙盘验证。' }];
    if (returned) qualification.push({ key: 'qualification:result', from: 'sandbox', to: 'release',
      action: '验证回执', text: `已返回 ${returned}/5，通过 ${totals.passed ?? 0}。` });
    messages.splice(nextReview < 0 ? messages.length : nextReview, 0, ...qualification);
  }
  if (!report.published_at && (report.status === 'ready' || report.status === 'changes_required')) {
    const ready = report.status === 'ready';
    messages.push({ key: 'release:decision', from: 'release', to: 'release',
      action: ready ? '待发布' : '需修订', text: ready ? '本版题包待发布。' : '本版题包需要修订。' });
  }
  return messages;
}
