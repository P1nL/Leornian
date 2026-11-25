export function nativeReplyOutcome(snapshot, turn) {
  if (turn.assistant_text?.trim()) return null;
  const run = snapshot.runs?.find((item) => item.turn_id === turn.id);
  const task = run && snapshot.delivery_tasks?.find((item) => item.run_id === run.id);
  if (run && ['queued', 'running', 'blocked_unknown'].includes(run.status)) return null;
  const messages = {
    waiting_input: '本轮回复等待补充信息，尚未交付正文。',
    waiting_config: '本轮回复等待模型配置，尚未交付正文。请在模型配置中核对后继续。',
    waiting_dependency: '本轮回复等待依赖恢复，尚未交付正文。可在后台任务中查看原任务。',
    blocked_protocol: '本轮回复未通过交付检查，原任务已暂停。可在后台任务中核对检查结论。',
    failed: '本轮回复未完成，没有已交付的正文。可在后台任务中查看原任务。',
    cancelled: '本轮回复已取消，没有已交付的正文。',
    superseded: '本轮回复的绑定已变化，没有交付正文。',
  };
  const status = messages[task?.status] ? task.status : run?.status;
  if (messages[status]) return {
    status, message: messages[status],
    ...(task?.required_input?.length ? { requiredInput: task.required_input } : {}),
    ...(run?.error_code ? { errorCode: run.error_code } : {}),
  };
  const steps = turn.thinking_steps ?? [];
  if (run?.status !== 'succeeded' && !turn.completed_at &&
    !(steps.length && !steps.some((step) => step.status === 'running'))) return null;
  return { status: 'empty', message: '本轮没有已交付的回复正文。可在后台任务中查看原任务状态。' };
}
