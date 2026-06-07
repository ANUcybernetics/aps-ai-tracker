import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

// GitHub Pages PROJECT page: served from /aps-ai-transparency-tracker/ (no custom
// domain). Every internal href/asset/fetch must go through withBase() in
// src/lib/paths.ts — a raw "/timeline" works in `astro dev` but 404s in prod.
export default defineConfig({
  site: "https://anucybernetics.github.io",
  base: "/aps-ai-transparency-tracker",
  trailingSlash: "ignore",
  output: "static",
  integrations: [svelte()],
});
