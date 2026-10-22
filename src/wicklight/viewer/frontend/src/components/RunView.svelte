<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import {
    getEvents,
    listRuns,
    streamEvents,
    type RunSummary,
    type TraceEvent,
    type TraceIssue,
  } from "../lib/api";
  import RunHeader from "./RunHeader.svelte";
  import Timeline from "./Timeline.svelte";

  let {
    runId,
    live = false,
    onBack,
  }: { runId: string; live?: boolean; onBack?: () => void } = $props();

  let summary = $state<RunSummary | null>(null);
  let events = $state<TraceEvent[]>([]);
  let issues = $state<TraceIssue[]>([]);
  let error = $state<string | null>(null);
  let following = $state(false);
  let source: EventSource | null = null;

  async function loadSummary() {
    const runs = await listRuns();
    summary = runs.find((r) => r.run_id === runId) ?? null;
  }

  onMount(async () => {
    try {
      await loadSummary();
      if (live) {
        following = true;
        // The stream re-sends every event from the start, then new ones; append
        // each so the timeline grows as the run executes.
        source = streamEvents(
          runId,
          (event) => (events = [...events, event]),
          () => {
            following = false;
            void loadSummary(); // refresh the final outcome
          },
        );
      } else {
        const data = await getEvents(runId);
        events = data.events;
        issues = data.issues;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  });

  onDestroy(() => source?.close());
</script>

<section>
  {#if onBack}
    <button class="back" type="button" onclick={onBack}>← all runs</button>
  {/if}

  {#if error}
    <p class="error">{error}</p>
  {:else if !summary && events.length === 0}
    <p class="muted">Loading…</p>
  {:else if summary}
    <RunHeader run={summary} {events} live={following} />
    {#if issues.length}
      <section class="issues">
        <h2>issues</h2>
        <ul>
          {#each issues as issue (issue.line)}
            <li>line {issue.line}: {issue.message} ({issue.severity})</li>
          {/each}
        </ul>
      </section>
    {/if}
    <Timeline {runId} {events} />
  {/if}
</section>
