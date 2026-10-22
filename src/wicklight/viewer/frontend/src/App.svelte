<script lang="ts">
  import { onMount } from "svelte";
  import { getEvents, listRuns, type RunEvents, type RunSummary } from "./lib/api";
  import RunHeader from "./components/RunHeader.svelte";
  import Timeline from "./components/Timeline.svelte";

  // Load the first (usually only) run and show it as a timeline. The run list
  // and live view arrive in DTN-250.
  let run = $state<RunSummary | null>(null);
  let data = $state<RunEvents | null>(null);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      const runs = await listRuns();
      if (runs.length === 0) {
        error = "No runs found.";
        return;
      }
      run = runs[0];
      data = await getEvents(run.run_id);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  });
</script>

<main>
  <h1>wicklight viewer</h1>

  {#if error}
    <p class="error">{error}</p>
  {:else if !run || !data}
    <p class="muted">Loading…</p>
  {:else}
    <RunHeader {run} events={data.events} />
    {#if data.issues.length}
      <section class="issues">
        <h2>issues</h2>
        <ul>
          {#each data.issues as issue (issue.line)}
            <li>line {issue.line}: {issue.message} ({issue.severity})</li>
          {/each}
        </ul>
      </section>
    {/if}
    <Timeline runId={run.run_id} events={data.events} />
  {/if}
</main>
