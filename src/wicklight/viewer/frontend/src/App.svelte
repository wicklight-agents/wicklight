<script lang="ts">
  import { onMount } from "svelte";
  import { getEvents, listRuns, type RunEvents, type RunSummary } from "./lib/api";

  // PR A skeleton: load the first (usually only) run and list its events so we
  // can prove the page talks to the local API. The rich timeline and expandable
  // step panels arrive in DTN-248/249.
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
    <header class="summary">
      <span class="agent">{run.agent ?? "(unknown agent)"}</span>
      <span class="status status-{run.status}">{run.status ?? "running"}</span>
      <span class="muted">{run.steps ?? "?"} steps</span>
      {#if run.models.length}<span class="muted">{run.models.join(", ")}</span>{/if}
      {#if run.blocks}<span class="pill blocked">{run.blocks} blocked</span>{/if}
      {#if run.approvals}<span class="pill approved">{run.approvals} approved</span>{/if}
    </header>

    <ol class="events">
      {#each data.events as event (event.step + ":" + event.type + ":" + event.timestamp)}
        <li>
          <span class="step">#{event.step}</span>
          <span class="type">{event.type}</span>
          <span class="explain">{event.explain}</span>
        </li>
      {/each}
    </ol>

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
  {/if}
</main>
