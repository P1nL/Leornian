import { afterEach, expect, test, vi } from 'vitest';
import { animateComposerArrival, observeMessageEntrances } from './baseline-motion';

afterEach(() => vi.unstubAllGlobals());

test('the composer moves from its welcome rectangle to its final position and respects reduced motion', () => {
  let reduced = false;
  vi.stubGlobal('window', { matchMedia: () => ({ matches: reduced }) });
  const surface = document.createElement('div');
  surface.getBoundingClientRect = () => ({ left: 80, top: 700, width: 840, height: 150 } as DOMRect);
  surface.animate = vi.fn();
  const origin = { left: 110, top: 300, width: 780, height: 150 };
  animateComposerArrival(surface, origin);
  expect(surface.animate).toHaveBeenCalledWith([
    expect.objectContaining({ transform: 'translate(30px, -400px) scale(0.9285714285714286, 1)' }),
    expect.objectContaining({ transform: 'none' }),
  ], expect.objectContaining({ duration: 440 }));
  reduced = true;
  animateComposerArrival(surface, origin);
  expect(surface.animate).toHaveBeenCalledOnce();
});

test('both roles enter once; streamed chunks and the persisted live reply do not restart animation', async () => {
  vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
  const container = document.createElement('div');
  const user = document.createElement('div');
  user.className = 'message-render'; user.id = 'turn:user';
  user.innerHTML = '<div class="user-turn">Question</div>';
  user.animate = vi.fn();
  container.append(user);
  const stop = observeMessageEntrances(container, new Set());
  expect(user.animate).toHaveBeenCalledOnce();
  const live = document.createElement('section');
  live.dataset.liveMessage = 'turn:assistant'; live.animate = vi.fn();
  container.append(live);
  await Promise.resolve();
  expect(live.animate).toHaveBeenCalledOnce();
  live.innerHTML = '<p>First streamed sentence</p>';
  await Promise.resolve();
  live.querySelector('p')!.textContent += ' Next chunk';
  await Promise.resolve();
  expect(live.animate).toHaveBeenCalledOnce();
  const saved = document.createElement('div');
  saved.id = 'turn:assistant'; saved.className = 'message-render'; saved.animate = vi.fn();
  live.replaceWith(saved);
  await Promise.resolve();
  expect(saved.animate).not.toHaveBeenCalled();
  expect(user.animate).toHaveBeenCalledOnce();
  stop();
});
