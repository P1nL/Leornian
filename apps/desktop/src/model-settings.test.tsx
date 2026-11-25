import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { initialProfile, modelTestMetrics, ModelSettingsPanel } from "./ModelSettingsPanel";

describe("用户模型配置", () => {
  it("不会默认启用模型、授权外发或虚构通道容量", () => {
    const profile = initialProfile("personal-connection");
    expect(profile.connection_id).toBe("personal-connection");
    expect(profile.enabled).toBe(false);
    expect(profile.allow_private_material).toBe(false);
    expect(profile.context_tokens).toBe(0);
    expect(profile.max_output_tokens).toBe(0);
    expect(profile.roles).toContain("delivery_review.v1");
    expect(profile.roles).toContain("material_review.v1");
    expect(new Set(profile.roles).size).toBe(profile.roles.length);
  });

  it("模型设置入口独立于目标，默认折叠且不回显任何凭据", () => {
    const html = renderToStaticMarkup(<ModelSettingsPanel session={{
      token: "test-local-session", actor: { id: "actor", display_name: "Learner" },
      expires_at: "2026-11-09T00:00:00Z",
    }} onUpdated={() => undefined} />);
    expect(html).toContain("配置我的模型");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("代码仍只在本机隔离环境执行");
    expect(html).not.toContain('type="password"');
    expect(html).not.toContain("test-local-session");
  });

  it("测试摘要只展示实际报告的数字，不把缺少用量当成零调用", () => {
    expect(modelTestMetrics({ elapsed_seconds: 1.234, usage: { total_tokens: 12 } }))
      .toBe("派发至回执 1.23 秒 · 总 Token 12");
    expect(modelTestMetrics(null)).toBe("用量与耗时未报告");
    expect(modelTestMetrics({ usage: { unexpected: "private-value" } }))
      .toBe("用量与耗时未报告");
  });
});
