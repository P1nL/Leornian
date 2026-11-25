export type ComposerOrigin = { left: number; top: number; width: number; height: number };

const easeOut = 'cubic-bezier(0.16, 1, 0.3, 1)';
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

export function animateComposerArrival(surface: HTMLElement, origin: ComposerOrigin) {
  if (reducedMotion() || !surface.animate || !origin.width || !origin.height) return;
  const target = surface.getBoundingClientRect();
  if (!target.width || !target.height) return;
  return surface.animate([
    { transformOrigin: 'top left',
      transform: `translate(${origin.left - target.left}px, ${origin.top - target.top}px) scale(${origin.width / target.width}, ${origin.height / target.height})` },
    { transformOrigin: 'top left', transform: 'none' },
  ], { duration: 440, easing: easeOut });
}

export function observeMessageEntrances(container: HTMLElement, seen: Set<string>) {
  const selector = '.message-render[id], [data-live-message]';
  const enter = (root: Element) => {
    const messages = root.matches(selector) ? [root] : Array.from(root.querySelectorAll(selector));
    for (const message of messages) {
      const id = message.getAttribute('data-live-message') ?? message.id;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      if (reducedMotion() || !(message instanceof HTMLElement) || !message.animate) continue;
      const fromX = message.querySelector('.user-turn') ? 10 : -10;
      message.animate([
        { opacity: 0, transform: `translate(${fromX}px, 8px)` },
        { opacity: 1, transform: 'none' },
      ], { duration: 280, easing: easeOut });
    }
  };
  enter(container);
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes' && record.target instanceof Element) enter(record.target);
      for (const node of record.addedNodes) if (node instanceof Element) enter(node);
    }
  });
  observer.observe(container, { childList: true, subtree: true, attributes: true,
    attributeFilter: ['id', 'data-live-message'] });
  return () => observer.disconnect();
}
