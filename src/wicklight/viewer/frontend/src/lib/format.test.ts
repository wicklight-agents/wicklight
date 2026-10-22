import { describe, expect, it } from "vitest";
import type { TraceEvent } from "./api";
import { cost, duration, outcomeBadge, totals } from "./format";

function ev(type: string, payload: Record<string, unknown>, ts = "2026-10-06T12:00:00Z"): TraceEvent {
  return { v: 1, run_id: "r", step: 1, timestamp: ts, type, explain: "", payload };
}

describe("totals", () => {
  it("sums tokens and cost across model_responded events", () => {
    const sums = totals([
      ev("model_responded", { input_tokens: 100, output_tokens: 10, cost_usd: 0.002 }),
      ev("model_responded", { input_tokens: 50, output_tokens: 5, cost_usd: 0.001 }),
      ev("tool_executed", { ok: true }),
    ]);
    expect(sums).toEqual({ inputTokens: 150, outputTokens: 15, costUsd: 0.003 });
  });
});

describe("duration", () => {
  it("reports elapsed time between first and last event", () => {
    expect(
      duration([
        ev("run_started", {}, "2026-10-06T12:00:00Z"),
        ev("run_finished", {}, "2026-10-06T12:00:03Z"),
      ]),
    ).toBe("3.0 s");
  });

  it("returns null when there is too little to measure", () => {
    expect(duration([ev("run_started", {})])).toBeNull();
  });
});

describe("cost", () => {
  it("formats small and zero amounts readably", () => {
    expect(cost(0)).toBe("$0");
    expect(cost(0.0005)).toBe("$0.0005");
    expect(cost(1.5)).toBe("$1.50");
  });
});

describe("outcomeBadge", () => {
  it("maps statuses to an icon + label + tone", () => {
    expect(outcomeBadge("completed").tone).toBe("ok");
    expect(outcomeBadge("error").tone).toBe("danger");
    expect(outcomeBadge("limit").label).toBe("limit reached");
    expect(outcomeBadge(null).label).toBe("running");
  });
});
