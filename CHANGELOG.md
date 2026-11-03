# Changelog

All notable changes to Wicklight are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-03

The first public release: a small, observable, safe-by-default agent harness.
Define an agent in one file, run it with full tracing, inspect it offline, and
deploy it as a locked-down container.

### Added

- **Skeleton & CI (M1).** Installable package, `wicklight` CLI entry point, and
  lint/type/test CI (uv, Ruff, Pyright, pytest) across Python 3.10–3.13.
- **Agent file (M2).** Parse and validate `agent.md` (YAML frontmatter +
  Markdown body) with line-numbered, one-pass errors; `wicklight check` prints
  the effective config.
- **Trace (M3).** Append-only JSONL trace with a content-addressed blob store, a
  validating reader, and `wicklight trace show`.
- **Provider contract (M4).** Neutral request/response types, a `Provider`
  protocol with entry-point discovery, a scripted `FakeProvider`, and a provider
  conformance kit.
- **Core loop & tools (M5).** The fixed loop; the tool contract and risk levels;
  permission checks; step/cost/time limits; the `Agent` API; `wicklight run`.
- **Policies & untrusted tagging (M6).** A policy contract and conformance kit;
  built-in policies (`email_only_to`, `paths_within`, `spend_limit`,
  `sender_denylist`); every tool result tagged as untrusted.
- **Approvals & waivers (M7).** An approval gate with a terminal approver;
  irreversible tools require approval by default; reasoned per-tool waivers.
- **Real providers (M8).** Anthropic, OpenAI, and OpenAI-compatible
  (Ollama/vLLM) adapters; keys from the environment, redacted from traces;
  recorded HTTP fixtures for offline tests; a capability preflight.
- **Replay, explain & dry-run (M9).** Runs record the model request/response and
  tool results, so `wicklight replay`, `wicklight explain`, `run --dry-run`, and
  counterfactual replay re-inspect a run offline with no model calls.
- **Model routing (M10).** Per-step model routing (step, context size, cost,
  data sensitivity), a fallback chain on provider errors, and enforced
  sensitivity routing that keeps sensitive data off disallowed models.
- **Local web viewer (M11).** `wicklight view` — an offline timeline + step
  detail UI (Svelte), shipped prebuilt in the wheel (no Node for users).
- **Deployment (M12).** `wicklight deploy` builds a locked-down, non-root,
  shell-less container; `deploy.yaml` with triggers, runtime secrets held by the
  harness, and an auto-derived egress allowlist enforced by a proxy; host
  control CLI (`ps`, `logs`, `stop`, `approve`, `undeploy`).
- **Release (M13).** A documentation site; curated example agents (one per
  safety feature) bundled in the wheel and copied out with `wicklight examples
  --copy`; a changelog; and trusted publishing to PyPI.

### Known limitations

- The `wicklight-agents` thin-alias package and an example third-party provider
  plugin repository are planned for a post-0.1 follow-up.
- Live smoke tests against real provider APIs are gated off by default.

[Unreleased]: https://github.com/wicklight-agents/wicklight/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wicklight-agents/wicklight/releases/tag/v0.1.0
