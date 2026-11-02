import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { GateSummary, PackSummary, PythonAttempt, Remediation, Session, Snapshot, TransferSummary } from "./api";
import { LearningFollowups } from "./LearningFollowups";
import { PythonPractice } from "./PythonPractice";

const session: Session = { token: "fixture", actor: { id: "learner", display_name: "Learner" },
  expires_at: "2030-01-01T00:00:00Z" };
const pack: PackSummary = { automatic: false, id: "pack", plan_id: "plan", plan_revision: 1, node_key: "loops",
  kind: "python_io", revision: 1, predecessor_id: null, status: "published",
  reviewed_roles: [], passed_roles: [], blind_passed: true, item_count: 5,
  created_at: "2026-10-31T00:00:00Z", published_at: "2026-10-31T00:00:00Z" };
const remediation: Remediation = { id: "remediation", pack_id: pack.id, parent_result_id: "result",
  status: "not_passed", transfer_required: true, created_at: pack.created_at };

describe("receipt-backed learning continuation", () => {
  it("distinguishes an unstarted supply need from an assigned successor", () => {
    const snapshot = { packs: [{ ...pack, kind: "choice" }], remediations: [remediation],
      transfers: [], supply_demands: [], evaluations: [], python_attempts: [] } as unknown as Snapshot;
    const html = renderToStaticMarkup(<LearningFollowups session={session} snapshot={snapshot}
      planId="plan" revision={1} disabled={false} onUpdated={() => {}} />);
    expect(html).toContain("缺题时启动供给");
    expect(html).toContain("先尝试从已发布题目选择");
    expect(html).not.toContain("已分配的新情境题");
  });
  it("continues the existing supply beyond three versions without a fresh-chain action", () => {
    const snapshot = { packs: [{ ...pack, kind: "choice" }], remediations: [remediation],
      transfers: [], evaluations: [], python_attempts: [], supply_demands: [{
        id: "need", remediation_id: remediation.id, source_pack_id: pack.id, plan_revision: 1,
        allowed_difficulties: [1, 2], created_at: pack.created_at,
        pack: { ...pack, kind: "choice", revision: 6, status: "changes_required", automatic: true,
          automation_status: "running", automation_action: "repair_output" },
      }] } as unknown as Snapshot;
    const html = renderToStaticMarkup(<LearningFollowups session={session} snapshot={snapshot}
      planId="plan" revision={1} disabled={false} onUpdated={() => {}} />);
    expect(html).toContain("正在修复已知输出问题");
    expect(html).not.toContain("已到三版上限");
    expect(html).not.toContain("追加供给修订版");
    expect(html).not.toContain("缺题时启动供给");
  });
  it("keeps failed code remediation distinct from choice remediation and missing supply", () => {
    const attempt: PythonAttempt = {
      id: "failed-code", pack_id: pack.id, slot: "remediation_1", gate_id: null,
      transfer_id: null, code: "print(0)", status: "not_passed", passed_cases: 1,
      total_cases: 3, feedback: "通过 1/3", created_at: pack.created_at, completed_at: pack.created_at,
    };
    const snapshot = { packs: [pack], remediations: [], python_attempts: [attempt],
      transfers: [], supply_demands: [], evaluations: [] } as unknown as Snapshot;
    const html = renderToStaticMarkup(<LearningFollowups session={session} snapshot={snapshot}
      planId="plan" revision={1} disabled={false} onUpdated={() => {}} />);
    expect(html).toContain("已锁定的代码补救失败");
    expect(html).toContain("五份盲解程序的隔离执行和六审");
    expect(html).toContain("缺题时启动供给");
    expect(html).not.toContain("已选定一个不同情境");
  });
  it("a passed code successor only enables independent Gate preparation, not completion", () => {
    const attempts: PythonAttempt[] = ["practice_1", "practice_2", "remediation_1"].map((slot) => ({
      id: slot, pack_id: pack.id, slot, gate_id: null, transfer_id: null, code: "print(0)",
      status: slot === "practice_2" ? "passed" : "not_passed", passed_cases: 1, total_cases: 3,
      feedback: "Bounded receipt.", created_at: pack.created_at, completed_at: pack.created_at,
    }));
    const transfer: TransferSummary = {
      id: "code-transfer", kind: "python_io", remediation_id: null,
      python_remediation_id: "remediation_1", source_pack_id: pack.id, plan_id: pack.plan_id,
      plan_revision: 1, node_key: pack.node_key, relation_run_id: "run",
      candidate_pack_id: "other-pack", candidate_slot: "practice_1", status: "passed",
      error_code: null, created_at: pack.created_at, opened_at: pack.created_at, completed_at: pack.created_at,
    };
    const html = renderToStaticMarkup(<PythonPractice session={session} pack={pack}
      attempts={attempts} gates={[]} transfers={[transfer]} sourcesCurrent modelReady
      examActive={false} hasActiveRun={false} lessonAvailable onUpdated={() => {}} />);
    expect(html).toMatch(/<button class="text-button">检查执行考核独立性<\/button>/);
    expect(html).toContain("只解除原补救阻断，不替代执行 Gate");
    expect(html).not.toContain("两道执行考核的全部绑定用例通过");
    expect(html).not.toContain("选择不同情境的后继题</button>");
  });
  it("shows queued execution as pending, never as a passed assessment", () => {
    const gate: GateSummary = { id: "gate", pack_id: pack.id, plan_id: pack.plan_id,
      plan_revision: 1, node_key: pack.node_key, lesson_id: "lesson", policy_version: "python-io-gate.v1",
      relation_run_id: "run", status: "submitted", error_code: null, created_at: pack.created_at,
      started_at: pack.created_at, completed_at: null };
    const html = renderToStaticMarkup(<PythonPractice session={session} pack={pack} attempts={[]}
      gates={[gate]} sourcesCurrent modelReady examActive hasActiveRun={false} lessonAvailable
      onUpdated={() => {}} />);
    expect(html).toContain("程序已锁定，等待隔离执行与服务端评分");
    expect(html).not.toContain("两道执行考核的全部绑定用例通过");
    expect(html).not.toContain("检查执行考核独立性</button>");
  });
});
