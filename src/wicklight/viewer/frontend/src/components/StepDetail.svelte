<script lang="ts">
  import { onMount } from "svelte";
  import {
    getJsonBlob,
    type ModelRequestBlob,
    type ModelResponseBlob,
    type ToolResultBlob,
    type TraceEvent,
  } from "../lib/api";
  import type { Step } from "../lib/steps";
  import CopyButton from "./CopyButton.svelte";
  import Untrusted from "./Untrusted.svelte";

  let { runId, step }: { runId: string; step: Step } = $props();

  // Events of a given type within this step.
  const of = (type: string): TraceEvent[] =>
    step.events.filter((e) => e.type === type);

  const routed = $derived(of("model_routed"));
  const proposals = $derived(of("tool_proposed"));
  const checks = $derived(
    step.events.filter((e) =>
      ["policy_checked", "approval_requested", "approval_resolved", "limit_hit", "error"].includes(
        e.type,
      ),
    ),
  );

  const refOf = (type: string, key: string): string | null => {
    const value = of(type)[0]?.payload[key];
    return typeof value === "string" ? value : null;
  };

  let request = $state<ModelRequestBlob | null>(null);
  let response = $state<ModelResponseBlob | null>(null);
  let result = $state<ToolResultBlob | null>(null);
  let loadError = $state<string | null>(null);

  onMount(async () => {
    try {
      const reqRef = refOf("model_called", "request_ref");
      const respRef = refOf("model_responded", "response_ref");
      const resRef = refOf("tool_executed", "result_ref");
      if (reqRef) request = await getJsonBlob<ModelRequestBlob>(runId, reqRef);
      if (respRef) response = await getJsonBlob<ModelResponseBlob>(runId, respRef);
      if (resRef) result = await getJsonBlob<ToolResultBlob>(runId, resRef);
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    }
  });

  function payloadStr(event: TraceEvent, key: string): string | null {
    const v = event.payload[key];
    return typeof v === "string" ? v : null;
  }

  function isDeny(event: TraceEvent): boolean {
    return event.type === "policy_checked" && payloadStr(event, "decision") === "deny";
  }

  const pretty = (value: unknown): string => JSON.stringify(value, null, 2);
</script>

<div class="detail">
  {#if loadError}
    <p class="error">could not load recorded data: {loadError}</p>
  {/if}

  <!-- Routing -->
  {#if routed.length}
    <section>
      <h3>Routing</h3>
      {#each routed as r (r.timestamp)}
        <p>
          <strong>{r.payload["model"]}</strong>
          by {r.payload["matched_rule"] ?? "default"}
          {#if r.payload["source"]}<span class="muted">({r.payload["source"]})</span>{/if}
          {#if Array.isArray(r.payload["excluded"]) && r.payload["excluded"].length}
            <span class="muted">· excluded for sensitivity: {(r.payload["excluded"] as string[]).join(", ")}</span>
          {/if}
        </p>
      {/each}
    </section>
  {/if}

  <!-- Context -->
  <section>
    <h3>Context the model saw</h3>
    {#if request}
      <ol class="messages">
        {#each request.messages as message, i (i)}
          {#if message.trusted}
            <li class="msg role-{message.role}">
              <span class="role">{message.role}{message.name ? ` · ${message.name}` : ""}</span>
              <pre>{message.content}</pre>
            </li>
          {:else}
            <li><Untrusted {message} /></li>
          {/if}
        {/each}
      </ol>
    {:else}
      <p class="muted">No recorded context for this step.</p>
    {/if}
  </section>

  <!-- Model response -->
  <section>
    <h3>Model response</h3>
    {#if response && response.content}
      <pre>{response.content}</pre>
    {/if}
    {#if proposals.length}
      <ul class="calls">
        {#each proposals as call (call.timestamp)}
          <li>
            <code>{call.payload["tool"]}</code>
            <CopyButton text={pretty(call.payload["arguments"])} label="copy args" />
            <pre>{pretty(call.payload["arguments"])}</pre>
          </li>
        {/each}
      </ul>
    {:else if !response?.content}
      <p class="muted">No model text or tool calls recorded.</p>
    {/if}
  </section>

  <!-- Checks -->
  {#if checks.length}
    <section>
      <h3>Checks</h3>
      <ul class="checks">
        {#each checks as check (check.type + check.timestamp)}
          <li class:deny={isDeny(check)}>
            <span class="explain">{check.explain}</span>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <!-- Result -->
  <section>
    <h3>Result</h3>
    {#if result}
      <p class="muted">{result.ok ? "ok" : "failed"}{result.sensitive ? " · sensitive" : ""}</p>
      <pre>{result.ok ? result.output : (result.error ?? result.output)}</pre>
    {:else if checks.some(isDeny)}
      <p class="muted">Blocked — no result; the model was told why (see Checks).</p>
    {:else}
      <p class="muted">No recorded result for this step.</p>
    {/if}
  </section>

  <!-- Raw events -->
  <details class="raw">
    <summary>raw events ({step.events.length})</summary>
    {#each step.events as event (event.type + event.timestamp)}
      <div class="raw-event">
        <CopyButton text={pretty(event)} label="copy JSON" />
        <pre>{pretty(event)}</pre>
      </div>
    {/each}
  </details>
</div>
