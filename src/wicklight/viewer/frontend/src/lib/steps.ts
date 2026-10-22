// Group a flat event list into per-step rows with a plain-words summary and
// the safety flags that drive the timeline's badges and filters. This is pure
// logic with no DOM, so it is unit-tested and reusable by the game's replay
// viewer (DTN-251).

import type { TraceEvent } from "./api";

export type StepFlag =
  | "blocked"
  | "approved"
  | "waived"
  | "error"
  | "retry"
  | "limit"
  | "dry_run"
  | "sensitive";

export interface Step {
  step: number;
  events: TraceEvent[];
  summary: string;
  flags: StepFlag[];
}

// The event whose `explain` best describes a step, most salient first.
const SUMMARY_PRIORITY = [
  "limit_hit",
  "policy_checked",
  "error",
  "approval_resolved",
  "tool_executed",
  "tool_proposed",
  "model_responded",
  "model_routed",
  "run_finished",
  "context_built",
  "run_started",
];

function payloadBool(event: TraceEvent, key: string): boolean {
  return event.payload[key] === true;
}

function payloadStr(event: TraceEvent, key: string): string | null {
  const value = event.payload[key];
  return typeof value === "string" ? value : null;
}

export function stepFlags(events: TraceEvent[]): StepFlag[] {
  const flags = new Set<StepFlag>();
  for (const event of events) {
    switch (event.type) {
      case "policy_checked":
        if (payloadStr(event, "decision") === "deny") flags.add("blocked");
        break;
      case "approval_resolved":
        if (payloadBool(event, "waived")) flags.add("waived");
        else if (payloadBool(event, "approved")) flags.add("approved");
        break;
      case "limit_hit":
        flags.add("limit");
        break;
      case "error":
        if (payloadBool(event, "recoverable")) flags.add("retry");
        else flags.add("error");
        break;
      case "tool_executed":
        if (payloadBool(event, "dry_run")) flags.add("dry_run");
        if (payloadBool(event, "sensitive")) flags.add("sensitive");
        break;
      case "model_routed": {
        const excluded = event.payload["excluded"];
        if (Array.isArray(excluded) && excluded.length > 0) flags.add("sensitive");
        break;
      }
      default:
        break;
    }
  }
  return [...flags];
}

export function stepSummary(events: TraceEvent[]): string {
  for (const type of SUMMARY_PRIORITY) {
    const match = events.find((event) => event.type === type);
    if (match) return match.explain;
  }
  return events[0]?.explain ?? "";
}

export function groupSteps(events: TraceEvent[]): Step[] {
  const byStep = new Map<number, TraceEvent[]>();
  for (const event of events) {
    const bucket = byStep.get(event.step);
    if (bucket) bucket.push(event);
    else byStep.set(event.step, [event]);
  }
  return [...byStep.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([step, stepEvents]) => ({
      step,
      events: stepEvents,
      summary: stepSummary(stepEvents),
      flags: stepFlags(stepEvents),
    }));
}

export type StepFilter = "all" | "blocks" | "approvals" | "errors";

export function matchesFilter(step: Step, filter: StepFilter): boolean {
  switch (filter) {
    case "blocks":
      return step.flags.includes("blocked");
    case "approvals":
      return step.flags.includes("approved") || step.flags.includes("waived");
    case "errors":
      return step.flags.includes("error") || step.flags.includes("retry");
    case "all":
    default:
      return true;
  }
}
