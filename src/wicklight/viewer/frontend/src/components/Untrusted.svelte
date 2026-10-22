<script lang="ts">
  import type { Message } from "../lib/api";

  let { message }: { message: Message } = $props();

  const label = $derived(
    message.role === "tool"
      ? `untrusted · tool result from ${message.name ?? "a tool"}`
      : "untrusted · model turn",
  );
</script>

<div class="untrusted">
  <div class="untrusted-label">
    <span aria-hidden="true">⚠</span>
    {label}
  </div>
  <pre>{message.content}</pre>
</div>
