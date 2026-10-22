# wicklight viewer frontend

A small **Svelte + Vite + TypeScript** app that renders a run trace. It is
prebuilt into `../assets/` (committed, shipped in the wheel), so users never need
Node. See [`docs/viewer.md`](../../../../docs/viewer.md) for the user-facing
guide and the HTTP API it talks to.

## Scripts

```bash
npm install        # once
npm run check      # svelte-check (type-check)
npm test           # vitest: unit (src/lib) + component (src/components)
npm run build      # writes ../assets/ (commit the result)
npm run dev        # dev server; proxies /api to a running `wicklight view`
npm run e2e        # Playwright smoke (local; needs: npx playwright install chromium)
```

CI runs `check` + `test` + `build` and fails if the committed `../assets/` drift
from a fresh build. Playwright (`e2e/`) is **local only**, not in the CI gate.

## Layout and reuse

The code is split so the game's replay viewer can reuse the core without the
app shell:

| Path | What |
| --- | --- |
| `src/lib/api.ts` | Typed client + blob/stream helpers for the viewer API. |
| `src/lib/steps.ts` | **Pure** — group events into per-step rows, derive flags and summaries, filter. No DOM; unit-tested. |
| `src/lib/format.ts` | **Pure** — durations, token/cost totals, and the badge vocabulary (icon + label + tone, never color alone). Unit-tested. |
| `src/components/Timeline.svelte` | The step timeline: filters, jump-to-step, expandable rows. |
| `src/components/StepDetail.svelte` | A step's context, routing, response, checks, and result (lazy-loads blobs). |
| `src/components/RunHeader.svelte`, `RunList.svelte`, `StepRow.svelte`, `Badge.svelte`, `Untrusted.svelte`, `CopyButton.svelte` | Self-contained pieces. |
| `src/App.svelte`, `RunView.svelte` | The app shell: run list, run view, and live follow. |

To reuse the timeline elsewhere, depend on `lib/steps.ts` + `lib/format.ts`
(pure, framework-agnostic data) and the `Timeline`/`StepDetail` components, which
take plain `TraceEvent[]` and a `runId`. Styling is CSS-variable based
(`app.css`) and works in light and dark mode.
