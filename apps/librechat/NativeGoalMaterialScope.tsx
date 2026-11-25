import { useEffect, useState } from 'react';
import type { components } from '@leornian/api-contracts';
import { Disclosure } from './LearningUI';

type Scope = components['schemas']['GoalMaterialScope'];
export type GoalScopeDraft = {
  enabled: boolean; language: string; languageVersion: string; framework: string; frameworkVersion: string;
};
const empty = (): GoalScopeDraft => ({
  enabled: false, language: '', languageVersion: '', framework: '', frameworkVersion: '',
});
const field = 'border-border-medium bg-surface-primary text-text-primary w-full min-w-0 rounded-lg border px-3 py-2 text-sm';
export const validGoalScope = (value: GoalScopeDraft) => !value.enabled ||
  Boolean(value.language.trim() && (!value.frameworkVersion.trim() || value.framework.trim()));
export const goalScopeInput = (value: GoalScopeDraft): Scope | null => value.enabled ? {
  contract: 'goal-material-scope.v1', language: value.language.trim(),
  language_version: value.languageVersion.trim() || null,
  framework: value.framework.trim() || null, framework_version: value.frameworkVersion.trim() || null,
  authorized_official_sources: true,
  authorized_public_sources: true,
} : null;

export function useGoalScopeDraft(actorId?: string) {
  const key = actorId ? `leornian.native.goal-scope.v1:${actorId}` : '';
  const [saved, setSaved] = useState({ key: '', value: empty() });
  useEffect(() => {
    let value = empty();
    try {
      const stored = JSON.parse(key ? sessionStorage.getItem(key) ?? 'null' : 'null');
      if (stored && typeof stored.enabled === 'boolean' &&
        ['language', 'languageVersion', 'framework', 'frameworkVersion'].every((name) => typeof stored[name] === 'string')) value = stored;
    } catch { value = empty(); }
    setSaved({ key, value });
  }, [key]);
  const value = saved.key === key ? saved.value : empty();
  const change = (next: GoalScopeDraft) => {
    setSaved({ key, value: next });
    if (key) sessionStorage.setItem(key, JSON.stringify(next));
  };
  const reset = () => {
    setSaved({ key, value: empty() });
    if (key) sessionStorage.removeItem(key);
  };
  return { value, change, reset };
}

export default function NativeGoalMaterialScope({ value, onChange, disabled = false }: {
  value: GoalScopeDraft; onChange: (value: GoalScopeDraft) => void; disabled?: boolean;
}) {
  return <Disclosure title="科目与学习材料（可选）">
    <div className="space-y-3">
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={value.enabled} disabled={disabled}
          onChange={(event) => onChange({ ...value, enabled: event.target.checked })} />
        指定课程科目并允许自动获取公开学习材料
      </label>
      {value.enabled && <>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">课程语言或科目（必填）<input className={field} value={value.language}
            maxLength={80} disabled={disabled} onChange={(event) => onChange({ ...value, language: event.target.value })} /></label>
          <label className="text-sm">指定语言版本（可选）<input className={field} value={value.languageVersion}
            maxLength={80} disabled={disabled} onChange={(event) => onChange({ ...value, languageVersion: event.target.value })} /></label>
          <label className="text-sm">指定框架（可选）<input className={field} value={value.framework}
            maxLength={100} disabled={disabled} onChange={(event) => onChange({ ...value, framework: event.target.value })} /></label>
          <label className="text-sm">指定框架版本（可选）<input className={field} value={value.frameworkVersion}
            maxLength={80} disabled={disabled} onChange={(event) => onChange({ ...value, frameworkVersion: event.target.value })} /></label>
        </div>
        <p className="demo-muted">系统优先复用已有材料和目录中的官方、优质第三方资料，按当前任务解析、检查；缺少材料时自动补搜。课程环境另行授权。</p>
        {value.frameworkVersion.trim() && !value.framework.trim() && <p className="demo-muted">填写框架版本前，请明确框架名称。</p>}
      </>}
    </div>
  </Disclosure>;
}
