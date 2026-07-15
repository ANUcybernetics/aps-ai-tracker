import sitemap from "@astrojs/sitemap";
import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";

// Served from the apex custom domain apsaitracker.app (CNAME in public/), so the
// base is root. Every internal href/asset/fetch still goes through withBase() in
// src/lib/paths.ts — a raw "/timeline" works in `astro dev` but this keeps links
// robust if the base ever changes again.
export default defineConfig({
  site: "https://apsaitracker.app",
  base: "/",
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
