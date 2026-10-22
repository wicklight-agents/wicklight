import { describe, expect, it } from "vitest";
import type { TraceEvent } from "./api";
import { groupSteps, matchesFilter, stepFlags, stepSummary } from "./steps";

function ev(step: number, type: string, payload: Record<string, unknown> = {}): TraceEvent {
  return {
    v: 1,
    run_id: "r",
    step,
    timestamp: `2026-10-06T12:00:0${step}Z`,
    type,
    explain: `${type} at ${step}`,
    payload,
  };
}

describe("groupSteps", () => {
  it("groups events by step in ascending order", () => {
    const steps = groupSteps([
      ev(2, "tool_proposed"),
      ev(0, "run_started"),
      ev(2, "tool_executed"),
      ev(1, "model_called"),
    ]);
    expect(steps.map((s) => s.step)).toEqual([0, 1, 2]);
    expect(steps[2].events).toHaveLength(2);
  });
});

describe("stepFlags", () => {
  it("flags a policy denial as blocked", () => {
    expect(stepFlags([ev(1, "policy_checked", { decision: "deny" })])).toContain("blocked");
  });

  it("distinguishes approved, waived, retry, error, limit, sensitive, dry run", () => {
    expect(stepFlags([ev(1, "approval_resolved", { approved: true })])).toContain("approved");
    expect(stepFlags([ev(1, "approval_resolved", { waived: true })])).toContain("waived");
    expect(stepFlags([ev(1, "error", { recoverable: true })])).toContain("retry");
    expect(stepFlags([ev(1, "error", { recoverable: false })])).toContain("error");
    expect(stepFlags([ev(1, "limit_hit", {})])).toContain("limit");
    expect(stepFlags([ev(1, "tool_executed", { sensitive: true, ok: true })])).toContain(
      "sensitive",
    );
    expect(stepFlags([ev(1, "tool_executed", { dry_run: true, ok: true })])).toContain(
      "dry_run",
    );
    expect(stepFlags([ev(1, "model_routed", { excluded: ["hosted/x"] })])).toContain(
      "sensitive",
    );
  });

  it("does not flag an allowed policy check", () => {
    expect(stepFlags([ev(1, "policy_checked", { decision: "allow" })])).not.toContain(
      "blocked",
    );
  });
});

describe("stepSummary", () => {
  it("prefers the most salient event's explain", () => {
    const summary = stepSummary([
      ev(3, "tool_proposed", { tool: "send_email" }),
      ev(3, "policy_checked", { decision: "deny" }),
    ]);
    expect(summary).toBe("policy_checked at 3");
  });
});

describe("matchesFilter", () => {
  const blocked = groupSteps([ev(1, "policy_checked", { decision: "deny" })])[0];
  const approved = groupSteps([ev(1, "approval_resolved", { approved: true })])[0];

  it("filters by category", () => {
    expect(matchesFilter(blocked, "all")).toBe(true);
    expect(matchesFilter(blocked, "blocks")).toBe(true);
    expect(matchesFilter(blocked, "approvals")).toBe(false);
    expect(matchesFilter(approved, "approvals")).toBe(true);
  });
});
