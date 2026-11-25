import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ChatPane, getChatPaneView } from "./librechat/ChatPane";
import { App } from "./App";

describe("LibreChat 窗格适配", () => {
  it("已有空会话仍可开始输入，不套用上游 generation 等待规则", () => {
    expect(getChatPaneView({ hasMessages: false, isLoading: false }))
      .toEqual({ isLanding: true, column: "landing" });
    expect(getChatPaneView({ hasMessages: true, isLoading: false }))
      .toEqual({ isLanding: false, column: "messages" });
    expect(getChatPaneView({ hasMessages: false, isLoading: true }).column).toBe("loading");
  });

  it("聊天窗格只摆放宿主槽位，不生成回复、动作或执行入口", () => {
    const html = renderToStaticMarkup(<ChatPane labelledBy="title"
      view={getChatPaneView({ hasMessages: true, isLoading: false })}
      header={<h2 id="title">Tutor</h2>} messages={<p>公开历史 &lt;script&gt;</p>}
      landing={<p>Empty conversation</p>} composer={<form><button>明确发送</button></form>}
      footer={<p>原学习功能</p>} />);
    expect(html).toContain('aria-labelledby="title"');
    expect(html).toContain("公开历史");
    expect(html).not.toContain("Empty conversation");
    expect(html.indexOf("公开历史")).toBeLessThan(html.indexOf("明确发送"));
    expect(html.indexOf("明确发送")).toBeLessThan(html.indexOf("原学习功能"));
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("重生成");
  });

  it("独立入口保留原学习空间，默认入口不自动切换", () => {
    const legacy = renderToStaticMarkup(<App />);
    const chat = renderToStaticMarkup(<App tutorPresentation="chat" />);
    expect(legacy).not.toContain("返回原学习空间");
    expect(chat).toContain('href="/"');
    expect(chat).toContain("返回原学习空间");
    expect(chat).toContain("进入本地学习空间");
  });
});
