import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import * as Ariakit from '@ariakit/react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { components } from '@leornian/api-contracts';
import { Action, Disclosure, Notice } from './LearningUI';
import { RequirementDetails } from './NativeExecution';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { confirmFirstNode } from './learning-routes.mjs';

type Manifest = components['schemas']['RouteEnvironmentManifest'];
type Plan = components['schemas']['LearningPlan'];
type Conversation = components['schemas']['Conversation'];

function environmentLabel(manifest: Manifest | null) {
  if (!manifest) return '正在核对';
  if (manifest.gaps?.length) return '部分环境待支持';
  if (manifest.demands.some((item) => item.status === 'blocked_unknown')) return '准备结果待核对';
  if (manifest.consent_required.length) return '待允许安装';
  if (!manifest.requirements.length) return '无需准备';
  if (manifest.demands.some((item) => item.status === 'failed')) return '准备未完成';
  if (manifest.engine.status !== 'ready') return '等待隔离引擎';
  if (manifest.demands.length === manifest.requirements.length
    && manifest.demands.every((item) => item.status === 'ready'
      && (!item.plan_id || item.plan_revision === manifest.plan_revision))) return '已就绪';
  return manifest.demands.length < manifest.requirements.length ? '待准备' : '准备中';
}

export default function NativeRouteConfirmation({ conversationId }: { conversationId?: string }) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const conversation = state.snapshot?.conversations.find((item) => item.id === conversationId);
  const plan = state.snapshot?.plans.find((item) => item.goal_id === conversation?.goal_id);
  if (!conversation || !plan) return null;
  return <RouteConfirmation key={`${state.snapshot?.actor.id}:${plan.id}:${plan.latest.revision}`}
    conversation={conversation} plan={plan} />;
}

