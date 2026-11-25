import { useEffect, useId, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight } from 'lucide-react';
import { ReaderLayout } from './DemoChrome';
import { AnimatedText, Disclosure } from './DemoUI';
import { LearningArtifact } from './LearningArtifacts';
import ComponentGallery from './ComponentGallery';
import CompositionGallery from './CompositionGallery';
import { TabBar, TabPanels } from './PracticeWorkbench';
import { componentCatalog, componentCount } from './component-catalog.mjs';
import { artifactCatalog, artifactGalleryPath, artifactStyleFiles, galleryGroups, learningInteractionCatalog } from './artifact-catalog.mjs';
import './artifact-gallery.css';

export default function ArtifactGallery() {
  const id = useId();
  const scrollRef = useRef<HTMLElement>(null);
  const [search, setSearch] = useSearchParams();
  const view = ['components', 'compositions'].includes(search.get('view') ?? '') ? search.get('view')! : 'artifacts';
  const [jump, setJump] = useState<string | null>(null);
  const [category, setCategory] = useState('all');
  const changeView = (value: string) => {
    const next = new URLSearchParams(search);
    next.set('view', value);
    setSearch(next);
    scrollRef.current?.scrollTo({ top: 0 });
  };
  const groups = category === 'all' ? galleryGroups : galleryGroups.filter((group) => group.id === category);
  const exampleCount = artifactCatalog.reduce((count, group) => count + group.examples.length, 0);
  const selectCategory = (value: string) => {
    setCategory(value);
    scrollRef.current?.scrollTo({ top: 0 });
  };
  useEffect(() => {
    const previous = document.title;
    document.title = '学习工件一览 · LibreChat';
    return () => { document.title = previous; };
  }, []);
  useEffect(() => {
    if (view !== 'artifacts' || !jump) return;
    scrollRef.current?.querySelector(`#gallery-${jump}`)?.scrollIntoView({ block: 'start' });
    setJump(null);
  }, [jump, view]);
  return <ReaderLayout className="demo-gallery-shell">
    <main ref={scrollRef} className="learning-demo demo-gallery" data-learning-demo aria-labelledby={`${id}-heading`}>
      <header className="demo-gallery-heading">
        <Link to="/c/demo-python-learning" className="demo-gallery-back"><ArrowLeft size={16} aria-hidden="true" />返回学习演示</Link>
        <h1 id={`${id}-heading`}>学习工件一览</h1>
        <p><AnimatedText block>{view === 'components'
          ? `${componentCatalog.length} 类可拼接组件 · ${componentCount} 个组件 · ${componentCatalog.reduce((sum, group) => sum + group.examples.length, 0)} 个样例`
          : view === 'compositions' ? '3 类配置驱动场景 · 4 个组合样例'
          : `${artifactCatalog.length} 类工件 · ${exampleCount} 个样例 · ${learningInteractionCatalog.examples.length} 项周边交互`}</AnimatedText></p>
        <p className="demo-muted">桌面交互演示：不调用模型、不执行代码、不安装环境。</p>
        <Disclosure className="demo-gallery-guide" title="样式修改位置">
          <dl>
            <dt>八类可拼接组件与接口</dt><dd><code>apps/librechat/LearningComponents.tsx</code></dd>
            <dt>图形、参数与代码差异</dt><dd><code>apps/librechat/LearningVisuals.tsx / learning-visuals.css</code></dd>
            <dt>通用外框、按钮、编辑器与工作台样式</dt><dd><code>{artifactStyleFiles[0]}</code></dd>
            <dt>独立工件 UI 与演示状态适配</dt><dd><code>apps/librechat/LearningUI.tsx / DemoUI.tsx</code></dd>
            <dt>配置驱动组合入口</dt><dd><code>apps/librechat/LearningComposition.tsx</code></dd>
            <dt>代码 / SQL 三分区布局、标签页与放大</dt><dd><code>{artifactStyleFiles[2]}</code></dd>
            <dt>各类工件内容与交互</dt><dd><code>apps/librechat/LearningArtifacts.tsx</code></dd>
            <dt>按钮、标签页、选项动效</dt><dd><code>apps/librechat/learning-motion.css</code></dd>
          </dl>
          <p className="demo-muted">修改共享组件后重新构建预览，原学习场景同步生效。</p>
        </Disclosure>
      </header>
      <div className="demo-gallery-view-switch"><TabBar id={`${id}-view`} label="一览视图"
        tabs={[{ id: 'components', label: '可拼接组件' }, { id: 'compositions', label: '组合场景' }, { id: 'artifacts', label: '完整工件' }]}
        selected={view} onSelect={changeView} /></div>
      <TabPanels id={`${id}-view`} autoHeight className="demo-gallery-view-panels" selected={view} tabs={[
        { id: 'compositions', label: '组合场景', content: <CompositionGallery active={view === 'compositions'} /> },
        { id: 'components', label: '可拼接组件', content: <ComponentGallery onViewArtifact={(artifactId) => {
          setCategory('all'); changeView('artifacts'); setJump(artifactId);
        }} /> },
        { id: 'artifacts', label: '完整工件', content: <>
      <div className="demo-gallery-toolbar">
        <label htmlFor={`${id}-category`}>按类型查看</label>
        <select id={`${id}-category`} value={category} onChange={(event) => selectCategory(event.target.value)}>
          <option value="all">全部工件与交互</option>
          {galleryGroups.map((group) => <option key={group.id} value={group.id}>{group.title}（{group.examples.length}）</option>)}
        </select>
      </div>
      <nav className="demo-gallery-index" aria-label="学习工件目录">
        {groups.map((group) => <div key={group.id}>
          <span>{group.title}</span>
          <ul>{group.examples.map((example) => <li key={example.id}>
            <a href={`${artifactGalleryPath}${search.toString() ? `?${search}` : ''}#gallery-${example.id}`}>{example.title}</a>
          </li>)}</ul>
        </div>)}
      </nav>
      <div className="demo-gallery-content">
        {groups.map((group) => <section key={group.id} className="demo-gallery-group" aria-labelledby={`${id}-${group.id}`}>
          <h2 id={`${id}-${group.id}`}>{group.title}</h2>
          {group.id === 'execution_result' && <p className="demo-muted">结果与代码样例共用状态，需要查看结果样式时，先<button
            type="button" className="demo-gallery-text-action" onClick={() => selectCategory('code_workspace')}>打开代码工作区</button>并明确运行内置样例。</p>}
          {group.examples.map((example) => <section key={example.id} id={`gallery-${example.id}`}
            className="demo-gallery-example" aria-label={`${example.title}样式样例`}>
            <div className="demo-gallery-example-heading">
              {['assistance', 'update'].includes(example.id) && <span>{example.title}</span>}
              <Link to={`/c/${example.conversationId}`}>{example.previewOnly ? '在工作台中使用' : '原学习场景'}<ArrowUpRight size={14} aria-hidden="true" /></Link>
            </div>
            <LearningArtifact id={example.id} />
            <Disclosure className="demo-gallery-source" title="源码与样式定位">
              <dl>
                <dt>组件</dt><dd><code>{group.source}</code> → <code>{'component' in example ? example.component : 'component' in group ? group.component : ''}</code></dd>
                <dt>样例 ID</dt><dd><code>{example.id}</code></dd>
                <dt>样式选择器</dt><dd><code>{'selectors' in example ? example.selectors : 'selectors' in group ? group.selectors : ''}</code></dd>
              </dl>
            </Disclosure>
          </section>)}
        </section>)}
      </div>
        </> },
      ]} />
    </main>
  </ReaderLayout>;
}
