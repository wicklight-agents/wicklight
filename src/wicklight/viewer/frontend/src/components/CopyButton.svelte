<script lang="ts">
  let { text, label = "copy" }: { text: string; label?: string } = $props();
  let copied = $state(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      setTimeout(() => (copied = false), 1200);
    } catch (e) {
      // Clipboard can be unavailable (insecure context); surface it, don't swallow.
      console.error("copy failed", e);
    }
  }
</script>

<button class="copy" type="button" onclick={copy}>
  {copied ? "copied" : label}
</button>
