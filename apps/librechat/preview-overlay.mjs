import { removeSilentAudio } from './app-overlay.mjs';

const registryPath = 'src/components/Nav/Settings/registry.tsx';
const typesPath = 'src/components/Nav/Settings/types.ts';
export const modelPreviewImport = 'virtual:leornian-model-configuration-preview';
export const artifactsPreviewImport = 'virtual:leornian-learning-artifacts';
export const chromePreviewImport = 'virtual:leornian-demo-chrome';
export const galleryPreviewImport = 'virtual:leornian-artifact-gallery';
export const previewModules = [
  'ModelConfigurationPreview.tsx', 'LearningArtifacts.tsx', 'DemoChrome.tsx', 'DemoUI.tsx', 'PracticeWorkbench.tsx',
  'learning-demo-data.mjs', 'demo-state.mjs', 'learning-demo.css', 'learning-motion.css',
  'ArtifactGallery.tsx', 'artifact-catalog.mjs', 'artifact-gallery.css',
  'LearningComponents.tsx', 'ComponentGallery.tsx', 'component-catalog.mjs',
  'LearningVisuals.tsx', 'learning-visuals.css', 'component-utils.mjs',
  'InlineCodeEditor.tsx', 'PhosphorIcons.tsx',
  'AlgorithmVisuals.tsx', 'AlgorithmExamples.tsx', 'algorithm-visuals.css', 'algorithm-demos.mjs',
  'LearningUI.tsx', 'LearningChrome.tsx', 'LearningComposition.tsx', 'CompositionGallery.tsx',
  'composition-runtime.mjs', 'composition-validator.generated.mjs', 'composition-examples.json',
];

function replaceOnce(source, before, after) {
  if (source.split(before).length !== 2) {
    throw new Error('Pinned LibreChat settings source changed; review the preview overlay before building.');
  }
  return source.replace(before, after);
}

function replacePatternOnce(source, pattern, replacement) {
  if ([...source.matchAll(pattern)].length !== 1) {
    throw new Error('Pinned LibreChat settings source changed; review the preview overlay before building.');
  }
  return source.replace(pattern, replacement);
}

