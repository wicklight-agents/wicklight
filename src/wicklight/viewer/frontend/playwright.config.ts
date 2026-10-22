import { defineConfig, devices } from "@playwright/test";

// End-to-end smoke tests for the viewer. Run locally with `npm run e2e` (after
// `npx playwright install chromium`); they are not part of the CI gate — CI runs
// svelte-check + vitest + the build (see .github/workflows/ci.yml). The web
// server is a real `wicklight view` over the committed injection fixture.
const PORT = 4173;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `cd ../../../.. && uv run wicklight view tests/fixtures/viewer/injection.jsonl --no-browser --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/runs`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
