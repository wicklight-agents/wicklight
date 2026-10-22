<script lang="ts">
  import type { RunSummary } from "../lib/api";
  import { cost, outcomeBadge } from "../lib/format";
  import Badge from "./Badge.svelte";

  let {
    runs,
    onSelect,
  }: { runs: RunSummary[]; onSelect: (runId: string) => void } = $props();

  function when(iso: string | null): string {
    if (!iso) return "—";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
  }
</script>

<div class="run-list">
  <div class="run-list-head" aria-hidden="true">
    <span>time</span>
    <span>agent</span>
    <span>outcome</span>
    <span class="num">steps</span>
    <span class="num">cost</span>
    <span class="num">blocks</span>
    <span class="num">approvals</span>
  </div>
  <ul>
    {#each runs as run (run.run_id)}
      <li>
        <button class="run-list-row" onclick={() => onSelect(run.run_id)}>
          <span class="muted">{when(run.started_at)}</span>
          <span class="agent">
            {run.agent ?? run.run_id}
            {#if run.dry_run}<Badge badge={{ label: "dry run", icon: "◌", tone: "info" }} />{/if}
            {#if run.counterfactual}
              <Badge badge={{ label: "counterfactual", icon: "⎇", tone: "info" }} />
            {/if}
          </span>
          <span><Badge badge={outcomeBadge(run.status)} /></span>
          <span class="num">{run.steps ?? "?"}</span>
          <span class="num">{cost(run.cost_usd ?? 0)}</span>
          <span class="num" class:flag={run.blocks > 0}>{run.blocks}</span>
          <span class="num">{run.approvals}</span>
        </button>
      </li>
    {/each}
  </ul>
</div>