function RouteConfirmation({ conversation, plan }: { conversation: Conversation; plan: Plan }) {
  const state = useSyncExternalStore(nativeStore.subscribe, nativeStore.getSnapshot);
  const navigate = useNavigate(), location = useLocation();
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [confirmedHere, setConfirmedHere] = useState(false);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [open, setOpen] = useState(false);
  const submitting = useRef(false);
  const popover = Ariakit.usePopoverStore({ open, setOpen, placement: 'bottom-start' });
  const confirmed = plan.active?.revision === plan.latest.revision || confirmedHere;
  const endpoint = `/v1/plans/${plan.id}/environment-requirements/${plan.latest.revision}`;
  const focus = state.snapshot?.teaching_sessions?.find((item) => item.conversation_id === conversation.id)?.focus;
  const planning = new URLSearchParams(location.search).get('stage') === 'planning';
  const hideConfirmed = !planning && plan.active && focus?.kind === 'node';
  const active = state.snapshot?.runs.some((run) => run.conversation_id === conversation.id
    && ['queued', 'running', 'blocked_unknown'].includes(run.status));
  const pending = state.pending.filter((item) => item.path.includes(conversation.id)
    || item.path.includes(`/plans/${plan.id}/`)
    || item.path === '/v1/environment-demands' && 'plan_id' in item.body
      && (!item.body.plan_id || item.body.plan_id === plan.id)
    || manifest?.demands.some((demand) => item.path.includes(`/environment-demands/${demand.id}/`)));

  useEffect(() => {
    let current = true;
    const read = () => nativeRequest(endpoint).then((value: Manifest) => {
      if (current) setManifest(value);
    }).catch((problem: Error) => { if (current) setError(problem.message); });
    void read();
    const timer = open ? window.setInterval(() => { void read(); }, 5000) : undefined;
    return () => { current = false; window.clearInterval(timer); };
  }, [endpoint, open, confirmed]);

  const confirm = async (install: boolean) => {
    if (submitting.current || !manifest) return;
    submitting.current = true; setBusy(true); setError('');
    try {
      const result = await confirmFirstNode(conversation, plan, {
        store: nativeStore, request: nativeRequest, storage: sessionStorage,
        onConfirmed: () => setConfirmedHere(true),
        ...(install ? { environmentRequirements: manifest.requirements } : {}),
      });
      setOpen(false);
      if (result) navigate(`/c/${conversation.id}?node=${encodeURIComponent(result.first.key)}`, {
        state: { learningNodeArrival: true },
      });
    } catch (problem) { setError((problem as Error).message); }
    finally { submitting.current = false; setBusy(false); }
  };
  const install = async () => {
    if (submitting.current || !manifest) return;
    submitting.current = true; setBusy(true); setError('');
    try {
      const current: Manifest = await nativeRequest(endpoint);
      setManifest(current);
      if (JSON.stringify(current.requirements) !== JSON.stringify(manifest.requirements)) {
        throw new Error('环境清单已变化，请查看后再决定安装。');
      }
      for (const requirement of current.consent_required) {
        const automatic = current.automatic_recipe_ids.includes(requirement.recipe_id);
        const scope = automatic ? null : current.plan_id;
        let demand = current.demands.find((item) => item.plan_id === scope
          && item.requirement.profile === requirement.profile
          && item.requirement.language === requirement.language
          && item.requirement.dialect === requirement.dialect);
        if (demand?.status === 'blocked_unknown') throw new Error('请先在本机执行中核对原准备任务。');
        if (!demand || JSON.stringify(demand.requirement) !== JSON.stringify(requirement)
          || !automatic && demand.plan_revision !== current.plan_revision) {
          const key = crypto.randomUUID();
          demand = await nativeStore.write('/v1/environment-demands', {
            recipe_id: requirement.recipe_id, plan_id: scope,
            ...(requirement.course_environment
              ? { course_environment: requirement.course_environment } : {}),
            plan_revision: automatic ? null : current.plan_revision,
            expected_requirement_revision: demand?.requirement_revision ?? 0,
          }, { key, lookup: `/v1/environment-demand-requests/${key}` });
          if (!demand || JSON.stringify(demand.requirement) !== JSON.stringify(requirement)) {
            throw new Error('环境清单已变化，请查看后再决定安装。');
          }
        }
        if (demand.decision === 'allow') continue;
        const key = crypto.randomUUID(), path = `/v1/environment-demands/${demand.id}/decisions`;
        await nativeStore.write(path, {
          decision: 'allow', expected_requirement_revision: demand.requirement_revision,
          expected_decision_revision: demand.decision_revision,
        }, { key, lookup: `${path}/${key}` });
      }
      setManifest(await nativeRequest(endpoint));
    } catch (problem) { setError((problem as Error).message); }
    finally { submitting.current = false; setBusy(false); }
  };
  const blocked = busy || pending.length > 0;
  const unknownEnvironment = manifest?.demands.some((item) => item.status === 'blocked_unknown');
  const label = environmentLabel(manifest);
  const extraNames = manifest?.consent_required.map((item) => item.title).join('、');

  return <div className="baseline-route-confirm mx-auto w-full px-4 sm:px-2 md:max-w-3xl xl:max-w-4xl">
    {!hideConfirmed && <>
      <p className="text-text-secondary text-sm">{plan.latest.document.nodes.length} 个学习节点 · 路线草案 {plan.latest.revision}</p>
      <Action important busy={busy} disabled={blocked || active || confirmed || !manifest} onClick={() => {
        if (manifest?.consent_required.length || manifest?.gaps?.length) setOpen(true);
        else void confirm(false);
      }}>{confirmed ? '路线已确认' : '确认路线，开始学习'}</Action>
    </>}
    {(manifest?.requirements.length || manifest?.gaps?.length || error) ? <>
      <Ariakit.PopoverDisclosure store={popover} render={<Action disabled={busy} />}>
        {`学习环境 · ${label}`}
      </Ariakit.PopoverDisclosure>
      <Ariakit.Popover store={popover} portal gutter={8}
        className="learning-demo demo-task-popover" aria-label="本路线的学习环境" data-learning-demo>
        <h3>{manifest?.consent_required.length ? '同时准备学习环境？' : '本路线的学习环境'}</h3>
        {extraNames && <p>本路线需要安装：{extraNames}，以及必要依赖。</p>}
        <p>系统自动安排专用隔离存储，不影响你现有的软件。</p>
        <p role="status">{label}</p>
        {unknownEnvironment && <Notice>请先在本机执行中核对原准备任务，再继续安装；仍可仅确认路线。</Notice>}
        {manifest?.gaps?.map((gap) => <Notice key={gap}>{gap}</Notice>)}
        {manifest?.requirements.length ? <Disclosure title="查看安装详情">
          {manifest.requirements.map((requirement) => <div className="demo-task-row" key={requirement.recipe_id}>
            <h4>{requirement.title}</h4><RequirementDetails requirement={requirement} />
          </div>)}
        </Disclosure> : null}
        {!confirmed && <>
          {!!manifest?.consent_required.length && <Action disabled={blocked || active || unknownEnvironment} busy={busy}
            onClick={() => { void confirm(true); }}>确认路线并安装</Action>}
          <Action disabled={blocked || active || !manifest} onClick={() => { void confirm(false); }}>仅确认路线</Action>
        </>}
        {confirmed && !!manifest?.consent_required.length && <Action disabled={blocked || unknownEnvironment} busy={busy}
          onClick={() => { void install(); }}>安装所需环境</Action>}
        {pending.map((item) => <Action key={item.key} disabled={busy} onClick={() => {
          setBusy(true);
          void nativeStore.reconcile(item.key).then(() => nativeRequest(endpoint))
            .then(setManifest).catch((problem: Error) => setError(problem.message))
            .finally(() => setBusy(false));
        }}>核对原操作</Action>)}
        {error && <Notice>{error}</Notice>}
      </Ariakit.Popover>
    </> : null}
    {error && !open && <Notice>{error}</Notice>}
  </div>;
}
