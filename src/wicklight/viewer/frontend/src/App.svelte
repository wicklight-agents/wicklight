<script lang="ts">
  import { onMount } from "svelte";
  import { getMeta, listRuns, type RunMeta, type RunSummary } from "./lib/api";
  import RunList from "./components/RunList.svelte";
  import RunView from "./components/RunView.svelte";

  let meta = $state<RunMeta | null>(null);
  let runs = $state<RunSummary[]>([]);
  let selected = $state<string | null>(null);
  let error = $state<string | null>(null);

  // When several runs are served, selecting one should offer a way back.
  const canList = $derived((meta?.run_count ?? 0) > 1);
  const isLive = $derived(meta?.live === true && selected === meta?.live_run_id);

  onMount(async () => {
    try {
      meta = await getMeta();
      runs = await listRuns();
      // Live run wins; otherwise a single run opens directly; many runs list.
      selected = meta.live_run_id ?? meta.single_run_id ?? null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  });
</script>

<main>
  <h1>wicklight viewer</h1>

  {#if error}
    <p class="error">{error}</p>
  {:else if !meta}
    <p class="muted">Loading…</p>
  {:else if selected}
    {#key selected}
      <RunView
        runId={selected}
        live={isLive}
        onBack={canList ? () => (selected = null) : undefined}
      />
    {/key}
  {:else if runs.length === 0}
    <p class="muted">No runs found.</p>
  {:else}
    <RunList {runs} onSelect={(id) => (selected = id)} />
  {/if}
</main>
