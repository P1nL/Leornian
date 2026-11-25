import { artifacts } from './learning-demo-data.mjs';

export const artifactGalleryPath = '/__preview/artifacts';
export const artifactStyleFiles = [
  'apps/librechat/learning-demo.css',
  'apps/librechat/LearningUI.tsx',
  'apps/librechat/PracticeWorkbench.tsx',
];

const definitions = [
  ['knowledge_check', '知识检查', 'KnowledgeCheck', '.demo-choice, .demo-textarea, .demo-step'],
  ['code_workspace', '代码工作区', 'CodeWorkspace', '.demo-workbench, .demo-editor, .demo-file-tabs'],
  ['execution_result', '执行结果', 'ExecutionResult', '.demo-table-wrap, .demo-notice'],
  ['code_review', '代码评审', 'CodeReview', '.demo-actions, .demo-notice'],
  ['sql_workspace', 'SQL 工作区', 'SqlWorkspace', '.demo-workbench, .demo-workbench-language'],
  ['demo', '交互演示', 'InteractiveDemo', '.demo-steps, .demo-step-value'],
  ['restricted_preview', 'HTML / CSS 受限预览', 'RestrictedPreview', '.demo-html-workbench, .demo-preview'],
  ['source_locator', '来源定位', 'SourceLocator', '.demo-reader, .demo-reader-content'],
];

export const artifactCatalog = definitions.map(([id, title, component, selectors]) => ({
  id, title, component, selectors,
  source: 'apps/librechat/LearningArtifacts.tsx',
  examples: artifacts.filter((artifact) => artifact.presentation.type === id).map((artifact) => ({
    id: artifact.id,
    title: artifact.title,
    conversationId: artifact.conversationId,
    ...(artifact.previewOnly ? { previewOnly: true } : {}),
  })),
}));

export const learningInteractionCatalog = {
  id: 'interactions',
  title: '周边学习交互',
  source: 'apps/librechat/LearningArtifacts.tsx',
  examples: [
    { id: 'route', title: '路线确认与版本', component: 'RouteWidget',
      selectors: '[data-presentation="route"]', conversationId: 'demo-python-learning' },
    { id: 'assistance', title: '提示答疑（组件样例）', component: 'Assistance', previewOnly: true,
      selectors: '[aria-label="提示与答疑"], .demo-qa', conversationId: 'demo-project-practice' },
    { id: 'exam', title: '正式考试', component: 'ExamWidget',
      selectors: '[data-presentation="exam"]', conversationId: 'demo-exam-review' },
    { id: 'reviewActivity', title: '复习与自评', component: 'ReviewActivity',
      selectors: '[data-presentation="review_activity"]', conversationId: 'demo-exam-review' },
    { id: 'update', title: '教材更新决定', component: 'MaterialUpdate',
      selectors: '[aria-label="教材更新提示"], .demo-dialog-body', conversationId: 'demo-python-learning' },
  ],
};

export const galleryGroups = [...artifactCatalog, learningInteractionCatalog];
