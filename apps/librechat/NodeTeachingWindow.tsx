import { useLayoutEffect, useRef, useState } from 'react';

export const NODE_WINDOW_MS = 8000;

export default function NodeTeachingWindow({ identity, after, enabled, onExpire }: {
  identity: string; after: string | null; enabled: boolean; onExpire: () => void;
}) {
  const rect = useRef<SVGRectElement>(null);
  const current = useRef({ identity, after, enabled, onExpire });
  const synchronize = useRef<() => void>();
  const [running, setRunning] = useState(false);
  useLayoutEffect(() => {
    current.current = { identity, after, enabled, onExpire };
    synchronize.current?.();
  }, [identity, after, enabled, onExpire]);

  useLayoutEffect(() => {
    const line = rect.current!;
    const surface = line.closest<HTMLElement>('.demo-composer-surface')!;
    const pane = surface.closest('[data-chat-pane]') ?? document;
    const editor = surface.querySelector('textarea')!;
    const controller = new window.AbortController();
    const options = { signal: controller.signal, capture: true };
    let hovered = Boolean(window.matchMedia?.('(hover: hover)').matches && surface.matches(':hover'));
    let focused = false, tabbing = false, composing = false, pointerFocus = false;
    let foreground = document.hasFocus(), fired = '', armed = '';
    let cancelClock: (() => void) | undefined;
    const ready = () => {
      const config = current.current, active = document.activeElement;
      return config.enabled && fired !== config.identity && foreground && !document.hidden &&
        !hovered && !focused && !composing && !editor.value.length &&
        !active?.closest('[role="dialog"], [data-artifact-id]') &&
        !document.querySelector('[aria-modal="true"]:not([hidden])') &&
        (!config.after || Boolean(pane.querySelector(`[data-node-reply="${config.after}"]`)));
    };
    const stop = () => {
      cancelClock?.();
      cancelClock = undefined; armed = '';
      setRunning(false);
    };
    const sync = () => {
      if (!ready()) { if (armed) stop(); return; }
      const key = current.current.identity;
      if (key === armed) return;
      stop(); armed = key; setRunning(true);
      const finish = () => {
        if (armed !== key || current.current.identity !== key || !ready()) return;
        fired = key;
        stop();
        current.current.onExpire();
      };
      if (line.animate) {
        const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        const animation = line.animate([{ strokeDashoffset: reduced ? 0 : 1 }, { strokeDashoffset: 0 }],
          { duration: NODE_WINDOW_MS, easing: 'linear', fill: 'both' });
        animation.onfinish = finish;
        cancelClock = () => { animation.onfinish = null; animation.cancel(); };
      } else {
        const timeout = window.setTimeout(finish, NODE_WINDOW_MS);
        cancelClock = () => window.clearTimeout(timeout);
      }
    };
    surface.addEventListener('pointerenter', (event) => {
      if (event.pointerType !== 'touch') { hovered = true; sync(); }
    }, options);
    surface.addEventListener('pointerleave', () => { hovered = false; sync(); }, options);
    document.addEventListener('pointerdown', (event) => {
      const target = event.target as Element;
      pointerFocus = surface.contains(target);
      if (pointerFocus) {
        focused = true;
        if (!target.closest('button,input,textarea,select,a')) editor.focus();
      } else if (!surface.contains(document.activeElement)) focused = false;
      sync();
    }, options);
    document.addEventListener('pointerup', () => { pointerFocus = false; }, options);
    document.addEventListener('keydown', (event) => {
      tabbing = event.key === 'Tab';
      if (surface.contains(event.target as Node)) { focused = true; sync(); }
    }, options);
    document.addEventListener('keyup', () => { tabbing = false; }, options);
    document.addEventListener('focusin', (event) => {
      focused = surface.contains(event.target as Node) && (focused || pointerFocus || tabbing);
      sync();
    }, options);
    document.addEventListener('focusout', (event) => {
      if (!surface.contains(event.relatedTarget as Node | null)) focused = false;
      queueMicrotask(() => { if (!controller.signal.aborted) sync(); });
    }, options);
    surface.addEventListener('compositionstart', () => { composing = true; focused = true; sync(); }, options);
    surface.addEventListener('compositionend', () => { composing = false; sync(); }, options);
    surface.addEventListener('input', sync, options);
    window.addEventListener('blur', () => { foreground = false; sync(); }, { signal: controller.signal });
    window.addEventListener('focus', () => { foreground = true; sync(); }, { signal: controller.signal });
    document.addEventListener('visibilitychange', sync, options);
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true,
      attributeFilter: ['data-node-reply', 'aria-modal', 'hidden'] });
    synchronize.current = sync;
    sync();
    return () => {
      controller.abort(); observer.disconnect(); synchronize.current = undefined; cancelClock?.(); armed = '';
    };
  }, []);
  return <>
    <svg aria-hidden="true" className="baseline-window-line" data-running={running}>
      <rect ref={rect} x="0" y="0" width="100%" height="100%" rx="20" pathLength="1" />
    </svg>
    {running && <span>稍后续讲 · 移入或点按输入框可暂停</span>}
  </>;
}
