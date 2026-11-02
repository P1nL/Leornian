import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { GateSummary, GeneratedLesson, LearningPlan, PackSummary, Remediation, Session, Source, TransferSummary } from "./api";
import { LessonReader } from "./LessonReader";
import { PlanOutline } from "./PlanOutline";
import { PackPractice } from "./PackPractice";
import { ConceptGatePanel } from "./ConceptGatePanel";
import { TransferPanel } from "./TransferPanel";
import { displayedPack, supplyStatus } from "./supply-view";

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

  it("shows review coverage without exposing unpublished candidate questions", () => {
    const pack: PackSummary = { automatic: false, kind: "choice", id: "pack-1", plan_id: plan.id, plan_revision: 1,
      node_key: "paths", revision: 1, predecessor_id: null, status: "reviewing",
      reviewed_roles: ["technical"], passed_roles: [], blind_passed: true,
      item_count: 5, created_at: source.created_at, published_at: null,
      pending_role: "ambiguity", pending_run_id: "run-2" };
    const html = renderToStaticMarkup(<PackPractice planId={plan.id} revision={1} nodeKey="paths"
      session={session} packs={[pack]} results={[]} sourcesCurrent={true} modelReady={true}
      hasActiveRun={true} onUpdated={() => undefined} />);
    expect(html).toContain("已收到 1/6 角色审核");
    expect(html).toContain("盲解一致");
    expect(html).toContain("保留考核需通过曝光关系检查后明确开启");
    expect(html).not.toContain("打开两道练习");
    expect(html).not.toContain("确认发布到我的学习空间");
  });

  it("does not open published practice from stale source material", () => {
    const pack: PackSummary = { automatic: false, kind: "choice", id: "pack-1", plan_id: plan.id, plan_revision: 1,
      node_key: "paths", revision: 1, predecessor_id: null, status: "published",
      reviewed_roles: [], passed_roles: [], blind_passed: true,
      item_count: 5, created_at: source.created_at, published_at: source.created_at };
    const html = renderToStaticMarkup(<PackPractice planId={plan.id} revision={1} nodeKey="paths"
      session={session} packs={[pack]} results={[]} sourcesCurrent={false} modelReady={true}
      hasActiveRun={false} onUpdated={() => undefined} />);
    expect(html).toContain("来源失效时，不再生成、发布或打开题目");
    expect(html).not.toContain("打开两道练习");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>自动准备题包/);
  });

  it("keeps ready Gate items hidden until the explicit server start", () => {
    const gate: GateSummary = { id: "gate-1", pack_id: "pack-1", plan_id: plan.id,
      plan_revision: 1, node_key: "paths", lesson_id: "lesson-1", policy_version: "concept-gate.v1",
      relation_run_id: "run-3", status: "ready", error_code: null, created_at: source.created_at,
      started_at: null, completed_at: null };
    const html = renderToStaticMarkup(<ConceptGatePanel session={session} packId="pack-1"
      revision={1} gates={[gate]} eligible={true} modelReady={true} hasActiveRun={false}
      examActive={false} sourcesCurrent={true} onUpdated={() => undefined} />);
    expect(html).toContain("独立性检查通过，可以开始");
    expect(html).toContain("不代表代码执行能力");
    expect(html).not.toContain('type="radio"');
    expect(html).not.toContain("一起提交两道考核");
  });

  it("does not ask the learner to publish or repair an automatic pack", () => {
    const pack: PackSummary = { kind: "choice", id: "pack-auto", plan_id: plan.id,
      plan_revision: 1, node_key: "paths", revision: 2, predecessor_id: "pack-old",
      automatic: true, status: "ready", reviewed_roles: ["technical"],
      passed_roles: ["technical"], blind_passed: true, item_count: 5,
      created_at: source.created_at, published_at: null };
    const render = (item: PackSummary) => renderToStaticMarkup(<PackPractice planId={plan.id}
      revision={1} nodeKey="paths" session={session} packs={[item]} results={[]}
      sourcesCurrent modelReady hasActiveRun={false} onUpdated={() => undefined} />);
    expect(render(pack)).toContain("系统正在自动发布");
    expect(render(pack)).not.toContain("确认发布到我的学习空间");
    expect(render({ ...pack, status: "failed", pending_role: "technical" }))
      .not.toContain("尝试补正超长审核格式");
    const continuing = render({ ...pack, revision: 8, status: "changes_required",
      automation_status: "running", automation_action: "repair_output" });
    expect(continuing).toContain("正在修复已知输出问题");
    expect(continuing).not.toContain("已到修订上限");
    expect(continuing).not.toContain("生成修订版");
    const waiting = render({ ...pack, automation_status: "waiting",
      automation_reason: "source_not_current" });
    expect(waiting).toContain("等待更新有效来源");
    expect(waiting).not.toContain("系统正在自动发布");
  });

  it("does not offer an original-question retake after a started cancellation", () => {
    const gate: GateSummary = { id: "gate-1", pack_id: "pack-1", plan_id: plan.id,
      plan_revision: 1, node_key: "paths", lesson_id: "lesson-1", policy_version: "concept-gate.v1",
      relation_run_id: "run-3", status: "cancelled", error_code: null, created_at: source.created_at,
      started_at: source.created_at, completed_at: source.created_at };
    const html = renderToStaticMarkup(<ConceptGatePanel session={session} packId="pack-1"
      revision={1} gates={[gate]} eligible={true} modelReady={true} hasActiveRun={false}
      examActive={false} sourcesCurrent={true} onUpdated={() => undefined} />);
    expect(html).toContain("不能原题重考");
    expect(html).not.toContain(">准备概念 Gate</button>");
  });

  it("links a failed independence report to a real revision rather than a new root", () => {
    const pack: PackSummary = { automatic: false, kind: "choice", id: "pack-1", plan_id: plan.id, plan_revision: 1,
      node_key: "paths", revision: 1, predecessor_id: null, status: "published",
      reviewed_roles: [], passed_roles: [], blind_passed: true,
      item_count: 5, created_at: source.created_at, published_at: source.created_at };
    const gate: GateSummary = { id: "gate-1", pack_id: pack.id, plan_id: plan.id,
      plan_revision: 1, node_key: "paths", lesson_id: "lesson-1", policy_version: "concept-gate.v1",
      relation_run_id: "run-3", status: "blocked", error_code: "assessment_not_independent",
      created_at: source.created_at, started_at: null, completed_at: source.created_at };
    const render = (revision: number) => renderToStaticMarkup(<PackPractice planId={plan.id}
      revision={1} nodeKey="paths" session={session} packs={[{ ...pack, revision }]} gates={[gate]}
      results={[]} sourcesCurrent={true} modelReady={true} hasActiveRun={false}
      onUpdated={() => undefined} />);
    const first = render(1);
    expect(first).toContain("将失败关系和原教学上下文交给作者");
    expect(first).toContain("生成修订版");
    expect(first).not.toContain(">生成新题包</button>");
    const later = render(7);
    expect(later).toContain("生成修订版");
    expect(later).not.toContain("三版上限");
  });

  it("keeps an explicitly selected ancestor while default mode follows the current head", () => {
    const old: PackSummary = { automatic: true, kind: "choice", id: "old", plan_id: plan.id,
      plan_revision: 1, node_key: "paths", revision: 3, predecessor_id: null,
      status: "changes_required", reviewed_roles: [], passed_roles: [], blind_passed: true,
      item_count: 5, created_at: source.created_at, published_at: null };
    const current = { ...old, id: "current", predecessor_id: old.id, revision: 4 };
    expect(displayedPack([current, old], old.id, false)?.id).toBe(old.id);
    expect(displayedPack([current, old], old.id, true)?.id).toBe(current.id);
    expect(displayedPack([current, old], "", true)?.id).toBe(current.id);
  });

  it("does not mislabel dependency waits or unresolved calls as completion", () => {
    const pack = { automation_status: "waiting", automation_reason: "external_result_unknown" } as PackSummary;
    expect(supplyStatus(pack)).toContain("不重复发送");
    expect(supplyStatus(pack)).not.toContain("已完成");
    expect(supplyStatus({ ...pack, automation_reason: "unauthorized" })).toContain("等待更新当前会话");
    expect(supplyStatus({ ...pack, automation_status: "cancelled" })).toContain("已取消");
  });

  it("keeps a selected transfer private until explicitly opened and prevents original-question retries", () => {
    const remediation: Remediation = { id: "remediation-1", pack_id: "pack-old",
      parent_result_id: "result-1", status: "not_passed", transfer_required: true,
      created_at: source.created_at };
    const transfer: TransferSummary = { id: "transfer-1", remediation_id: remediation.id,
      kind: "choice", python_remediation_id: null,
      source_pack_id: remediation.pack_id, plan_id: plan.id, plan_revision: 1, node_key: "paths",
      relation_run_id: "run-transfer", candidate_pack_id: "pack-new", candidate_slot: "practice_1",
      status: "ready", error_code: null, created_at: source.created_at,
      opened_at: null, completed_at: null };
    const render = (item: TransferSummary) => renderToStaticMarkup(<TransferPanel
      session={session} remediation={remediation} revision={1} transfers={[item]}
      modelReady={true} hasActiveRun={false} examActive={false} sourcesCurrent={true}
      onUpdated={() => undefined} />);
    const ready = render(transfer);
    expect(ready).toContain("已选定一个不同情境的后继");
    expect(ready).not.toContain('type="radio"');
    expect(ready).not.toContain("提交这道新情境检查");
    const failed = render({ ...transfer, status: "not_passed", opened_at: source.created_at });
    expect(failed).toContain("不原题重试，也不自动再抽一道题");
    expect(failed).not.toContain(">选择不同情境的后继题</button>");
  });
});
