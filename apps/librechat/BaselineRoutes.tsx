import { useId, useState } from 'react';
import type { MouseEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as Ariakit from '@ariakit/react';
import { DropdownPopup } from '@librechat/client';
import { Ellipsis } from 'lucide-react';
import type { components } from '@leornian/api-contracts';
import { useNative } from './NativeLearning';
import { nativeRequest, nativeStore } from './native-client.mjs';
import { enterTeachingNode, routeNodes } from './learning-routes.mjs';
import { Action, DemoDialog, Notice } from './LearningUI';
import { LearningRouteFolder, LearningRouteNode } from './LearningNavigation';

function RouteActions({ goal, onDeleted }: {
  goal: components['schemas']['Goal']; onDeleted: () => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false), [dialog, setDialog] = useState('');
  const [title, setTitle] = useState(goal.title), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const save = async () => {
    if (busy || dialog === 'rename' && !title.trim()) return;
    setBusy(true); setError('');
    try {
      await nativeRequest(`/v1/goals/${goal.id}`, dialog === 'rename'
        ? { method: 'PATCH', body: JSON.stringify({ title: title.trim() }) } : { method: 'DELETE' });
      await nativeStore.refresh();
      setDialog('');
      if (dialog === 'delete') onDeleted();
    } catch (problem) { setError((problem as Error).message); }
    finally { setBusy(false); }
  };
  return <>
    <DropdownPopup portal menuId={id} focusLoop unmountOnHide isOpen={open} setIsOpen={setOpen}
      items={[{ id: 'rename', label: '重命名', onClick: () => {
        setOpen(false); setTitle(goal.title); setError(''); setDialog('rename');
      } }, { id: 'delete', label: '删除', onClick: () => {
        setOpen(false); setError(''); setDialog('delete');
      } }]}
      trigger={<Ariakit.MenuButton className="baseline-route-menu" aria-label={`${goal.title} 操作`}
        onClick={(event: MouseEvent<HTMLButtonElement>) => event.stopPropagation()}><Ellipsis size={17} /></Ariakit.MenuButton>} />
    <DemoDialog open={Boolean(dialog)} onClose={() => { if (!busy) setDialog(''); }}
      title={dialog === 'rename' ? '重命名学习计划' : '删除学习计划'}>
      <form className="demo-stack" onSubmit={(event) => { event.preventDefault(); void save(); }}>
        {dialog === 'rename' ? <label>名称<input autoFocus value={title} maxLength={120} disabled={busy}
          onChange={(event) => setTitle(event.target.value)} /></label>
          : <p>将“{goal.title}”从学习与最近中移除，历史对话和调用记录保留。</p>}
        {error && <Notice>{error}</Notice>}
        <div className="demo-actions"><Action disabled={busy} onClick={() => setDialog('')}>取消</Action>
          <Action type="submit" busy={busy} disabled={busy || dialog === 'rename' && !title.trim()}>
            {dialog === 'rename' ? '保存名称' : '确认删除'}</Action></div>
      </form>
    </DemoDialog>
  </>;
}

export function BaselineRoutes() {
  const state = useNative(), navigate = useNavigate(), { conversationId } = useParams();
  const [busy, setBusy] = useState(''), [error, setError] = useState('');
  const snapshot = state.snapshot;
  return <section className="baseline-routes" aria-label="学习路线">
    <h2>学习</h2>
    {error && <Notice>{error}</Notice>}
    {snapshot?.goals.map((goal) => {
      const plan = snapshot.plans.find((item) => item.goal_id === goal.id);
      const conversation = snapshot.conversations.find((item) => item.goal_id === goal.id);
      const current = snapshot.teaching_sessions?.find((item) => item.conversation_id === conversation?.id);
      const nodes = plan && conversation ? routeNodes(snapshot, plan, conversation.id) : [];
      return <LearningRouteFolder key={goal.id} title={goal.title} current={conversation?.id === conversationId}
        actions={<RouteActions goal={goal} onDeleted={() => {
            if (conversation?.id === conversationId) navigate('/c/new');
          }} />}>
        {conversation && <button className="baseline-node" onClick={() =>
          navigate(`/c/${conversation.id}?stage=planning`)}>讨论与调整路线</button>}
        {nodes.length ? <ol>{nodes.map((node, index) => <li key={node.key}>
          <LearningRouteNode title={node.title} index={index} unlocked={node.unlocked} studied={node.studied || node.ended}
            current={current?.focus.node_key === node.key && conversation?.id === conversationId}
            busy={Boolean(busy)} onOpen={() => {
              if (!conversation || !plan?.active) return;
              setBusy(node.key); setError('');
              void (async () => {
                const focus = { kind: 'node' as const, plan_id: plan.id,
                  expected_plan_revision: plan.active!.revision, node_key: node.key };
                await enterTeachingNode(conversation.id, focus, { store: nativeStore, request: nativeRequest });
                navigate(`/c/${conversation.id}?node=${encodeURIComponent(node.key)}`, { state: { learningNodeArrival: true } });
              })().catch((problem: Error) => setError(problem.message)).finally(() => setBusy(''));
            }} />
        </li>)}</ol> : <p className="demo-muted px-3 text-sm">路线尚未准备完成
          {conversation && <button className="ml-2 underline" onClick={() => navigate(`/c/${conversation.id}`)}>继续准备</button>}</p>}
      </LearningRouteFolder>;
    })}
    {snapshot?.goals.length === 0 && <p className="demo-muted mt-6 text-sm">创建学习计划后，路线和节点会出现在这里。</p>}
  </section>;
}
