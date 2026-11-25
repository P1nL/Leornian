import type { ReactNode, Ref } from 'react';
import * as Ariakit from '@ariakit/react';
import { ArrowUp, ListTodo, Paperclip } from 'lucide-react';
import { Action, Disclosure, Notice } from './LearningUI';

export function LearningWelcome() {
  return <section className="learning-demo baseline-welcome" data-learning-demo aria-label="Leornian">
    <h2>Leornian</h2>
  </section>;
}

export function LearningLoginForm({ name, token, busy, error, onName, onToken, onEnter }: {
  name: string; token: string; busy: boolean; error: string;
  onName: (value: string) => void; onToken: (value: string) => void; onEnter: () => void;
}) {
  const field = 'border-border-medium bg-surface-primary text-text-primary w-full min-w-0 rounded-lg border px-3 py-2 text-sm';
  return <section className="learning-demo space-y-4" data-learning-demo aria-label="本机学习身份">
    <h1 className="text-2xl font-semibold">进入本机学习</h1>
    <p>这是本机匿名开发身份，不是 LibreChat 账号。学习记录和模型凭据仍由 Leornian 保管。</p>
    <label className="block">称呼<input className={field} value={name} maxLength={60}
      onChange={(event) => onName(event.target.value)} autoComplete="nickname" /></label>
    <Disclosure title="沿用已有本机会话">
      <label className="block">会话令牌<input className={field} type="password" value={token} autoComplete="off"
        onChange={(event) => onToken(event.target.value)} /></label>
      <p>仅用于明确沿用已有 Leornian 身份；不在这里填写模型 API Key。</p>
    </Disclosure>
    <Action busy={busy} disabled={!name.trim() && !token} onClick={onEnter}>进入</Action>
    {error && <Notice>{error}</Notice>}
  </section>;
}

export function LearningStartFrame({ description, children }: { description: string; children?: ReactNode }) {
  return <section className="learning-demo demo-start" data-learning-demo aria-label="开始学习引导">
    <h2>今天想学什么？</h2>
    <p className="demo-muted">{description}</p>
    {children}
  </section>;
}

export function LearningComposerFrame({
  value, onChange, onSubmit, onAttachment, placeholder, label, sendLabel, status,
  disabled = false, sendDisabled = false, maxLength = 2000, leading, children, attachments, surfaceRef,
  attachmentLabel = '添加学习材料',
}: {
  value: string; onChange: (value: string) => void; onSubmit: () => void; onAttachment: () => void;
  placeholder: string; label: string; sendLabel: string; status: ReactNode;
  disabled?: boolean; sendDisabled?: boolean; maxLength?: number; leading?: ReactNode; children?: ReactNode; attachmentLabel?: string;
  attachments?: ReactNode; surfaceRef?: Ref<HTMLDivElement>;
}) {
  return <div className="learning-demo demo-composer" data-learning-demo>
    {leading}
    <div ref={surfaceRef} className="demo-composer-surface" data-testid="composer-surface">
      {attachments}
      <textarea aria-label={label} rows={2} placeholder={placeholder} value={value}
        maxLength={maxLength} disabled={disabled} onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (!disabled && !sendDisabled && value.trim()) onSubmit();
          }
        }} />
      <div className="demo-composer-actions">
        <button type="button" className="demo-icon-button" aria-label={attachmentLabel}
          disabled={disabled} onClick={onAttachment}><Paperclip size={20} /></button>
        {status && <span className="demo-muted" role="status">{status}</span>}
        <button type="button" className="demo-icon-button" aria-label={sendLabel}
          disabled={disabled || sendDisabled || !value.trim()} onClick={onSubmit}><ArrowUp size={20} /></button>
      </div>
    </div>
    {children}
  </div>;
}

export function LearningTaskPopover({ children, label = '后台任务', description }: {
  children: ReactNode; label?: string; description?: string;
}) {
  const popover = Ariakit.usePopoverStore({ placement: 'bottom-end' });
  return <div className="learning-demo" data-learning-demo>
    <Ariakit.PopoverDisclosure store={popover} className="demo-icon-button" aria-label={label}>
      <ListTodo size={20} />
    </Ariakit.PopoverDisclosure>
    <Ariakit.Popover store={popover} portal gutter={8}
      className="learning-demo demo-task-popover" aria-label="后台任务" data-learning-demo>
      <h3>当前学习的任务</h3>
      {description && <p className="demo-muted">{description}</p>}
      {children}
    </Ariakit.Popover>
  </div>;
}
