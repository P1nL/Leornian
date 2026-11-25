import { componentCatalog } from './component-catalog.mjs';
import { editableUiSource } from './editable-ui.mjs';

export const workbenchGroups = [
  ['layout', '页面与布局'], ['identity', '身份与开始'], ['navigation', '导航与路线'],
  ['header', '顶栏与任务'], ['messages', '消息与教学'], ['composer', '输入与附件'],
  ['course', '路线与学习记录'], ['artifacts', '学习工件'], ['materials', '材料与来源'],
  ['settings', '设置与模型'], ['common', '公共控件与反馈'], ['visual', '样式与动效'],
].map(([id, title]) => ({ id, title }));

const stateLabels = {
  default: '默认', empty: '空内容', long: '长内容', error: '出错', loading: '加载中',
  busy: '处理中', disabled: '禁用', completed: '已完成', unknown: '结果未知',
  collapsed: '收起', expanded: '展开', draft: '待确认', confirmed: '已确认',
  attached: '带附件', uploading: '上传中', ready: '就绪', waiting: '待授权',
  preset: '预设提供方', custom: '自定义提供方', edit: '编辑模型',
  due: '待复习', presented: '回忆中', revoked: '权限已撤销', streaming: '流式内容',
};
const app = (file) => `apps/librechat/${file}`;
const upstream = (file) => editableUiSource(file) ?? `.local/upstream/LibreChat-f4154b6/client/src/${file}`;
/** @typedef {{id: string, title: string, group: string, component: string, source: string[],
 * styles: string[], kind: string, surface: string, selector: string, panel: string, width: number,
 * note: string, states: {id: string, label: string}[]}} WorkbenchStory */
/** @returns {WorkbenchStory} */
function story(id, title, group, component, source, options = {}) {
  return {
    id, title, group, component, source: source.map((file) => file.includes('/') ? file : app(file)),
    styles: [upstream('style.css'), app('baseline-learning.css'), app('learning-demo.css'),
      ...(group === 'settings' ? [app('native-models.css'), app('ccs-models.css')] : [])],
    kind: 'surface', surface: id, selector: '', panel: '', width: 1024, note: '',
    ...options,
    states: (options.states ?? ['default']).map((id) => ({ id, label: stateLabels[id] ?? id })),
  };
}

