import { removeSilentAudio } from './app-overlay.mjs';

const imported = 'virtual:leornian-native-learning';
export const nativeImports = { [imported]: 'NativeLearning.tsx',
  'virtual:leornian-native-message-extras': 'NativeMessageExtras.tsx',
  'virtual:leornian-native-chat-actions': 'NativeChatActions.ts' };
export const nativeFiles = [
  'NativeMessageExtras.tsx', 'native-reply-outcome.mjs',
  'NativeTavilySettings.tsx', 'NativePlanAction.tsx',
  'NativeModelProviders.tsx', 'NativeModelCustom.tsx', 'CCSProviderPresetSelector.tsx', 'CCSApiKeyInput.tsx', 'CCSModelPicker.tsx', 'ccs-models.css',
  'NativeLearning.tsx', 'NativeChatActions.ts', 'NativeModels.tsx', 'NativeMaterialUpdates.tsx', 'native-models.css', 'native-client.mjs', 'native-intake.mjs', 'LearningCompositionV2.tsx',
  'NativePractice.tsx', 'NativeProgramPractice.tsx', 'NativeExampleRun.tsx', 'NativeAssistance.tsx', 'NativeDemo.tsx', 'NativeTeaching.tsx', 'NativeReplyParts.tsx', 'NativeThinking.tsx', 'NativeReviewReport.tsx', 'native-practice.ts',
  'NativeCourse.tsx', 'NativeRouteConfirmation.tsx', 'learning-routes.mjs', 'NativeAssessment.tsx', 'NativeRecovery.tsx', 'NativeGoalMaterialScope.tsx', 'NativeReviews.tsx', 'NativeLearningEvidence.tsx',
  'NativeMaterialIntake.tsx', 'NativeMaterialSources.tsx', 'native-material-upload.mjs', 'NativeExecution.tsx',
  'composition-v2-runtime.mjs', 'composition-v2-validator.generated.mjs', 'composition-directory.generated.json', 'composition-v2.css',
  'LearningUI.tsx', 'LearningChrome.tsx', 'LearningSourceReader.tsx', 'LearningComponents.tsx', 'LearningVisuals.tsx', 'PracticeWorkbench.tsx',
  'InlineCodeEditor.tsx', 'PhosphorIcons.tsx', 'AlgorithmVisuals.tsx', 'algorithm-demos.mjs',
  'learning-demo.css', 'learning-motion.css', 'learning-visuals.css', 'algorithm-visuals.css', 'component-utils.mjs',
];
export const nativeOverlayPaths = [
  'src/App.jsx', 'src/Providers/ChatContext.tsx',
  'src/data-provider/mutations.ts', 'src/components/Conversations/ConvoOptions/DeleteButton.tsx',
  'src/components/Chat/ChatView.tsx', 'src/components/Chat/Messages/Content/MessageContent.tsx',
  'src/components/Chat/Header.tsx', 'src/components/SidePanel/SidePanelGroup.tsx', 'src/components/Auth/Login.tsx',
  'src/components/Chat/Messages/Thread/List.tsx', 'src/components/Chat/Messages/MessagesView.tsx',
  'src/components/Chat/Messages/Content/Part.tsx',
  'src/components/Messages/ContentRender.tsx',
];
const once = (source, before, after) => {
  if (source.split(before).length !== 2) throw new Error('Pinned native frontend insertion point changed.');
  return source.replace(before, after);
};
export function overlayNativeSource(path, source) {
  source = source.replaceAll('\r\n', '\n');
  if (path === 'src/App.jsx') return removeSilentAudio(source);
  if (path === 'src/data-provider/mutations.ts') return once(
    `import { deleteNativeConversation } from 'virtual:leornian-native-chat-actions';\n${source}`,
    'dataService.deleteConversation(payload) as Promise<t.TDeleteConversationResponse>',
    'deleteNativeConversation(payload) as Promise<t.TDeleteConversationResponse>',
  );
  if (path === 'src/components/Conversations/ConvoOptions/DeleteButton.tsx') {
    let next = once(source, '    onError: () => {', '    onError: (error) => {');
    next = once(next, "message: localize('com_ui_convo_delete_error'),",
      "message: error instanceof Error ? error.message : localize('com_ui_convo_delete_error'),");
    return once(next, 'i18nKey="com_ui_delete_confirm_strong"',
      `i18nKey="com_leornian_delete_recent_confirm"
          defaults="<strong>{{title}}</strong> will be removed from Recent. Your learning plan, history and background requests are retained."`);
  }
  if (path === 'src/Providers/ChatContext.tsx') return once(source,
    "export { ChatContext, useChatContext } from '@librechat/chat/react';",
    `import { useChatContext as useUpstreamChatContext } from '@librechat/chat/react';
import { useNativeChatActions } from 'virtual:leornian-native-chat-actions';
export { ChatContext } from '@librechat/chat/react';
export function useChatContext() { return useNativeChatActions(useUpstreamChatContext()); }`);
  if (path === 'src/components/Chat/Messages/MessagesView.tsx') {
    let next = `import { NativeThreadTail } from '${imported}';\n` + once(source, "import { FLAT_THREAD, ThreadList } from './Thread';", "import { ThreadList } from './Thread';");
    next = once(next, 'useThreadRows(FLAT_THREAD ? messages : null,', 'useThreadRows(messages,');
    next = once(next, 'if (FLAT_THREAD && threadRows)', 'if (threadRows)');
    return once(next, 'renderThread={(props) => <Thread {...props} />}',
      'renderThread={(props) => <><Thread {...props} /><NativeThreadTail conversationId={props.conversationId} /></>}');
  }
  if (path === 'src/components/Chat/Messages/Thread/List.tsx') {
    let next = `import { NativeTeachingRows } from '${imported}';\n${source}`;
    next = once(next, '    <>', '    <NativeTeachingRows rows={rows} renderRows={(items) => <>');
    next = once(next, '{rows.map((row) =>', '{items.map((row) =>');
    return once(next, '    </>', '    </>} />');
  }
  if (path === 'src/components/Chat/Messages/Content/Part.tsx') {
    return once(`import { NativeThinking } from '${imported}';\n${source}`,
      "      const reasoning = typeof part.think === 'string' ? part.think : part.think?.value;",
      `      const reasoning = typeof part.think === 'string' ? part.think : part.think?.value;
      const native = part as typeof part & {
        leornian_steps?: import('@leornian/api-contracts').components['schemas']['ThinkingStep'][];
        leornian_key?: string;
      };
      if (native.leornian_key && Array.isArray(native.leornian_steps)) {
        return <NativeThinking scopeKey={native.leornian_key}
          steps={native.leornian_steps} reasoning={reasoning ?? ''} />;
      }`);
  }
  if (path === 'src/components/Auth/Login.tsx') {
    if (!source.includes('function Login()')) throw new Error('Pinned login changed.');
    return `export { NativeLogin as default } from '${imported}';`;
  }
  if (path === 'src/components/Chat/ChatView.tsx') {
    let next = `import { NativeSync, NativeStart, NativeComposer, useNativePaneView, NativeConversationContent } from '${imported}';\n${source}`;
    next = once(next, `const view = getChatPaneView({
    conversationId,
    isLoading,
    hasMessages: messagesTree != null && messagesTree.length > 0,
  });`, `const view = useNativePaneView(getChatPaneView({
    conversationId,
    isLoading,
    hasMessages: messagesTree != null && messagesTree.length > 0,
  }), conversationId, isLoading);`);
    next = once(next, '<TraceSurface conversationId={conversationId}>', '<NativeSync /><TraceSurface conversationId={conversationId}>');
    next = once(next, 'messages={<MessagesView messagesTree={messagesTree} messages={messages} />}',
      'messages={<NativeConversationContent conversationId={conversationId}><MessagesView messagesTree={messagesTree} messages={messages} /></NativeConversationContent>}');
    next = once(next, 'landing={<Landing centerFormOnLanding={centerFormOnLanding} />}', 'landing={<NativeStart />}');
    const pattern = /<ChatForm\n[\s\S]*?\/>/g;
    if ([...next.matchAll(pattern)].length !== 1) throw new Error('Pinned composer changed.');
    return next.replace(pattern, '<NativeComposer conversationId={conversationId} />');
  }
  if (path === 'src/components/Chat/Messages/Content/MessageContent.tsx') return once(
    `import NativeMessageExtras from 'virtual:leornian-native-message-extras';\n${source}`, '      </CollapsibleText>',
    '        <NativeMessageExtras message={message} />\n      </CollapsibleText>',
  );
  if (path === 'src/components/Messages/ContentRender.tsx') return once(
    `import NativeMessageExtras from 'virtual:leornian-native-message-extras';\n${source}`,
    '      </AuthorContext.Provider>',
    '      </AuthorContext.Provider>\n      {!edit && <NativeMessageExtras message={msg} />}',
  );
  if (path === 'src/components/SidePanel/SidePanelGroup.tsx') return once(
    `import { NativeSourcePanel } from '${imported}';\n${source}`, 'export default SidePanelGroup;',
    'export default function LeornianSidePanel(props: SidePanelProps) { return <NativeSourcePanel {...props} NativeGroup={SidePanelGroup} />; }',
  );
  if (path === 'src/components/Chat/Header.tsx') {
    let next = `import { NativeTasks, NativeLearningMenu } from '${imported}';\n${source}`;
    next = once(next, '{!readOnly && <ModelSelector startupConfig={startupConfig} />}',
      '<span className="truncate text-sm font-medium" aria-label="当前学习">{isNewChat ? "开始学习" : conversation?.title ?? "当前学习"}</span>');
    next = once(next, '<BackgroundTasksButton', '<NativeTasks');
    next = once(next, '<HeaderMenu', '<NativeLearningMenu');
    return once(next, '<ExportAndShareMenu', '<NativeLearningMenu');
  }
  return null;
}
