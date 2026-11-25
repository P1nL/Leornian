import { useRef, useState, useSyncExternalStore } from 'react';
import { Action, Notice } from './LearningUI';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { sendPlanningTurn } from './native-intake.mjs';

export default function NativePlanAction({ conversationId, turnId }: {
  conversationId?: string; turnId: string;
}) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const submitting = useRef(false);
  const turns = state.snapshot?.turns.find((page) => page.conversation_id === conversationId)?.turns ?? [];
  const latest = turns.filter((turn) => turn.purpose === 'planning').at(-1);
  const planning = latest?.planning_state;
  if (!conversationId || latest?.id !== turnId || !latest.completed_at || !planning?.information_complete ||
    planning.missing_information?.length || (planning.plan_requested && !planning.material_blocked)) return null;
  const conversation = state.snapshot?.conversations?.find((item) => item.id === conversationId);
  const goal = state.snapshot?.goals?.find((item) => item.id === conversation?.goal_id);
  if (planning.material_blocked && goal?.material_scope?.authorized_public_sources) return null;
  const active = state.snapshot?.runs.some((run) => run.conversation_id === conversationId &&
    ['queued', 'running', 'blocked_unknown'].includes(run.status));
  const run = state.snapshot?.runs.find((item) => item.turn_id === turnId);
  const recovering = planning.material_blocked && state.snapshot?.delivery_tasks?.some(
    (task) => task.run_id === run?.id && task.status === 'waiting_dependency',
  );
  const pending = state.pending.some((item) => item.path.includes(`/conversations/${conversationId}/`));
  return <div>
    <Action busy={busy} disabled={busy || active || pending || recovering} onClick={() => {
      if (submitting.current) return;
      submitting.current = true; setBusy(true); setError('');
      void (async () => {
        if (planning.material_blocked) {
          await nativeRequest(`/v1/conversations/${conversationId}/material-repair`, { method: 'POST' });
          await nativeStore.refresh();
          return;
        }
        await sendPlanningTurn(nativeStore, conversationId, '制定计划', crypto.randomUUID(), planning);
      })().catch((problem: Error) => setError(problem.message))
        .finally(() => { submitting.current = false; setBusy(false); });
    }}>{planning.material_blocked ? '修复并继续' : '制定计划'}</Action>
    {error && <Notice>{error}</Notice>}
  </div>;
}
