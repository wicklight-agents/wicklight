import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import type { TraceEvent } from "../lib/api";
import Timeline from "./Timeline.svelte";

function ev(step: number, type: string, payload: Record<string, unknown>, explain: string): TraceEvent {
  return { v: 1, run_id: "r", step, timestamp: `2026-10-06T12:00:0${step}Z`, type, explain, payload };
}

const events: TraceEvent[] = [
  ev(1, "model_responded", { input_tokens: 10, output_tokens: 2 }, "model answered ok"),
  ev(2, "policy_checked", { decision: "deny" }, "blocked: send_email by email_only_to"),
];

describe("Timeline", () => {
  it("lists every step, then filters to blocks only", async () => {
    render(Timeline, { props: { runId: "r", events } });

    expect(screen.getByText("model answered ok")).toBeInTheDocument();
    expect(screen.getByText(/blocked: send_email/)).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "blocks" }));

    // Only the blocked step remains after filtering.
    expect(screen.queryByText("model answered ok")).not.toBeInTheDocument();
    expect(screen.getByText(/blocked: send_email/)).toBeInTheDocument();
  });

  it("marks the active filter with aria-pressed", async () => {
    render(Timeline, { props: { runId: "r", events } });
    const errorsBtn = screen.getByRole("button", { name: "errors" });
    expect(errorsBtn).toHaveAttribute("aria-pressed", "false");
    await fireEvent.click(errorsBtn);
    expect(errorsBtn).toHaveAttribute("aria-pressed", "true");
  });
});
