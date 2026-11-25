import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { components } from '@leornian/api-contracts';
import { Action, Notice } from './LearningUI';
import { NativeApiError, nativeRequest, nativeStore } from './native-client.mjs';

type UpdateNotification = components['schemas']['Notification'];
type Offer = components['schemas']['MaterialUpdateOffer'];
type Decision = components['schemas']['MaterialUpdateDecision'];
type Preparation = components['schemas']['MaterialRepreparation'];
type Choice = components['schemas']['MaterialUpdateDecisionInput']['decision'];
const labels = { unread: '未读', read: '已读', deferred: '稍后决定', kept_current: '本轮保留旧版', accepted: '已接受更新' };
const decisionPath = (id: string) => `/v1/material-update-offers/${id}/decisions`;
const receiptText = (receipt: Decision) => receipt.decision === 'accept_update'
  ? `已保存后继绑定修订 ${receipt.successor_binding_revision}。${receipt.requires_reprepare.length
    ? '相关内容需要重新准备，既有路线和课时保留原引用。' : '后续新消费可使用已接受材料。'}`
  : receipt.decision === 'decide_later' ? '已选择稍后决定，当前绑定保持原版。' : '本轮继续使用旧版，当前绑定保持不变。';

function MaterialRepreparationStatus({ decision }: { decision: Decision }) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const [items, setItems] = useState<Preparation[]>([]), [error, setError] = useState('');
  useEffect(() => {
    let current = true, timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const result: Preparation[] = await nativeRequest(
          `/v1/material-update-decisions/${decision.id}/repreparations`,
        );
        if (!current) return;
        setItems(result); setError('');
        if (result.some((item) => !['ready', 'superseded', 'cancelled'].includes(item.state))) {
          timer = setTimeout(() => void load(), 2500);
        }
      } catch (problem) { if (current) setError((problem as Error).message); }
    };
    void load();
    return () => { current = false; clearTimeout(timer); };
  }, [decision.id, state.epoch]);
  const labels: Record<Preparation['state'], string> = {
    queued: '已登记准备', waiting_priority: '等待当前教学或考核结束', waiting_confirmation: '等待明确确认新路线',
    running: '原任务正在准备', waiting_receipt: '原结果未知，等待回执', ready: '已准备完成',
    superseded: '后续已有新内容', cancelled: '已取消', waiting_dependency: '等待材料或任务依赖',
  };
  return <section aria-label="已接受更新的内容准备" className="demo-stack">
    <h4>更新后的路线与课时准备</h4>
    {error && <Notice>{error}</Notice>}
    {items.map((item) => <div className="demo-task-row" key={item.id}>
      <p>{item.kind === 'plan' ? '路线候选' : `课时 · ${item.node_key}`} · {labels[item.state]}</p>
      {item.output_plan_revision && <p className="demo-muted">对应路线修订 {item.output_plan_revision}</p>}
      {item.state === 'waiting_confirmation' && <Notice>请在“学习路线与课时”明确确认对应的新路线，再准备课时。</Notice>}
      {item.state === 'waiting_receipt' && <Notice>保留原任务，读取回执后继续。</Notice>}
      {item.run_id && <p className="demo-muted">原任务 {item.run_id}</p>}
      {item.output_lesson_id && <p className="demo-muted">已保存课时 {item.output_lesson_id}</p>}
      {item.reason && <p className="demo-muted">当前原因：{item.reason}</p>}
    </div>)}
    {!items.length && !error && <p className="demo-muted">当前没有待处理的内容准备记录。</p>}
  </section>;
}

