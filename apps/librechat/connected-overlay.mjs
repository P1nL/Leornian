import { nativeFiles, nativeImports, nativeOverlayPaths, overlayNativeSource } from './native-overlay.mjs';
import { overlayPreviewSource } from './preview-overlay.mjs';
import { connectedSettingsPaths, overlayConnectedSettings } from './connected-settings.mjs';

const connected = 'virtual:leornian-connected-learning';
export const connectedFiles = [...nativeFiles, 'LearningChrome.tsx', 'BaselineLearning.tsx', 'BaselinePanels.tsx', 'BaselineAttachments.tsx', 'LearningAttachments.tsx',
  'BaselineRoutes.tsx', 'LearningNavigation.tsx', 'BaselineQuestionBank.tsx', 'QuestionBankGeneration.tsx', 'question-bank.css',
  'QuestionBankRelay.tsx', 'generation-relay.ts', ...['view.mjs', 'score.mjs', 'sequence.js', 'script.js', 'style.css', 'vendor/gsap.min.js']
    .map((file) => `question-bank-relay/${file}`),
  'BaselineRagProgress.tsx', 'NodeTeachingWindow.tsx', 'baseline-motion.ts', 'baseline-learning.css'];
export const connectedImports = {
  ...nativeImports, [connected]: 'BaselineLearning.tsx',
  'virtual:leornian-native-models': 'NativeModels.tsx',
};
export const connectedOverlayPaths = [...nativeOverlayPaths,
  ...connectedSettingsPaths,
  'src/hooks/Nav/useUnifiedSidebarLinks.ts',
  ...['en', 'zh-Hans', 'zh-Hant'].map((language) => `src/locales/${language}/translation.json`)];

export function overlayConnectedSource(path, source) {
  source = source.replaceAll('\r\n', '\n');
  if (connectedSettingsPaths.includes(path)) return overlayConnectedSettings(path, source);
  if (path.startsWith('src/locales/')) {
    const translation = JSON.parse(overlayPreviewSource(path, source));
    const en = path.includes('/en/'), traditional = path.includes('/zh-Hant/');
    translation.com_leornian_model_roles = en ? 'Model Usage' : '用途分配';
    translation.com_leornian_appearance = en ? 'Appearance' : traditional ? '外觀' : '外观';
    translation.com_ui_new_chat = en ? 'Create learning plan' : traditional ? '建立新學習計畫' : '创建新学习计划';
    translation.com_ui_chat_history = en ? 'Recent' : '最近';
    translation.com_leornian_delete_recent_confirm = en
      ? '<strong>{{title}}</strong> will be removed from Recent. Your learning plan, history and background requests are retained.'
      : traditional
        ? '<strong>{{title}}</strong> 將從最近中移除；學習路線、歷史記錄及背景請求保留。'
        : '<strong>{{title}}</strong> 将从最近中移除；学习路线、历史记录及后台请求保留。';
    translation.com_leornian_learning_preferences = en ? 'Learning' : traditional ? '學習' : '学习';
    translation.com_leornian_question_bank = en ? 'Question bank' : traditional ? '題庫' : '题库';
    return JSON.stringify(translation);
  }
  if (path === 'src/hooks/Nav/useUnifiedSidebarLinks.ts') {
    const insertion = '    if (\n      !insightsFeatureEnabled';
    if (!source.includes('return [conversationLink, ...sideNavLinks];') ||
      source.split(insertion).length !== 2 ||
      !source.includes('BarChart3, MessagesSquare')) throw new Error('Pinned sidebar links changed.');
    return `import { BaselineRoutes, BaselineQuestionBank } from '${connected}';\n` + source
      .replace('BarChart3, MessagesSquare', 'BarChart3, MessagesSquare, BookOpen, Layers')
      .replace(insertion, `    const learningLink: NavLink = {
      title: 'com_leornian_learning_preferences', label: '', icon: BookOpen,
      id: 'learning', Component: BaselineRoutes,
    };
    const bankLink: NavLink = {
      title: 'com_leornian_question_bank', label: '', icon: Layers,
      id: 'question-bank', Component: BaselineQuestionBank,
    };
    if (
      !insightsFeatureEnabled`)
      .replaceAll('[conversationLink, ...', '[conversationLink, learningLink, bankLink, ...');
  }
  const native = overlayNativeSource(path, source);
  if (native === null) return null;
  if (path === 'src/components/Chat/ChatView.tsx') return native
    .replace('NativeSync, NativeStart, NativeComposer,', 'NativeSync,')
    .replace('<NativeStart />', '<BaselineStart />')
    .replace('<NativeComposer ', '<BaselineComposer ')
    .replaceAll('<NativeConversationContent', '<BaselineConversationContent')
    .replaceAll('</NativeConversationContent>', '</BaselineConversationContent>')
    .replace(/^/, `import { BaselineStart, BaselineComposer, BaselineConversationContent } from '${connected}';\n`);
  if (path === 'src/components/Chat/Header.tsx') return native
    .replace(`from 'virtual:leornian-native-learning'`, `from '${connected}'`)
    .replaceAll('NativeTasks', 'BaselineTasks').replaceAll('NativeLearningMenu', 'BaselineLearningMenu');
  if (path === 'src/components/SidePanel/SidePanelGroup.tsx') return native
    .replace(`from 'virtual:leornian-native-learning'`, `from '${connected}'`)
    .replaceAll('NativeSourcePanel', 'BaselineSourcePanel');
  return native;
}
