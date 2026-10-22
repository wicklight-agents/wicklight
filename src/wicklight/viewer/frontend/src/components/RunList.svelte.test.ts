import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import type { RunSummary } from "../lib/api";
import RunList from "./RunList.svelte";

function run(partial: Partial<RunSummary>): RunSummary {
  return {
    run_id: "r",
    agent: "agentA",
    status: "completed",
    steps: 3,
    cost_usd: 0,
    models: [],
    blocks: 0,
    approvals: 0,
    started_at: null,
    dry_run: false,
    counterfactual: false,
    ...partial,
  };
}

describe("RunList", () => {
  it("renders a row per run and selects on click (keyboard-accessible button)", async () => {
    const onSelect = vi.fn();
    render(RunList, {
      props: {
        runs: [run({ run_id: "a", agent: "agentA" }), run({ run_id: "b", agent: "agentB" })],
        onSelect,
      },
    });

    const rows = screen.getAllByRole("button");
    expect(rows).toHaveLength(2);

    await fireEvent.click(screen.getByRole("button", { name: /agentA/ }));
    expect(onSelect).toHaveBeenCalledWith("a");
  });
});
