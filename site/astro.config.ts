import sitemap from "@astrojs/sitemap";
import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

// GitHub Pages PROJECT page: served from /aps-ai-tracker/ (no custom
// domain). Every internal href/asset/fetch must go through withBase() in
// src/lib/paths.ts — a raw "/timeline" works in `astro dev` but 404s in prod.
export default defineConfig({
  site: "https://anucybernetics.github.io",
  base: "/aps-ai-tracker",
  trailingSlash: "ignore",
  output: "static",
  // Static MPA with cross-document view transitions: prefetch internal links as
  // they enter the viewport so navigations feel instant. Astro emits
  // <link rel="prefetch">, which degrades cleanly where the Speculation Rules
  // API isn't supported.
  prefetch: {
    prefetchAll: true,
    defaultStrategy: "viewport",
  },
  integrations: [
    svelte(),
    // Exclude the JSON data endpoint; it isn't a navigable page.
    sitemap({ filter: (page) => !page.includes("/data/") }),
  ],
});
