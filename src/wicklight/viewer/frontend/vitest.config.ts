import { defineConfig } from "vitest/config";

// Unit tests cover the pure logic in src/lib (step grouping, formatting). They
// need no DOM, so the node environment keeps them fast. Component and
// end-to-end (Playwright) tests arrive with DTN-251.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
