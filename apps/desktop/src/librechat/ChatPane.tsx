// Adapted from LibreChat f4154b6 pane/ChatPane.tsx and pane/view.ts.
// Copyright (c) 2026 LibreChat. Original license and adaptation scope: NOTICE.md.
import type { ReactNode } from "react";

type ChatPaneColumn = "loading" | "landing" | "messages";
export type ChatPaneView = { isLanding: boolean; column: ChatPaneColumn };

export function getChatPaneView({ hasMessages, isLoading }: {
  hasMessages: boolean; isLoading: boolean;
}): ChatPaneView {
  // Leornian can persist an empty conversation before its first accepted turn.
  // A server conversation id alone must not leave that pane permanently loading.
  const isLanding = !hasMessages;
  return { isLanding, column: isLoading ? "loading" : isLanding ? "landing" : "messages" };
}

type ChatPaneProps = {
  view: ChatPaneView;
  labelledBy: string;
  header: ReactNode;
  messages: ReactNode;
  landing: ReactNode;
  composer: ReactNode;
  footer?: ReactNode;
};

const columns: Record<ChatPaneColumn, (props: ChatPaneProps) => ReactNode> = {
  loading: () => <p className="empty" role="status">正在读取教学对话…</p>,
  landing: ({ landing }) => landing,
  messages: ({ messages }) => messages,
};

export function ChatPane(props: ChatPaneProps) {
  const { view, labelledBy, header, composer, footer } = props;
  return (
    <section className="tutor-workspace tutor-chat" aria-labelledby={labelledBy}>
      <div className="lc-chat-header">{header}</div>
      <div className={`lc-chat-column${view.isLanding ? " lc-chat-landing" : ""}`}>
        <div className="lc-chat-messages">{columns[view.column](props)}</div>
        <div className="lc-composer-band">{composer}</div>
      </div>
      {footer && <div className="lc-chat-context">{footer}</div>}
    </section>
  );
}
