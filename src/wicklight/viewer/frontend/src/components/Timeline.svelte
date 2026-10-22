<script lang="ts">
  import type { TraceEvent } from "../lib/api";
  import { groupSteps, matchesFilter, type StepFilter } from "../lib/steps";
  import StepRow from "./StepRow.svelte";

  let { runId, events }: { runId: string; events: TraceEvent[] } = $props();

  const steps = $derived(groupSteps(events));
  const filters: StepFilter[] = ["all", "blocks", "approvals", "errors"];

  let filter = $state<StepFilter>("all");
  let openSteps = $state(new Set<number>());
  let jump = $state("");

  const visible = $derived(steps.filter((s) => matchesFilter(s, filter)));

  function toggle(n: number) {
    const next = new Set(openSteps);
    if (next.has(n)) next.delete(n);
    else next.add(n);
    openSteps = next;
  }

  function doJump(event: Event) {
    event.preventDefault();
    const n = Number(jump);
    if (!Number.isInteger(n)) return;
    const next = new Set(openSteps);
    next.add(n);
    openSteps = next;
    requestAnimationFrame(() =>
      document
        .getElementById(`step-${n}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }
</script>

<div class="toolbar">
  <div class="filters" role="group" aria-label="filter steps">
    {#each filters as f (f)}
      <button
        type="button"
        class:active={filter === f}
        aria-pressed={filter === f}
        onclick={() => (filter = f)}
      >
        {f}
      </button>
    {/each}
  </div>
  <form class="jump" onsubmit={doJump}>
    <label>
      jump to step
      <input type="number" min="0" bind:value={jump} />
    </label>
    <button type="submit">go</button>
  </form>
</div>

{#if visible.length === 0}
  <p class="muted">No steps match “{filter}”.</p>
{:else}
  <ol class="timeline">
    {#each visible as step (step.step)}
      <StepRow
        {runId}
        {step}
        open={openSteps.has(step.step)}
        onToggle={() => toggle(step.step)}
      />
    {/each}
  </ol>
{/if}
