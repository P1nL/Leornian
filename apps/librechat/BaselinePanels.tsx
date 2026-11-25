import { useParams } from 'react-router-dom';
import type { components } from '@leornian/api-contracts';
import { Notice } from './LearningUI';
import { NativeLearningScope, useNative } from './NativeLearning';
import NativeModels from './NativeModels';
import NativeMaterialUpdates from './NativeMaterialUpdates';
import NativeCourse from './NativeCourse';
import NativeExecution from './NativeExecution';
import NativeLearningEvidence from './NativeLearningEvidence';
import NativeMaterialIntake from './NativeMaterialIntake';
import NativeMaterialSources from './NativeMaterialSources';
import { NativeReviews, NativeReviewPreferences } from './NativeReviews';

type Snapshot = components['schemas']['Snapshot'];
export const baselinePanelTitles: Record<string, string> = {
  route: '当前路线', records: '学习记录', reviews: '到期复习', materials: '教材与更新',
  preferences: '学习方式与提醒', models: '我的模型配置', environment: '本机执行环境',
};

export function BaselineRecords({ reviews = false }: { reviews?: boolean }) {
  const state = useNative(), { conversationId } = useParams(), snapshot = state.snapshot as Snapshot | null;
  const goalId = snapshot?.conversations.find((item) => item.id === conversationId)?.goal_id;
  const planIds = new Set(snapshot?.plans.filter((item) => item.goal_id === goalId).map((item) => item.id));
  const packIds = new Set(snapshot?.packs.filter((item) => planIds.has(item.plan_id)).map((item) => item.id));
  const results = snapshot?.evaluations.filter((item) => packIds.has(item.pack_id)) ?? [];
  const planId = snapshot?.plans.find((item) => item.goal_id === goalId)?.id;
  return <div className="demo-stack">{reviews ? <>
    {conversationId && goalId ? <NativeReviews conversationId={conversationId} goalId={goalId} />
      : <Notice>进入一个学习目标后查看到期复习。</Notice>}
  </> : <>
    <NativeLearningEvidence key={goalId} planId={planId} epoch={state.epoch} />
    {results.length === 0 && <Notice>当前学习暂无已记录的评测回执。</Notice>}
    {results.map((item) => <div className="demo-task-row" key={item.id}>
      <p>{item.source_kind} · {item.correct === null ? '参考回答' : item.correct ? '通过' : '未通过'}</p>
      <p className="demo-muted">原提交 {item.source_id}</p>
    </div>)}
    <Notice>练习的完整 Attempt 和结果保留在原工件中；这里读取近期快照记录。</Notice>
  </>}</div>;
}

export function BaselineMaterials() {
  const state = useNative(), { conversationId } = useParams(), snapshot = state.snapshot as Snapshot | null;
  const goalId = snapshot?.conversations.find((item) => item.id === conversationId)?.goal_id;
  const sources = snapshot?.sources.filter((item) => item.goal_id === goalId) ?? [];
  return <div className="demo-stack">
    {goalId ? <NativeMaterialIntake goalId={goalId} />
      : <Notice>先进入一个学习目标，再为该目标添加材料。</Notice>}
    {goalId && <NativeMaterialSources goalId={goalId} />}
    <NativeMaterialUpdates />
    <p className="demo-muted">工件中的来源卡片可打开原文，并重新核对固定版本与当前使用权限。</p>
    {sources.map((item) => <div className="demo-task-row" key={item.id}>
      <p>{item.title} · 版本 {item.revision}</p><p className="demo-muted">{item.usable ? '当前可用' : '当前不可用'}</p>
    </div>)}
    {sources.length === 0 && <Notice>当前学习尚无近期材料记录。</Notice>}
  </div>;
}

export function BaselinePreferences() {
  const { conversationId } = useParams();
  return <>{conversationId && conversationId !== 'new' ? <><NativeLearningScope />
    <NativeReviewPreferences conversationId={conversationId} /></>
    : <Notice>进入一个学习目标后，可设置教学主题、答疑与后续教学方式。</Notice>}</>;
}

export function BaselineEnvironmentSettings() {
  return <NativeExecution />;
}

/** Content is shared by the product menu and isolated component previews. */
export function BaselinePanelContent({ panel, onClose }: { panel: string; onClose?: () => void }) {
  const state = useNative(), { conversationId } = useParams();
  const goalId = state.snapshot?.conversations.find((item) => item.id === conversationId)?.goal_id;
  switch (panel) {
    case 'route': return conversationId && goalId
      ? <NativeCourse conversationId={conversationId} goalId={goalId} onFocus={onClose} />
      : <Notice>进入一个学习目标后准备路线与课时。</Notice>;
    case 'records': return <BaselineRecords />;
    case 'reviews': return <BaselineRecords reviews />;
    case 'materials': return <BaselineMaterials />;
    case 'preferences': return <BaselinePreferences />;
    case 'models': return <NativeModels />;
    case 'environment': return <BaselineEnvironmentSettings />;
    default: return null;
  }
}