export default function NativeMaterialUpdates() {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot, nativeStore.getSnapshot);
  return <MaterialUpdates key={state.snapshot?.actor.id ?? 'unloaded'} />;
}
function MaterialUpdates() {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot, nativeStore.getSnapshot);
  const [notifications, setNotifications] = useState<UpdateNotification[]>([]);
  const [selected, setSelected] = useState<UpdateNotification | null>(null), [offer, setOffer] = useState<Offer | null>(null);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [more, setMore] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [decisionReceipt, setDecisionReceipt] = useState<Decision | null>(null);
  const alive = useRef(true), generation = useRef(0);
  const pending = state.pending.filter((item) => item.path.startsWith('/v1/material-update-offers/'));
  const waiting = offer && pending.some((item) => item.path === decisionPath(offer.id));
  const terminal = selected && ['accepted', 'kept_current'].includes(selected.state);
  const load = async (append = false) => {
    const current = ++generation.current;
    const before = append ? notifications.at(-1)?.id : undefined;
    setLoading(true);
    try {
      const page: UpdateNotification[] = await nativeRequest(`/v1/notifications?limit=20${before ? `&before=${before}` : ''}`);
      if (alive.current && current === generation.current) {
        setNotifications((previous) => append ? [...previous, ...page.filter((item) => !previous.some((old) => old.id === item.id))] : page);
        setMore(page.length === 20);
      }
    } finally { if (alive.current && current === generation.current) setLoading(false); }
  };
  const failure = (problem: unknown) => {
    if (problem instanceof NativeApiError && problem.code === 'stale_version') {
      return '材料绑定或更新提案已变化，请重新打开更新详情后决定。';
    }
    if (problem instanceof NativeApiError && problem.status === 404) return '当前后台尚未提供这份教材更新记录。';
    return problem instanceof Error ? problem.message : '教材更新暂时无法同步，请重新读取。';
  };
  useEffect(() => {
    alive.current = true;
    void load().catch((problem) => { if (alive.current) setError(failure(problem)); });
    return () => { alive.current = false; generation.current++; };
  }, [state.epoch]);
  const open = async (item: UpdateNotification) => {
    setBusy(true); setError(''); setNotice(''); setOffer(null); setDecisionReceipt(null);
    try {
      const value: Offer = await nativeRequest(`/v1/material-update-offers/${item.offer_id}`);
      if (!alive.current) return;
      setSelected(item); setOffer(value);
      if (item.state === 'unread') {
        const read: UpdateNotification = await nativeRequest(`/v1/notifications/${item.id}/read`, { method: 'POST' });
        if (alive.current) {
          setSelected(read); setNotifications((previous) => previous.map((old) => old.id === read.id ? read : old));
        }
      }
    } catch (problem) { if (alive.current) { setOffer(null); setError(failure(problem)); } }
    finally { if (alive.current) setBusy(false); }
  };
  const decide = async (decision: Choice) => {
    if (!offer || waiting || terminal || busy) return;
    const path = decisionPath(offer.id), key = crypto.randomUUID();
    setBusy(true); setError(''); setNotice('');
    try {
      const receipt: Decision = await nativeStore.write(path, {
        decision, expected_offer_revision: offer.revision, expected_binding_revision: offer.binding_revision,
      }, { key, lookup: `${path}/${key}` });
      if (alive.current) {
        setNotice(receiptText(receipt)); setDecisionReceipt(receipt); setOffer(null); await load();
      }
    } catch (problem) { if (alive.current) setError(failure(problem)); }
    finally { if (alive.current) setBusy(false); }
  };
  return <section className="demo-stack" aria-label="教材更新通知">
    <div className="demo-section-heading"><h3>教材更新</h3>
      <Action disabled={busy || loading} onClick={() => {
        setError(''); setOffer(null); void load().catch((problem) => setError(failure(problem)));
      }}>重新读取更新</Action></div>
    <p className="demo-muted">这里显示本人已准备合格的教材更新，默认继续使用当前版本。</p>
    {error && <div role="alert"><Notice>{error}</Notice></div>}
    {notice && <Notice>{notice}</Notice>}
    {decisionReceipt?.decision === 'accept_update' && decisionReceipt.requires_reprepare.length > 0 &&
      <MaterialRepreparationStatus key={decisionReceipt.id} decision={decisionReceipt} />}
    {pending.map((item) => <div className="demo-task-row" key={item.key}>
      <p>原更新决定尚待核对。</p>
      <Action disabled={busy} onClick={() => {
        setBusy(true); setError('');
        void nativeStore.reconcile(item.key).then((receipt: Decision) => {
          if (alive.current) {
            setNotice(receiptText(receipt)); setDecisionReceipt(receipt); setOffer(null); return load();
          }
        }).catch((problem) => { if (alive.current) setError(failure(problem)); })
          .finally(() => { if (alive.current) setBusy(false); });
      }}>读取原决定回执</Action>
    </div>)}
    {offer && <div className="demo-task-row" aria-label="教材更新详情">
      <h4>版本 {offer.baseline_revision} → {offer.candidate_revision}</h4>
      <p>{offer.summary}</p>
      <p className="demo-muted">候选准备已完成 · {offer.impact.dependencies.filter((item) => item.kind === 'plan').length} 份路线、
        {offer.impact.dependencies.filter((item) => item.kind === 'lesson').length} 份课时有实际依赖。</p>
      <p>{offer.migration_cost === 'dependent_content_requires_reprepare'
        ? '接受后，相关内容需要重新准备；既有路线和课时保留，路线改变时仍需明确确认。'
        : '接受后新增后继绑定，供后续新消费使用。'}</p>
      {terminal ? <Notice>{labels[selected!.state]}</Notice> : <div className="demo-actions">
        <Action disabled={busy || Boolean(waiting)} onClick={() => void decide('keep_current_for_track')}>本轮保留旧版</Action>
        <Action disabled={busy || Boolean(waiting)} onClick={() => void decide('decide_later')}>稍后决定</Action>
        <Action disabled={busy || Boolean(waiting)} onClick={() => void decide('accept_update')}>接受此更新</Action>
      </div>}
      <Action disabled={busy} onClick={() => setOffer(null)}>关闭详情</Action>
    </div>}
    {notifications.map((item) => <div className="demo-task-row" key={item.id}>
      <p>版本 {item.payload.baseline_revision} → {item.payload.candidate_revision} · {labels[item.state]}</p>
      <p className="demo-muted">{state.snapshot?.goals.find((goal) => goal.id === item.payload.goal_id)?.title ?? '本人学习目标'}
        {item.payload.node_key ? ` · ${item.payload.node_key}` : ''}</p>
      <Action disabled={busy} onClick={() => void open(item)}>查看更新详情</Action>
    </div>)}
    {loading && <p role="status">正在读取教材更新…</p>}
    {!loading && !notifications.length && !error && <p className="demo-muted">当前没有已准备合格的教材更新通知。</p>}
    {more && <Action disabled={loading || busy} onClick={() => void load(true).catch((problem) => setError(failure(problem)))}>读取更早更新</Action>}
  </section>;
}
