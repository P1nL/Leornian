import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { deliveryStatus, TutorPanel } from "./TutorPanel";
import type { Session, Snapshot } from "./api";

describe("教学交付状态", () => {
  it("区分候选、合格草案、课时与学习完成", () => {
    expect(deliveryStatus({ status: "checking", kind: "teaching" })).toContain("尚未正式交付");
    expect(deliveryStatus({ status: "repairing", kind: "lesson" })).toContain("继续推进");
    expect(deliveryStatus({ status: "accepted", kind: "planning" })).toContain("仍需确认");
    expect(deliveryStatus({ status: "accepted", kind: "lesson" })).toContain("不代表学习完成");
  });

  it("未知结果不显示重试或已交付", () => {
    const text = deliveryStatus({ status: "blocked_unknown", kind: "teaching" });
    expect(text).toContain("不会重发");
    expect(text).not.toContain("已通过");
  });

  it("等待用户信息时显示原任务的补充入口和取消屏障", () => {
    const actor = { id: "actor", display_name: "Learner" };
    const session: Session = { actor, token: "offline", expires_at: "2026-11-08T00:00:00Z" };
    const snapshot: Snapshot = {
      actor, cursor: 0, limit: 100, events: [], jobs: [],
      artifacts: [], artifact_jobs: [], tool_activities: [],
      tracks: [], attempts: [], sources: [], reviews: [], lessons: [], choice_results: [],
      remediations: [], node_progress: [], transfers: [], supply_demands: [],
      python_attempts: [], execution_progress: [],
      goals: [{ id: "goal", title: "Python paths", motivation: "", created_at: "2026-11-01T00:00:00Z" }],
      conversations: [{ id: "conversation", goal_id: "goal", created_at: "2026-11-01T00:00:00Z" }],
      turns: [{ conversation_id: "conversation", turns: [{
        id: "turn", user_text: "Explain paths", assistant_text: null,
        purpose: "teaching", context_focus: { kind: "goal" },
        created_at: "2026-11-01T00:00:00Z", completed_at: null,
      }] }],
      runs: [{ id: "run", conversation_id: "conversation", turn_id: "turn", status: "failed",
        cancel_requested: false, error_code: "delivery_needs_input",
        tool_count: 0, can_resume: false, purpose: "teaching",
        created_at: "2026-11-01T00:00:00Z", completed_at: null }],
      plans: [], gates: [], evaluations: [], packs: [],
      delivery_tasks: [{
        id: "task", run_id: "run", kind: "teaching", status: "waiting_input",
        revision: 1, repair_strategy: "diagnostic", cancel_requested: false, can_resume: true,
        required_input: ["你的 Python 基础是什么？"],
        created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
      }],
    };
    const html = renderToStaticMarkup(<TutorPanel session={session} snapshot={snapshot}
      onUpdated={() => undefined} />);
    expect(html).toContain("你的 Python 基础是什么？");
    expect(html).toContain("承接原交付任务");
    expect(html).toContain("取消交付任务");
    expect(html).not.toContain("已通过交付检查并保存");
  });
});
