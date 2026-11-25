import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, Check, Code2, Copy, ExternalLink, Moon, MousePointer2, PanelRightClose, PanelRightOpen, RotateCcw, Search, Sun } from 'lucide-react';
import { findWorkbenchStory, workbenchConversationId, workbenchGroups, workbenchStories } from './workbench-catalog.mjs';
import './workbench.css';

type Selection = { selector: string; tag: string; text: string; owner: string; files: string[] };

function ComponentWorkbench() {
  const initial = new URLSearchParams(location.search);
  const [selected, setSelected] = useState(initial.get('component') ?? 'page');
  const story = findWorkbenchStory(selected);
  const [variant, setVariant] = useState(initial.get('state') ?? story.states[0].id);
  const state = story.states.some((item) => item.id === variant) ? variant : story.states[0].id;
  const [query, setQuery] = useState(''), [theme, setTheme] = useState(initial.get('theme') ?? 'light');
  const [width, setWidth] = useState(story.width), [revision, setRevision] = useState(0);
  const [details, setDetails] = useState(() => window.matchMedia('(min-width: 1100px)').matches);
  const [file, setFile] = useState(story.source[0]);
  const [code, setCode] = useState(''), [sourceError, setSourceError] = useState('');
  const [sourceVersion, setSourceVersion] = useState(0);
  const [status, setStatus] = useState('正在加载组件…'), [failure, setFailure] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null), [inspecting, setInspecting] = useState(false);
  const [copied, setCopied] = useState(false), [scale, setScale] = useState(1);
  const frame = useRef<HTMLIFrameElement>(null), canvas = useRef<HTMLDivElement>(null);
  const instance = useMemo(() => crypto.randomUUID(), [story.id, state, theme, revision]);
  const blank = story.id === 'welcome' || state === 'empty' && ['page', 'sidebar', 'recent'].includes(story.id);
  const url = `/c/${blank ? 'new' : workbenchConversationId}?${new URLSearchParams({
    __workbench: instance, component: story.id, state, theme,
    ...(story.id === 'route-confirmation' || state === 'draft' ? { stage: 'planning' } : {}),
  })}`;
  const files = [...new Set([...story.source, ...story.styles, ...(selection?.files ?? [])])];
  const groups = workbenchGroups.map((group) => ({ ...group,
    items: workbenchStories.filter((item) => item.group === group.id &&
      `${item.title} ${item.component} ${item.source.join(' ')}`.toLowerCase().includes(query.toLowerCase())),
  })).filter((group) => group.items.length);

  function choose(id: string) {
    const next = findWorkbenchStory(id);
    setSelected(next.id); setVariant(next.states[0].id); setWidth(next.width);
    setFile(next.source[0]); setSelection(null); setInspecting(false);
  }
  useEffect(() => {
    setStatus('正在加载组件…'); setFailure(false); setSelection(null); setInspecting(false);
    history.replaceState(null, '', `/__components?${new URLSearchParams({ component: story.id, state, theme })}`);
  }, [instance]);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== frame.current?.contentWindow ||
        event.data?.source !== 'leornian-workbench' || event.data.instance !== instance) return;
      if (event.data.type === 'ready') { setStatus('已就绪 · 保存源码后自动更新'); setFailure(false); }
      if (event.data.type === 'error') { setStatus(event.data.message); setFailure(true); }
      if (event.data.type === 'selection') {
        setSelection(event.data); setInspecting(false); setDetails(true);
        if (event.data.files?.[0]) setFile(event.data.files[0]);
      }
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [instance]);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const measure = () => setScale(Math.min(1, Math.max(240, element.clientWidth - 32) / width));
    measure(); const observer = new ResizeObserver(measure); observer.observe(element);
    return () => observer.disconnect();
  }, [width, details]);
  useEffect(() => {
    const hot = (import.meta as ImportMeta & { hot?: {
      on: (event: string, listener: () => void) => void;
      off: (event: string, listener: () => void) => void;
    } }).hot;
    const changed = () => setSourceVersion((version) => version + 1);
    hot?.on('vite:afterUpdate', changed);
    return () => hot?.off('vite:afterUpdate', changed);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setSourceError(''); setCode('');
    fetch(`/__components/source?${new URLSearchParams({ path: file })}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('源码文件暂不可读');
        return response.text();
      }).then(setCode).catch((error: Error) => { if (!controller.signal.aborted) setSourceError(error.message); });
    return () => controller.abort();
  }, [file, revision, sourceVersion]);
  const copyPath = async () => {
    await navigator.clipboard.writeText(file); setCopied(true); window.setTimeout(() => setCopied(false), 1500);
  };
  const inspect = () => {
    const next = !inspecting; setInspecting(next);
    frame.current?.contentWindow?.postMessage({ source: 'leornian-workbench-control', type: 'inspect', enabled: next }, location.origin);
  };
  return <div className="wb-app" data-theme={theme}>
    <aside className="wb-navigation" aria-label="组件目录">
      <div className="wb-brand"><span className="wb-wordmark">Leornian</span><span>组件工作台</span></div>
      <label className="wb-search"><Search size={16} aria-hidden /><input aria-label="搜索组件"
        placeholder="搜索组件或文件…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="wb-catalog" aria-label="按区域浏览组件">
        {groups.map((group) => <section key={group.id}><h2>{group.title}</h2>
          {group.items.map((item) => <button key={item.id} type="button" className="wb-story"
            aria-current={item.id === story.id ? 'page' : undefined} onClick={() => choose(item.id)}>
            <span>{item.title}</span><span className="wb-story-dot" aria-hidden />
          </button>)}
        </section>)}
        {!groups.length && <p className="wb-empty">没有匹配的组件。</p>}
      </div>
      <footer className="wb-nav-footer">{workbenchStories.length} 个预览入口 · 共用产品源码</footer>
    </aside>
    <main className="wb-main">
      <header className="wb-toolbar">
        <div className="wb-title"><h1>{story.title}</h1><span>{story.component}</span></div>
        <div className="wb-tools">
          {story.id !== 'page' && <button type="button" onClick={() => choose('page')} title="查看完整学习页面"><ArrowLeft size={16} />完整页面</button>}
          <button type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={theme === 'dark' ? '切换浅色主题' : '切换深色主题'}>
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <button type="button" onClick={() => setRevision(revision + 1)} title="重置本地样例" aria-label="重置预览"><RotateCcw size={17} /></button>
          <button type="button" onClick={() => setDetails(!details)} aria-label={details ? '收起源码面板' : '展开源码面板'}>
            {details ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
          </button>
        </div>
      </header>
      <div className="wb-controls">
        <label>状态<select aria-label="组件状态" value={state} onChange={(event) => setVariant(event.target.value)}>
          {story.states.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select></label>
        <label>宽度<select aria-label="预览宽度" value={width} onChange={(event) => setWidth(Number(event.target.value))}>
          {[...new Set([story.width, 1440, 1024, 768, 390])].sort((a, b) => b - a).map((value) => <option key={value} value={value}>{value} px</option>)}
        </select></label>
        <span className="wb-scale">{Math.round(scale * 100)}%</span>
        <div className="wb-controls-end"><button type="button" aria-pressed={inspecting} onClick={inspect}>
          <MousePointer2 size={15} />{inspecting ? '点击画布中的元素' : '点选元素'}
        </button><a href={url} target="_blank" rel="noreferrer"><ExternalLink size={15} />单独打开</a></div>
      </div>
      {story.note && <p className="wb-note">{story.note}</p>}
      <div className={`wb-content ${details ? '' : 'wb-content-wide'}`}>
        <section ref={canvas} className="wb-canvas" aria-label={`${story.title}预览画布`}>
          <div className="wb-frame-shell" style={{ width: width * scale }}>
            <iframe ref={frame} key={instance} title={`${story.title}交互预览`} src={url}
              style={{ width, height: `calc((100vh - 190px) / ${scale})`, transform: `scale(${scale})` }} />
          </div>
        </section>
        {details && <aside className="wb-details" aria-label="组件源码与元素信息">
          <div className="wb-details-heading"><Code2 size={16} /><h2>修改位置</h2></div>
          <p className="wb-help">选择文件查看源码。修改对应文件并保存，画布自动更新。</p>
          <div className="wb-file-list">{files.map((path) => <button type="button" key={path}
            aria-pressed={file === path} onClick={() => setFile(path)}>{path}</button>)}</div>
          <div className="wb-source-toolbar"><span>{file.split('/').at(-1)}</span>
            <button type="button" onClick={() => void copyPath()} aria-label="复制源码路径">{copied ? <Check size={14} /> : <Copy size={14} />}</button></div>
          {sourceError ? <p role="alert" className="wb-help">{sourceError}</p>
            : <pre className="wb-source" tabIndex={0} aria-label="所选文件源码"><code>{code || '正在读取源码…'}</code></pre>}
          {selection && <section className="wb-selection" aria-label="点选元素信息">
            <h2>所选元素</h2><p>{selection.owner}</p><code>{selection.selector}</code>
            {selection.text && <p>{selection.text}</p>}
          </section>}
        </aside>}
      </div>
      <footer className="wb-status" data-error={failure}><span className="wb-status-dot" /><span role="status">{status}</span>
        <span className="wb-local-data">本地样例 · 可交互、可重置</span></footer>
    </main>
  </div>;
}

const container = document.getElementById('workbench-root')! as HTMLElement & {
  leornianWorkbenchRoot?: ReturnType<typeof createRoot>;
};
container.leornianWorkbenchRoot ??= createRoot(container);
container.leornianWorkbenchRoot.render(<ComponentWorkbench />);
