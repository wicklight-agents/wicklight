<script lang="ts">
  import type { RunSummary, TraceEvent } from "../lib/api";
  import { cost, duration, outcomeBadge, totals } from "../lib/format";
  import Badge from "./Badge.svelte";

  let {
    run,
    events,
    live = false,
  }: { run: RunSummary; events: TraceEvent[]; live?: boolean } = $props();

  const sums = $derived(totals(events));
  const elapsed = $derived(duration(events));
  // Derive the step count from events so it updates live; fall back to the
  // recorded summary for an empty event list.
  const stepCount = $derived(
    events.length ? Math.max(...events.map((e) => e.step)) + 1 : (run.steps ?? 0),
  );
</script>

<header class="run-header">
  <div class="run-title">
    <span class="agent">{run.agent ?? "(unknown agent)"}</span>
    {#if live}<span class="live" title="following this run">● live</span>{/if}
    <Badge badge={outcomeBadge(run.status)} />
    {#if run.dry_run}<Badge badge={{ label: "dry run", icon: "◌", tone: "info" }} />{/if}
    {#if run.counterfactual}
      <Badge badge={{ label: "counterfactual", icon: "⎇", tone: "info" }} />
    {/if}
  </div>
  <dl class="run-stats">
    <div><dt>run</dt><dd>{run.run_id}</dd></div>
    <div><dt>steps</dt><dd>{stepCount}</dd></div>
    {#if run.models.length}
      <div><dt>models</dt><dd>{run.models.join(", ")}</dd></div>
    {/if}
    <div><dt>tokens</dt><dd>{sums.inputTokens} in / {sums.outputTokens} out</dd></div>
    <div><dt>cost</dt><dd>{cost(sums.costUsd)}</dd></div>
    {#if elapsed}<div><dt>duration</dt><dd>{elapsed}</dd></div>{/if}
  </dl>
</header>
