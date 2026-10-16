# Running Wicklight fully locally

Wicklight can run against a local, OpenAI-compatible model server — no hosted
API, no API key, nothing leaving your machine. The `local/<model>` provider
(DTN-231) speaks the OpenAI Chat Completions wire format, which [Ollama],
[vLLM], and many other servers expose.

## With Ollama

1. Install Ollama and pull a tool-capable model:

   ```bash
   ollama pull llama3.1
   ```

   Ollama serves an OpenAI-compatible endpoint at `http://localhost:11434/v1`,
   which is the `local/` provider's default — so no configuration is needed.

2. Run the local example:

   ```bash
   uv run wicklight run examples/inbox_local.md "summarize my inbox" --trace
   ```

   `wicklight check examples/inbox_local.md` shows "api keys: none required" —
   a local model needs no credential.

## Pointing at another server (vLLM, LM Studio, a gateway)

Set `OPENAI_BASE_URL` to the server's OpenAI endpoint (including the `/v1`
suffix):

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1   # e.g. vLLM
uv run wicklight run examples/inbox_local.md "summarize my inbox"
```

## Capabilities vary

Local servers differ in what they support: some lack tool calling or parallel
tool calls. The `local/` provider declares a conservative capability set (text
+ streaming). Per-endpoint capability declarations in the agent file, and a
`check` warning when an agent needs a capability the endpoint may not provide,
are tracked as a follow-up (DTN-268).

## How it works

`local/` reuses the OpenAI adapter's request/response translation
(`wicklight.providers.openai`) and only changes the endpoint and auth — it
targets the configured base URL and sends no key. See `docs/credentials.md` for
how keys are handled for the hosted providers.

[Ollama]: https://ollama.com
[vLLM]: https://github.com/vllm-project/vllm
