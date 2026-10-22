<script lang="ts">
  import { flagBadge } from "../lib/format";
  import type { Step } from "../lib/steps";
  import Badge from "./Badge.svelte";
  import StepDetail from "./StepDetail.svelte";

  let {
    runId,
    step,
    open,
    onToggle,
  }: { runId: string; step: Step; open: boolean; onToggle: () => void } = $props();
</script>

<li id="step-{step.step}" class="step-row" class:open>
  <button class="step-head" aria-expanded={open} onclick={onToggle}>
    <span class="step-num">#{step.step}</span>
    <span class="step-summary">{step.summary}</span>
    <span class="step-badges">
      {#each step.flags as flag (flag)}<Badge badge={flagBadge(flag)} />{/each}
      <span class="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
    </span>
  </button>
  {#if open}
    <StepDetail {runId} {step} />
  {/if}
</li>
