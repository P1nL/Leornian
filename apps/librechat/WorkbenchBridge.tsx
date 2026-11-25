import { Component, useEffect, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useSetAtom } from 'jotai';
import { useSetRecoilState } from 'recoil';
import { settingsOpenAtom } from '~/components/Nav/Settings';
import useSidebarToggle from '~/hooks/Nav/useSidebarToggle';
import store from '~/store';
import { nativeStore } from './native-client.mjs';
import { useNative } from './NativeLearning';
import { Notice } from './LearningUI';
import WorkbenchSpecimens from './WorkbenchSpecimens';
import { findWorkbenchStory, workbenchStories } from './workbench-catalog.mjs';
import './workbench-surface.css';

function report(type: string, payload: object = {}) {
  const instance = new URLSearchParams(location.search).get('__workbench');
  window.parent.postMessage({ source: 'leornian-workbench', instance, type, ...payload }, location.origin);
}

class SurfaceBoundary extends Component<{ children: ReactNode }, { error: string }> {
  state = { error: '' };
  static getDerivedStateFromError(error: Error) { return { error: error.message }; }
  componentDidCatch(error: Error, _info: ErrorInfo) { report('error', { message: error.message }); }
  render() { return this.state.error ? <div data-workbench-error><Notice>组件未能显示：{this.state.error}</Notice></div> : this.props.children; }
}