// Build-time source overlays keep the pinned upstream checkout unchanged.
export function overlayPreviewSource(path, source) {
  source = source.replaceAll('\r\n', '\n');
  if (path === 'src/App.jsx') return removeSilentAudio(source);
  if (path === 'src/routes/index.tsx') {
    return replaceOnce(
      `import ArtifactGallery from '${galleryPreviewImport}';\n${source}`,
      "                  path: 'c/:conversationId?',",
      "                  path: '__preview/artifacts',\n                  element: <ArtifactGallery />,\n                },\n                {\n                  path: 'c/:conversationId?',",
    );
  }
  if (path === registryPath) {
    return replaceOnce(
      source,
      'export const registry: SettingEntry[] = [',
      `import ModelConfigurationPreview from '${modelPreviewImport}';
import { DemoEnvironmentSettings, DemoPreferences } from '${chromePreviewImport}';

export const registry: SettingEntry[] = [
  {
    id: 'leornianModelConfiguration',
    tab: 'leornianModels',
    section: 'apiKeys',
    labelKey: 'com_leornian_model_configuration',
    keywords: ['模型', 'API Key', '提供方', '连接', 'OCR', 'embedding', 'rerank'],
    Component: ModelConfigurationPreview,
  },
  {
    id: 'leornianExecution',
    tab: 'leornianExecution',
    section: 'codeExecution',
    labelKey: 'com_leornian_local_execution',
    keywords: ['本机', '环境', '安装', '授权', 'Python', 'Flask'],
    Component: DemoEnvironmentSettings,
  },
  {
    id: 'leornianPreferences',
    tab: CHAT,
    section: 'sending',
    labelKey: 'com_leornian_learning_preferences',
    keywords: ['学习', '模式', '提醒', '暂停', '时段'],
    Component: DemoPreferences,
  },`,
    );
  }
  if (path === typesPath) {
    let result = replaceOnce(source, 'import { MessageSquare, Info }', 'import { MessageSquare, Info, Settings2 }');
    result = replaceOnce(result, 'export type SettingsTab =', "export type SettingsTab =\n  | 'leornianModels'\n  | 'leornianExecution'");
    return replaceOnce(result, 'export const TABS: TabMeta[] = [', `export const TABS: TabMeta[] = [
  {
    id: 'leornianModels',
    labelKey: 'com_leornian_model_configuration',
    icon: createElement(Settings2, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [{ id: 'apiKeys', labelKey: 'com_leornian_model_configuration' }],
  },
  {
    id: 'leornianExecution',
    labelKey: 'com_leornian_local_execution',
    icon: createElement(Settings2, { className: 'icon-sm', 'aria-hidden': true }),
    sections: [{ id: 'codeExecution', labelKey: 'com_leornian_local_execution' }],
  },`);
  }
  if (path === 'src/components/Chat/Messages/Content/MessageContent.tsx') {
    return replaceOnce(
      `import LearningArtifacts from '${artifactsPreviewImport}';\n${source}`,
      '      </CollapsibleText>',
      '        {!isCreatedByUser && <LearningArtifacts messageId={message?.messageId} />}\n      </CollapsibleText>',
    );
  }
  if (path === 'src/components/SidePanel/SidePanelGroup.tsx') {
    return replaceOnce(
      `import { DemoSourcePanel } from '${chromePreviewImport}';\n${source}`,
      'export default SidePanelGroup;',
      'export default function PreviewSidePanel(props: SidePanelProps) { return <DemoSourcePanel {...props} NativeGroup={SidePanelGroup} />; }',
    );
  }
  if (path === 'src/components/Chat/Header.tsx') {
    let result = `import { DemoTasks, DemoLearningMenu } from '${chromePreviewImport}';\n${source}`;
    result = replaceOnce(result, '{!readOnly && <ModelSelector startupConfig={startupConfig} />}',
      '<span className="truncate text-sm font-medium" aria-label="当前学习" title={isNewChat ? "开始学习" : conversation?.title ?? "当前学习"}>{isNewChat ? "开始学习" : conversation?.title ?? "当前学习"}</span>');
    result = replaceOnce(result, '<BackgroundTasksButton', '<DemoTasks');
    result = replaceOnce(result, '<HeaderMenu', '<DemoLearningMenu');
    return replaceOnce(result, '<ExportAndShareMenu', '<DemoLearningMenu');
  }
  if (path === 'src/components/Chat/ChatView.tsx') {
    let result = `import { DemoStart, DemoComposer } from '${chromePreviewImport}';\n${source}`;
    result = replaceOnce(result, 'landing={<Landing centerFormOnLanding={centerFormOnLanding} />}',
      'landing={<DemoStart />}');
    return replacePatternOnce(result, /<ChatForm\n[\s\S]*?\/>/g,
      '<DemoComposer conversationId={conversationId} />');
  }
  if (path === 'src/components/Chat/Input/Files/MyFilesModal.tsx') {
    return replaceOnce(
      `import { DemoFiles } from '${chromePreviewImport}';\n${source}`,
      '<DataTable columns={columns} data={files} />',
      '<><DataTable columns={columns} data={files} /><DemoFiles onRead={() => onOpenChange(false)} /></>',
    );
  }
  if (path === 'src/components/Nav/SearchBar.tsx') {
    return replaceOnce(source,
      "    if (value.length > 0 && location.pathname !== '/search') {\n      navigate('/search', { replace: true });\n    }",
      '    // Demo searches filter the complete static history in this same sidebar.',
    );
  }
  if (/^src\/locales\/(en|zh-Hans|zh-Hant)\/translation\.json$/.test(path)) {
    const translation = JSON.parse(source);
    translation.com_leornian_model_configuration = path.includes('/en/')
      ? 'Model Configuration' : path.includes('/zh-Hant/') ? '模型設定' : '模型配置';
    translation.com_leornian_local_execution = path.includes('/en/') ? 'Local Execution' : path.includes('/zh-Hant/') ? '本機執行' : '本机执行';
    translation.com_leornian_learning_preferences = path.includes('/en/') ? 'Learning Preferences' : path.includes('/zh-Hant/') ? '學習方式與提醒' : '学习方式与提醒';
    return JSON.stringify(translation);
  }
  return null;
}

export const previewOverlayPaths = [
  'src/App.jsx',
  registryPath, typesPath,
  'src/routes/index.tsx',
  'src/components/Chat/Messages/Content/MessageContent.tsx',
  'src/components/SidePanel/SidePanelGroup.tsx',
  'src/components/Chat/Header.tsx',
  'src/components/Chat/ChatView.tsx',
  'src/components/Chat/Input/Files/MyFilesModal.tsx',
  'src/components/Nav/SearchBar.tsx',
  ...['en', 'zh-Hans', 'zh-Hant'].map((locale) => `src/locales/${locale}/translation.json`),
];
