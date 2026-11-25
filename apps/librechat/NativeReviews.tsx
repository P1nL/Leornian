import { useEffect, useState, useSyncExternalStore } from 'react';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { Action, Notice } from './LearningUI';

type Card = {
  id: string; revision: number; status: 'scheduled' | 'paused'; due: boolean;
  prompt: string; next_due_at: string; algorithm_version: string; parameter_version: string;
};
type Activity = {
  kind: 'memory_review'; id: string; goal_id: string; card_id: string; card_revision: number;
  state: 'due' | 'presented' | 'completed' | 'cancelled'; conversation_id: string | null;
  source_receipt: string | null; presented_at: string | null; created_at: string; card: Card;
};
type Preference = {
  revision: number; enabled: boolean; timezone: string; start_minute: number; end_minute: number;
};
const labels = { due: '待复习', presented: '回忆练习', completed: '已记录', cancelled: '已取消' };
const clock = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
const minutes = (value: string) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));

export function NativeReviews({ conversationId, goalId, presentedOnly = false }: {
  conversationId: string; goalId?: string; presentedOnly?: boolean;
}) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const [items, setItems] = useState<Activity[]>([]), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [logs, setLogs] = useState<Record<string, { id: string; rating: string; reviewed_at: string; due_at: string; algorithm_version: string }[]>>({});
  const inScope = (item: Activity) => item.conversation_id === conversationId ||
    !presentedOnly && item.goal_id === goalId && item.state === 'due' && !item.conversation_id;
  const reload = async () => {
    const all = await nativeRequest('/v1/review-activities') as Activity[];
    setItems(all.filter(inScope));
  };
  useEffect(() => {
    let current = true;
    setItems([]); setError('');
    void nativeRequest('/v1/review-activities').then((all: Activity[]) => {
      if (current) setItems(all.filter(inScope));
    }).catch((problem: Error) => { if (current) setError(problem.message); });
    return () => { current = false; };
  }, [conversationId, goalId, presentedOnly, state.epoch, state.snapshot?.actor.id]);
  const command = async (item: Activity, action: 'present' | 'responses' | 'cancel', rating?: string) => {
    const key = crypto.randomUUID();
    setBusy(true); setError('');
    try {
      await nativeStore.write(`/v1/review-activities/${item.id}/${action}`,
        action === 'responses' ? { expected_revision: item.card_revision, rating }
          : action === 'present' ? { expected_card_revision: item.card_revision, conversation_id: conversationId } : {},
        { key, lookup: `/v1/review-activities/${item.id}/commands/${key}` });
      await reload();
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <section aria-label="会话复习活动" className="mx-auto w-full max-w-3xl space-y-4">
    {error && <Notice>{error}</Notice>}
    {!items.length && !error && !presentedOnly && <p className="demo-muted">当前没有待复习活动。</p>}
    {items.map((item) => {
      const pending = state.pending.filter((entry) => entry.path.startsWith(`/v1/review-activities/${item.id}/`));
      const blocked = busy || pending.length > 0;
      return <article key={item.id} data-review-activity={item.id}
      className="border-border-light bg-surface-secondary rounded-xl border px-5 py-4">
      <header className="text-text-secondary mb-3 flex flex-wrap justify-between gap-2 text-xs">
        <span>记忆复习 · {labels[item.state]}</span>
        <time dateTime={item.presented_at ?? item.created_at}>{new Date(item.presented_at ?? item.created_at).toLocaleString()}</time>
      </header>
      <p className="text-text-primary whitespace-pre-wrap leading-7">{item.card.prompt}</p>
      {item.state === 'due' && <Action disabled={blocked} onClick={() => void command(item, 'present')}>在本会话开始复习</Action>}
      {item.state === 'presented' && item.card.due && item.card.revision === item.card_revision
        ? <div className="mt-4 flex flex-wrap gap-2" aria-label="本人回忆情况">
          <Action disabled={blocked} onClick={() => void command(item, 'responses', 'again')}>没想起来</Action>
          <Action disabled={blocked} onClick={() => void command(item, 'responses', 'good')}>想起来了</Action>
          <Action disabled={blocked} onClick={() => void command(item, 'responses', 'easy')}>轻松回忆</Action>
          <Action disabled={blocked} onClick={() => void command(item, 'cancel')}>取消这次复习</Action>
        </div> : <p className="text-text-secondary mt-3 text-sm">
          下次安排：{new Date(item.card.next_due_at).toLocaleString()} · {item.card.algorithm_version}
        </p>}
      <p className="text-text-secondary mt-3 text-xs">按本人回忆情况安排记忆复习，能力证据按概念、执行与迁移分别查看。</p>
      {pending.map((entry) => <Notice key={entry.key}>原动作尚待核对。
        <Action disabled={busy} onClick={() => {
          void nativeStore.reconcile(entry.key).then(reload).catch((problem: Error) => setError(problem.message));
        }}>读取原动作回执</Action>
      </Notice>)}
      <button className="mt-2 text-xs underline" onClick={() => {
        void nativeRequest(`/v1/reviews/${item.card_id}/logs`).then((history) => {
          setLogs((previous) => ({ ...previous, [item.id]: history }));
        }).catch((problem: Error) => setError(problem.message));
      }}>查看真实复习日志</button>
      {logs[item.id] && <ol className="text-text-secondary mt-2 space-y-1 text-xs">
        {logs[item.id].map((log) => <li key={log.id}>
          {new Date(log.reviewed_at).toLocaleString()} · {log.rating} · 下次 {new Date(log.due_at).toLocaleString()} · {log.algorithm_version}
        </li>)}
      </ol>}
    </article>;
    })}
  </section>;
}

export function NativeReviewPreferences({ conversationId }: { conversationId: string }) {
  const [preference, setPreference] = useState<Preference>({
    revision: 0, enabled: false, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    start_minute: 540, end_minute: 1260,
  });
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => {
    void nativeRequest(`/v1/conversations/${conversationId}/proactive-preference`).then((value) => {
      if (value) setPreference(value);
    }).catch((problem: Error) => setError(problem.message));
  }, [conversationId]);
  const save = async () => {
    const key = crypto.randomUUID();
    setBusy(true); setError('');
    try {
      const result = await nativeStore.write(`/v1/conversations/${conversationId}/proactive-preference`, {
        expected_revision: preference.revision, enabled: preference.enabled,
        timezone: preference.timezone, start_minute: preference.start_minute, end_minute: preference.end_minute,
      }, { key, lookup: `/v1/conversations/${conversationId}/proactive-preference/commands/${key}` });
      setPreference(result);
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <details className="border-border-light rounded-lg border p-3">
    <summary className="cursor-pointer text-sm">主动教学与复习时段</summary>
    <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
      <label><input type="checkbox" checked={preference.enabled} onChange={(event) =>
        setPreference({ ...preference, enabled: event.target.checked })} /> 允许本会话主动提示</label>
      <label>从 <input type="time" value={clock(preference.start_minute)} onChange={(event) =>
        setPreference({ ...preference, start_minute: minutes(event.target.value) })} /></label>
      <label>到 <input type="time" value={clock(preference.end_minute)} onChange={(event) =>
        setPreference({ ...preference, end_minute: minutes(event.target.value) })} /></label>
      <span>{preference.timezone}</span>
      <Action disabled={busy} onClick={() => void save()}>保存安排</Action>
    </div>
    <p className="text-text-secondary mt-2 text-xs">引导模式下按已提交结果与到期事实提示；暂停、当前输入与考试优先。</p>
    {error && <Notice>{error}</Notice>}
  </details>;
}
