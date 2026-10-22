<script lang="ts">
  import type { Badge } from "../lib/format";

  let { badge }: { badge: Badge } = $props();
</script>

<span class="badge tone-{badge.tone}">
  <span class="badge-icon" aria-hidden="true">{badge.icon}</span>
  <span class="badge-label">{badge.label}</span>
</span>