export const workbenchStories = [
  story('page', '完整学习页面', 'layout', 'Root + ChatView', [
    upstream('routes/Root.tsx'), upstream('components/Chat/ChatView.tsx'), 'BaselineLearning.tsx',
  ], { kind: 'region', states: ['default', 'empty', 'long', 'error', 'streaming'], width: 1440 }),
  story('sidebar', '侧栏与区域伸缩', 'layout', 'UnifiedSidebar', [
    upstream('components/UnifiedSidebar/UnifiedSidebar.tsx'),
  ], { kind: 'region', selector: '[data-workbench-region="sidebar"]', width: 360,
    states: ['default', 'collapsed', 'empty', 'long'] }),
  story('welcome', '欢迎区域', 'identity', 'LearningWelcome', ['LearningChrome.tsx'],
    { kind: 'region', selector: '.baseline-welcome', width: 800 }),
  story('login', '本机登录表单', 'identity', 'LearningLoginForm', ['LearningChrome.tsx', 'NativeLearning.tsx'],
    { states: ['default', 'busy', 'error'], width: 600 }),
  story('routes', '学习文件夹与课时节点', 'navigation', 'BaselineRoutes', ['BaselineRoutes.tsx', 'LearningNavigation.tsx'],
    { selector: '.baseline-routes', states: ['default', 'empty', 'draft', 'long'], width: 360 }),
  story('route-node', '节点选中、完成与锁定', 'navigation', 'LearningRouteFolder + LearningRouteNode', ['LearningNavigation.tsx'],
    { states: ['default', 'collapsed', 'disabled'], width: 360 }),
  story('recent', '最近会话与操作菜单', 'navigation', 'ConversationsSection', [
    upstream('components/UnifiedSidebar/ConversationsSection.tsx'),
    upstream('components/Conversations/ConvoOptions/DeleteButton.tsx'),
  ], { kind: 'region', selector: '[data-workbench-region="sidebar"]', states: ['default', 'empty', 'long'], width: 360 }),
  story('search', '搜索输入控件', 'navigation', 'SearchBar', [upstream('components/Nav/SearchBar.tsx')],
    { note: '当前产品宿主关闭了历史搜索；这里独立展示现有输入控件。', width: 440 }),
  story('account', '账户入口与菜单', 'navigation', 'AccountSettings', [upstream('components/Nav/AccountSettings.tsx')], { width: 440 }),
  story('header', '当前学习顶栏', 'header', 'Header + BaselineLearningMenu', [
    upstream('components/Chat/Header.tsx'), 'BaselineLearning.tsx',
  ], { kind: 'region', selector: '[data-workbench-region="header"]', width: 1024 }),
  story('tasks', '后台任务与核对状态', 'header', 'NativeTaskList', ['NativeLearning.tsx', 'LearningChrome.tsx'],
    { states: ['default', 'empty', 'busy', 'unknown', 'error'], width: 600 }),
  story('learning-menu', '学习菜单与弹窗', 'header', 'BaselineLearningMenu', ['BaselineLearning.tsx', 'BaselinePanels.tsx'], { width: 700 }),
  story('messages', '消息列表与操作', 'messages', 'MessagesView + NativeConversationContent', [
    upstream('components/Chat/Messages/MessagesView.tsx'), 'NativeLearning.tsx', 'NativeMessageExtras.tsx',
  ], { kind: 'region', selector: '[data-baseline-conversation]', states: ['default', 'long', 'error', 'streaming'], width: 960 }),
  story('thinking', '思考文本与步骤', 'messages', 'NativeThinking', ['NativeThinking.tsx'],
    { states: ['default', 'busy', 'completed', 'error'], width: 760 }),
  story('teaching', '教学模式、暂停与答疑', 'messages', 'NativeTeachingControls', ['NativeTeaching.tsx'],
    { states: ['default', 'busy', 'error'], width: 800 }),
  story('route-confirmation', '对话中的路线确认', 'messages', 'NativeRouteConfirmation', ['NativeRouteConfirmation.tsx'],
    { states: ['draft', 'confirmed', 'busy'], width: 800 }),
  story('composer', '学习输入框', 'composer', 'LearningComposerFrame', ['LearningChrome.tsx', 'BaselineLearning.tsx'],
    { selector: '.demo-composer', states: ['default', 'empty', 'busy', 'disabled', 'error', 'long'], width: 960 }),
  story('attachments', '附件与上传反馈', 'composer', 'LearningAttachmentList + LearningComposerFrame', [
    'LearningAttachments.tsx', 'BaselineAttachments.tsx', 'LearningChrome.tsx',
  ], { selector: '.baseline-attachments', states: ['attached', 'uploading', 'error'], width: 960 }),
  ...[
    ['route', '路线草案与课时', 'NativeCourse', ['NativeCourse.tsx'], ['draft', 'confirmed', 'empty', 'busy', 'error']],
    ['records', '学习记录与能力证据', 'BaselineRecords', ['BaselinePanels.tsx', 'NativeLearningEvidence.tsx'], ['default', 'empty', 'error']],
    ['reviews', '到期复习与回忆反馈', 'NativeReviews', ['NativeReviews.tsx'], ['due', 'presented', 'empty', 'error']],
    ['preferences', '学习方式与提醒', 'BaselinePreferences', ['BaselinePanels.tsx', 'NativeTeaching.tsx', 'NativeReviews.tsx'], ['default', 'error']],
  ].map(([id, title, component, source, states]) => story(id, title, 'course', component, source,
    { panel: id, states, width: 860 })),
  story('assessment', '正式考核与整组提交', 'course', 'NativeAssessment', ['NativeAssessment.tsx'],
    { states: ['ready', 'presented', 'completed'], width: 900 }),
  story('recovery', '补救后的新情境检查', 'course', 'NativeRecovery', ['NativeRecovery.tsx'],
    { states: ['ready', 'presented', 'completed'], width: 900 }),
  story('assistance', '分级提示与参考答案', 'course', 'NativeAssistance', ['NativeAssistance.tsx'],
    { states: ['default', 'completed', 'disabled'], width: 800 }),
  story('artifact-gallery', '全部工件与组合场景', 'artifacts', 'ArtifactGallery', [
    'ArtifactGallery.tsx', 'LearningArtifacts.tsx', 'LearningComposition.tsx',
  ], { surface: 'artifact-gallery', width: 1180 }),
  ...componentCatalog.flatMap((group) => group.examples.map((example) => story(
    `component-${example.id}`, example.title, 'artifacts', example.components.join(' + '),
    [example.id.startsWith('algorithm-') ? 'AlgorithmVisuals.tsx'
      : ['code-diff', 'tree-view', 'relation-graph', 'sequence-diagram', 'parameter-control'].includes(example.id)
        ? 'LearningVisuals.tsx' : 'LearningComponents.tsx', 'ComponentGallery.tsx'],
    { surface: 'component-gallery', selector: `#component-${example.id}`, width: 1000,
      styles: [app('learning-demo.css'), app('learning-visuals.css'), app('algorithm-visuals.css'), app('learning-motion.css')] },
  ))),
  story('materials', '材料上传与教材更新', 'materials', 'BaselineMaterials', ['BaselinePanels.tsx', 'NativeMaterialIntake.tsx'],
    { panel: 'materials', states: ['default', 'empty', 'error'], width: 900 }),
  story('material-sources', '公开来源与观察记录', 'materials', 'NativeMaterialSources', ['NativeMaterialSources.tsx'],
    { states: ['default', 'empty', 'revoked', 'error'], width: 900 }),
  story('material-updates', '教材更新通知与决定', 'materials', 'NativeMaterialUpdates', ['NativeMaterialUpdates.tsx'],
    { states: ['default', 'empty', 'error'], width: 900 }),
  story('rag-progress', '资料处理进度', 'materials', 'BaselineRagProgress', ['BaselineRagProgress.tsx'],
    { states: ['busy', 'ready', 'unknown', 'error'], width: 460 }),
  story('source-reader', '原文、页码与权限反馈', 'materials', 'LearningSourceReader', ['LearningSourceReader.tsx', 'NativeLearning.tsx'],
    { states: ['default', 'loading', 'revoked', 'long'], width: 760 }),
  story('source-panel', '来源阅读侧栏与关闭', 'materials', 'NativeSourcePanel', ['NativeLearning.tsx', 'LearningSourceReader.tsx'],
    { kind: 'region', selector: '.demo-reader, [role="dialog"]', states: ['default', 'revoked'], width: 1000 }),
  story('appearance', '外观、语言与缩放设置', 'settings', 'SettingsDialog', [
    upstream('components/Nav/Settings/Dialog.tsx'), 'connected-settings.mjs',
  ], { width: 1100 }),
  story('models', '模型提供方与编辑', 'settings', 'NativeModels', ['NativeModels.tsx', 'NativeModelProviders.tsx', 'NativeModelCustom.tsx'],
    { states: ['default', 'empty', 'preset', 'custom', 'edit', 'error'], width: 1100 }),
  story('model-roles', '教学与材料的用途分配', 'settings', 'NativeModelRoles', ['NativeModels.tsx'],
    { states: ['default', 'empty', 'error'], width: 1000 }),
  story('model-key', '密钥输入控件', 'settings', 'CCSApiKeyInput', ['CCSApiKeyInput.tsx'], { width: 760 }),
  story('environment', '本机引擎与课程环境', 'settings', 'NativeExecution', ['NativeExecution.tsx'],
    { panel: 'environment', states: ['ready', 'waiting', 'empty', 'error'], width: 1000 }),
  story('buttons', '按钮、图标与状态', 'common', 'Action + ArtifactAction', ['LearningUI.tsx', 'PhosphorIcons.tsx'],
    { states: ['default', 'busy', 'completed', 'disabled', 'unknown'], width: 760 }),
  story('disclosure', '折叠内容与过渡', 'common', 'Disclosure + Collapse + AnimatedText', ['LearningUI.tsx'],
    { states: ['collapsed', 'expanded'], width: 760 }),
  story('dialog', '弹窗、确认与关闭', 'common', 'DemoDialog', ['LearningUI.tsx'],
    { states: ['default', 'busy', 'error'], width: 860 }),
  story('notice', '提示、加载与错误反馈', 'common', 'Notice', ['LearningUI.tsx'],
    { states: ['default', 'loading', 'error', 'unknown'], width: 760 }),
  story('toast', '全局通知与关闭', 'common', 'Toast + ToastViewport', [upstream('App.jsx')],
    { states: ['default', 'error'], width: 760 }),
  story('keyboard', '快捷键说明与设置', 'common', 'KeyboardShortcutsDialog', [
    upstream('components/Nav/KeyboardShortcutsDialog.tsx'),
  ], { width: 1100 }),
  story('tabs', '标签页与内容切换', 'common', 'TabBar + TabPanels', ['PracticeWorkbench.tsx'], { width: 900 }),
  story('tokens', '主题、字体与间距', 'visual', 'Theme variables + shared CSS', [
    upstream('style.css'), 'baseline-learning.css', 'learning-demo.css', 'native-models.css',
  ], { width: 1000 }),
  story('motion', '进入、折叠与按钮动效', 'visual', 'ContentTransition + Action + Collapse', [
    'LearningUI.tsx', 'baseline-motion.ts', 'learning-motion.css',
  ], { width: 900 }),
];

export const workbenchConversationId = '00000000-0000-4000-8000-000000000001';
export function findWorkbenchStory(id) {
  return workbenchStories.find((item) => item.id === id) ?? workbenchStories[0];
}
