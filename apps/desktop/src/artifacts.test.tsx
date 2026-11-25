import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ArtifactDocumentView, ArtifactPanel } from "./ArtifactPanel";
import { deliveryStatus } from "./TutorPanel";
import type { ArtifactView, Session, Snapshot } from "./api";

describe("教学工件", () => {
  it("按文本展示脚本与代码，不执行模型生成内容", () => {
    const artifact: ArtifactView = {
      id: "artifact", goal_id: "goal", revision: 2, title: "循环笔记", focus: { kind: "goal" },
      created_at: "2026-11-02T00:00:00Z",
      document: { title: "循环笔记", sections: [{
        heading: "例子", text: "<script>alert('x')</script>",
        code: "<img src=x onerror=alert(1)>", language: "html", source_refs: [],
      }] },
    };
    const html = renderToStaticMarkup(<ArtifactDocumentView artifact={artifact} />);
    expect(html).toContain("第 2 版");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain("代码仅展示，未执行");
    expect(html).toContain("不代表学习通过");
  });

  it("空范围和排队任务不显示成已交付，并兼容服务端 null 绑定", () => {
    const actor = { id: "actor", display_name: "Learner" };
    const session: Session = { actor, token: "offline", expires_at: "2026-11-08T00:00:00Z" };
    const conversation = {
      id: "conversation", goal_id: "goal", created_at: "2026-11-02T00:00:00Z",
      studied_nodes: [], hidden_from_recents: false,
    };
    const snapshot: Snapshot = {
      actor, goals: [], jobs: [], events: [], cursor: 0, limit: 100,
      conversations: [], turns: [], runs: [], tracks: [], attempts: [], sources: [], reviews: [],
      teaching_sessions: [], teaching_branches: [],
      plans: [], lessons: [], packs: [], choice_results: [], remediations: [], gates: [],
      node_progress: [], transfers: [], supply_demands: [], evaluations: [], python_attempts: [],
      program_attempts: [],
      execution_progress: [], delivery_tasks: [], tool_activities: [], learning_artifacts: [],
      artifacts: [{
        id: "artifact", goal_id: "goal", revision: 1, title: "已检查的笔记",
        focus: { kind: "goal", plan_id: null, node_key: null },
        created_at: conversation.created_at,
      }],
      artifact_jobs: [{
        id: "job", conversation_id: "conversation", artifact_id: "pending",
        expected_revision: 0, instruction: "整理循环", status: "queued", run_id: null,
        created_at: conversation.created_at,
      }],
    };
    const html = renderToStaticMarkup(<ArtifactPanel session={session} snapshot={snapshot}
      conversation={conversation} focus={{ kind: "goal" }} disabled={false} onUpdated={() => undefined} />);
    expect(html).toContain("打开 已检查的笔记");
    expect(html).toContain("等待当前对话结束后生成");
    expect(html).toContain("取消工件任务");
    expect(html).not.toContain("重试生成");
    expect(deliveryStatus({ status: "accepted", kind: "artifact" })).toContain("代码未执行");
  });
});
