import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { GeneratedLesson, LearningPlan, Session, Source } from "./api";
import { LessonReader } from "./LessonReader";
import { PlanOutline } from "./PlanOutline";

const source: Source = {
  id: "source-1", goal_id: "goal-1", revision: 1, title: "Owned source",
  source_url: "https://owned.invalid/paths", excerpt: "Iterate over paths before moving files.",
  origin: "learner_supplied", admission: "admitted", valid_until: "2030-01-01T00:00:00Z",
  usable: true, created_at: "2026-10-31T00:00:00Z",
};
const material = { source_id: source.id, revision: 1, title: source.title,
  source_url: source.source_url, excerpt: source.excerpt, origin: source.origin,
  valid_until: source.valid_until! };
const revision: LearningPlan["latest"] = {
  id: "revision-1", revision: 1, predecessor_revision: 0, created_at: source.created_at,
  sources: [material], document: {
    title: "Safe directory reader", summary: "Inspect paths first.", assumptions: [],
    nodes: [{ key: "paths", title: "Read paths", objective: "Inspect directory children.",
      estimated_minutes: 20, prerequisite_keys: [], source_refs: [{ source_id: source.id, revision: 1 }] }],
  },
};
const plan: LearningPlan = { id: "plan-1", goal_id: source.goal_id, latest: revision, active: null };
const session: Session = {
  token: "not-a-real-session", actor: { id: "actor-1", display_name: "Learner" },
  expires_at: "2030-01-01T00:00:00Z",
};
const lesson: GeneratedLesson = {
  id: "lesson-1", plan_id: plan.id, plan_revision: 1, node_key: "paths",
  created_at: source.created_at, sources: [material], document: {
    title: "Read paths", introduction: "Look before changing files.",
    sections: [{ heading: "Inspect each child", explanation: "Treat paths as data.",
      code_example: '<script>alert("not executable")</script>',
      source_refs: [{ source_id: source.id, revision: 1 }] }], recall_prompts: ["What if it is empty?"],
  },
};

function outline(current: LearningPlan, sources: Source[] = [source]) {
  return renderToStaticMarkup(<PlanOutline plan={current} session={session} sources={sources}
    lessons={[]} modelReady={false} hasActiveRun={false} busy={false}
    setBusy={() => undefined} onUpdated={() => undefined} />);
}

describe("versioned learning content", () => {
  it("does not show an unconfirmed draft as an available lesson", () => {
    const html = outline(plan);
    expect(html).toContain("新草案 · 等待确认");
    expect(html).toContain("确认使用版本 1");
    expect(html).not.toContain("生成这个节点的课时");
  });

  it("keeps the active route separate and disables generation with no model", () => {
    const html = outline({ ...plan, active: revision, latest: { ...revision, id: "revision-2", revision: 2 } });
    expect(html).toContain("当前确认版本仍为 1");
    expect(html).toContain("计划版本 1");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>生成这个节点的课时/);
  });

  it("renders code as inert text and labels stale citations without claiming completion", () => {
    const html = renderToStaticMarkup(<LessonReader lesson={lesson} sources={[]} />);
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).toContain("引用来源已变化或失效");
    expect(html).toContain("未执行或测试");
    expect(html).toContain("不标记课程完成");
    expect(html).toContain("https://owned.invalid/paths");
  });
});
