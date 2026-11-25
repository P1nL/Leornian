import { createContext, useContext, useRef } from 'react';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { appMessagePartsHost, MessagePartsHostProvider } from '~/Providers/MessagePartsHostContext';
import NativeThinking from './NativeThinking';
import type { ThinkingStep } from './NativeThinking';
import NativeMessageExtras from './NativeMessageExtras';

const ReplyContext = createContext({
  messageId: '', conversationId: '', isSubmitting: false, isLatestMessage: true,
});
function useReplyMessage() { return useContext(ReplyContext); }

export default function NativeReplyParts({ turnId, conversationId, actorId, replyId, steps = [], reasoning, text, generating, status }: {
  turnId: string; conversationId: string; actorId?: string; steps?: ThinkingStep[];
  replyId?: string;
  reasoning: string; text: string; generating: boolean; status?: string;
}) {
  const host = useRef({ ...appMessagePartsHost, useMessage: useReplyMessage }).current;
  return <ReplyContext.Provider value={{
    messageId: replyId ?? `${turnId}:assistant`, conversationId, isSubmitting: generating, isLatestMessage: true,
  }}>
    <MessagePartsHostProvider host={host}>
      {steps.length || reasoning ? <NativeThinking scopeKey={`${actorId ?? conversationId}:${replyId?.includes(':stage:') ? replyId : turnId}`}
        steps={steps} reasoning={reasoning} generating={generating} />
        : generating && !text && <p role="status" className="text-sm text-text-secondary">
          {status ?? '正在等待模型返回可展示的思考文本…'}
        </p>}
      {text && <Markdown content={text} isLatestMessage />}
      {!generating && <NativeMessageExtras message={{
        messageId: replyId ?? `${turnId}:assistant`, isCreatedByUser: false,
      }} />}
    </MessagePartsHostProvider>
  </ReplyContext.Provider>;
}
