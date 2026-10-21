import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// The build writes into the Python package's `assets/` directory, which ships
// prebuilt in the wheel. `base: "./"` makes asset URLs relative so they resolve
// whether the app is served at `/` or a sub-path. During `npm run dev` the API
// is proxied to a locally running `wicklight view`.
export default defineConfig({
  plugins: [svelte()],
  base: "./",
  build: {
    outDir: "../assets",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
