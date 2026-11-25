import { vi } from 'vitest';
import { createRequire } from 'node:module';
import { cloneElement, createElement } from 'react';

// Reuse the installed pinned DOM runtime; do not install a second dependency tree.
const pinned = createRequire(new URL('../../.local/upstream/LibreChat-f4154b6/client/package.json', import.meta.url));
const { JSDOM } = pinned('jsdom');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost', pretendToBeVisual: true });
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'Element',
  'Node', 'Document', 'DocumentFragment', 'MutationObserver', 'DOMParser', 'MouseEvent', 'KeyboardEvent',
  'CustomEvent', 'Event', 'sessionStorage', 'localStorage']) Object.defineProperty(globalThis, name, { value: dom.window[name], configurable: true });
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
globalThis.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window);
globalThis.cancelAnimationFrame = dom.window.cancelAnimationFrame.bind(dom.window);
Object.defineProperty(window, 'matchMedia', {
  value: (query: string) => ({
    matches: true, media: query, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {},
  }),
});
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
// Adapter tests isolate the pinned client's independently built message-rendering tree.
vi.mock('./NativeReplyParts', () => ({ default: () => null }));
vi.mock('./NativeThinking', () => ({ default: () => null }));
vi.mock('@librechat/client', () => ({
  useRemScale: () => 1,
  useMediaQuery: (query: string) => window.matchMedia(query).matches,
  TooltipAnchor: ({ render }: { render: unknown }) => render,
  DropdownPopup: ({ trigger, items, isOpen, setIsOpen }: any) => createElement('div', null,
    cloneElement(trigger, { onClick: (event: MouseEvent) => { event.stopPropagation(); setIsOpen(!isOpen); } }),
    isOpen && items.map((item: any) => createElement('button', { key: item.id, onClick: item.onClick }, item.label))),
  OGDialog: ({ children, open }: { children: unknown; open: boolean }) => open ? children : null,
  OGDialogContent: ({ children }: { children: unknown }) => children,
  OGDialogHeader: ({ children }: { children: unknown }) => children,
  OGDialogTitle: ({ children }: { children: unknown }) => children,
  ResizablePanelGroup: ({ children }: { children: unknown }) => children,
  ResizablePanel: ({ children }: { children: unknown }) => children,
  ResizableHandle: () => null,
}));
