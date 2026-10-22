import { svelte } from "@sveltejs/vite-plugin-svelte";
import { svelteTesting } from "@testing-library/svelte/vite";
import { defineConfig } from "vitest/config";

// Unit tests cover the pure logic in src/lib and the components in src/components
// (rendered with @testing-library/svelte in jsdom). End-to-end (Playwright) tests
// live in e2e/ and run via `npm run e2e`, not under vitest.
export default defineConfig({
  plugins: [svelte(), svelteTesting()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    setupFiles: ["./vitest-setup.ts"],
  },
});