function PreviewBridge() {
  const params = new URLSearchParams(location.search), id = params.get('component') ?? 'page';
  const story = findWorkbenchStory(id), variant = params.get('state') ?? story.states[0].id;
  const state = useNative(), openSettings = useSetAtom(settingsOpenAtom);
  const { setSidebarOpen } = useSidebarToggle();
  const openShortcuts = useSetRecoilState(store.showShortcutsDialog);
  const [inspecting, setInspecting] = useState(false);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== window.parent || event.data?.source !== 'leornian-workbench-control') return;
      if (event.data.type === 'inspect') setInspecting(Boolean(event.data.enabled));
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, []);
  useEffect(() => {
    document.body.dataset.workbench = 'true';
    if (story.kind !== 'region') document.body.dataset.workbenchStandalone = 'true';
    if (id === 'appearance') { openSettings(true); document.body.dataset.workbenchStandalone = 'true'; }
    if (id === 'keyboard') openShortcuts(true);
    const productRoot = document.getElementById('root');
    if (productRoot && story.kind !== 'region') productRoot.inert = true;
    if (id === 'source-panel') void nativeStore.openSource('/v1/workbench/source');
    if (id === 'sidebar' || id === 'recent') setSidebarOpen(variant !== 'collapsed');
    const error = (event: ErrorEvent) => report('error', { message: event.message });
    window.addEventListener('error', error);
    return () => { window.removeEventListener('error', error); delete document.body.dataset.workbench;
      delete document.body.dataset.workbenchStandalone; if (productRoot) productRoot.inert = false; };
  }, [id, story.kind, openSettings]);
  useEffect(() => {
    if (!state.snapshot) return;
    let ready = false, deadline = window.setTimeout(() => {
      if (!ready) report('error', { message: `未找到预览区域：${story.selector || story.component}` });
    }, 15000);
    const find = () => {
      if (document.querySelector('[data-workbench-error]')) return;
      const target = story.kind === 'region' && story.selector
        ? document.querySelector<HTMLElement>(story.selector)
        : story.surface === 'component-gallery'
          ? document.querySelector<HTMLElement>(story.selector) : document.querySelector<HTMLElement>('[data-workbench-surface]');
      const pageReady = story.id === 'page' && document.querySelector(
        variant === 'empty' ? '.baseline-welcome' : '[data-baseline-conversation] [data-testid="message-body"]');
      if (pageReady || target || ['appearance', 'keyboard'].includes(story.id) && document.querySelector('[role="dialog"]')) {
        if (target && (story.kind === 'region' || story.surface === 'component-gallery') && params.get('context') !== 'page') {
          target.dataset.workbenchIsolated = 'true';
          let parent = target.parentElement;
          while (parent && parent !== document.body) {
            parent.dataset.workbenchAncestor = 'true'; parent = parent.parentElement;
          }
          document.body.dataset.workbenchIsolate = 'true';
        }
        if (!ready) { ready = true; clearTimeout(deadline); report('ready', { component: story.component }); }
      }
    };
    const observer = new MutationObserver(find);
    observer.observe(document.body, { childList: true, subtree: true });
    find();
    return () => { clearTimeout(deadline); observer.disconnect(); };
  }, [state.snapshot?.actor.id, story.id]);
  useEffect(() => {
    if (id !== 'models' || !['preset', 'custom', 'edit'].includes(variant)) return;
    const steps = variant === 'edit' ? ['编辑模型 教学模型（样例）']
      : ['添加教学与路线规划提供方', variant === 'preset' ? 'DeepSeek' : '自定义'];
    let index = 0;
    const advance = () => {
      const button = [...document.querySelectorAll<HTMLButtonElement>('button')].find((element) =>
        element.getAttribute('aria-label') === steps[index] || element.textContent?.trim() === steps[index]);
      if (button) { index++; button.click(); }
      if (index >= steps.length) observer.disconnect();
    };
    const observer = new MutationObserver(advance);
    observer.observe(document.body, { childList: true, subtree: true });
    advance();
    return () => observer.disconnect();
  }, [id, variant]);
  useEffect(() => {
    if (!['assessment', 'recovery'].includes(id)) return;
    const title = id === 'assessment' ? '正式独立考核' : '补救后的新情境检查';
    const open = () => {
      const button = [...document.querySelectorAll<HTMLButtonElement>('[data-workbench-surface] button')]
        .find((item) => item.textContent?.trim() === title && item.getAttribute('aria-expanded') === 'false');
      if (button) { button.click(); observer.disconnect(); }
    };
    const observer = new MutationObserver(open);
    observer.observe(document.body, { childList: true, subtree: true }); open();
    return () => observer.disconnect();
  }, [id]);
  useEffect(() => {
    const select = (event: MouseEvent) => {
      if (!inspecting || !(event.target instanceof Element)) return;
      const element = event.target instanceof HTMLElement ? event.target : event.target.closest<HTMLElement>('button, a') ?? event.target.parentElement;
      if (!element) return;
      event.preventDefault(); event.stopPropagation();
      document.querySelector('[data-workbench-selected]')?.removeAttribute('data-workbench-selected');
      element.dataset.workbenchSelected = 'true';
      const owner = workbenchStories.map((item) => ({ item, element: item.selector ? element.closest(item.selector) : null }))
        .filter((match) => match.element).sort((left, right) => {
          let current: Element | null = element;
          while (current) {
            if (current === left.element) return -1;
            if (current === right.element) return 1;
            current = current.parentElement;
          }
          return 0;
        })[0]?.item;
      report('selection', {
        tag: element.tagName.toLowerCase(), text: element.textContent?.trim().slice(0, 100),
        selector: element.id ? `#${CSS.escape(element.id)}`
          : `${element.tagName.toLowerCase()}${[...element.classList].slice(0, 3).map((name) => `.${CSS.escape(name)}`).join('')}`,
        owner: owner?.component ?? story.component, files: owner?.source ?? story.source,
      });
      setInspecting(false);
    };
    document.addEventListener('click', select, true);
    document.body.dataset.workbenchInspecting = String(inspecting);
    return () => document.removeEventListener('click', select, true);
  }, [inspecting, story.id]);
  if (story.kind === 'region' || story.id === 'appearance' || story.id === 'keyboard') return null;
  return createPortal(<main className={`wb-standalone learning-demo ${id === 'models' || id === 'model-roles' ? 'leornian-settings' : ''}`}
    data-learning-demo data-workbench-surface style={{ maxWidth: story.width }}>
    <SurfaceBoundary>{state.snapshot
      ? <WorkbenchSpecimens surface={story.surface} state={variant} panel={story.panel} />
      : <Notice>正在读取预览数据…</Notice>}</SurfaceBoundary>
  </main>, document.body);
}

export default function WorkbenchBridge() {
  return new URLSearchParams(location.search).has('__workbench') ? <PreviewBridge /> : null;
}
