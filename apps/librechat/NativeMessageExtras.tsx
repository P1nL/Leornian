import { NativeArtifacts, useNative } from './NativeLearning';
import { Notice } from './LearningUI';
import { nativeReplyOutcome } from './native-reply-outcome.mjs';

type ReplyOutcome = {
  status: string;
  message: string;
  requiredInput?: string[];
  errorCode?: string;
};

export default function NativeMessageExtras({ message }: {
  message?: {
    messageId?: string;
    isCreatedByUser?: boolean;
    leornianOutcome?: ReplyOutcome;
  };
}) {
  const state = useNative();
  if (!message || message.isCreatedByUser) return null;
  const turnId = message.messageId?.endsWith(':assistant')
    ? message.messageId.slice(0, -':assistant'.length) : '';
  const turn = state.snapshot?.turns.flatMap((page) => page.turns).find((item) => item.id === turnId);
  const outcome: ReplyOutcome | null | undefined = turn
    ? nativeReplyOutcome(state.snapshot, turn) : message.leornianOutcome;
  return <div className="learning-demo" data-learning-demo data-node-reply={turnId || undefined}>
    {outcome && <div data-reply-outcome={outcome.status}>
      <Notice>{outcome.message}</Notice>
      {outcome.requiredInput?.length ? <ul>
        {outcome.requiredInput.map((text, index) => <li key={index}>{text}</li>)}
      </ul> : null}
      {outcome.errorCode && <p className="demo-muted">任务代码：{outcome.errorCode}</p>}
    </div>}
    <NativeArtifacts messageId={message.messageId} />
  </div>;
}
